"""Deterministic checks for multimodal transcriptions.

Schema violations are errors; identifiers that cannot be tied to the
participant dataset are kept and flagged (never dropped or corrected).
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..models import EvidenceObservation
from .csv_loader import AuditLogRow, IdentityRow
from .multimodal_rules import EMAIL_TOKEN, USER_TOKEN
from .vlm_extractor import FAMILY_FIELDS, LIST_FIELDS, MAP_FIELDS

PHONE_TOKEN = re.compile(r"\+\d[\d\s()-]{7,}\d")
PHONE_FULL = re.compile(r"^\+\d[\d\s()-]{7,}\d$")
EMAIL_FULL = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
RESOURCE_FULL = re.compile(
    r"^(?:account|support|search|data_flow|analytics|export|backup|audit_record|tombstone|legal_hold|object|marketing)_\w+$"
)
RESOURCE_LIKE = re.compile(r"\b[a-z][a-z_]*_\d+\b")


@dataclass
class ValidationReport:
    fields: dict[str, Any]
    flags: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def normalize_identifier(value: str) -> str:
    text = " ".join(value.split()).strip().lower()
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") and digits:
        return digits
    return text


def build_known_identifiers(
    identities: Sequence[IdentityRow] = (),
    audit_log: Sequence[AuditLogRow] = (),
    observations: Iterable[EvidenceObservation] = (),
) -> set[str]:
    known: set[str] = set()
    for row in identities:
        for value in (row.name, row.email, row.phone, row.email_hash, row.user_id):
            if value:
                known.add(normalize_identifier(value))
    for audit in audit_log:
        for value in (audit.old_value, audit.new_value):
            if value:
                known.add(normalize_identifier(value))
    for observation in observations:
        for value in observation.identifiers:
            known.add(normalize_identifier(value))
        known.add(normalize_identifier(observation.resource_id))
    return known


def _iter_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_strings(item)


def validate_transcription(
    family: str,
    fields: dict[str, Any],
    known_identifiers: set[str],
) -> ValidationReport:
    report = ValidationReport(fields=fields)
    if family not in FAMILY_FIELDS:
        report.errors.append(f"unknown_family:{family}")
        return report
    expected = set(FAMILY_FIELDS[family])
    present = set(fields)
    for name in sorted(expected - present):
        report.errors.append(f"schema_violation:missing:{name}")
    for name in sorted(present - expected):
        report.errors.append(f"schema_violation:unexpected:{name}")
    list_fields = LIST_FIELDS.get(family, frozenset())
    map_fields = MAP_FIELDS.get(family, frozenset())
    for name in sorted(expected & present):
        value = fields[name]
        if value is None:
            continue
        if name in list_fields and not isinstance(value, list):
            report.errors.append(f"schema_violation:not_a_list:{name}")
        elif name in map_fields and not isinstance(value, dict):
            report.errors.append(f"schema_violation:not_an_object:{name}")
        elif name not in list_fields | map_fields and isinstance(value, (list, dict)):
            report.errors.append(f"schema_violation:not_a_scalar:{name}")

    flags: set[str] = set()
    for text in _iter_strings(fields):
        stripped = text.strip()
        if "@" in stripped:
            for email in EMAIL_TOKEN.finditer(stripped):
                token = email.group(0)
                if token.lower() not in known_identifiers:
                    flags.add(f"identifier_unverified:{token}")
            if not EMAIL_TOKEN.search(stripped) and "@" in stripped:
                report.errors.append(f"invalid_email:{stripped}"[:160])
        if stripped.startswith("+") and re.search(r"\d", stripped):
            if not PHONE_FULL.match(stripped):
                report.errors.append(f"invalid_phone:{stripped}"[:160])
            else:
                normalized = normalize_identifier(stripped)
                if normalized not in known_identifiers:
                    flags.add(f"identifier_unverified:{stripped}")
        for phone in PHONE_TOKEN.finditer(stripped):
            token = phone.group(0)
            if (
                not stripped.startswith("+")
                and normalize_identifier(token) not in known_identifiers
            ):
                flags.add(f"identifier_unverified:{token}")
        for user in USER_TOKEN.finditer(stripped):
            token = user.group(0)
            if token.lower() not in known_identifiers:
                flags.add(f"identifier_unverified:{token}")
        if RESOURCE_LIKE.fullmatch(stripped) and not stripped.startswith("user_"):
            if not RESOURCE_FULL.match(stripped):
                report.errors.append(f"invalid_resource_prefix:{stripped}")

    report.flags = sorted(flags)
    report.errors = sorted(set(report.errors))
    return report
