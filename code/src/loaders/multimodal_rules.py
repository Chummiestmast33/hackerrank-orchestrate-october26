"""Explicit decode tables for multimodal facts and metadata-only relations.

This slice covers PDFs only. Decoding is strictly table-driven: document
families with a documented rule produce an observation; families that carry no
resource id produce facts only; missing required fields produce diagnostics.
Database/activity relations are computed by :func:`relate_to_structured` for
notes, tests and later verification work — they never change a decoded state.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..models import (
    EvidenceObservation,
    ExtractedRecord,
    ObservationState,
    ParseReport,
    Provenance,
    make_observation,
)
from .csv_loader import ActivityRow

RESOURCE_TOKEN = re.compile(
    r"\b(?:account|support|search|data_flow|analytics|export|backup|audit_record|tombstone|legal_hold|object|marketing)_\w+\b"
)
EMAIL_TOKEN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
USER_TOKEN = re.compile(r"\buser_\d+\b")
REFERENCE_TOKEN = re.compile(r"\b(?:ORD|CS|FIN)-\d+\b")

FAMILIES_WITH_OBSERVATIONS = {"support_attachment", "compliance_journal"}


@dataclass(frozen=True)
class RelationMatch:
    token: str
    kind: str
    status: str
    matches: tuple[tuple[str, str, str], ...] = ()
    link_activity_ids: tuple[str, ...] = ()


def _support_observation(record: ExtractedRecord, captured_at: str) -> EvidenceObservation:
    support_id = str(record.field("support_id"))
    name = record.field("requester_name")
    email = record.field("requester_email")
    phone = record.field("requester_phone")
    identifiers = tuple(str(value) for value in (name, email, phone) if value)
    pii_exposed = bool(identifiers)
    return make_observation(
        file_id=record.file_id,
        captured_at=captured_at,
        system_id="support_platform",
        resource_id=support_id,
        data_category="SUPPORT_ATTACHMENT",
        state=ObservationState.PRESENT,
        reason="document_attachment_present" + ("_with_pii" if pii_exposed else ""),
        locator=f"pdf:{record.family}:{record.record_index}",
        provenance=Provenance.DOCUMENT_TEXT,
        identifiers=identifiers,
        state_inputs={
            "ticket_ref": str(record.field("ticket_ref") or ""),
            "order_ref": str(record.field("order_ref") or ""),
            "file_name": str(record.field("file_name") or ""),
            "submitted_at": str(record.field("submitted_at") or ""),
        },
        pii_exposed=pii_exposed,
    )


def _journal_observation(record: ExtractedRecord, captured_at: str) -> EvidenceObservation:
    return make_observation(
        file_id=record.file_id,
        captured_at=captured_at,
        system_id="security_service",
        resource_id=str(record.field("event_reference")),
        data_category="SECURITY_AUDIT_LOG",
        state=ObservationState.PRESENT,
        reason="signed_journal_record_present",
        locator=f"pdf:{record.family}:{record.record_index}",
        provenance=Provenance.DOCUMENT_TEXT,
        identifiers=(str(record.field("subject_reference")),),
        state_inputs={
            "retain_until": str(record.field("retain_until") or ""),
            "recorded_at": str(record.field("recorded_at") or ""),
            "event_name": str(record.field("event_name") or ""),
            "journal_reference": str(record.field("journal_reference") or ""),
            "integrity_seal": str(record.field("integrity_seal") or ""),
        },
    )


def decode_pdf_records(
    records: Sequence[ExtractedRecord],
    *,
    captured_at: str,
) -> tuple[list[EvidenceObservation], list[str]]:
    """Decode extracted PDF facts via the explicit table; never guess."""
    observations: list[EvidenceObservation] = []
    diagnostics: list[str] = []
    for record in records:
        if record.family == "support_attachment":
            if record.field("support_id") is None:
                diagnostics.append(f"missing_field:support_id:{record.record_index}")
                continue
            observations.append(_support_observation(record, captured_at))
        elif record.family == "compliance_journal":
            missing = [
                name
                for name in ("event_reference", "subject_reference")
                if record.field(name) is None
            ]
            if missing:
                diagnostics.extend(
                    f"missing_field:{name}:{record.record_index}" for name in missing
                )
                continue
            observations.append(_journal_observation(record, captured_at))
        elif record.family in {"customer_statement", "retention_register"}:
            continue  # facts only: no resource id in these document families
        else:
            diagnostics.append(f"unknown_document_family:{record.family}")
    return observations, diagnostics


def _record_tokens(records: Sequence[ExtractedRecord]) -> dict[str, str]:
    tokens: dict[str, str] = {}

    def scan(text: str) -> None:
        for pattern, kind in (
            (RESOURCE_TOKEN, "resource_id"),
            (EMAIL_TOKEN, "email"),
            (USER_TOKEN, "user_id"),
            (REFERENCE_TOKEN, "reference"),
        ):
            for match in pattern.finditer(text):
                tokens.setdefault(match.group(0), kind)

    def walk(value: Any) -> None:
        if isinstance(value, str):
            scan(value)
        elif isinstance(value, Mapping):
            for item in value.values():
                walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    for record in records:
        for _key, value in record.fields:
            walk(value)
    return tokens


def relate_to_structured(
    records: Sequence[ExtractedRecord],
    index: Mapping[str, tuple[Sequence[EvidenceObservation], ParseReport]],
    activity: Sequence[ActivityRow] = (),
) -> list[RelationMatch]:
    """Return metadata-only relations between extracted tokens and evidence."""
    resource_matches: dict[str, set[tuple[str, str, str]]] = {}
    identifier_matches: dict[str, set[tuple[str, str, str]]] = {}
    for file_id, (observations, _report) in index.items():
        for observation in observations:
            key = (file_id, observation.system_id, observation.state.value)
            resource_matches.setdefault(observation.resource_id, set()).add(key)
            for identifier in observation.identifiers:
                identifier_matches.setdefault(identifier.strip().lower(), set()).add(key)

    link_rows = [row for row in activity if row.event_type == "LINK_RESOURCE_IDENTITY"]
    relations: list[RelationMatch] = []
    for token, kind in sorted(_record_tokens(records).items()):
        if kind == "resource_id":
            matches = resource_matches.get(token, set())
        elif kind in {"email", "user_id"}:
            matches = identifier_matches.get(token.lower(), set())
        else:
            matches = set()
        link_ids = tuple(
            sorted(
                {
                    row.activity_id
                    for row in link_rows
                    if row.resource_id == token or token.lower() in row.details.lower()
                }
            )
        )
        if matches:
            status = "matched"
        elif link_ids:
            status = "linked_only"
        else:
            status = "sole_source"
        relations.append(
            RelationMatch(
                token=token,
                kind=kind,
                status=status,
                matches=tuple(sorted(matches)),
                link_activity_ids=link_ids,
            )
        )
    return relations
