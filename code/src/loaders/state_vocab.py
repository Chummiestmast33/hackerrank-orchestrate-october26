"""Explicit raw-field to state decoders.

Every function returns ``(state, reason)``. Unknown values produce
``ObservationState.UNKNOWN`` with a reason such as ``missing_field:rows`` or
``unknown_result:MAYBE``; no decoder silently defaults to PRESENT or ABSENT.
"""

from collections.abc import Mapping

from ..models import ObservationState

StateResult = tuple[ObservationState, str]

# Shared vocabulary used by the handover text and the ledger-style JSON families.
RESULT_TO_STATE: dict[str, ObservationState] = {
    "NOT_FOUND": ObservationState.ABSENT,
    "FOUND": ObservationState.PRESENT,
    "IDENTIFIABLE": ObservationState.PRESENT,
    "ANONYMIZED": ObservationState.ANONYMIZED,
    "REDACTED": ObservationState.REDACTED,
    "ACTIVE": ObservationState.ACTIVE,
    "BLOCKED": ObservationState.BLOCKED,
    "DISABLED": ObservationState.DISABLED,
}

BOOLEAN_TRUE = {"true", "1", "yes", "enabled", "allowed"}
BOOLEAN_FALSE = {"false", "0", "no", "disabled", "denied"}


def is_null(value: object) -> bool:
    """Treat None, empty strings and the literal 'null' as null."""
    if value is None:
        return True
    return str(value).strip().lower() in {"", "null", "none"}


def clean(value: object) -> str | None:
    return None if is_null(value) else str(value).strip()


def decode_result(value: object) -> StateResult:
    token = clean(value)
    if token is None:
        return ObservationState.UNKNOWN, "missing_field:result"
    state = RESULT_TO_STATE.get(token.upper())
    if state is None:
        return ObservationState.UNKNOWN, f"unknown_result:{token}"
    return state, f"result={token}"


def decode_boolean(
    value: object, true_state: ObservationState, false_state: ObservationState
) -> StateResult:
    token = clean(value)
    if token is None:
        return ObservationState.UNKNOWN, "missing_field:boolean"
    lowered = token.lower()
    if lowered in BOOLEAN_TRUE:
        return true_state, f"boolean={token}"
    if lowered in BOOLEAN_FALSE:
        return false_state, f"boolean={token}"
    return ObservationState.UNKNOWN, f"unknown_boolean:{token}"


def decode_enabled(value: object) -> StateResult:
    return decode_boolean(value, ObservationState.ACTIVE, ObservationState.DISABLED)


def decode_restore_allowed(value: object) -> StateResult:
    return decode_boolean(value, ObservationState.ACTIVE, ObservationState.BLOCKED)


def decode_restore_decision(value: object) -> StateResult:
    token = clean(value)
    if token is None:
        return ObservationState.UNKNOWN, "missing_field:decision"
    lowered = token.lower()
    if lowered == "deny":
        return ObservationState.BLOCKED, f"decision={token}"
    if lowered == "allow":
        return ObservationState.ACTIVE, f"decision={token}"
    return ObservationState.UNKNOWN, f"unknown_decision:{token}"


def _as_count(value: object) -> int | None:
    token = clean(value)
    if token is None:
        return None
    try:
        return int(token)
    except ValueError:
        return None


def decode_account_readback(rows: object, http_status: object) -> StateResult:
    row_count = _as_count(rows)
    status = _as_count(http_status)
    if row_count is None and status is None:
        return ObservationState.UNKNOWN, "missing_field:rows_and_http_status"
    if status == 404 or row_count == 0:
        return ObservationState.ABSENT, f"rows={rows},http_status={http_status}"
    if row_count is not None and row_count >= 1:
        return ObservationState.PRESENT, f"rows={rows},http_status={http_status}"
    if status == 200:
        return ObservationState.PRESENT, f"rows={rows},http_status={http_status}"
    return ObservationState.UNKNOWN, f"inconclusive_readback:rows={rows},http_status={http_status}"


def decode_row_count(rows: object) -> StateResult:
    row_count = _as_count(rows)
    if row_count is None:
        return ObservationState.UNKNOWN, "missing_field:rows"
    if row_count == 0:
        return ObservationState.ABSENT, f"rows={rows}"
    return ObservationState.PRESENT, f"rows={rows}"


def decode_search_result(result: object, total_hits: object = None) -> StateResult:
    hits = _as_count(total_hits)
    token = clean(result)
    if hits is not None:
        if hits == 0:
            if token is not None and token.lower() in {"hit", "found"}:
                return ObservationState.UNKNOWN, "conflicting_fields:total_hits=0,result=hit"
            return ObservationState.ABSENT, f"total_hits={total_hits}"
        return ObservationState.PRESENT, f"total_hits={total_hits}"
    if token is None:
        return ObservationState.UNKNOWN, "missing_field:total_hits_and_result"
    lowered = token.lower()
    if lowered in {"miss", "not_found", "not found"}:
        return ObservationState.ABSENT, f"result={token}"
    if lowered in {"hit", "found"}:
        return ObservationState.PRESENT, f"result={token}"
    return ObservationState.UNKNOWN, f"unknown_result:{token}"


def decode_analytics(direct_identifiers: object, pii_values: Mapping[str, object]) -> StateResult:
    count = _as_count(direct_identifiers)
    if count is not None:
        if count == 0:
            return ObservationState.ANONYMIZED, f"direct_identifiers={direct_identifiers}"
        return ObservationState.PRESENT, f"direct_identifiers={direct_identifiers}"
    provided = [value for value in pii_values.values() if not is_null(value)]
    keys = list(pii_values)
    if not keys:
        return ObservationState.UNKNOWN, "missing_field:direct_identifiers"
    if provided:
        return ObservationState.PRESENT, "pii_fields_present"
    return ObservationState.ANONYMIZED, "all_pii_fields_null"


def decode_profile_pii(identifier_fields: Mapping[str, object], reference: object) -> StateResult:
    """Profile-like records: any direct identifier => PRESENT, else tombstone check."""
    if not identifier_fields:
        return ObservationState.UNKNOWN, "missing_field:identifier_fields"
    exposed = [name for name, value in identifier_fields.items() if not is_null(value)]
    if exposed:
        return ObservationState.PRESENT, "direct_identifiers_present:" + ",".join(sorted(exposed))
    if not is_null(reference):
        return ObservationState.REDACTED, "all_direct_identifiers_null,reference_present"
    return ObservationState.UNKNOWN, "all_direct_identifiers_null,no_reference"


def decode_support(requester_fields: Mapping[str, object], reference: object = None) -> StateResult:
    if not requester_fields:
        return ObservationState.UNKNOWN, "missing_field:requester_fields"
    exposed = [name for name, value in requester_fields.items() if not is_null(value)]
    if exposed:
        return ObservationState.PRESENT, "direct_identifiers_present:" + ",".join(sorted(exposed))
    if not is_null(reference):
        return ObservationState.PRESENT, "subject_reference_present"
    return ObservationState.REDACTED, "all_requester_fields_null"


def decode_matched_value(value: object) -> StateResult:
    token = clean(value)
    if token is None:
        return ObservationState.UNKNOWN, "missing_field:matched_value"
    return ObservationState.PRESENT, "pii_scan_matched"


def decode_available(value: object) -> StateResult:
    token = clean(value)
    if token is None:
        return ObservationState.UNKNOWN, "missing_field:available"
    lowered = token.lower()
    if lowered in BOOLEAN_TRUE:
        return ObservationState.PRESENT, f"available={token}"
    if lowered in BOOLEAN_FALSE:
        return ObservationState.UNKNOWN, "available_false_does_not_prove_absence"
    return ObservationState.UNKNOWN, f"unknown_available:{token}"


def decode_existence() -> StateResult:
    return ObservationState.PRESENT, "row_exists"
