"""Unit tests for PDF decode tables and metadata-only relations (P4.3)."""

from src.loaders.csv_loader import ActivityRow
from src.loaders.multimodal_rules import decode_pdf_records, relate_to_structured
from src.models import (
    EvidenceObservation,
    ExtractedRecord,
    ObservationState,
    ParseReport,
    ParseStatus,
    Provenance,
    make_observation,
)

CAPTURED = "2026-09-12T07:30:00Z"


def record(
    family: str,
    fields: dict[str, object],
    file_id: str = "evidence_syn",
    index: int = 0,
) -> ExtractedRecord:
    return ExtractedRecord(
        file_id=file_id,
        family=family,
        record_index=index,
        fields=tuple(fields.items()),
        source="pdf_text",
    )


def test_support_attachment_decodes_present_with_pii() -> None:
    observations, diagnostics = decode_pdf_records(
        [
            record(
                "support_attachment",
                {
                    "support_id": "support_001",
                    "ticket_ref": "CS-4827",
                    "requester_name": "Priya Raman",
                    "requester_email": "priya.raman@gmail.com",
                    "requester_phone": "+91 98765 73142",
                },
            )
        ],
        captured_at=CAPTURED,
    )
    assert diagnostics == []
    (observation,) = observations
    assert observation.system_id == "support_platform"
    assert observation.resource_id == "support_001"
    assert observation.data_category == "SUPPORT_ATTACHMENT"
    assert observation.state is ObservationState.PRESENT
    assert observation.provenance is Provenance.DOCUMENT_TEXT
    assert observation.pii_exposed is True
    assert "priya.raman@gmail.com" in observation.identifiers


def test_compliance_journal_decodes_present_with_retention() -> None:
    observations, diagnostics = decode_pdf_records(
        [
            record(
                "compliance_journal",
                {
                    "event_reference": "audit_record_003",
                    "subject_reference": "user_03",
                    "retain_until": "25 Aug 2027 04:03 UTC",
                    "recorded_at": "25 Aug 2026 04:03 UTC",
                    "event_name": "Account closure recorded",
                },
            )
        ],
        captured_at=CAPTURED,
    )
    assert diagnostics == []
    (observation,) = observations
    assert observation.system_id == "security_service"
    assert observation.resource_id == "audit_record_003"
    assert observation.state is ObservationState.PRESENT
    assert ("retain_until", "25 Aug 2027 04:03 UTC") in observation.state_inputs
    assert observation.identifiers == ("user_03",)


def test_register_and_statement_produce_facts_only() -> None:
    observations, diagnostics = decode_pdf_records(
        [
            record("retention_register", {"order_ref": "ORD-20264118", "user_id": "user_08"}),
            record("customer_statement", {"user_id": "user_18", "order_ref": "ORD-20261260"}),
        ],
        captured_at=CAPTURED,
    )
    assert observations == []
    assert diagnostics == []


def test_missing_required_fields_are_diagnostics() -> None:
    observations, diagnostics = decode_pdf_records(
        [
            record("support_attachment", {"ticket_ref": "CS-1"}),
            record("compliance_journal", {"event_reference": "audit_record_9"}, index=1),
            record("mystery_document", {"x": "y"}, index=2),
        ],
        captured_at=CAPTURED,
    )
    assert observations == []
    assert "missing_field:support_id:0" in diagnostics
    assert "missing_field:subject_reference:1" in diagnostics
    assert "unknown_document_family:mystery_document" in diagnostics


def _observation(
    resource_id: str,
    system_id: str,
    state: ObservationState,
    identifiers: tuple[str, ...] = (),
) -> EvidenceObservation:
    return make_observation(
        file_id="evidence_01",
        captured_at=CAPTURED,
        system_id=system_id,
        resource_id=resource_id,
        data_category="TEST",
        state=state,
        reason="test",
        locator="test",
        provenance=Provenance.EXPLICIT_FIELD,
        identifiers=identifiers,
    )


def _activity(activity_id: str, resource_id: str, details: str) -> ActivityRow:
    return ActivityRow(
        activity_id=activity_id,
        event_time=CAPTURED,
        event_type="LINK_RESOURCE_IDENTITY",
        source_system="data_catalog",
        target_system="account_service",
        resource_id=resource_id,
        reported_result="SUCCESS",
        details=details,
    )


def test_relations_are_metadata_only_and_grounded() -> None:
    report = ParseReport(
        file_id="evidence_01",
        family="test",
        captured_at=CAPTURED,
        sha256="0",
        status=ParseStatus.OK,
    )
    index = {
        "evidence_01": (
            [
                _observation(
                    "account_5762",
                    "account_service",
                    ObservationState.ABSENT,
                    ("haruka.s1838@zoho.com",),
                )
            ],
            report,
        )
    }
    activity = [
        _activity("activity_4000", "account_5762", "linked to haruka.s1838@zoho.com and user_11"),
        _activity(
            "activity_4010", "audit_record_003", "linked to oliver-bennett@gmail.com and user_03"
        ),
    ]
    records = [
        record(
            "customer_statement",
            {
                "account_id": "account_5762",
                "email": "haruka.s1838@zoho.com",
                "user_id": "user_11",
                "order_ref": "ORD-20261260",
            },
        ),
        record(
            "compliance_journal",
            {
                "event_reference": "audit_record_003",
                "subject_reference": "user_03",
            },
            index=1,
        ),
    ]
    relations = relate_to_structured(records, index, activity)
    by_token = {relation.token: relation for relation in relations}
    assert by_token["account_5762"].status == "matched"
    assert by_token["account_5762"].matches == (("evidence_01", "account_service", "ABSENT"),)
    assert by_token["haruka.s1838@zoho.com"].status == "matched"
    assert by_token["user_11"].status == "linked_only"
    assert by_token["ORD-20261260"].status == "sole_source"
    assert by_token["ORD-20261260"].kind == "reference"
    assert by_token["audit_record_003"].status == "linked_only"
    assert by_token["audit_record_003"].link_activity_ids == ("activity_4010",)
    assert by_token["user_03"].status == "linked_only"
    assert all(relation.status != "conflict" for relation in relations)
    # Deterministic ordering by token/kind.
    assert [relation.token for relation in relations] == sorted(by_token)


def test_relations_empty_index_marks_everything_sole_source() -> None:
    records = [
        record(
            "support_attachment", {"support_id": "support_001", "requester_email": "p@example.test"}
        )
    ]
    relations = relate_to_structured(records, {})
    statuses = {relation.token: relation.status for relation in relations}
    assert statuses == {"support_001": "sole_source", "p@example.test": "sole_source"}
