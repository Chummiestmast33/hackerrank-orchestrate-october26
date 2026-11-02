"""Unit tests for the explicit state decoders (P3.2)."""

from src.loaders import state_vocab as sv
from src.models import ObservationState


def test_decode_result_known_tokens() -> None:
    expected = {
        "FOUND": ObservationState.PRESENT,
        "NOT_FOUND": ObservationState.ABSENT,
        "IDENTIFIABLE": ObservationState.PRESENT,
        "ANONYMIZED": ObservationState.ANONYMIZED,
        "REDACTED": ObservationState.REDACTED,
        "ACTIVE": ObservationState.ACTIVE,
        "BLOCKED": ObservationState.BLOCKED,
        "DISABLED": ObservationState.DISABLED,
    }
    for token, state in expected.items():
        result, reason = sv.decode_result(token)
        assert result is state
        assert token in reason


def test_decode_result_unknown_and_missing() -> None:
    assert sv.decode_result("MAYBE")[0] is ObservationState.UNKNOWN
    assert "unknown_result:MAYBE" in sv.decode_result("MAYBE")[1]
    assert sv.decode_result(None)[0] is ObservationState.UNKNOWN
    assert "missing_field:result" in sv.decode_result("")[1]


def test_decode_enabled_and_restore_allowed() -> None:
    assert sv.decode_enabled("true")[0] is ObservationState.ACTIVE
    assert sv.decode_enabled("false")[0] is ObservationState.DISABLED
    assert sv.decode_enabled(None)[0] is ObservationState.UNKNOWN
    assert sv.decode_restore_allowed(1)[0] is ObservationState.ACTIVE
    assert sv.decode_restore_allowed(0)[0] is ObservationState.BLOCKED
    assert sv.decode_restore_allowed("maybe")[0] is ObservationState.UNKNOWN


def test_decode_restore_decision() -> None:
    assert sv.decode_restore_decision("deny")[0] is ObservationState.BLOCKED
    assert sv.decode_restore_decision("allow")[0] is ObservationState.ACTIVE
    assert sv.decode_restore_decision("later")[0] is ObservationState.UNKNOWN
    assert "unknown_decision:later" in sv.decode_restore_decision("later")[1]


def test_decode_account_readback() -> None:
    assert sv.decode_account_readback("0", "404")[0] is ObservationState.ABSENT
    assert sv.decode_account_readback("1", "200")[0] is ObservationState.PRESENT
    assert sv.decode_account_readback(None, None)[0] is ObservationState.UNKNOWN
    assert sv.decode_account_readback("abc", "500")[0] is ObservationState.UNKNOWN
    assert "inconclusive_readback" in sv.decode_account_readback("abc", "500")[1]


def test_decode_row_count() -> None:
    assert sv.decode_row_count("0")[0] is ObservationState.ABSENT
    assert sv.decode_row_count("2")[0] is ObservationState.PRESENT
    assert sv.decode_row_count(None)[0] is ObservationState.UNKNOWN


def test_decode_search_result() -> None:
    assert sv.decode_search_result(None, "0")[0] is ObservationState.ABSENT
    assert sv.decode_search_result(None, "3")[0] is ObservationState.PRESENT
    assert sv.decode_search_result("hit", None)[0] is ObservationState.PRESENT
    assert sv.decode_search_result("miss", None)[0] is ObservationState.ABSENT
    assert sv.decode_search_result("hit", "0")[0] is ObservationState.UNKNOWN
    assert sv.decode_search_result(None, None)[0] is ObservationState.UNKNOWN
    assert sv.decode_search_result("weird", None)[0] is ObservationState.UNKNOWN


def test_decode_analytics() -> None:
    assert sv.decode_analytics("0", {})[0] is ObservationState.ANONYMIZED
    assert sv.decode_analytics("2", {})[0] is ObservationState.PRESENT
    all_null = {"email": None, "phone": None, "email_hash": None}
    assert sv.decode_analytics(None, all_null)[0] is ObservationState.ANONYMIZED
    assert sv.decode_analytics(None, {"email": "x@y.z"})[0] is ObservationState.PRESENT
    assert sv.decode_analytics(None, {})[0] is ObservationState.UNKNOWN


def test_decode_profile_pii() -> None:
    fields = {"name": "A", "email": "a@x", "phone": None, "email_hash": None}
    assert sv.decode_profile_pii(fields, None)[0] is ObservationState.PRESENT
    null_fields = {"name": None, "email": None, "phone": None, "email_hash": None}
    assert sv.decode_profile_pii(null_fields, "user_1")[0] is ObservationState.REDACTED
    assert sv.decode_profile_pii(null_fields, None)[0] is ObservationState.UNKNOWN
    assert sv.decode_profile_pii({}, None)[0] is ObservationState.UNKNOWN


def test_decode_support() -> None:
    assert sv.decode_support({"requester_email": "a@x"}, None)[0] is ObservationState.PRESENT
    nulls = {"requester_name": None, "requester_email": None, "requester_phone": None}
    assert sv.decode_support(nulls, None)[0] is ObservationState.REDACTED
    assert sv.decode_support(nulls, "user_5")[0] is ObservationState.PRESENT
    assert sv.decode_support({}, None)[0] is ObservationState.UNKNOWN


def test_decode_matched_available_existence() -> None:
    assert sv.decode_matched_value("a@x")[0] is ObservationState.PRESENT
    assert sv.decode_matched_value(None)[0] is ObservationState.UNKNOWN
    assert sv.decode_available("true")[0] is ObservationState.PRESENT
    assert sv.decode_available("false")[0] is ObservationState.UNKNOWN
    assert "does_not_prove_absence" in sv.decode_available("false")[1]
    assert sv.decode_existence() == (ObservationState.PRESENT, "row_exists")


def test_null_helpers() -> None:
    assert sv.is_null(None) and sv.is_null("") and sv.is_null("null")
    assert not sv.is_null("x")
    assert sv.clean("  ") is None
    assert sv.clean(" x ") == "x"
