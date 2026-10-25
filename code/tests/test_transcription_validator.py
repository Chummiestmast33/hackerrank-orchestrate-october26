"""Unit tests for the transcription validator (P4.6)."""

from src.loaders.csv_loader import AuditLogRow, IdentityRow
from src.loaders.transcription_validator import (
    build_known_identifiers,
    normalize_identifier,
    validate_transcription,
)
from src.loaders.vlm_extractor import FAMILY_FIELDS


def full_fields(family: str, **overrides: object) -> dict[str, object]:
    fields: dict[str, object] = dict.fromkeys(FAMILY_FIELDS[family])
    fields.update(overrides)
    return fields


def known() -> set[str]:
    return {
        "haruka.s1838@zoho.com",
        "user_11",
        "819076102507",
        "haruka sato",
    }


def test_valid_fields_have_no_errors_or_flags() -> None:
    report = validate_transcription(
        "account_console",
        full_fields(
            "account_console",
            name="Haruka Sato",
            user_id="user_11",
            account_id="account_5762",
            email="haruka.s1838@zoho.com",
            phone="+81 90 7610 2507",
            orders=[{"order_id": "ORD-20265762", "status": "Delivered"}],
        ),
        known(),
    )
    assert report.errors == []
    assert report.flags == []


def test_missing_and_unexpected_fields_are_schema_errors() -> None:
    fields = full_fields("account_console")
    del fields["name"]
    fields["surprise"] = "x"
    report = validate_transcription("account_console", fields, known())
    assert "schema_violation:missing:name" in report.errors
    assert "schema_violation:unexpected:surprise" in report.errors


def test_wrong_container_types_are_schema_errors() -> None:
    report = validate_transcription(
        "account_console",
        full_fields("account_console", orders="not-a-list", support_ref=["x"]),
        known(),
    )
    assert "schema_violation:not_a_list:orders" in report.errors
    assert "schema_violation:not_an_object:support_ref" in report.errors


def test_invalid_email_and_phone_formats() -> None:
    report = validate_transcription(
        "account_console",
        full_fields("account_console", email="bad@@x", phone="+12"),
        known(),
    )
    assert any(error.startswith("invalid_email:") for error in report.errors)
    assert any(error.startswith("invalid_phone:") for error in report.errors)


def test_unverified_identifiers_are_flagged_not_dropped() -> None:
    report = validate_transcription(
        "account_console",
        full_fields(
            "account_console",
            email="stranger@example.test",
            phone="+1 555 010 9999",
            user_id="user_999",
        ),
        known(),
    )
    assert report.errors == []
    assert "identifier_unverified:stranger@example.test" in report.flags
    assert "identifier_unverified:+1 555 010 9999" in report.flags
    assert "identifier_unverified:user_999" in report.flags
    assert report.fields["email"] == "stranger@example.test"


def test_known_identifiers_match_case_and_phone_formatting() -> None:
    report = validate_transcription(
        "account_console",
        full_fields(
            "account_console",
            email="HARUKA.S1838@ZOHO.COM",
            phone="+81 90 7610 2507",
            user_id="USER_11",
        ),
        known(),
    )
    assert report.flags == []


def test_invalid_resource_prefix_is_an_error() -> None:
    report = validate_transcription(
        "account_console",
        full_fields("account_console", account_id="banana_12"),
        known(),
    )
    assert any(error.startswith("invalid_resource_prefix:banana_12") for error in report.errors)


def test_unknown_family_is_an_error() -> None:
    report = validate_transcription("mystery", {"x": 1}, known())
    assert "unknown_family:mystery" in report.errors


def test_normalize_identifier_and_build_known() -> None:
    assert normalize_identifier("  +81 90 7610 2507 ") == "819076102507"
    assert normalize_identifier("A@EXAMPLE.TEST ") == "a@example.test"
    identities = [
        IdentityRow(
            user_id="user_11",
            name="Haruka Sato",
            email="haruka.s1838@zoho.com",
            phone="+81 90 7610 2507",
            email_hash="hash",
            updated_at="2026-01-01T00:00:00Z",
        )
    ]
    audit = [
        AuditLogRow(
            audit_id="audit_1",
            user_id="user_11",
            event_time="2025-01-01T00:00:00Z",
            field_name="email",
            old_value="old@example.test",
            new_value="haruka.s1838@zoho.com",
        )
    ]
    known_values = build_known_identifiers(identities, audit)
    assert "819076102507" in known_values
    assert "haruka.s1838@zoho.com" in known_values
    assert "old@example.test" in known_values
    assert "haruka sato" in known_values
