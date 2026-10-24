"""Unit tests for the aggressive parse cache and the parse-all CLI (P3.7)."""

import json
from pathlib import Path

from src.loaders import cache as cache_mod
from src.loaders import cli
from src.loaders.csv_loader import EvidenceFileRow
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
    (dataset / "evidence" / "documents").mkdir(parents=True)
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
    (dataset / "evidence" / "documents" / "scan.pdf").write_bytes(b"%PDF-1.4 fake")
    return dataset


def manifest_rows(dataset: Path) -> list[EvidenceFileRow]:
    rows = [
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
    if (dataset / "evidence" / "documents" / "scan.pdf").exists():
        rows.append(
            EvidenceFileRow(
                file_id="evidence_03",
                file_path="evidence/documents/scan.pdf",
                origin="test",
                captured_at=CAPTURED,
            )
        )
    return rows


def run_parse(dataset: Path, cache_path: Path, force: bool = False) -> cache_mod.ParseAllResult:
    return cache_mod.parse_all(
        manifest_rows(dataset).copy(),
        dataset_dir=dataset,
        cache_path=cache_path,
        force=force,
    )


def test_parse_all_then_cache_hits(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    first = run_parse(dataset, cache_path)
    assert first.stats.misses == 3 and first.stats.hits == 0
    assert first.stats.unsupported == 1
    assert cache_path.exists()
    second = run_parse(dataset, cache_path)
    assert second.stats.hits == 3 and second.stats.misses == 0
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
    assert second.stats.hits == 2 and second.stats.misses == 1
    assert len(second.entries["evidence_01"].observations) == 2


def test_force_rebuilds_all(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    run_parse(dataset, cache_path)
    forced = run_parse(dataset, cache_path, force=True)
    assert forced.stats.hits == 0 and forced.stats.misses == 3


def test_corrupt_cache_is_tolerated(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    cache_path.parent.mkdir(parents=True)
    cache_path.write_text("{not json", encoding="utf-8")
    result = run_parse(dataset, cache_path)
    assert result.stats.misses == 3 and result.stats.hits == 0


def test_parser_version_mismatch_forces_rebuild(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    run_parse(dataset, cache_path)
    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    payload["meta"]["parser_version"] = "old-version"
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    result = run_parse(dataset, cache_path)
    assert result.stats.hits == 0 and result.stats.misses == 3


def test_pdf_placeholder_and_exit_codes(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    result = run_parse(dataset, cache_path)
    pdf_entry = result.entries["evidence_03"]
    assert pdf_entry.report is not None
    assert pdf_entry.report.status is ParseStatus.UNSUPPORTED_FORMAT
    assert pdf_entry.observations == []
    assert cli.exit_code(result, strict=False) == 0


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
    assert set(census) == {"evidence_01", "evidence_02", "evidence_03"}
    assert census["evidence_01"]["observations"] == 1
    assert census["evidence_01"]["states"] == {"PRESENT": 1}
    assert census["evidence_02"]["states"] == {"REDACTED": 1}
    assert census["evidence_03"]["status"] == "UNSUPPORTED_FORMAT"


def test_load_evidence_index_roundtrip(tmp_path: Path) -> None:
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    run_parse(dataset, cache_path)
    index, warnings = cache_mod.load_evidence_index(cache_path)
    assert warnings == []
    assert set(index) == {"evidence_01", "evidence_02", "evidence_03"}
    observations, report = index["evidence_02"]
    assert report.status is ParseStatus.OK
    assert observations[0].state.value == "REDACTED"


def test_cli_main_clean_and_broken(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dataset = build_dataset(tmp_path)
    cache_path = tmp_path / "cache" / "parsed_evidence.json"
    with (dataset / "evidence_files.csv").open("w", encoding="utf-8") as handle:
        handle.write("file_id,file_path,origin,captured_at\n")
        handle.write("evidence_01,evidence/logs/test_events.log,test,2026-09-01T00:00:00Z\n")
        handle.write(
            "evidence_02,evidence/records/customer_data_snapshot_bundle_20260901.json,test,2026-09-01T00:00:00Z\n"
        )
        handle.write("evidence_03,evidence/documents/scan.pdf,test,2026-09-01T00:00:00Z\n")
    assert cli.main(["--dataset", str(dataset), "--cache", str(cache_path), "--quiet"]) == 0
    broken = dataset / "evidence" / "records" / "customer_data_snapshot_bundle_broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with (dataset / "evidence_files.csv").open("w", encoding="utf-8") as handle:
        handle.write("file_id,file_path,origin,captured_at\n")
        handle.write("evidence_01,evidence/logs/test_events.log,test,2026-09-01T00:00:00Z\n")
        handle.write(
            "evidence_02,evidence/records/customer_data_snapshot_bundle_broken.json,test,2026-09-01T00:00:00Z\n"
        )
    assert cli.main(["--dataset", str(dataset), "--cache", str(cache_path), "--quiet"]) == 1
    output = capsys.readouterr().out
    assert "cache_hits" in output


def test_cli_manifest_error_returns_two(tmp_path: Path) -> None:
    assert cli.main(["--dataset", str(tmp_path), "--cache", str(tmp_path / "c.json")]) == 2
