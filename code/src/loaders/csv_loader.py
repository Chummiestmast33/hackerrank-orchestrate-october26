"""CSV loaders for the participant-facing dataset files.

Rows are returned as typed dataclasses; malformed rows (missing columns, bad
ISO-8601 timestamps, duplicate keys) are reported as ``path:line: message``
strings and skipped. Nothing is inferred: absent or unparsable values stay
visible to the caller as errors.
"""

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MANIFEST_COLUMNS = ("file_id", "file_path", "origin", "captured_at")
REQUEST_COLUMNS = (
    "case_id",
    "email",
    "requested_at",
    "reported_status",
    "reported_at",
    "audit_at",
    "request_text",
)
IDENTITY_COLUMNS = ("user_id", "name", "email", "phone", "email_hash", "updated_at")
AUDIT_COLUMNS = ("audit_id", "user_id", "event_time", "field_name", "old_value", "new_value")
ACTIVITY_COLUMNS = (
    "activity_id",
    "event_time",
    "event_type",
    "source_system",
    "target_system",
    "resource_id",
    "reported_result",
    "details",
)
RULE_COLUMNS = ("rule_id", "data_category", "condition", "required_action")


@dataclass(frozen=True)
class EvidenceFileRow:
    file_id: str
    file_path: str
    origin: str
    captured_at: str


@dataclass(frozen=True)
class DeletionRequestRow:
    case_id: str
    email: str
    requested_at: str
    reported_status: str
    reported_at: str
    audit_at: str
    request_text: str


@dataclass(frozen=True)
class IdentityRow:
    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: str


@dataclass(frozen=True)
class AuditLogRow:
    audit_id: str
    user_id: str
    event_time: str
    field_name: str
    old_value: str
    new_value: str


@dataclass(frozen=True)
class ActivityRow:
    activity_id: str
    event_time: str
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


@dataclass(frozen=True)
class DeletionRuleRow:
    rule_id: str
    data_category: str
    condition: str
    required_action: str


def parse_iso8601(value: str) -> datetime | None:
    token = value.strip()
    if not token:
        return None
    try:
        return datetime.fromisoformat(token.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_csv_rows(
    path: Path,
    required_columns: tuple[str, ...],
    key_field: str,
    timestamp_fields: tuple[str, ...] = (),
) -> tuple[list[dict[str, str]], list[str]]:
    errors: list[str] = []
    rows: list[dict[str, str]] = []
    if not path.exists():
        return rows, [f"{path}: file not found"]
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        missing = [column for column in required_columns if column not in fieldnames]
        if missing:
            return rows, [f"{path}: missing columns {missing}"]
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            key = (row.get(key_field) or "").strip()
            if not key:
                errors.append(f"{path.name}:{line_number}: missing {key_field}")
                continue
            if key in seen:
                errors.append(f"{path.name}:{line_number}: duplicate {key_field} {key!r}")
                continue
            bad_timestamp = False
            for field in timestamp_fields:
                raw = row.get(field) or ""
                if parse_iso8601(raw) is None:
                    errors.append(f"{path.name}:{line_number}: invalid ISO-8601 {field} {raw!r}")
                    bad_timestamp = True
            if bad_timestamp:
                continue
            seen.add(key)
            rows.append(
                {key_: (value or "").strip() for key_, value in row.items() if key_ is not None}
            )
    return rows, errors


def load_evidence_manifest(path: Path) -> tuple[list[EvidenceFileRow], list[str]]:
    rows, errors = load_csv_rows(path, MANIFEST_COLUMNS, "file_id", ("captured_at",))
    parsed = [
        EvidenceFileRow(
            file_id=row["file_id"],
            file_path=row["file_path"],
            origin=row["origin"],
            captured_at=row["captured_at"],
        )
        for row in rows
    ]
    return parsed, errors


def load_deletion_requests(path: Path) -> tuple[list[DeletionRequestRow], list[str]]:
    rows, errors = load_csv_rows(
        path, REQUEST_COLUMNS, "case_id", ("requested_at", "reported_at", "audit_at")
    )
    parsed = [
        DeletionRequestRow(
            case_id=row["case_id"],
            email=row["email"],
            requested_at=row["requested_at"],
            reported_status=row["reported_status"],
            reported_at=row["reported_at"],
            audit_at=row["audit_at"],
            request_text=row["request_text"],
        )
        for row in rows
    ]
    return parsed, errors


def load_identities(path: Path) -> tuple[list[IdentityRow], list[str]]:
    rows, errors = load_csv_rows(path, IDENTITY_COLUMNS, "user_id", ("updated_at",))
    parsed = [
        IdentityRow(
            user_id=row["user_id"],
            name=row["name"],
            email=row["email"],
            phone=row["phone"],
            email_hash=row["email_hash"],
            updated_at=row["updated_at"],
        )
        for row in rows
    ]
    return parsed, errors


def load_audit_log(path: Path) -> tuple[list[AuditLogRow], list[str]]:
    rows, errors = load_csv_rows(path, AUDIT_COLUMNS, "audit_id", ("event_time",))
    parsed = [
        AuditLogRow(
            audit_id=row["audit_id"],
            user_id=row["user_id"],
            event_time=row["event_time"],
            field_name=row["field_name"],
            old_value=row["old_value"],
            new_value=row["new_value"],
        )
        for row in rows
    ]
    return parsed, errors


def load_activity(path: Path) -> tuple[list[ActivityRow], list[str]]:
    rows, errors = load_csv_rows(path, ACTIVITY_COLUMNS, "activity_id", ("event_time",))
    parsed = [
        ActivityRow(
            activity_id=row["activity_id"],
            event_time=row["event_time"],
            event_type=row["event_type"],
            source_system=row["source_system"],
            target_system=row["target_system"],
            resource_id=row["resource_id"],
            reported_result=row["reported_result"],
            details=row["details"],
        )
        for row in rows
    ]
    return parsed, errors


def load_rules(path: Path) -> tuple[list[DeletionRuleRow], list[str]]:
    rows, errors = load_csv_rows(path, RULE_COLUMNS, "rule_id")
    parsed = [
        DeletionRuleRow(
            rule_id=row["rule_id"],
            data_category=row["data_category"],
            condition=row["condition"],
            required_action=row["required_action"],
        )
        for row in rows
    ]
    return parsed, errors
