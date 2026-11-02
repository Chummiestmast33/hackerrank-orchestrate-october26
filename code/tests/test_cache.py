"""Unit tests for the aggressive parse cache and the parse-all CLI (P3.7/P4.8)."""

import json
from pathlib import Path

from src.loaders import cache as cache_mod
from src.loaders import cli
from src.loaders.common import file_sha256
from src.loaders.csv_loader import EvidenceFileRow
from src.loaders.transcription_store import (
    TranscriptionEntry,
    save_store,
    store_key,
)
from src.loaders.vlm_extractor import FAMILY_FIELDS, PROMPT_VERSION
from src.models import ParseReport, ParseStatus

CAPTURED = "2026-09-01T00:00:00Z"

LOG_LINE = (
    "2026-09-01T00:00:00Z level=INFO service=account_service "
    'event=profile_lookup_completed resource_id=account_1 rows=1 http_status=200 email="a@x"'
)


def build_dataset(tmp_path: Path) -> Path:
    dataset = tmp_path / "dataset"
    (dataset / "evidence" / "logs").mkdir(parents=True)
    (dataset / "evidence" / "records").mkdir(parents=True)
    (dataset / "evidence" / "images").mkdir(parents=True)
    (dataset / "evidence" / "logs" / "test_events.log").write_text(
        LOG_LINE + "\n", encoding="utf-8"
    )
    bundle = {
        "exported_at": CAPTURED,
        "source": "records_assurance_service",
        "snapshots": [
            {
                "captured_at": CAPTURED,
                "data_store": "identity_service",
                "collection": "deleted_customer_references",
                "records": [
                    {
                        "resource_id": "tombstone_1",
                        "subject_reference": "user_1",
                        "name": None,
                        "email": None,
                        "phone": None,
                        "email_hash": None,
                    }
                ],
            }
        ],
    }
    (dataset / "evidence" / "records" / "customer_data_snapshot_bundle_20260901.json").write_text(
        json.dumps(bundle), encoding="utf-8"
    )
    (dataset / "evidence" / "images" / "account_admin_console.png").write_bytes(b"fake-png")
    return dataset


def write_manifest(dataset: Path, rows: list[tuple[str, str, str]]) -> None:
    with (dataset / "evidence_files.csv").open("w", encoding="utf-8") as handle:
        handle.write("file_id,file_path,origin,captured_at\n")
        for file_id, file_path, origin in rows:
            handle.write(f"{file_id},{file_path},{origin},{CAPTURED}\n")


def manifest_rows() -> list[EvidenceFileRow]:
    return [
        EvidenceFileRow(
            file_id="evidence_01",
            file_path="evidence/logs/test_events.log",
            origin="test",
            captured_at=CAPTURED,
        ),
        EvidenceFileRow(
            file_id="evidence_02",
            file_path="evidence/records/customer_data_snapshot_bundle_20260901.json",
            origin="test",
            captured_at=CAPTURED,
        ),
    ]


def image_row() -> EvidenceFileRow:
    return EvidenceFileRow(
        file_id="evidence_03",
        file_path="evidence/images/account_admin_console.png",
        origin="account_admin_portal",
        captured_at=CAPTURED,
    )


def account_fields(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = dict.fromkeys(FAMILY_FIELDS["account_console"])
    fields.update(overrides)
    return fields


def write_transcription_store(dataset: Path, store_path: Path, fields: dict[str, object]) -> None:
    image_path = dataset / "evidence" / "images" / "account_admin_console.png"
    sha = file_sha256(image_path)
    entry = TranscriptionEntry(
        file_id="evidence_03",
        sha256=sha,
        prompt_version=PROMPT_VERSION,
        model_a="model-a",
        model_b="model-b",
        pass_a=fields,
        pass_b=fields,
        merged=fields,
    )
    save_store(store_path, {store_key(sha, PROMPT_VERSION, "model-a", "model-b"): entry})


def run_parse(dataset: Path, cache_path: Path, force: bool = False) -> cache_mod.ParseAllResult:
    return cache_mod.parse_all(
        manifest_rows(),
        dataset_dir=dataset,
        cache_path=cache_path,
        force=force,
    )


def test_parse_all_then_cache_hits(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    first = run_parse(dataset, cache_path)
    assert first.stats.misses == 2 and first.stats.hits == 0
    assert first.stats.unsupported == 0
    assert cache_path.exists()
    second = run_parse(dataset, cache_path)
    assert second.stats.hits == 2 and second.stats.misses == 0
    assert {fid: entry.sha256 for fid, entry in first.entries.items()} == {
        fid: entry.sha256 for fid, entry in second.entries.items()
    }


def test_content_change_reparses_only_changed_file(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    run_parse(dataset, cache_path)
    log_path = dataset / "evidence" / "logs" / "test_events.log"
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "2026-09-01T00:00:01Z level=INFO service=account_service "
            "event=profile_lookup_completed resource_id=account_2 rows=0 http_status=404\n"
        )
    second = run_parse(dataset, cache_path)
    assert second.stats.hits == 1 and second.stats.misses == 1
    assert len(second.entries["evidence_01"].observations) == 2


def test_force_rebuilds_all(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    run_parse(dataset, cache_path)
    forced = run_parse(dataset, cache_path, force=True)
    assert forced.stats.hits == 0 and forced.stats.misses == 2


def test_corrupt_cache_is_tolerated(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("{not json", encoding="utf-8")
    result = run_parse(dataset, cache_path)
    assert result.stats.misses == 2 and result.stats.hits == 0


def test_parser_version_mismatch_forces_rebuild(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    run_parse(dataset, cache_path)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["meta"]["parser_version"] = "old-version"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    result = run_parse(dataset, cache_path)
    assert result.stats.hits == 0 and result.stats.misses == 2


def test_unknown_pdf_is_parse_error(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    (dataset / "evidence" / "documents").mkdir(parents=True, exist_ok=True)
    (dataset / "evidence" / "documents" / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
    manifest = [
        EvidenceFileRow(
            file_id="evidence_04",
            file_path="evidence/documents/scan.pdf",
            origin="support_platform",
            captured_at=CAPTURED,
        )
    ]
    result = cache_mod.parse_all(
        manifest, dataset_dir=dataset, cache_path=tmp_path / "c.json", persist=False
    )
    entry = result.entries["evidence_04"]
    assert entry.report is not None
    assert entry.report.status is ParseStatus.PARSE_ERROR
    assert "unknown_document_family" in entry.report.errors
    assert cli.exit_code(result, strict=False) == 1


def test_multimodal_dispatch_uses_transcription_store(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    store_path = tmp_path / "store.json"
    write_transcription_store(
        dataset,
        store_path,
        account_fields(
            account_id="account_5762",
            email="haruka.s1838@zoho.com",
            user_id="user_11",
        ),
    )
    result = cache_mod.parse_all(
        [image_row()],
        dataset_dir=dataset,
        cache_path=tmp_path / "cache.json",
        persist=False,
        transcription_store_path=store_path,
    )
    entry = result.entries["evidence_03"]
    assert entry.report is not None
    assert entry.report.status is ParseStatus.OK
    assert entry.report.extracted_records
    assert any(observation.resource_id == "account_5762" for observation in entry.observations)


def test_multimodal_dispatch_offline_without_store_is_unsupported(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    result = cache_mod.parse_all(
        [image_row()],
        dataset_dir=dataset,
        cache_path=tmp_path / "cache.json",
        persist=False,
        transcription_store_path=tmp_path / "missing-store.json",
    )
    entry = result.entries["evidence_03"]
    assert entry.report is not None
    assert entry.report.status is ParseStatus.UNSUPPORTED_FORMAT
    assert "extraction_unavailable" in entry.report.errors


def test_exit_codes_for_parse_error_and_strict_unknown() -> None:
    def entry(file_id: str, status: ParseStatus) -> cache_mod.CacheEntry:
        report = ParseReport(
            file_id=file_id,
            family="test",
            captured_at=CAPTURED,
            sha256="0",
            status=status,
        )
        return cache_mod.CacheEntry(
            file_id=file_id, sha256="0", parser_version=cache_mod.PARSER_VERSION, report=report
        )

    ok_result = cache_mod.ParseAllResult(
        entries={"a": entry("a", ParseStatus.OK)}, stats=cache_mod.CacheStats()
    )
    assert cli.exit_code(ok_result, strict=False) == 0
    unknown_result = cache_mod.ParseAllResult(
        entries={"a": entry("a", ParseStatus.UNKNOWN_STATE)}, stats=cache_mod.CacheStats()
    )
    assert cli.exit_code(unknown_result, strict=False) == 0
    assert cli.exit_code(unknown_result, strict=True) == 1
    error_result = cache_mod.ParseAllResult(
        entries={"a": entry("a", ParseStatus.PARSE_ERROR)}, stats=cache_mod.CacheStats()
    )
    assert cli.exit_code(error_result, strict=False) == 1


def test_cache_serialization_is_deterministic(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_a = tmp_path / "cache_a.json"
    cache_b = tmp_path / "cache_b.json"
    run_parse(dataset, cache_a)
    run_parse(dataset, cache_b)
    files_a = json.loads(cache_a.read_text(encoding="utf-8"))["files"]
    files_b = json.loads(cache_b.read_text(encoding="utf-8"))["files"]
    assert files_a == files_b
    cache_mod.write_cache(
        tmp_path / "fixed_a.json", run_parse(dataset, cache_a).entries, generated_at="T"
    )
    cache_mod.write_cache(
        tmp_path / "fixed_b.json", run_parse(dataset, cache_b).entries, generated_at="T"
    )
    assert (tmp_path / "fixed_a.json").read_bytes() == (tmp_path / "fixed_b.json").read_bytes()


def test_build_census_shape(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    result = run_parse(dataset, cache_path)
    census = cache_mod.build_census(result.entries)
    assert set(census) == {"evidence_01", "evidence_02"}
    assert census["evidence_01"]["observations"] == 1
    assert census["evidence_01"]["states"] == {"PRESENT": 1}
    assert census["evidence_02"]["states"] == {"REDACTED": 1}


def test_load_evidence_index_roundtrip(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    run_parse(dataset, cache_path)
    index, warnings = cache_mod.load_evidence_index(cache_path)
    assert warnings == []
    assert set(index) == {"evidence_01", "evidence_02"}
    observations, report = index["evidence_02"]
    assert report.status is ParseStatus.OK
    assert observations[0].state.value == "REDACTED"


def test_cli_main_clean_and_broken(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    write_manifest(
        dataset,
        [
            ("evidence_01", "evidence/logs/test_events.log", "test"),
            ("evidence_02", "evidence/records/customer_data_snapshot_bundle_20260901.json", "test"),
        ],
    )
    assert cli.main(["--dataset", str(dataset), "--cache", str(cache_path), "--quiet"]) == 0
    broken = dataset / "evidence" / "records" / "customer_data_snapshot_bundle_broken.json"
    broken.write_text("{not json", encoding="utf-8")
    write_manifest(
        dataset,
        [
            ("evidence_01", "evidence/logs/test_events.log", "test"),
            ("evidence_02", "evidence/records/customer_data_snapshot_bundle_broken.json", "test"),
        ],
    )
    assert cli.main(["--dataset", str(dataset), "--cache", str(cache_path), "--quiet"]) == 1
    output = capsys.readouterr().out
    assert "cache_hits" in output


def test_cli_manifest_error_returns_two(tmp_path: Path) -> None:
    assert cli.main(["--dataset", str(tmp_path), "--cache", str(tmp_path / "c.json")]) == 2


def test_cli_extract_images_without_credentials_returns_two(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    dataset = build_dataset(tmp_path)
    write_manifest(dataset, [("evidence_01", "evidence/logs/test_events.log", "test")])
    monkeypatch.setenv("VISION_MODEL_PROVIDER", "qwen")
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("VISION_MODEL", raising=False)
    code = cli.main(
        [
            "--dataset",
            str(dataset),
            "--cache",
            str(tmp_path / "c.json"),
            "--extract-images",
            "--quiet",
        ]
    )
    assert code == 2
