"""Unit tests for ExtractedRecord and the extended ParseReport (P4.1)."""

from src.models import ExtractedRecord, ParseReport, ParseStatus, Provenance

CAPTURED = "2026-09-12T07:30:00Z"


def sample_record() -> ExtractedRecord:
    return ExtractedRecord(
        file_id="evidence_58",
        family="support_attachment",
        record_index=0,
        fields=(("support_id", "support_001"), ("requester_email", "priya.raman@gmail.com")),
        source="pdf_text",
        confidence_flags=("manual_reviewed",),
    )


def test_extracted_record_roundtrip_and_field_access() -> None:
    record = sample_record()
    data = record.to_dict()
    assert data["fields"] == {
        "support_id": "support_001",
        "requester_email": "priya.raman@gmail.com",
    }
    assert ExtractedRecord.from_dict(data) == record
    assert record.field("support_id") == "support_001"
    assert record.field("missing") is None


def test_parse_report_roundtrip_with_extracted_records() -> None:
    record = sample_record()
    report = ParseReport(
        file_id="evidence_58",
        family="pdf:support_attachment",
        captured_at=CAPTURED,
        sha256="abc",
        status=ParseStatus.OK,
        extracted_records=(record,),
    )
    restored = ParseReport.from_dict(report.to_dict())
    assert restored.extracted_records == (record,)
    assert restored.status is ParseStatus.OK


def test_parse_report_back_compat_without_extracted_records() -> None:
    report = ParseReport(
        file_id="evidence_01",
        family="log",
        captured_at=CAPTURED,
        sha256="abc",
        status=ParseStatus.OK,
    )
    payload = report.to_dict()
    del payload["extracted_records"]
    restored = ParseReport.from_dict(payload)
    assert restored.extracted_records == ()


def test_provenance_values_added() -> None:
    assert Provenance.DOCUMENT_TEXT.value == "DOCUMENT_TEXT"
    assert Provenance.VISION_TRANSCRIPTION.value == "VISION_TRANSCRIPTION"
