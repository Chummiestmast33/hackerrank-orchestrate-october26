"""Unit tests for multimodal integration (P4.8): PDF dispatch, PNG store, offline."""

from pathlib import Path

import pytest
from src.evaluation.metering import Meter
from src.loaders import multimodal_parser
from src.loaders.common import file_sha256
from src.loaders.multimodal_parser import parse_multimodal_file
from src.loaders.transcription_store import TranscriptionEntry, save_store, store_key
from src.loaders.vlm_extractor import FAMILY_FIELDS, PROMPT_VERSION, VisionConfig
from src.models import ParseStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS = REPO_ROOT / "dataset" / "evidence" / "documents"
CAPTURED = "2026-09-12T07:30:00Z"


def account_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = dict.fromkeys(FAMILY_FIELDS["account_console"])
    fields.update(overrides)
    return fields


def make_png(tmp_path: Path) -> Path:
    path = tmp_path / "account_admin_console.png"
    path.write_bytes(b"fake-png-bytes")
    return path


def write_store(store_path: Path, image_path: Path, fields: dict[str, object], disagreements=()):  # type: ignore[no-untyped-def]
    sha = file_sha256(image_path)
    entry = TranscriptionEntry(
        file_id="evidence_04",
        sha256=sha,
        prompt_version=PROMPT_VERSION,
        model_a="model-a",
        model_b="model-b",
        pass_a=fields,
        pass_b=fields,
        merged=fields,
        disagreements=tuple(disagreements),
    )
    save_store(store_path, {store_key(sha, PROMPT_VERSION, "model-a", "model-b"): entry})
    return entry


def test_pdf_support_attachment_decodes_offline() -> None:
    if not DOCS.exists():
        pytest.skip("dataset/evidence/documents not available")
    observations, report = parse_multimodal_file(
        "evidence_58",
        DOCS / "delivery_correction_attachment.pdf",
        CAPTURED,
        origin="support_platform",
    )
    assert report.status is ParseStatus.OK
    assert report.family == "pdf:support_attachment"
    assert report.extracted_records
    assert observations[0].resource_id == "support_001"
    assert observations[0].state.value == "PRESENT"
    assert observations[0].pii_exposed is True


def test_pdf_facts_only_document_has_no_observations() -> None:
    if not DOCS.exists():
        pytest.skip("dataset/evidence/documents not available")
    observations, report = parse_multimodal_file(
        "evidence_18",
        DOCS / "account_history_report_20260718.pdf",
        "2026-07-18T11:00:00Z",
        origin="account_history_service",
    )
    assert report.status is ParseStatus.OK
    assert report.family == "pdf:customer_statement"
    assert report.extracted_records
    assert observations == []


def test_unknown_pdf_is_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "mystery.pdf"
    path.write_bytes(b"%PDF-1.4 fake")
    observations, report = parse_multimodal_file(
        "evidence_x", path, CAPTURED, origin="support_platform"
    )
    assert observations == []
    assert report.status is ParseStatus.PARSE_ERROR
    assert "unknown_document_family" in report.errors


def test_png_store_hit_decodes_without_calls(tmp_path: Path) -> None:
    image_path = make_png(tmp_path)
    store_path = tmp_path / "store.json"
    write_store(
        store_path,
        image_path,
        account_fields(
            account_id="account_5762",
            email="haruka.s1838@zoho.com",
            user_id="user_11",
        ),
    )
    observations, report = parse_multimodal_file(
        "evidence_04",
        image_path,
        CAPTURED,
        origin="account_admin_portal",
        store_path=store_path,
    )
    assert report.status is ParseStatus.OK
    assert report.family == "png:account_console"
    assert observations[0].resource_id == "account_5762"
    assert observations[0].provenance.value == "VISION_TRANSCRIPTION"
    assert report.extracted_records[0].source == "vlm"


def test_png_offline_miss_is_unsupported(tmp_path: Path) -> None:
    image_path = make_png(tmp_path)
    observations, report = parse_multimodal_file(
        "evidence_04",
        image_path,
        CAPTURED,
        origin="account_admin_portal",
        store_path=tmp_path / "missing.json",
    )
    assert observations == []
    assert report.status is ParseStatus.UNSUPPORTED_FORMAT
    assert "extraction_unavailable" in report.errors


def test_png_model_path_persists_and_decodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_path = make_png(tmp_path)
    store_path = tmp_path / "store.json"
    fields = account_fields(
        account_id="account_5762",
        email="haruka.s1838@zoho.com",
        user_id="user_11",
    )

    def fake_transcribe(*args, **kwargs):  # type: ignore[no-untyped-def]
        return write_store(store_path, image_path, fields)

    monkeypatch.setattr(multimodal_parser, "transcribe_two_pass", fake_transcribe)
    config = VisionConfig(
        provider="qwen",
        model="model-a",
        model_pass_b="model-b",
        base_url="http://example.test",
        api_key="key",
    )
    observations, report = parse_multimodal_file(
        "evidence_04",
        image_path,
        CAPTURED,
        origin="account_admin_portal",
        allow_model_calls=True,
        vision_config=config,
        meter=Meter(log_path=tmp_path / "usage.jsonl", run_id="test"),
        store_path=store_path,
    )
    assert report.status is ParseStatus.OK
    assert observations[0].resource_id == "account_5762"


def test_png_schema_violation_is_parse_error(tmp_path: Path) -> None:
    image_path = make_png(tmp_path)
    store_path = tmp_path / "store.json"
    write_store(store_path, image_path, {"account_id": "account_5762"})
    observations, report = parse_multimodal_file(
        "evidence_04",
        image_path,
        CAPTURED,
        origin="account_admin_portal",
        store_path=store_path,
    )
    assert observations == []
    assert report.status is ParseStatus.PARSE_ERROR
    assert any(error.startswith("schema_violation:missing:") for error in report.errors)


def test_png_disagreement_marks_unknown_state(tmp_path: Path) -> None:
    image_path = make_png(tmp_path)
    store_path = tmp_path / "store.json"
    write_store(
        store_path,
        image_path,
        account_fields(
            account_id="account_5762",
            email=None,
            user_id="user_11",
        ),
        disagreements=("vlm_disagreement:email",),
    )
    observations, report = parse_multimodal_file(
        "evidence_04",
        image_path,
        CAPTURED,
        origin="account_admin_portal",
        store_path=store_path,
    )
    assert report.status is ParseStatus.UNKNOWN_STATE
    assert "vlm_disagreement:email" in report.errors
    assert observations and observations[0].resource_id == "account_5762"


def test_unknown_png_origin_is_unknown_state(tmp_path: Path) -> None:
    image_path = make_png(tmp_path)
    observations, report = parse_multimodal_file(
        "evidence_x", image_path, CAPTURED, origin="mystery_origin"
    )
    assert observations == []
    assert report.status is ParseStatus.UNKNOWN_STATE
    assert any("unknown_png_family_for_origin" in error for error in report.errors)


def test_object_storage_is_facts_only(tmp_path: Path) -> None:
    image_path = make_png(tmp_path)
    store_path = tmp_path / "store.json"
    fields: dict[str, object] = dict.fromkeys(FAMILY_FIELDS["object_storage"])
    fields.update({"bucket": "northstar-customer-data", "objects": [{"name": "x.pdf"}]})
    write_store(store_path, image_path, fields)
    observations, report = parse_multimodal_file(
        "evidence_46", image_path, CAPTURED, origin="object_storage", store_path=store_path
    )
    assert observations == []
    assert report.status is ParseStatus.OK
    assert report.extracted_records


def test_metered_call_recorded_only_on_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    image_path = make_png(tmp_path)
    store_path = tmp_path / "store.json"
    fields = account_fields(account_id="account_1")
    config = VisionConfig(
        provider="qwen",
        model="model-a",
        model_pass_b="model-b",
        base_url="http://example.test",
        api_key="key",
    )
    calls = {"n": 0}

    def fake_transcribe(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        kwargs["meter"].record("qwen", "model-a", "vlm:test", 10, 5)
        return write_store(store_path, image_path, fields)

    monkeypatch.setattr(multimodal_parser, "transcribe_two_pass", fake_transcribe)
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test")
    parse_multimodal_file(
        "evidence_04",
        image_path,
        CAPTURED,
        origin="account_admin_portal",
        allow_model_calls=True,
        vision_config=config,
        meter=meter,
        store_path=store_path,
    )
    assert calls["n"] == 1
    parse_multimodal_file(
        "evidence_04",
        image_path,
        CAPTURED,
        origin="account_admin_portal",
        allow_model_calls=True,
        vision_config=config,
        meter=meter,
        store_path=store_path,
    )
    assert calls["n"] == 1
