"""Typed evidence observations shared by every Phase 3 parser.

No state is ever inferred here: an observation either carries a state decoded
from an explicit field or the explicit ``UNKNOWN`` state with a reason. File or
record failures are represented by ``ParseStatus.PARSE_ERROR``; families owned by
Phase 4 (PDF/PNG) are ``UNSUPPORTED_FORMAT``.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ObservationState(StrEnum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    REDACTED = "REDACTED"
    ANONYMIZED = "ANONYMIZED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


class ParseStatus(StrEnum):
    OK = "OK"
    UNKNOWN_STATE = "UNKNOWN_STATE"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"


class Provenance(StrEnum):
    EXPLICIT_FIELD = "EXPLICIT_FIELD"
    LEDGER_RESULT = "LEDGER_RESULT"
    READBACK = "READBACK"
    NULL_PII_RULE = "NULL_PII_RULE"
    SCOPE_IMPLICIT = "SCOPE_IMPLICIT"
    HANDOVER = "HANDOVER"
    DOCUMENT_TEXT = "DOCUMENT_TEXT"
    VISION_TRANSCRIPTION = "VISION_TRANSCRIPTION"


@dataclass(frozen=True)
class EvidenceObservation:
    file_id: str
    captured_at: str
    system_id: str
    resource_id: str
    data_category: str | None
    state: ObservationState
    parse_status: ParseStatus
    reason: str
    locator: str
    provenance: Provenance
    identifiers: tuple[str, ...] = ()
    state_inputs: tuple[tuple[str, str], ...] = ()
    pii_exposed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "captured_at": self.captured_at,
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "data_category": self.data_category,
            "state": self.state.value,
            "parse_status": self.parse_status.value,
            "reason": self.reason,
            "locator": self.locator,
            "provenance": self.provenance.value,
            "identifiers": list(self.identifiers),
            "state_inputs": dict(self.state_inputs),
            "pii_exposed": self.pii_exposed,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceObservation":
        return cls(
            file_id=str(data["file_id"]),
            captured_at=str(data["captured_at"]),
            system_id=str(data["system_id"]),
            resource_id=str(data["resource_id"]),
            data_category=None if data.get("data_category") is None else str(data["data_category"]),
            state=ObservationState(data["state"]),
            parse_status=ParseStatus(data["parse_status"]),
            reason=str(data["reason"]),
            locator=str(data["locator"]),
            provenance=Provenance(data["provenance"]),
            identifiers=tuple(sorted({str(item) for item in data.get("identifiers", [])})),
            state_inputs=tuple(
                sorted((str(k), str(v)) for k, v in dict(data.get("state_inputs", {})).items())
            ),
            pii_exposed=bool(data.get("pii_exposed", False)),
        )


@dataclass(frozen=True)
class ExtractedRecord:
    """One transcribed record from a PDF page or image; facts only, no state."""

    file_id: str
    family: str
    record_index: int
    fields: tuple[tuple[str, Any], ...]
    source: str
    confidence_flags: tuple[str, ...] = ()

    def field(self, name: str) -> Any | None:
        for key, value in self.fields:
            if key == name:
                return value
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "family": self.family,
            "record_index": self.record_index,
            "fields": dict(self.fields),
            "source": self.source,
            "confidence_flags": list(self.confidence_flags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExtractedRecord":
        return cls(
            file_id=str(data["file_id"]),
            family=str(data["family"]),
            record_index=int(data["record_index"]),
            fields=tuple((str(key), value) for key, value in dict(data.get("fields", {})).items()),
            source=str(data.get("source", "")),
            confidence_flags=tuple(str(flag) for flag in data.get("confidence_flags", [])),
        )


@dataclass(frozen=True)
class CapturedCollection:
    """Explicit metadata that a snapshot covered a collection (even when empty)."""

    data_store: str
    collection: str
    captured_at: str
    record_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_store": self.data_store,
            "collection": self.collection,
            "captured_at": self.captured_at,
            "record_count": self.record_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CapturedCollection":
        return cls(
            data_store=str(data["data_store"]),
            collection=str(data["collection"]),
            captured_at=str(data["captured_at"]),
            record_count=int(data["record_count"]),
        )


@dataclass
class ParseReport:
    file_id: str
    family: str
    captured_at: str
    sha256: str
    status: ParseStatus
    errors: list[str] = field(default_factory=list)
    scope: dict[str, str] = field(default_factory=dict)
    captured_collections: list[CapturedCollection] = field(default_factory=list)
    direct_systems: tuple[str, ...] = ()
    ignored_lines: int = 0
    extracted_records: tuple[ExtractedRecord, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_id": self.file_id,
            "family": self.family,
            "captured_at": self.captured_at,
            "sha256": self.sha256,
            "status": self.status.value,
            "errors": list(self.errors),
            "scope": dict(self.scope),
            "captured_collections": [c.to_dict() for c in self.captured_collections],
            "direct_systems": list(self.direct_systems),
            "ignored_lines": self.ignored_lines,
            "extracted_records": [record.to_dict() for record in self.extracted_records],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParseReport":
        return cls(
            file_id=str(data["file_id"]),
            family=str(data["family"]),
            captured_at=str(data["captured_at"]),
            sha256=str(data["sha256"]),
            status=ParseStatus(data["status"]),
            errors=[str(item) for item in data.get("errors", [])],
            scope={str(k): str(v) for k, v in dict(data.get("scope", {})).items()},
            captured_collections=[
                CapturedCollection.from_dict(item) for item in data.get("captured_collections", [])
            ],
            direct_systems=tuple(str(s) for s in data.get("direct_systems", [])),
            ignored_lines=int(data.get("ignored_lines", 0)),
            extracted_records=tuple(
                ExtractedRecord.from_dict(item) for item in data.get("extracted_records", [])
            ),
        )


def finalize_status(errors: list[str], observations: list[EvidenceObservation]) -> ParseStatus:
    """Derive the file status from decode errors and UNKNOWN observations."""
    if errors:
        return ParseStatus.UNKNOWN_STATE
    if any(obs.state is ObservationState.UNKNOWN for obs in observations):
        return ParseStatus.UNKNOWN_STATE
    return ParseStatus.OK


def make_observation(
    *,
    file_id: str,
    captured_at: str,
    system_id: str,
    resource_id: str,
    data_category: str | None,
    state: ObservationState,
    reason: str,
    locator: str,
    provenance: Provenance,
    identifiers: tuple[str, ...] = (),
    state_inputs: dict[str, str] | None = None,
    pii_exposed: bool = False,
) -> EvidenceObservation:
    parse_status = (
        ParseStatus.UNKNOWN_STATE if state is ObservationState.UNKNOWN else ParseStatus.OK
    )
    return EvidenceObservation(
        file_id=file_id,
        captured_at=captured_at,
        system_id=system_id,
        resource_id=resource_id,
        data_category=data_category,
        state=state,
        parse_status=parse_status,
        reason=reason,
        locator=locator,
        provenance=provenance,
        identifiers=tuple(sorted({item.strip() for item in identifiers if item and item.strip()})),
        state_inputs=tuple(sorted((state_inputs or {}).items())),
        pii_exposed=pii_exposed,
    )
