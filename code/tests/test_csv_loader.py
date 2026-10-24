"""Unit tests for CSV loading and validation (P3.3)."""

from pathlib import Path

from src.loaders import csv_loader


def write(path: Path, content: str) -> Path:
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def test_manifest_valid_rows(tmp_path: Path) -> None:
    path = write(
        tmp_path / "evidence_files.csv",
        "file_id,file_path,origin,captured_at\n"
        "evidence_01,evidence/logs/a.log,origin_x,2026-09-15T11:59:39Z\n"
        "evidence_02,evidence/records/b.json,origin_y,2026-09-17T12:00:00Z",
    )
    rows, errors = csv_loader.load_evidence_manifest(path)
    assert errors == []
    assert [row.file_id for row in rows] == ["evidence_01", "evidence_02"]
    assert rows[1].captured_at == "2026-09-17T12:00:00Z"


def test_manifest_invalid_timestamp_skipped(tmp_path: Path) -> None:
    path = write(
        tmp_path / "evidence_files.csv",
        "file_id,file_path,origin,captured_at\nevidence_01,evidence/logs/a.log,origin_x,not-a-date",
    )
    rows, errors = csv_loader.load_evidence_manifest(path)
    assert rows == []
    assert any("invalid ISO-8601 captured_at" in error for error in errors)


def test_manifest_duplicate_and_missing_key(tmp_path: Path) -> None:
    path = write(
        tmp_path / "evidence_files.csv",
        "file_id,file_path,origin,captured_at\n"
        "evidence_01,evidence/a.log,o,2026-01-01T00:00:00Z\n"
        "evidence_01,evidence/b.log,o,2026-01-02T00:00:00Z\n"
        ",evidence/c.log,o,2026-01-03T00:00:00Z",
    )
    rows, errors = csv_loader.load_evidence_manifest(path)
    assert len(rows) == 1
    assert any("duplicate file_id" in error for error in errors)
    assert any("missing file_id" in error for error in errors)


def test_manifest_missing_column(tmp_path: Path) -> None:
    path = write(tmp_path / "evidence_files.csv", "file_id,file_path\nx,y")
    rows, errors = csv_loader.load_evidence_manifest(path)
    assert rows == []
    assert any("missing columns" in error for error in errors)


def test_manifest_missing_file(tmp_path: Path) -> None:
    rows, errors = csv_loader.load_evidence_manifest(tmp_path / "absent.csv")
    assert rows == []
    assert any("file not found" in error for error in errors)


def test_requests_loader(tmp_path: Path) -> None:
    path = write(
        tmp_path / "requests.csv",
        "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text\n"
        "case_01,a@x,2026-08-18T09:14:00Z,COMPLETE,2026-08-20T16:42:00Z,"
        '2026-09-03T11:30:00Z,"Please delete my account."',
    )
    rows, errors = csv_loader.load_deletion_requests(path)
    assert errors == []
    assert rows[0].case_id == "case_01"
    assert rows[0].reported_status == "COMPLETE"


def test_requests_bad_timestamp_skipped(tmp_path: Path) -> None:
    path = write(
        tmp_path / "requests.csv",
        "case_id,email,requested_at,reported_status,reported_at,audit_at,request_text\n"
        "case_01,a@x,2026-08-18T09:14:00Z,COMPLETE,2026-08-20T16:42:00Z,bad,text",
    )
    rows, errors = csv_loader.load_deletion_requests(path)
    assert rows == []
    assert any("invalid ISO-8601 audit_at" in error for error in errors)


def test_parse_iso8601() -> None:
    assert csv_loader.parse_iso8601("2026-09-03T11:30:00Z") is not None
    assert csv_loader.parse_iso8601("2026-09-03T11:30:00+00:00") is not None
    assert csv_loader.parse_iso8601("") is None
    assert csv_loader.parse_iso8601("nope") is None
