"""Deterministic parser for JSON evidence and the handover text file.

Families: snapshot bundles, per-service resource exports, ledger-style record
lists (connector configurations, export manifest, security ledger), export jobs,
analytics reports, and the customer-account handover text. Unknown families,
collections, service keys, or status tokens are surfaced as explicit errors or
UNKNOWN observations; nothing is inferred.
"""

import json
import re
from pathlib import Path

from ..models import (
    CapturedCollection,
    EvidenceObservation,
    ObservationState,
    ParseReport,
    ParseStatus,
    Provenance,
    finalize_status,
    make_observation,
)
from .collection_rules import (
    COLLECTION_RULES,
    DecodedRecord,
    decode_analytics_record,
    decode_backup_record,
    decode_connector_record,
    decode_export_record,
    decode_lookup_record,
    decode_security_record,
    decode_support_record,
)
from .common import file_sha256
from .state_vocab import (
    clean,
    decode_profile_pii,
    decode_result,
    decode_search_result,
    is_null,
)

ParseOutput = tuple[list[EvidenceObservation], ParseReport]

JSON_FAMILIES: tuple[tuple[str, str], ...] = (
    ("customer_data_snapshot_bundle", "snapshot_bundle"),
    ("service_resource_export", "service_export"),
    ("connector_configurations", "ledger"),
    ("customer_export_manifest", "ledger"),
    ("security_audit_ledger", "ledger"),
    ("customer_export_jobs", "export_jobs"),
    ("customer_analytics_report", "analytics_report"),
)

HANDOVER_FAMILY = "handover"
HANDOVER_LINE = re.compile(r"^- (\S+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ([^|]+) \| ?(.*)$")

SERVICE_EXPORT_KEYS: dict[str, frozenset[str]] = {
    "account_service": frozenset({"profile_lookups"}),
    "analytics_platform": frozenset({"profiles"}),
    "backup_service": frozenset({"restore_entries"}),
    "export_service": frozenset({"exports"}),
    "integration_service": frozenset({"connectors"}),
    "search_service": frozenset({"index_queries"}),
    "security_service": frozenset({"audit_records"}),
    "support_platform": frozenset({"tickets"}),
}

_READBACK_PROVENANCE = Provenance.READBACK


def json_family(file_path: str) -> str:
    stem = Path(file_path).stem
    if Path(file_path).suffix.lower() == ".txt":
        return HANDOVER_FAMILY if stem.startswith("customer_account_handover") else "unknown"
    for prefix, family in JSON_FAMILIES:
        if stem.startswith(prefix):
            return family
    return "unknown"


def _observation(
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


def _decoded(
    category: str,
    state: ObservationState,
    reason: str,
    identifiers: tuple[str, ...] = (),
    state_inputs: dict[str, str] | None = None,
    pii_exposed: bool = False,
) -> DecodedRecord:
    return DecodedRecord(
        data_category=category,
        state=state,
        reason=reason,
        identifiers=identifiers,
        pii_exposed=pii_exposed,
        state_inputs=state_inputs or {},
    )


# --------------------------------------------------------------------------- #
# Families
# --------------------------------------------------------------------------- #


def _parse_bundle(
    payload: dict[str, object],
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, list):
        report.errors.append("bundle: snapshots is not a list")
        return
    for index, snapshot in enumerate(snapshots):
        if not isinstance(snapshot, dict):
            report.errors.append(f"bundle: snapshot[{index}] is not an object")
            continue
        data_store = str(snapshot.get("data_store") or "").strip()
        collection = str(snapshot.get("collection") or "").strip()
        snapshot_time = str(snapshot.get("captured_at") or captured_at)
        records = snapshot.get("records")
        if not data_store or not collection or not isinstance(records, list):
            report.errors.append(f"bundle: snapshot[{index}] missing data_store/collection/records")
            continue
        report.captured_collections.append(
            CapturedCollection(
                data_store=data_store,
                collection=collection,
                captured_at=snapshot_time,
                record_count=len(records),
            )
        )
        rule = COLLECTION_RULES.get(collection)
        if rule is None:
            report.errors.append(f"bundle: unknown_collection:{collection}")
            continue
        for record_index, record in enumerate(records):
            if not isinstance(record, dict):
                report.errors.append(
                    f"bundle: snapshot[{index}].records[{record_index}] not an object"
                )
                continue
            resource_id = str(record.get("resource_id") or "").strip()
            if not resource_id:
                report.errors.append(
                    f"bundle: snapshot[{index}].records[{record_index}] without resource_id"
                )
                continue
            decoded = rule(record)
            observations.append(
                _observation(
                    file_id=file_id,
                    captured_at=snapshot_time,
                    system_id=data_store,
                    resource_id=resource_id,
                    locator=f"{data_store}/{collection}[{record_index}]",
                    decoded=decoded,
                    provenance=Provenance.EXPLICIT_FIELD,
                )
            )


def _decode_profile_lookup(item: dict[str, object]) -> DecodedRecord:
    status = item.get("status_code")
    profile = item.get("profile")
    try:
        status_code = int(str(status)) if status is not None else None
    except (TypeError, ValueError):
        status_code = None
    inputs = {"status_code": "" if status is None else str(status)}
    if status_code == 404:
        return _decoded(
            "USER_PROFILE", ObservationState.ABSENT, "status_code=404", state_inputs=inputs
        )
    if isinstance(profile, dict):
        fields = {
            "name": profile.get("full_name"),
            "email": profile.get("email"),
            "phone": profile.get("phone"),
            "email_hash": profile.get("email_hash"),
        }
        reference = profile.get("customer_reference")
        state, reason = decode_profile_pii(fields, reference)
        identifiers = tuple(
            str(value)
            for value in (
                fields["name"],
                fields["email"],
                fields["phone"],
                fields["email_hash"],
                reference,
            )
            if clean(value) is not None
        )
        exposed = any(clean(value) is not None for value in fields.values())
        inputs |= {key: "" if value is None else str(value) for key, value in fields.items()}
        return _decoded("USER_PROFILE", state, reason, identifiers, inputs, pii_exposed=exposed)
    if status_code == 200:
        return _decoded(
            "USER_PROFILE",
            ObservationState.UNKNOWN,
            "profile_missing,status=200",
            state_inputs=inputs,
        )
    return _decoded(
        "USER_PROFILE", ObservationState.UNKNOWN, "missing_field:status_code", state_inputs=inputs
    )


def _parse_service_export(
    payload: dict[str, object],
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    exports = payload.get("service_exports")
    if not isinstance(exports, dict):
        report.errors.append("service_export: service_exports is not an object")
        return
    for service_name, service_payload in exports.items():
        known_keys = SERVICE_EXPORT_KEYS.get(service_name)
        if known_keys is None:
            report.errors.append(f"service_export: unknown_service:{service_name}")
            continue
        if not isinstance(service_payload, dict):
            report.errors.append(f"service_export: {service_name} payload is not an object")
            continue
        for key, items in service_payload.items():
            if key not in known_keys:
                report.errors.append(f"service_export: unknown_key:{service_name}.{key}")
                continue
            if not isinstance(items, list):
                report.errors.append(f"service_export: {service_name}.{key} is not a list")
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    report.errors.append(
                        f"service_export: {service_name}.{key}[{index}] not an object"
                    )
                    continue
                resource_id = str(item.get("resource_id") or "").strip()
                if not resource_id:
                    report.errors.append(
                        f"service_export: {service_name}.{key}[{index}] without resource_id"
                    )
                    continue
                observed_at = str(item.get("observed_at") or captured_at)
                try:
                    decoded = _decode_service_item(service_name, key, item)
                except (TypeError, ValueError) as exc:  # explicit decode failures only
                    report.errors.append(f"service_export: {service_name}.{key}[{index}]: {exc}")
                    continue
                if decoded is None:
                    report.errors.append(f"service_export: unhandled_key:{service_name}.{key}")
                    continue
                observations.append(
                    _observation(
                        file_id=file_id,
                        captured_at=observed_at,
                        system_id=service_name,
                        resource_id=resource_id,
                        locator=f"{service_name}/{key}[{index}]",
                        decoded=decoded,
                        provenance=_READBACK_PROVENANCE,
                    )
                )


def _decode_search_export(item: dict[str, object]) -> DecodedRecord:
    hits = item.get("hits")
    if isinstance(hits, dict):
        total = hits.get("total")
        documents = hits.get("documents")
        state, reason = decode_search_result(None, total)
        identifiers: list[str] = []
        pii_exposed = False
        if isinstance(documents, list):
            for document in documents:
                if not isinstance(document, dict):
                    continue
                for field in ("display_name", "email", "phone", "email_hash", "customer_reference"):
                    value = document.get(field)
                    if not is_null(value):
                        identifiers.append(str(value))
                        if field in {"display_name", "email", "phone", "email_hash"}:
                            pii_exposed = True
        inputs = {
            "total": "" if total is None else str(total),
            "documents": str(len(documents)) if isinstance(documents, list) else "",
        }
        return _decoded(
            "SEARCH_INDEX_ENTRY", state, reason, tuple(identifiers), inputs, pii_exposed=pii_exposed
        )
    state, reason = decode_search_result(None, hits)
    return _decoded(
        "SEARCH_INDEX_ENTRY",
        state,
        reason,
        (),
        {"hits": "" if hits is None else str(hits)},
    )


def _decode_service_item(
    service_name: str, key: str, item: dict[str, object]
) -> DecodedRecord | None:
    if service_name == "account_service" and key == "profile_lookups":
        return _decode_profile_lookup(item)
    if service_name == "analytics_platform" and key == "profiles":
        return decode_analytics_record(item)
    if service_name == "backup_service" and key == "restore_entries":
        return decode_backup_record(item)
    if service_name == "export_service" and key == "exports":
        return decode_export_record(item)
    if service_name == "integration_service" and key == "connectors":
        return decode_connector_record(item)
    if service_name == "search_service" and key == "index_queries":
        return _decode_search_export(item)
    if service_name == "security_service" and key == "audit_records":
        return decode_security_record(item)
    if service_name == "support_platform" and key == "tickets":
        return decode_support_record(item)
    return None


def _parse_ledger(
    payload: dict[str, object],
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    records = payload.get("records")
    if not isinstance(records, list):
        report.errors.append("ledger: records is not a list")
        return
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            report.errors.append(f"ledger: records[{index}] is not an object")
            continue
        resource_id = str(record.get("resource_id") or "").strip()
        system_id = str(record.get("system") or "").strip()
        if not resource_id or not system_id:
            report.errors.append(f"ledger: records[{index}] missing resource_id/system")
            continue
        observed_at = str(record.get("recorded_at") or captured_at)
        decoded = decode_lookup_record(record)
        observations.append(
            _observation(
                file_id=file_id,
                captured_at=observed_at,
                system_id=system_id,
                resource_id=resource_id,
                locator=f"records[{index}]",
                decoded=decoded,
                provenance=Provenance.LEDGER_RESULT,
            )
        )


def _parse_export_jobs(
    payload: dict[str, object],
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    records = payload.get("records")
    if not isinstance(records, list):
        report.errors.append("export_jobs: records is not a list")
        return
    observed_at = str(payload.get("captured_at") or captured_at)
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            report.errors.append(f"export_jobs: records[{index}] is not an object")
            continue
        resource_id = str(record.get("resource_id") or "").strip()
        if not resource_id:
            report.errors.append(f"export_jobs: records[{index}] without resource_id")
            continue
        decoded = decode_export_record(record)
        observations.append(
            _observation(
                file_id=file_id,
                captured_at=observed_at,
                system_id="export_service",
                resource_id=resource_id,
                locator=f"records[{index}]",
                decoded=decoded,
                provenance=Provenance.EXPLICIT_FIELD,
            )
        )


def _parse_analytics_report(
    payload: dict[str, object],
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    records = payload.get("records")
    if not isinstance(records, list):
        report.errors.append("analytics_report: records is not a list")
        return
    observed_at = str(payload.get("captured_at") or captured_at)
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            report.errors.append(f"analytics_report: records[{index}] is not an object")
            continue
        resource_id = str(record.get("resource_id") or "").strip()
        if not resource_id:
            report.errors.append(f"analytics_report: records[{index}] without resource_id")
            continue
        decoded = decode_analytics_record(record)
        observations.append(
            _observation(
                file_id=file_id,
                captured_at=observed_at,
                system_id="analytics_platform",
                resource_id=resource_id,
                locator=f"records[{index}]",
                decoded=decoded,
                provenance=Provenance.EXPLICIT_FIELD,
            )
        )


def _parse_handover(
    text: str,
    *,
    file_id: str,
    captured_at: str,
    report: ParseReport,
    observations: list[EvidenceObservation],
) -> None:
    for line_number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("-"):
            report.ignored_lines += 1
            continue
        match = HANDOVER_LINE.match(stripped)
        if match is None:
            report.errors.append(f"handover:{line_number}: malformed record line")
            continue
        observed_at = match.group(1).strip()
        system_id = match.group(2).strip()
        resource_id = match.group(3).strip()
        category = match.group(4).strip()
        status = match.group(5).strip()
        identifier = match.group(6).strip()
        state, reason = decode_result(status)
        observations.append(
            make_observation(
                file_id=file_id,
                captured_at=observed_at or captured_at,
                system_id=system_id,
                resource_id=resource_id,
                data_category=category or None,
                state=state,
                reason=reason,
                locator=f"line:{line_number}",
                provenance=Provenance.HANDOVER,
                identifiers=(identifier,) if clean(identifier) is not None else (),
                state_inputs={"status": status},
            )
        )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def parse_json_txt_file(
    file_id: str,
    path: Path,
    captured_at: str,
    family: str | None = None,
) -> ParseOutput:
    family_name = family or json_family(str(path))
    suffix = path.suffix.lower()
    report = ParseReport(
        file_id=file_id,
        family=f"{'txt' if suffix == '.txt' else 'json'}:{family_name}",
        captured_at=captured_at,
        sha256=file_sha256(path),
        status=ParseStatus.OK,
    )
    observations: list[EvidenceObservation] = []
    if family_name == "unknown":
        report.errors.append(f"unrecognized_json_family:{path.name}")
        report.status = ParseStatus.UNKNOWN_STATE
        return observations, report
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.errors.append(f"read_error:{exc}")
        report.status = ParseStatus.PARSE_ERROR
        return observations, report
    if family_name == HANDOVER_FAMILY:
        _parse_handover(
            text,
            file_id=file_id,
            captured_at=captured_at,
            report=report,
            observations=observations,
        )
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            report.errors.append(f"json_error:{exc}")
            report.status = ParseStatus.PARSE_ERROR
            return observations, report
        if not isinstance(payload, dict):
            report.errors.append("json_error: top-level value is not an object")
            report.status = ParseStatus.PARSE_ERROR
            return observations, report
        if family_name == "snapshot_bundle":
            _parse_bundle(
                payload,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
        elif family_name == "service_export":
            _parse_service_export(
                payload,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
        elif family_name == "ledger":
            _parse_ledger(
                payload,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
        elif family_name == "export_jobs":
            _parse_export_jobs(
                payload,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
        elif family_name == "analytics_report":
            _parse_analytics_report(
                payload,
                file_id=file_id,
                captured_at=captured_at,
                report=report,
                observations=observations,
            )
    report.status = finalize_status(report.errors, observations)
    return observations, report
