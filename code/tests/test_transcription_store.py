"""Unit tests for the transcription store (P4.5)."""

import json
from pathlib import Path

from src.loaders.transcription_store import (
    TranscriptionEntry,
    find_entry,
    load_store,
    save_store,
    store_key,
)


def sample_entry(file_id: str = "evidence_04") -> TranscriptionEntry:
    return TranscriptionEntry(
        file_id=file_id,
        sha256="abc123",
        prompt_version="p4-v1",
        model_a="model-a",
        model_b="model-b",
        pass_a={"name": "A"},
        pass_b={"name": "A"},
        merged={"name": "A"},
        disagreements=(),
        review_flags=("manual_reviewed",),
    )


def test_store_key_format() -> None:
    assert store_key("abc", "p4-v1", "m1", "m2") == "p4-v1|m1|m2|abc"


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    entry = sample_entry()
    key = store_key(entry.sha256, entry.prompt_version, entry.model_a, entry.model_b)
    save_store(path, {key: entry})
    loaded, warnings = load_store(path)
    assert warnings == []
    assert loaded == {key: entry}


def test_deterministic_bytes(tmp_path: Path) -> None:
    entry = sample_entry()
    key = "k"
    save_store(tmp_path / "a.json", {key: entry}, generated_at="2026-01-01T00:00:00+00:00")
    save_store(tmp_path / "b.json", {key: entry}, generated_at="2026-01-01T00:00:00+00:00")
    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()


def test_corrupt_store_is_tolerated(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text("{not json", encoding="utf-8")
    entries, warnings = load_store(path)
    assert entries == {}
    assert warnings and "unreadable" in warnings[0]


def test_schema_mismatch_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "store.json"
    path.write_text(json.dumps({"meta": {"schema": 999}, "transcriptions": {}}), encoding="utf-8")
    entries, warnings = load_store(path)
    assert entries == {}
    assert warnings and "schema mismatch" in warnings[0]


def test_missing_store_is_empty(tmp_path: Path) -> None:
    entries, warnings = load_store(tmp_path / "absent.json")
    assert entries == {} and warnings == []


def test_find_entry_hit_and_miss() -> None:
    entry = sample_entry()
    key = store_key(entry.sha256, entry.prompt_version, entry.model_a, entry.model_b)
    entries = {key: entry}
    assert (
        find_entry(
            entries,
            sha256=entry.sha256,
            prompt_version=entry.prompt_version,
            model_a=entry.model_a,
            model_b=entry.model_b,
        )
        == entry
    )
    assert (
        find_entry(entries, sha256="other", prompt_version="p4-v1", model_a="a", model_b="b")
        is None
    )
