"""Deterministic parser for SQLite-compatible SQL evidence snapshots.

Families handled by name convention (explicit, documented mapping):

- ``customer_data_inventory_*``: typed tables sharing ``snapshot_scope``
- ``customer_data_read_replica_*`` / ``_regional_replicas_*`` /
  ``_reporting_replica_*`` / ``customer_data_failover_replica_*``: generic
  ``(resource_id, origin_system, collection_name, record_json, updated_at)``
  tables decoded per ``collection_name``
- ``customer_accounts_failover_replica_*``: dedicated account-profile replica
- ``customer_search_primary_*``: dedicated search document replica

Any other SQL file, table or collection is left undecoded with an explicit
error; states are never guessed.
"""

import json
import sqlite3
from collections.abc import Callable
from pathlib import Path

from ..models import (
    EvidenceObservation,
    ObservationState,
    ParseReport,
    ParseStatus,
    Provenance,
    finalize_status,
    make_observation,
)
from .collection_rules import COLLECTION_RULES, DecodedRecord
from .common import file_sha256

ParseOutput = tuple[list[EvidenceObservation], ParseReport]

INVENTORY_TABLES: dict[str, tuple[str, str]] = {
    "customer_profiles": ("account_service", "customer_profiles"),
    "customer_search_documents": ("search_service", "customer_search_documents"),
    "customer_analytics_profiles": ("analytics_platform", "customer_analytics_profiles"),
    "support_records": ("support_platform", "support_records"),
    "customer_exports": ("export_service", "customer_exports"),
    "connector_subscriptions": ("integration_service", "connector_subscriptions"),
    "backup_restore_entries": ("backup_service", "backup_restore_entries"),
    "security_audit_records": ("security_service", "security_audit_records"),
}

GENERIC_COLUMNS = frozenset(
    {"resource_id", "origin_system", "collection_name", "record_json", "updated_at"}
)

SQL_FAMILIES: tuple[tuple[str, str], ...] = (
    ("customer_data_inventory", "inventory"),
    ("customer_accounts_failover_replica", "accounts_failover"),
    ("customer_search_primary", "search_primary"),
    ("customer_data_failover_replica", "generic_replica"),
    ("customer_data_read_replica", "generic_replica"),
    ("customer_data_regional_replicas", "generic_replica"),
    ("customer_data_reporting_replica", "generic_replica"),
)


def sql_family(file_path: str) -> str:
    stem = Path(file_path).stem
    for prefix, family in SQL_FAMILIES:
        if stem.startswith(prefix):
            return family
    return "unknown"


def _connect(script: str) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(script)
    return connection


def _table_names(connection: sqlite3.Connection) -> list[str]:
    return [
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    ]


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, object]]:
    columns = _columns(connection, table)
    return [
        dict(zip(columns, row, strict=True))
        for row in connection.execute(f'SELECT * FROM "{table}"')
    ]


def _decode_row(
    rule: Callable[[dict[str, object]], DecodedRecord], record: dict[str, object]
) -> DecodedRecord:
    return rule(record)


def _build_observation(
    *,
    file_id: str,
    captured_at: str,
    system_id: str,
    resource_id: str,
    locator: str,
    decoded: DecodedRecord,
    provenance: Provenance,
) -> EvidenceObservation:
    return make_observation(
        file_id=file_id,
        captured_at=captured_at,
        system_id=system_id,
        resource_id=resource_id,
        data_category=decoded.data_category,
        state=decoded.state,
        reason=decoded.reason,
        locator=locator,
        provenance=provenance,
        identifiers=decoded.identifiers,
        state_inputs=decoded.state_inputs,
        pii_exposed=decoded.pii_exposed,
    )


def _parse_inventory(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    tables = _table_names(connection)
    if "snapshot_scope" in tables:
        for row in _rows(connection, "snapshot_scope"):
            system = str(row.get("origin_system") or "").strip()
            scope_time = str(row.get("captured_at") or captured_at)
            if system:
                report.scope[system] = scope_time
            else:
                report.errors.append("snapshot_scope row without origin_system")
    for table in tables:
        if table == "snapshot_scope":
            continue
        mapping = INVENTORY_TABLES.get(table)
        if mapping is None:
            report.errors.append(f"unknown_inventory_table:{table}")
            continue
        system_id, collection = mapping
        rule = COLLECTION_RULES[collection]
        for record in _rows(connection, table):
            resource_id = str(record.get("resource_id") or "").strip()
            if not resource_id:
                report.errors.append(f"{table}: row without resource_id")
                continue
            decoded = _decode_row(rule, record)
            observations.append(
                _build_observation(
                    file_id=file_id,
                    captured_at=captured_at,
                    system_id=system_id,
                    resource_id=resource_id,
                    locator=f"{table}:{resource_id}",
                    decoded=decoded,
                    provenance=Provenance.EXPLICIT_FIELD
                    if decoded.state is not ObservationState.ANONYMIZED
                    and decoded.state is not ObservationState.REDACTED
                    else Provenance.NULL_PII_RULE,
                )
            )
    missing = [table for table in INVENTORY_TABLES if table not in tables]
    if missing:
        report.errors.append(f"missing_inventory_tables:{','.join(sorted(missing))}")


def _parse_generic_replica(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    for table in _table_names(connection):
        columns = set(_columns(connection, table))
        if not GENERIC_COLUMNS <= columns:
            report.errors.append(f"unexpected_replica_table:{table}")
            continue
        for record in _rows(connection, table):
            resource_id = str(record.get("resource_id") or "").strip()
            system_id = str(record.get("origin_system") or "").strip()
            collection = str(record.get("collection_name") or "").strip()
            if not resource_id or not system_id or not collection:
                report.errors.append(
                    f"{table}: row missing resource_id/origin_system/collection_name"
                )
                continue
            rule = COLLECTION_RULES.get(collection)
            if rule is None:
                report.errors.append(f"{table}:{resource_id}: unknown_collection:{collection}")
                continue
            raw_json = record.get("record_json")
            try:
                payload = json.loads(str(raw_json))
            except (TypeError, json.JSONDecodeError):
                report.errors.append(f"{table}:{resource_id}: invalid record_json")
                continue
            if not isinstance(payload, dict):
                report.errors.append(f"{table}:{resource_id}: record_json is not an object")
                continue
            decoded = _decode_row(rule, payload)
            observations.append(
                _build_observation(
                    file_id=file_id,
                    captured_at=captured_at,
                    system_id=system_id,
                    resource_id=resource_id,
                    locator=f"{table}:{resource_id}",
                    decoded=decoded,
                    provenance=Provenance.EXPLICIT_FIELD,
                )
            )


def _parse_accounts_failover(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    rule = COLLECTION_RULES["customer_profiles"]
    known_tables = {"customer_profiles_failover_replica", "customer_profiles_primary"}
    for table in _table_names(connection):
        if table not in known_tables:
            report.errors.append(f"unexpected_accounts_table:{table}")
            continue
        for record in _rows(connection, table):
            resource_id = str(record.get("resource_id") or "").strip()
            if not resource_id:
                report.errors.append(f"{table}: row without resource_id")
                continue
            decoded = _decode_row(rule, record)
            observations.append(
                _build_observation(
                    file_id=file_id,
                    captured_at=captured_at,
                    system_id="account_service",
                    resource_id=resource_id,
                    locator=f"{table}:{resource_id}",
                    decoded=decoded,
                    provenance=Provenance.NULL_PII_RULE
                    if decoded.state is ObservationState.REDACTED
                    else Provenance.EXPLICIT_FIELD,
                )
            )


def _parse_search_primary(
    connection: sqlite3.Connection,
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    rule = COLLECTION_RULES["customer_search_documents"]
    for table in _table_names(connection):
        if table != "search_documents_primary":
            report.errors.append(f"unexpected_search_table:{table}")
            continue
        for record in _rows(connection, table):
            resource_id = str(record.get("resource_id") or "").strip()
            if not resource_id:
                report.errors.append(f"{table}: row without resource_id")
                continue
            decoded = _decode_row(rule, record)
            observations.append(
                _build_observation(
                    file_id=file_id,
                    captured_at=captured_at,
                    system_id="search_service",
                    resource_id=resource_id,
                    locator=f"{table}:{resource_id}",
                    decoded=decoded,
                    provenance=Provenance.EXPLICIT_FIELD,
                )
            )


def parse_sql_file(
    file_id: str,
    path: Path,
    captured_at: str,
    family: str | None = None,
) -> ParseOutput:
    family_name = family or sql_family(str(path))
    report = ParseReport(
        file_id=file_id,
        family=f"sql:{family_name}",
        captured_at=captured_at,
        sha256=file_sha256(path),
        status=ParseStatus.OK,
    )
    observations: list[EvidenceObservation] = []
    if family_name == "unknown":
        report.errors.append(f"unrecognized_sql_family:{path.name}")
        report.status = ParseStatus.UNKNOWN_STATE
        return observations, report
    try:
        connection = _connect(path.read_text(encoding="utf-8", errors="replace"))
    except (sqlite3.Error, OSError) as exc:
        report.errors.append(f"sqlite_error:{exc}")
        report.status = ParseStatus.PARSE_ERROR
        return observations, report
    try:
        if family_name == "inventory":
            _parse_inventory(
                connection,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
        elif family_name == "generic_replica":
            _parse_generic_replica(
                connection,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
        elif family_name == "accounts_failover":
            report.direct_systems = ("account_service",)
            _parse_accounts_failover(
                connection,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
        elif family_name == "search_primary":
            report.direct_systems = ("search_service",)
            _parse_search_primary(
                connection,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
    finally:
        connection.close()
    report.status = finalize_status(report.errors, observations)
    return observations, report
