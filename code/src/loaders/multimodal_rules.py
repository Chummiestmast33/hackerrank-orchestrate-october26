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


# --------------------------------------------------------------------------- #
# PNG decode tables (P4.7)
# --------------------------------------------------------------------------- #

PNG_FAMILY_TARGETS: dict[str, tuple[str, str]] = {
    "account_console": ("account_service", "USER_PROFILE"),
    "search_inspector": ("search_service", "SEARCH_INDEX_ENTRY"),
    "connector_console": ("integration_service", "DATA_FLOW"),
    "analytics_profile": ("analytics_platform", "ANALYTICS_PROFILE"),
    "export_console": ("export_service", "USER_EXPORT"),
    "support_console": ("support_platform", "SUPPORT_MESSAGE"),
    "backup_console": ("backup_service", "BACKUP_ARCHIVE"),
    "marketing_profile": ("marketing_platform", "MARKETING_PROFILE"),
    "sentinel_events": ("security_service", "SECURITY_AUDIT_LOG"),
    "reference_registry": ("identity_service", "ACCOUNT_TOMBSTONE"),
}

STATUS_TOKENS: dict[str, ObservationState] = {
    "disabled": ObservationState.DISABLED,
    "blocked": ObservationState.BLOCKED,
    "restore blocked": ObservationState.BLOCKED,
    "anonymized": ObservationState.ANONYMIZED,
    "de-identified": ObservationState.ANONYMIZED,
    "redacted": ObservationState.REDACTED,
    "deleted": ObservationState.ABSENT,
    "not found": ObservationState.ABSENT,
    "removed": ObservationState.ABSENT,
    "enabled": ObservationState.ACTIVE,
}

STATUS_KEY_HINTS = ("status", "mode", "state", "restore", "opt_in", "badge", "integrity")
PHONE_TOKEN = re.compile(r"\+\d[\d\s()-]{7,}\d")
NAME_KEYS = ("name", "customer_name", "display_name", "requester_name")


@dataclass
class _Candidate:
    resource_id: str
    identifiers: tuple[str, ...] = ()
    status_labels: tuple[str, ...] = ()
    category: str | None = None
    existence_present: bool = False
    forced_state: ObservationState | None = None


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        found: list[str] = []
        for item in value.values():
            found.extend(_strings(item))
        return found
    if isinstance(value, (list, tuple)):
        found = []
        for item in value:
            found.extend(_strings(item))
        return found
    return []


def _labels_from(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    labels: list[str] = []
    for key, value in mapping.items():
        lowered = str(key).lower()
        if "order" in lowered:
            continue
        if any(hint in lowered for hint in STATUS_KEY_HINTS):
            labels.extend(text for text in _strings(value) if text)
    return tuple(labels)


def _pii_from(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    found: list[str] = []
    for key, value in mapping.items():
        if isinstance(value, str):
            if any(part == key.lower() or part in key.lower() for part in NAME_KEYS):
                if value.strip():
                    found.append(value.strip())
            found.extend(match.group(0) for match in EMAIL_TOKEN.finditer(value))
            found.extend(match.group(0) for match in PHONE_TOKEN.finditer(value))
        else:
            for text in _strings(value):
                found.extend(match.group(0) for match in EMAIL_TOKEN.finditer(text))
                found.extend(match.group(0) for match in PHONE_TOKEN.finditer(text))
    return tuple(dict.fromkeys(found))


def _row_resource(row: Mapping[str, Any]) -> str | None:
    for key in (
        "resource_id",
        "account_id",
        "analytics_id",
        "marketing_id",
        "audit_id",
        "support_id",
        "_id",
        "id",
    ):
        value = row.get(key)
        if isinstance(value, str) and RESOURCE_TOKEN.fullmatch(value):
            return value
    return None


def _png_candidates(
    family: str,
    fields: Mapping[str, Any],
    activity: Sequence[ActivityRow],
) -> tuple[list[_Candidate], list[str]]:
    candidates: list[_Candidate] = []
    diagnostics: list[str] = []
    if family == "account_console":
        account = fields.get("account_id")
        if isinstance(account, str) and RESOURCE_TOKEN.fullmatch(account):
            candidates.append(
                _Candidate(
                    resource_id=account,
                    identifiers=_pii_from(
                        {
                            "name": fields.get("name"),
                            "email": fields.get("email"),
                            "phone": fields.get("phone"),
                        }
                    ),
                    status_labels=_labels_from(fields),
                )
            )
        support = fields.get("support_ref")
        if isinstance(support, Mapping):
            support_id = support.get("support_id") or support.get("resource_id")
            if isinstance(support_id, str) and RESOURCE_TOKEN.fullmatch(support_id):
                candidates.append(
                    _Candidate(
                        resource_id=support_id,
                        identifiers=_pii_from(
                            {
                                "name": fields.get("name"),
                                "email": fields.get("email"),
                                "phone": fields.get("phone"),
                            }
                        ),
                        category="SUPPORT_MESSAGE",
                    )
                )
    elif family == "search_inspector":
        for row in fields.get("results") or []:
            if not isinstance(row, Mapping):
                continue
            resource = _row_resource(row)
            if resource is None:
                continue
            candidates.append(_Candidate(resource_id=resource, identifiers=_pii_from(row)))
    elif family == "connector_console":
        for row in fields.get("connectors") or []:
            if not isinstance(row, Mapping):
                continue
            resource = _row_resource(row)
            if resource is None:
                continue
            candidates.append(
                _Candidate(
                    resource_id=resource,
                    identifiers=_pii_from(row),
                    status_labels=_labels_from(row),
                )
            )
        detail = fields.get("detail")
        if isinstance(detail, Mapping):
            resource = _row_resource(detail)
            if resource is not None:
                candidates.append(
                    _Candidate(
                        resource_id=resource,
                        identifiers=_pii_from(detail),
                        status_labels=_labels_from(detail),
                    )
                )
    elif family == "analytics_profile":
        resource = fields.get("analytics_id")
        if isinstance(resource, str) and RESOURCE_TOKEN.fullmatch(resource):
            candidates.append(
                _Candidate(
                    resource_id=resource,
                    identifiers=_pii_from(
                        {
                            "name": fields.get("name"),
                            "email": fields.get("email"),
                        }
                    ),
                    status_labels=_labels_from(fields),
                )
            )
    elif family == "export_console":
        for row in fields.get("jobs") or []:
            if not isinstance(row, Mapping):
                continue
            resource = _row_resource(row)
            if resource is None:
                continue
            candidates.append(
                _Candidate(
                    resource_id=resource,
                    identifiers=_pii_from(row),
                    status_labels=_labels_from(row),
                )
            )
    elif family == "support_console":
        resource = fields.get("resource_id")
        if isinstance(resource, str) and RESOURCE_TOKEN.fullmatch(resource):
            candidates.append(
                _Candidate(
                    resource_id=resource,
                    identifiers=_pii_from(
                        {
                            "name": fields.get("customer_name"),
                            "email": fields.get("email"),
                        }
                    ),
                    status_labels=_labels_from(fields),
                )
            )
    elif family == "backup_console":
        for row in fields.get("archives") or []:
            if not isinstance(row, Mapping):
                continue
            resource = _row_resource(row)
            if resource is None:
                continue
            candidates.append(
                _Candidate(
                    resource_id=resource,
                    identifiers=_pii_from(row),
                    status_labels=_labels_from(row),
                )
            )
        detail = fields.get("detail")
        if isinstance(detail, Mapping):
            resource = _row_resource(detail)
            if resource is not None:
                candidates.append(
                    _Candidate(
                        resource_id=resource,
                        identifiers=_pii_from(detail),
                        status_labels=_labels_from(detail),
                    )
                )
    elif family == "marketing_profile":
        resource = fields.get("marketing_id")
        if isinstance(resource, str) and RESOURCE_TOKEN.fullmatch(resource):
            candidates.append(
                _Candidate(
                    resource_id=resource,
                    identifiers=_pii_from(
                        {
                            "name": fields.get("name"),
                            "email": fields.get("email"),
                            "phone": fields.get("phone"),
                        }
                    ),
                    status_labels=_labels_from(fields),
                )
            )
    elif family == "sentinel_events":
        for row in fields.get("events") or []:
            if not isinstance(row, Mapping):
                continue
            resource = _row_resource(row)
            if resource is None:
                continue
            candidates.append(
                _Candidate(
                    resource_id=resource,
                    identifiers=tuple(text for text in _strings(row.get("subject")) if text),
                    status_labels=_labels_from(row),
                    existence_present=True,
                )
            )
    elif family == "reference_registry":
        subject = fields.get("subject_reference")
        identifiers = _pii_from(fields)
        if isinstance(subject, str) and subject.strip():
            tombstone: str | None = None
            for row in activity:
                if row.event_type != "LINK_RESOURCE_IDENTITY":
                    continue
                if subject not in row.details:
                    continue
                tokens = RESOURCE_TOKEN.findall(row.details)
                tombstone = next(
                    (token for token in tokens if token.startswith("tombstone_")), None
                )
                if tombstone:
                    break
            if tombstone is None:
                diagnostics.append("unresolved_subject_reference")
            else:
                candidates.append(
                    _Candidate(
                        resource_id=tombstone,
                        identifiers=identifiers,
                        forced_state=ObservationState.PRESENT
                        if identifiers
                        else ObservationState.REDACTED,
                    )
                )
        else:
            diagnostics.append("missing_field:subject_reference")
    elif family == "object_storage":
        diagnostics.append("no_resource_id_in_document")
    else:
        diagnostics.append(f"unknown_png_family:{family}")
    return candidates, diagnostics


def _merge_candidate(existing: _Candidate, incoming: _Candidate) -> _Candidate:
    return _Candidate(
        resource_id=existing.resource_id,
        identifiers=tuple(dict.fromkeys(existing.identifiers + incoming.identifiers)),
        status_labels=tuple(dict.fromkeys(existing.status_labels + incoming.status_labels)),
        category=existing.category or incoming.category,
        existence_present=existing.existence_present or incoming.existence_present,
        forced_state=existing.forced_state or incoming.forced_state,
    )


def _has_direct_pii(identifiers: Sequence[str]) -> bool:
    for value in identifiers:
        if "@" in value or PHONE_TOKEN.fullmatch(value):
            return True
        if USER_TOKEN.fullmatch(value) or RESOURCE_TOKEN.fullmatch(value):
            continue
        if value.strip():
            return True
    return False


def decode_png_records(
    family: str,
    fields: Mapping[str, Any],
    *,
    file_id: str,
    captured_at: str,
    activity: Sequence[ActivityRow] = (),
) -> tuple[list[EvidenceObservation], list[str]]:
    """Decode a PNG transcription via explicit tables; never guess a state."""
    candidates, diagnostics = _png_candidates(family, fields, activity)
    if family not in PNG_FAMILY_TARGETS:
        return [], diagnostics
    system_id, default_category = PNG_FAMILY_TARGETS[family]
    merged: dict[str, _Candidate] = {}
    for candidate in candidates:
        if candidate.resource_id in merged:
            merged[candidate.resource_id] = _merge_candidate(
                merged[candidate.resource_id], candidate
            )
        else:
            merged[candidate.resource_id] = candidate
    observations: list[EvidenceObservation] = []
    for resource_id in sorted(merged):
        candidate = merged[resource_id]
        explicit: tuple[ObservationState, str] | None = None
        for label in candidate.status_labels:
            state = STATUS_TOKENS.get(label.strip().lower())
            if state is not None:
                explicit = (state, f"console_status={label.strip()}")
                break
        pii_exposed = _has_direct_pii(candidate.identifiers)
        if candidate.forced_state is not None:
            state = candidate.forced_state
            reason = (
                "registry_reference_redacted"
                if state is ObservationState.REDACTED
                else "registry_identifiers_visible"
            )
        elif explicit is not None:
            state, reason = explicit
        elif candidate.existence_present:
            state, reason = ObservationState.PRESENT, "row_exists"
        elif pii_exposed:
            state, reason = ObservationState.PRESENT, "row_present_with_direct_pii"
        elif candidate.status_labels:
            state = ObservationState.UNKNOWN
            reason = f"unmapped_console_status:{candidate.status_labels[0]}"
        else:
            state, reason = ObservationState.UNKNOWN, "no_state_fields"
        observations.append(
            make_observation(
                file_id=file_id,
                captured_at=captured_at,
                system_id=system_id,
                resource_id=resource_id,
                data_category=candidate.category or default_category,
                state=state,
                reason=reason,
                locator=f"png:{family}:{resource_id}",
                provenance=Provenance.VISION_TRANSCRIPTION,
                identifiers=candidate.identifiers,
                state_inputs={
                    "console_status": "; ".join(candidate.status_labels),
                },
                pii_exposed=pii_exposed and state is not ObservationState.REDACTED,
            )
        )
    return observations, diagnostics
