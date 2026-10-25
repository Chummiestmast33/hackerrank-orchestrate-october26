"""Persistent store for vision transcriptions (both passes + merged facts).

Entries are keyed by image content hash, prompt version and both model ids, so
changing the parser never triggers new model calls and a committed store lets
offline runs reproduce results without credentials.
"""

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STORE_SCHEMA = 1
CODE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_STORE_PATH = CODE_DIR / "data" / "multimodal_transcriptions.json"


@dataclass
class TranscriptionEntry:
    file_id: str
    sha256: str
    prompt_version: str
    model_a: str
    model_b: str
    pass_a: dict[str, Any]
    pass_b: dict[str, Any]
    merged: dict[str, Any]
    disagreements: tuple[str, ...] = ()
    review_flags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "sha256": self.sha256,
            "prompt_version": self.prompt_version,
            "model_a": self.model_a,
            "model_b": self.model_b,
            "pass_a": self.pass_a,
            "pass_b": self.pass_b,
            "merged": self.merged,
            "disagreements": list(self.disagreements),
            "review_flags": list(self.review_flags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranscriptionEntry":
        return cls(
            file_id=str(data["file_id"]),
            sha256=str(data["sha256"]),
            prompt_version=str(data["prompt_version"]),
            model_a=str(data.get("model_a", "")),
            model_b=str(data.get("model_b", "")),
            pass_a=dict(data.get("pass_a", {})),
            pass_b=dict(data.get("pass_b", {})),
            merged=dict(data.get("merged", {})),
            disagreements=tuple(str(item) for item in data.get("disagreements", [])),
            review_flags=tuple(str(item) for item in data.get("review_flags", [])),
        )


def store_key(sha256: str, prompt_version: str, model_a: str, model_b: str) -> str:
    return f"{prompt_version}|{model_a}|{model_b}|{sha256}"


def load_store(path: Path) -> tuple[dict[str, TranscriptionEntry], list[str]]:
    warnings: list[str] = []
    if not path.exists():
        return {}, warnings
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"transcription store unreadable ({exc}); ignoring"]
    if not isinstance(payload, dict):
        return {}, ["transcription store payload is not an object; ignoring"]
    meta = payload.get("meta") or {}
    if meta.get("schema") != STORE_SCHEMA:
        return {}, ["transcription store schema mismatch; ignoring"]
    entries: dict[str, TranscriptionEntry] = {}
    for key, raw in dict(payload.get("transcriptions") or {}).items():
        try:
            entries[str(key)] = TranscriptionEntry.from_dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            warnings.append(f"transcription entry {key} unreadable ({exc}); ignoring")
    return entries, warnings


def save_store(
    path: Path,
    entries: dict[str, TranscriptionEntry],
    generated_at: str | None = None,
) -> None:
    payload = {
        "meta": {
            "schema": STORE_SCHEMA,
            "generated_at": generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "transcriptions": {key: entries[key].to_dict() for key in sorted(entries)},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=path.name, suffix=".tmp", delete=False
    )
    try:
        with handle:
            handle.write(serialized)
            handle.write("\n")
        os.replace(handle.name, path)
    except BaseException:
        try:
            os.unlink(handle.name)
        except OSError:
            pass
        raise


def find_entry(
    entries: dict[str, TranscriptionEntry],
    *,
    sha256: str,
    prompt_version: str,
    model_a: str,
    model_b: str,
) -> TranscriptionEntry | None:
    return entries.get(store_key(sha256, prompt_version, model_a, model_b))
