"""Multimodal loader: PDF facts and PNG vision transcriptions into observations.

PDFs are deterministic text extraction (no model). PNGs are decoded only from a
committed transcription store or a fresh two-pass metered extraction; offline
runs never call a model. Decoding stays table-driven in ``multimodal_rules``.
"""

from collections.abc import Sequence
from pathlib import Path

from ..evaluation.metering import Meter
from ..models import (
    EvidenceObservation,
    ExtractedRecord,
    ParseReport,
    ParseStatus,
    finalize_status,
)
from .common import file_sha256
from .csv_loader import ActivityRow
from .multimodal_rules import decode_pdf_records, decode_png_records
from .pdf_extractor import extract_pdf_records
from .transcription_store import TranscriptionEntry, find_entry, load_store
from .transcription_validator import validate_transcription
from .vlm_extractor import (
    FAMILY_FIELDS,
    PROMPT_VERSION,
    VisionConfig,
    VisionError,
    transcribe_two_pass,
)

PNG_FAMILY_BY_ORIGIN: dict[str, str] = {
    "account_admin_portal": "account_console",
    "search_index_admin": "search_inspector",
    "integration_admin": "connector_console",
    "analytics_platform": "analytics_profile",
    "export_service": "export_console",
    "support_platform": "support_console",
    "backup_service": "backup_console",
    "security_service": "sentinel_events",
    "identity_service": "reference_registry",
    "object_storage": "object_storage",
    "marketing_platform": "marketing_profile",
}

INFORMATIONAL_DIAGNOSTICS = {"no_resource_id_in_document"}


def _report(
    file_id: str,
    family: str,
    captured_at: str,
    sha256: str,
    status: ParseStatus = ParseStatus.OK,
) -> ParseReport:
    return ParseReport(
        file_id=file_id,
        family=family,
        captured_at=captured_at,
        sha256=sha256,
        status=status,
    )


def _store_entry(
    store_path: Path | None, sha256: str, config: VisionConfig | None
) -> TranscriptionEntry | None:
    if store_path is None or not store_path.exists():
        return None
    entries, _warnings = load_store(store_path)
    if config is not None:
        exact = find_entry(
            entries,
            sha256=sha256,
            prompt_version=PROMPT_VERSION,
            model_a=config.model,
            model_b=config.resolve_pass_b(),
        )
        if exact is not None:
            return exact
    matches = [
        entry
        for entry in entries.values()
        if entry.sha256 == sha256 and entry.prompt_version == PROMPT_VERSION
    ]
    if not matches:
        return None
    return sorted(matches, key=lambda entry: (entry.model_a, entry.model_b))[0]


def _parse_pdf(
    file_id: str, path: Path, captured_at: str, sha256: str
) -> tuple[list[EvidenceObservation], ParseReport]:
    extraction = extract_pdf_records(file_id, path)
    report = _report(file_id, f"pdf:{extraction.family}", captured_at, sha256)
    report.extracted_records = tuple(extraction.records)
    if extraction.family == "unknown":
        report.errors.append("unknown_document_family")
        report.status = ParseStatus.PARSE_ERROR
        return [], report
    observations, diagnostics = decode_pdf_records(extraction.records, captured_at=captured_at)
    report.errors.extend(diagnostics)
    report.status = finalize_status(report.errors, observations)
    return observations, report


def _parse_png(
    file_id: str,
    path: Path,
    captured_at: str,
    sha256: str,
    *,
    origin: str,
    allow_model_calls: bool,
    vision_config: VisionConfig | None,
    meter: Meter | None,
    store_path: Path | None,
    activity: Sequence[ActivityRow],
    known_identifiers: frozenset[str] | set[str],
) -> tuple[list[EvidenceObservation], ParseReport]:
    family = PNG_FAMILY_BY_ORIGIN.get(origin)
    report = _report(file_id, f"png:{family or 'unknown'}", captured_at, sha256)
    if family is None or family not in FAMILY_FIELDS:
        report.errors.append(f"unknown_png_family_for_origin:{origin}")
        report.status = ParseStatus.UNKNOWN_STATE
        return [], report
    entry = _store_entry(store_path, sha256, vision_config)
    if entry is None:
        can_extract = (
            allow_model_calls
            and vision_config is not None
            and vision_config.available()
            and meter is not None
        )
        if not can_extract:
            report.status = ParseStatus.UNSUPPORTED_FORMAT
            report.errors.append("extraction_unavailable")
            return [], report
        assert vision_config is not None
        assert meter is not None
        try:
            entry = transcribe_two_pass(
                vision_config,
                path,
                file_id=file_id,
                family=family,
                meter=meter,
                store_path=store_path,
            )
        except VisionError as exc:
            report.status = ParseStatus.PARSE_ERROR
            report.errors.append(f"vision_error:{exc}")
            return [], report
    validation = validate_transcription(family, dict(entry.merged), set(known_identifiers))
    confidence = tuple(sorted(set(validation.flags) | set(entry.disagreements)))
    report.extracted_records = (
        ExtractedRecord(
            file_id=file_id,
            family=family,
            record_index=0,
            fields=tuple(entry.merged.items()),
            source="vlm",
            confidence_flags=confidence,
        ),
    )
    if validation.errors:
        report.errors.extend(validation.errors)
        report.status = ParseStatus.PARSE_ERROR
        return [], report
    if entry.disagreements:
        report.errors.extend(entry.disagreements)
    observations, diagnostics = decode_png_records(
        family,
        entry.merged,
        file_id=file_id,
        captured_at=captured_at,
        activity=activity,
    )
    for diagnostic in diagnostics:
        if diagnostic not in INFORMATIONAL_DIAGNOSTICS:
            report.errors.append(diagnostic)
    report.status = finalize_status(report.errors, observations)
    return observations, report


def parse_multimodal_file(
    file_id: str,
    path: Path,
    captured_at: str,
    *,
    origin: str,
    allow_model_calls: bool = False,
    vision_config: VisionConfig | None = None,
    meter: Meter | None = None,
    store_path: Path | None = None,
    activity: Sequence[ActivityRow] = (),
    known_identifiers: frozenset[str] | set[str] = frozenset(),
) -> tuple[list[EvidenceObservation], ParseReport]:
    """Parse one PDF/PNG evidence file; never guesses a state."""
    suffix = path.suffix.lower()
    sha256 = file_sha256(path) if path.exists() else ""
    if suffix == ".pdf":
        return _parse_pdf(file_id, path, captured_at, sha256)
    if suffix == ".png":
        return _parse_png(
            file_id,
            path,
            captured_at,
            sha256,
            origin=origin,
            allow_model_calls=allow_model_calls,
            vision_config=vision_config,
            meter=meter,
            store_path=store_path,
            activity=activity,
            known_identifiers=known_identifiers,
        )
    report = _report(file_id, f"binary:{suffix or 'unknown'}", captured_at, sha256)
    report.status = ParseStatus.UNSUPPORTED_FORMAT
    report.errors.append(f"unsupported_suffix:{suffix or '<none>'}")
    return [], report
