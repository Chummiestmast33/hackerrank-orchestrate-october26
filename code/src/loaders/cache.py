"""Aggressive all-in-one parse cache for evidence files.

One artifact (`code/cache/parsed_evidence.json`, gitignored) stores every parse
result. Entries are reused indefinitely while the file's content hash and
``PARSER_VERSION`` match; a content or parser change reparses only the affected
files. Writes are atomic and deterministic.
"""

import json
import os
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..evaluation.metering import Meter
from ..models import EvidenceObservation, ParseReport, ParseStatus
from . import PARSER_VERSION
from .common import file_sha256
from .csv_loader import ActivityRow, EvidenceFileRow
from .json_txt_parser import parse_json_txt_file
from .log_parser import parse_log_file
from .multimodal_parser import parse_multimodal_file
from .sql_parser import parse_sql_file
from .vlm_extractor import VisionConfig

CACHE_SCHEMA = 1
SUPPORTED_SUFFIXES = {".sql", ".json", ".txt", ".log"}


@dataclass
class CacheEntry:
    file_id: str
    sha256: str
    parser_version: str
    observations: list[EvidenceObservation] = field(default_factory=list)
    report: ParseReport | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.report is None:  # pragma: no cover - defensive
            raise ValueError("cache entry without report")
        return {
            "sha256": self.sha256,
            "parser_version": self.parser_version,
            "observations": [obs.to_dict() for obs in self.observations],
            "report": self.report.to_dict(),
        }

    @classmethod
    def from_dict(cls, file_id: str, data: dict[str, Any]) -> "CacheEntry":
        return cls(
            file_id=file_id,
            sha256=str(data.get("sha256", "")),
            parser_version=str(data.get("parser_version", "")),
            observations=[
                EvidenceObservation.from_dict(item) for item in data.get("observations", [])
            ],
            report=ParseReport.from_dict(data.get("report", {})),
        )


@dataclass
class CacheStats:
    files: int = 0
    hits: int = 0
    misses: int = 0
    unsupported: int = 0
    observations: int = 0
    errors: int = 0


@dataclass
class ParseAllResult:
    entries: dict[str, CacheEntry]
    stats: CacheStats


def read_cache(path: Path) -> tuple[dict[str, CacheEntry], list[str]]:
    """Load cached entries; malformed or mismatched caches are ignored safely."""
    warnings: list[str] = []
    if not path.exists():
        return {}, warnings
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"cache unreadable ({exc}); rebuilding"]
    if not isinstance(payload, dict):
        return {}, ["cache payload is not an object; rebuilding"]
    meta = payload.get("meta") or {}
    if meta.get("schema") != CACHE_SCHEMA or meta.get("parser_version") != PARSER_VERSION:
        return {}, ["cache schema/version mismatch; rebuilding"]
    entries: dict[str, CacheEntry] = {}
    for file_id, raw in dict(payload.get("files") or {}).items():
        try:
            entries[str(file_id)] = CacheEntry.from_dict(str(file_id), raw)
        except (KeyError, TypeError, ValueError) as exc:
            warnings.append(f"cache entry {file_id} unreadable ({exc}); reparsing")
    return entries, warnings


def write_cache(
    path: Path,
    entries: dict[str, CacheEntry],
    generated_at: str | None = None,
) -> None:
    payload = {
        "meta": {
            "schema": CACHE_SCHEMA,
            "parser_version": PARSER_VERSION,
            "generated_at": generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "files": {file_id: entries[file_id].to_dict() for file_id in sorted(entries)},
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


def _parse_file(
    row: EvidenceFileRow,
    dataset_dir: Path,
    *,
    allow_model_calls: bool = False,
    vision_config: VisionConfig | None = None,
    meter: Meter | None = None,
    transcription_store_path: Path | None = None,
    activity: Sequence[ActivityRow] = (),
    known_identifiers: frozenset[str] | set[str] = frozenset(),
) -> tuple[list[EvidenceObservation], ParseReport]:
    path = dataset_dir / row.file_path
    suffix = path.suffix.lower()
    if suffix == ".sql":
        return parse_sql_file(row.file_id, path, row.captured_at)
    if suffix in {".json", ".txt"}:
        return parse_json_txt_file(row.file_id, path, row.captured_at)
    if suffix == ".log":
        return parse_log_file(row.file_id, path, row.captured_at)
    return parse_multimodal_file(
        row.file_id,
        path,
        row.captured_at,
        origin=row.origin,
        allow_model_calls=allow_model_calls,
        vision_config=vision_config,
        meter=meter,
        store_path=transcription_store_path,
        activity=activity,
        known_identifiers=known_identifiers,
    )


def parse_all(
    manifest: Sequence[EvidenceFileRow],
    *,
    dataset_dir: Path,
    cache_path: Path | None,
    force: bool = False,
    persist: bool = True,
    allow_model_calls: bool = False,
    vision_config: VisionConfig | None = None,
    meter: Meter | None = None,
    transcription_store_path: Path | None = None,
    activity: Sequence[ActivityRow] = (),
    known_identifiers: frozenset[str] | set[str] = frozenset(),
) -> ParseAllResult:
    cached: dict[str, CacheEntry] = {}
    if cache_path is not None and not force:
        cached, _warnings = read_cache(cache_path)
    entries: dict[str, CacheEntry] = {}
    stats = CacheStats(files=len(manifest))
    for row in manifest:
        path = dataset_dir / row.file_path
        sha256 = file_sha256(path) if path.exists() else ""
        previous = cached.get(row.file_id)
        if (
            previous is not None
            and previous.sha256 == sha256
            and previous.parser_version == PARSER_VERSION
            and previous.report is not None
        ):
            entries[row.file_id] = previous
            stats.hits += 1
        else:
            try:
                observations, report = _parse_file(
                    row,
                    dataset_dir,
                    allow_model_calls=allow_model_calls,
                    vision_config=vision_config,
                    meter=meter,
                    transcription_store_path=transcription_store_path,
                    activity=activity,
                    known_identifiers=known_identifiers,
                )
            except Exception as exc:  # noqa: BLE001 - a bad file must not abort the batch
                report = ParseReport(
                    file_id=row.file_id,
                    family="unknown",
                    captured_at=row.captured_at,
                    sha256=sha256,
                    status=ParseStatus.PARSE_ERROR,
                    errors=[f"internal_error:{type(exc).__name__}:{exc}"],
                )
                observations = []
            entries[row.file_id] = CacheEntry(
                file_id=row.file_id,
                sha256=sha256,
                parser_version=PARSER_VERSION,
                observations=observations,
                report=report,
            )
            stats.misses += 1
            if report.status is ParseStatus.UNSUPPORTED_FORMAT:
                stats.unsupported += 1
        entry = entries[row.file_id]
        stats.observations += len(entry.observations)
        assert entry.report is not None
        stats.errors += len(entry.report.errors)
    if persist and cache_path is not None:
        write_cache(cache_path, entries)
    return ParseAllResult(entries=entries, stats=stats)


def build_census(entries: dict[str, CacheEntry]) -> dict[str, dict[str, Any]]:
    """Deterministic per-file census used by tests and the CLI."""
    census: dict[str, dict[str, Any]] = {}
    for file_id in sorted(entries):
        entry = entries[file_id]
        report = entry.report
        if report is None:  # pragma: no cover - defensive
            continue
        states: dict[str, int] = {}
        for observation in entry.observations:
            states[observation.state.value] = states.get(observation.state.value, 0) + 1
        census[file_id] = {
            "family": report.family,
            "status": report.status.value,
            "observations": len(entry.observations),
            "states": dict(sorted(states.items())),
            "errors": len(report.errors),
            "scope": sorted(report.scope),
            "captured_collections": len(report.captured_collections),
            "direct_systems": list(report.direct_systems),
        }
    return census


def load_evidence_index(
    cache_path: Path,
) -> tuple[dict[str, tuple[list[EvidenceObservation], ParseReport]], list[str]]:
    """Read the on-disk evidence cache into observation/report pairs."""
    entries, warnings = read_cache(cache_path)
    index = {
        file_id: (entry.observations, entry.report)
        for file_id, entry in entries.items()
        if entry.report is not None
    }
    return index, warnings
