"""Per-collection decoding rules shared by the SQL and JSON parsers.

Collection names are explicit keys copied from the dataset (`collection_name`,
`collection`); an unknown collection is never decoded by guesswork — callers
record it as an error/UNKNOWN instead.
"""

from collections.abc import Callable
from dataclasses import dataclass

from ..models import ObservationState
from .state_vocab import (
    StateResult,
    clean,
    decode_analytics,
    decode_available,
    decode_enabled,
    decode_existence,
    decode_profile_pii,
    decode_restore_allowed,
    decode_result,
    decode_support,
    is_null,
)


@dataclass(frozen=True)
class DecodedRecord:
    data_category: str
    state: ObservationState
    reason: str
    identifiers: tuple[str, ...]
    pii_exposed: bool
    state_inputs: dict[str, str]


RuleFunc = Callable[[dict[str, object]], DecodedRecord]


def _first(record: dict[str, object], *keys: str) -> object:
    for key in keys:
        if key in record:
            return record[key]
    return None


def _join_identifiers(*values: object) -> tuple[str, ...]:
    found: list[str] = []
    for value in values:
        if isinstance(value, list):
            found.extend(str(item) for item in value if not is_null(item))
        elif not is_null(value):
            found.append(str(value))
    return tuple(sorted({item.strip() for item in found if item.strip()}))


def _inputs(**values: object) -> dict[str, str]:
    return {key: "" if value is None else str(value) for key, value in values.items()}


def _decoded(
    category: str,
    result: StateResult,
    identifiers: tuple[str, ...],
    inputs: dict[str, str],
    pii_exposed: bool = False,
) -> DecodedRecord:
    state, reason = result
    return DecodedRecord(
        data_category=category,
        state=state,
        reason=reason,
        identifiers=identifiers,
        pii_exposed=pii_exposed,
        state_inputs=inputs,
    )


def decode_profile_record(record: dict[str, object]) -> DecodedRecord:
    fields = {
        "name": _first(record, "full_name", "display_name", "name"),
        "email": record.get("email"),
        "phone": record.get("phone"),
        "email_hash": record.get("email_hash"),
    }
    reference = _first(record, "customer_reference", "user_id", "subject_reference")
    result = decode_profile_pii(fields, reference)
    exposed = any(not is_null(value) for value in fields.values())
    return _decoded(
        "USER_PROFILE",
        result,
        _join_identifiers(
            fields["name"], fields["email"], fields["phone"], fields["email_hash"], reference
        ),
        _inputs(**fields, customer_reference=reference),
        pii_exposed=exposed,
    )


def decode_search_record(record: dict[str, object]) -> DecodedRecord:
    document = record.get("document")
    if document is None and "document" in record:
        return _decoded(
            "SEARCH_INDEX_ENTRY",
            (ObservationState.UNKNOWN, "missing_field:document"),
            (),
            _inputs(document=document),
        )
    inner = document if isinstance(document, dict) else record
    fields = {
        "name": _first(inner, "display_name", "full_name"),
        "email": inner.get("email"),
        "phone": inner.get("phone"),
        "email_hash": inner.get("email_hash"),
    }
    reference = _first(inner, "customer_reference", "user_id")
    result = decode_profile_pii(fields, reference)
    exposed = any(not is_null(value) for value in fields.values())
    return _decoded(
        "SEARCH_INDEX_ENTRY",
        result,
        _join_identifiers(
            fields["name"], fields["email"], fields["phone"], fields["email_hash"], reference
        ),
        _inputs(**fields, customer_reference=reference),
        pii_exposed=exposed,
    )


def decode_analytics_record(record: dict[str, object]) -> DecodedRecord:
    pii = {
        "customer_reference": _first(record, "customer_reference", "user_id"),
        "email": record.get("email"),
        "phone": record.get("phone"),
        "email_hash": record.get("email_hash"),
    }
    result = decode_analytics(record.get("direct_identifiers"), pii)
    exposed = any(not is_null(value) for value in pii.values())
    return _decoded(
        "ANALYTICS_PROFILE",
        result,
        _join_identifiers(pii["customer_reference"], pii["email"], pii["phone"], pii["email_hash"]),
        _inputs(**pii, direct_identifiers=record.get("direct_identifiers")),
        pii_exposed=exposed,
    )


def decode_support_record(record: dict[str, object]) -> DecodedRecord:
    fields = {
        "requester_name": record.get("requester_name"),
        "requester_email": record.get("requester_email"),
        "requester_phone": record.get("requester_phone"),
    }
    reference = record.get("subject_reference")
    result = decode_support(fields, reference)
    exposed = any(not is_null(value) for value in fields.values())
    return _decoded(
        "SUPPORT_MESSAGE",
        result,
        _join_identifiers(
            fields["requester_name"],
            fields["requester_email"],
            fields["requester_phone"],
            reference,
        ),
        _inputs(**fields, subject_reference=reference),
        pii_exposed=exposed,
    )


def decode_attachment_record(record: dict[str, object]) -> DecodedRecord:
    return _decoded(
        "SUPPORT_ATTACHMENT",
        decode_existence(),
        _join_identifiers(record.get("uploaded_by"), record.get("subject_reference")),
        _inputs(file_name=record.get("file_name"), ticket_id=record.get("ticket_id")),
        pii_exposed=not is_null(record.get("uploaded_by")),
    )


def decode_export_record(record: dict[str, object]) -> DecodedRecord:
    available = record.get("available")
    if available is None:
        result = decode_existence()
    else:
        result = decode_available(available)
    return _decoded(
        "USER_EXPORT",
        result,
        _join_identifiers(
            record.get("owner_email"), record.get("owner_phone"), record.get("customer_reference")
        ),
        _inputs(owner_email=record.get("owner_email"), available=available),
        pii_exposed=not is_null(record.get("owner_email")),
    )


def decode_connector_record(record: dict[str, object]) -> DecodedRecord:
    return _decoded(
        "DATA_FLOW",
        decode_enabled(record.get("enabled")),
        _join_identifiers(
            record.get("customer_email"),
            record.get("customer_reference"),
            record.get("subject_selector"),
        ),
        _inputs(enabled=record.get("enabled"), connector_name=record.get("connector_name")),
        pii_exposed=not is_null(record.get("customer_email")),
    )


def decode_backup_record(record: dict[str, object]) -> DecodedRecord:
    return _decoded(
        "BACKUP_ARCHIVE",
        decode_restore_allowed(record.get("restore_allowed")),
        _join_identifiers(
            record.get("customer_email"),
            record.get("customer_reference"),
            record.get("subject_reference"),
        ),
        _inputs(
            restore_allowed=record.get("restore_allowed"), archive_path=record.get("archive_path")
        ),
        pii_exposed=not is_null(record.get("customer_email")),
    )


def decode_security_record(record: dict[str, object]) -> DecodedRecord:
    return _decoded(
        "SECURITY_AUDIT_LOG",
        decode_existence(),
        _join_identifiers(record.get("subject_reference")),
        _inputs(retention_until=record.get("retention_until"), event=record.get("event_name")),
    )


def decode_tombstone_record(record: dict[str, object]) -> DecodedRecord:
    fields = {
        "name": record.get("name"),
        "email": record.get("email"),
        "phone": record.get("phone"),
        "email_hash": record.get("email_hash"),
    }
    reference = record.get("subject_reference")
    exposed = any(not is_null(value) for value in fields.values())
    if exposed:
        result: StateResult = (ObservationState.PRESENT, "leaked_direct_identifiers")
    elif not is_null(reference):
        result = (ObservationState.REDACTED, "all_direct_identifiers_null,reference_present")
    else:
        result = (ObservationState.UNKNOWN, "all_direct_identifiers_null,no_reference")
    return _decoded(
        "ACCOUNT_TOMBSTONE",
        result,
        _join_identifiers(*fields.values(), reference),
        _inputs(**fields, subject_reference=reference),
        pii_exposed=exposed,
    )


def decode_legal_record(record: dict[str, object]) -> DecodedRecord:
    return _decoded(
        "LEGAL_HOLD_RECORD",
        decode_existence(),
        _join_identifiers(record.get("subject_reference")),
        _inputs(retained_until=record.get("retained_until")),
    )


def decode_lookup_record(record: dict[str, object]) -> DecodedRecord:
    category = clean(record.get("record_type")) or "UNKNOWN"
    return _decoded(
        category,
        decode_result(record.get("result")),
        _join_identifiers(record.get("lookup_value"), record.get("subject_reference")),
        _inputs(result=record.get("result"), record_type=record.get("record_type")),
    )


COLLECTION_RULES: dict[str, RuleFunc] = {
    "customer_profiles": decode_profile_record,
    "customer_search_documents": decode_search_record,
    "customer_analytics_profiles": decode_analytics_record,
    "customer_analytics_reports": decode_analytics_record,
    "support_records": decode_support_record,
    "support_conversations": decode_support_record,
    "ticket_attachments": decode_attachment_record,
    "customer_exports": decode_export_record,
    "customer_export_jobs": decode_export_record,
    "connector_subscriptions": decode_connector_record,
    "connector_configurations": decode_connector_record,
    "backup_restore_entries": decode_backup_record,
    "backup_catalog": decode_backup_record,
    "security_audit_records": decode_security_record,
    "security_audit_events": decode_security_record,
    "deleted_customer_references": decode_tombstone_record,
    "retained_order_records": decode_legal_record,
    "operational_record_history": decode_lookup_record,
}
