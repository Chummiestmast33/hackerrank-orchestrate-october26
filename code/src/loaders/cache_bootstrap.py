"""Offline bootstrap for the evidence parse cache."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from ..models import ParseStatus
from .cache import ParseAllResult, parse_all, read_cache
from .csv_loader import (
    ActivityRow,
    AuditLogRow,
    EvidenceFileRow,
    IdentityRow,
    load_activity,
    load_audit_log,
    load_evidence_manifest,
    load_identities,
)
from .transcription_validator import build_known_identifiers

CODE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_TRANSCRIPTION_STORE = CODE_DIR / "data" / "multimodal_transcriptions.json"


class CacheBuildError(RuntimeError):
    """Raised when evidence cannot be parsed into a safe cache."""


def _load_manifest(dataset_dir: Path) -> list[EvidenceFileRow]:
    manifest_path = dataset_dir / "evidence_files.csv"
    manifest, errors = load_evidence_manifest(manifest_path)
    if errors:
        raise CacheBuildError("; ".join(errors))
    if not manifest:
        raise CacheBuildError(f"evidence manifest is empty: {manifest_path}")
    return manifest


def _png_rows(manifest: Sequence[EvidenceFileRow]) -> list[EvidenceFileRow]:
    return [row for row in manifest if Path(row.file_path).suffix.lower() == ".png"]


def _validate_result(
    result: ParseAllResult,
    manifest: Sequence[EvidenceFileRow],
) -> None:
    expected = {row.file_id for row in manifest}
    missing = sorted(expected - set(result.entries))
    if missing:
        raise CacheBuildError(f"evidence cache is incomplete; missing: {', '.join(missing)}")

    errors: list[str] = []
    unsupported_pngs: list[str] = []
    for file_id, entry in sorted(result.entries.items()):
        report = entry.report
        if report is None:
            errors.append(f"{file_id}: missing parse report")
            continue
        if report.errors or report.status is ParseStatus.PARSE_ERROR:
            detail = "; ".join(report.errors[:3]) or report.status.value
            errors.append(f"{file_id}: {detail}")
        if report.family.startswith("png:") and report.status is ParseStatus.UNSUPPORTED_FORMAT:
            unsupported_pngs.append(file_id)

    if errors:
        raise CacheBuildError("evidence parsing failed: " + " | ".join(errors[:10]))
    if unsupported_pngs:
        raise CacheBuildError(
            "PNG evidence could not be decoded offline: " + ", ".join(unsupported_pngs)
        )


def ensure_evidence_cache(
    *,
    dataset_dir: Path,
    cache_path: Path,
    manifest: Sequence[EvidenceFileRow] | None = None,
    activity: Sequence[ActivityRow] | None = None,
    identities: Sequence[IdentityRow] | None = None,
    audit_log: Sequence[AuditLogRow] | None = None,
    transcription_store_path: Path | None = None,
    force: bool = False,
) -> ParseAllResult:
    """Build or refresh the parse cache without model calls."""
    dataset_dir = Path(dataset_dir)
    cache_path = Path(cache_path)
    rows = list(manifest) if manifest is not None else _load_manifest(dataset_dir)
    if not rows:
        raise CacheBuildError("evidence manifest has no rows")

    activity_rows = (
        list(activity)
        if activity is not None
        else load_activity(dataset_dir / "system_activity.csv")[0]
    )
    identity_rows = (
        list(identities)
        if identities is not None
        else load_identities(dataset_dir / "user_identities.csv")[0]
    )
    audit_rows = (
        list(audit_log)
        if audit_log is not None
        else load_audit_log(dataset_dir / "user_audit_log.csv")[0]
    )

    store_path = (
        Path(transcription_store_path)
        if transcription_store_path is not None
        else DEFAULT_TRANSCRIPTION_STORE
    )
    if _png_rows(rows) and not store_path.exists():
        raise CacheBuildError(f"transcription store missing: {store_path}")

    cached, _warnings = read_cache(cache_path)
    prior_observations = [
        observation for entry in cached.values() for observation in entry.observations
    ]
    known_identifiers = build_known_identifiers(
        identity_rows,
        audit_rows,
        prior_observations,
    )

    try:
        result = parse_all(
            rows,
            dataset_dir=dataset_dir,
            cache_path=cache_path,
            force=force,
            persist=True,
            allow_model_calls=False,
            transcription_store_path=store_path,
            activity=activity_rows,
            known_identifiers=known_identifiers,
        )
    except OSError as exc:
        raise CacheBuildError(f"could not write evidence cache {cache_path}: {exc}") from exc

    _validate_result(result, rows)
    return result
