"""Unit tests for the deterministic PDF extractor (P4.2)."""

from pathlib import Path

import pytest
from src.loaders import pdf_extractor

DOCS = Path(__file__).resolve().parents[2] / "dataset" / "evidence" / "documents"


def require_docs() -> None:
    if not DOCS.exists():
        pytest.skip("dataset/evidence/documents not available")


def fields_of(record) -> dict[str, object]:  # type: ignore[no-untyped-def]
    return dict(record.fields)


def test_compliance_journal_extraction() -> None:
    require_docs()
    result = pdf_extractor.extract_pdf_records(
        "evidence_55", DOCS / "security_retention_extract.pdf"
    )
    assert result.family == "compliance_journal"
    assert result.diagnostics == []
    fields = fields_of(result.records[0])
    assert fields["event_reference"] == "audit_record_003"
    assert fields["subject_reference"] == "user_03"
    assert fields["journal_reference"] == "CJX-20260905-0630"
    assert "2027" in str(fields["retain_until"])
    assert "25 Aug 2026" in str(fields["recorded_at"])
    assert fields["integrity_seal"] == "valid"


def test_support_attachment_extraction() -> None:
    require_docs()
    result = pdf_extractor.extract_pdf_records(
        "evidence_58", DOCS / "delivery_correction_attachment.pdf"
    )
    assert result.family == "support_attachment"
    assert result.diagnostics == []
    fields = fields_of(result.records[0])
    assert fields["support_id"] == "support_001"
    assert fields["ticket_ref"] == "CS-4827"
    assert fields["requester_name"] == "Priya Raman"
    assert fields["requester_email"] == "priya.raman@gmail.com"
    assert "98765" in str(fields["requester_phone"])
    assert fields["order_ref"] == "ORD-20264827"
    assert fields["file_name"] == "delivery_address_correction.pdf"


def test_customer_statement_extraction() -> None:
    require_docs()
    result = pdf_extractor.extract_pdf_records(
        "evidence_18", DOCS / "account_history_report_20260718.pdf"
    )
    assert result.family == "customer_statement"
    assert result.diagnostics == []
    fields = fields_of(result.records[0])
    assert fields["statement_id"] == "NST-2026-0718-1842"
    assert fields["customer_name"] == "Ingrid Dahl"
    assert fields["user_id"] == "user_18"
    assert fields["email"] == "ingrid.dahl@outlook.com"
    assert fields["order_ref"] == "ORD-20261260"
    assert fields["item_sku"] == "LAMP-SD-04"


def test_retention_register_extraction() -> None:
    require_docs()
    result = pdf_extractor.extract_pdf_records(
        "evidence_27", DOCS / "legal_retention_register_20260529.pdf"
    )
    assert result.family == "retention_register"
    assert result.diagnostics == []
    assert len(result.records) == 6
    first = fields_of(result.records[0])
    assert first["order_ref"] == "ORD-20264118"
    assert first["user_id"] == "user_08"
    assert first["reason"] == "Card dispute"
    assert "2033" in str(first["retain_until"])
    assert first["owner"] == "AR"
    assert first["register_month"] == "May 2026"


def test_normalize_text_rejoins_times_and_drops_labels() -> None:
    raw = "issued 05 Sep 2026 06\n30 UTC\nRecord\nDetail\nCustomer Priya\nDetail"
    normalized = pdf_extractor.normalize_text(raw)
    assert "06:30 UTC" in normalized
    assert "Record" not in normalized.splitlines()
    assert "Detail" not in normalized.splitlines()
    assert "Customer Priya" in normalized


def test_unknown_header_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(pdf_extractor, "extract_text", lambda path: "Unrelated content")
    result = pdf_extractor.extract_pdf_records("evidence_x", tmp_path / "fake.pdf")
    assert result.family == "unknown"
    assert result.records == []
    assert "unknown_document_family" in result.diagnostics


def test_pdfplumber_fallback_used_when_primary_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pdf_extractor, "_pypdf_text", lambda path: "   ")
    monkeypatch.setattr(pdf_extractor, "_pdfplumber_text", lambda path: "fallback text")
    assert pdf_extractor.extract_text(tmp_path / "fake.pdf") == "fallback text"
