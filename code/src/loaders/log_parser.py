"""Deterministic parser for log evidence.

Seven line shapes are recognised explicitly (plain ``key=value``, syslog-RFC,
JSON-per-line, pipe-delimited, bracketed, ``cloud_runtime message="..."``).
Only events that carry documented state fields become observations; every other
line is ignored and counted. A state-bearing line with missing/unknown fields
becomes an UNKNOWN observation, a structurally broken line becomes a line-level
error, and neither is silently dropped.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..models import (
    EvidenceObservation,
    ObservationState,
    ParseReport,
    ParseStatus,
    Provenance,
    finalize_status,
    make_observation,
)
from .common import file_sha256
from .state_vocab import (
    StateResult,
    clean,
    decode_account_readback,
    decode_analytics,
    decode_available,
    decode_enabled,
    decode_matched_value,
    decode_restore_allowed,
    decode_restore_decision,
    decode_result,
    decode_row_count,
    decode_search_result,
    decode_support,
    is_null,
)

ParseOutput = tuple[list[EvidenceObservation], ParseReport]

TIMESTAMP = re.compile(r"^(\S+Z)\s+")
TOKEN = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)=("(?:[^"\\]|\\.)*"|\S+)')

BRACKET = re.compile(r"^\S+Z\s+\[(\w+)\]\s+\[([\w.-]+)\]\s+\[([\w.-]+)\]\s+(\w+):\s*(.*)$")
PIPE = re.compile(r"^\S+Z\s+\|\s+(\w+)\s+\|\s+([\w.-]+)\s+\|\s+(\S+)\s+\|\s+(\w+)\s+\|\s+(.*)$")
JSON_LINE = re.compile(r"^\S+Z\s+(\{.*\})\s*$")
SYSLOG = re.compile(r"^\S+Z\s+<\d+>1\s+(\S+)\s+(\S+)\s+(\S+)\s+-\s+-\s+(.*)$")
CLOUD = re.compile(r'^\S+Z\s+requestId=(\S+)\s+level=(\w+)\s+function=(\S+)\s+message="(.*)"\s*$')
PLAIN = re.compile(r"^\S+Z\s+(.*)$")


@dataclass(frozen=True)
class DecodedEvent:
    system_id: str
    data_category: str
    result: StateResult
    identifiers: tuple[str, ...]
    state_inputs: dict[str, str]
    pii_exposed: bool
    provenance: Provenance


def parse_tokens(text: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    for key, raw in TOKEN.findall(text):
        value = raw
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        tokens[key] = value
    return tokens


def parse_line(line: str) -> tuple[str, dict[str, str]] | None:
    """Return (shape, fields) for recognised shapes, else None."""
    match = JSON_LINE.match(line)
    if match:
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        body = {str(key): "" if value is None else str(value) for key, value in payload.items()}
        if "logger" in body:
            body.setdefault("service", body["logger"])
        return "json", body
    match = SYSLOG.match(line)
    if match:
        body = parse_tokens(match.group(4))
        body.setdefault("service", match.group(2))
        body.setdefault("trace_id", match.group(3))
        return "syslog", body
    match = PIPE.match(line)
    if match:
        body = parse_tokens(match.group(5))
        body["event"] = match.group(4)
        body.setdefault("service", match.group(2))
        return "pipe", body
    match = BRACKET.match(line)
    if match:
        body = parse_tokens(match.group(5))
        body["event"] = match.group(4)
        body.setdefault("service", match.group(2))
        return "bracket", body
    match = CLOUD.match(line)
    if match:
        body = parse_tokens(match.group(4).replace('\\"', '"'))
        body.setdefault("level", match.group(2))
        return "cloud", body
    match = PLAIN.match(line)
    if match:
        body = parse_tokens(match.group(1))
        return "plain", body
    return None


def _identifiers(*values: object) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if clean(value) is not None)


def _pii(*values: object) -> bool:
    return any(not is_null(value) for value in values)


def _readback_account(body: dict[str, str]) -> DecodedEvent:
    state, reason = decode_account_readback(body.get("rows"), body.get("http_status"))
    reference = body.get("customer_reference")
    if (
        state is ObservationState.PRESENT
        and not _pii(body.get("email"), body.get("phone"))
        and clean(reference) is not None
    ):
        state = ObservationState.REDACTED
        reason = f"{reason},direct_identifiers_null,reference_present"
    return DecodedEvent(
        system_id="account_service",
        data_category="USER_PROFILE",
        result=(state, reason),
        identifiers=_identifiers(body.get("email"), body.get("phone"), reference),
        state_inputs={
            "rows": body.get("rows", ""),
            "http_status": body.get("http_status", ""),
            "customer_reference": "" if reference is None else reference,
        },
        pii_exposed=_pii(body.get("email"), body.get("phone")),
        provenance=Provenance.READBACK,
    )


def _support_readback(body: dict[str, str]) -> DecodedEvent:
    fields = {
        "requester_name": body.get("requester_name"),
        "requester_email": body.get("requester_email"),
        "requester_phone": body.get("requester_phone"),
    }
    reference = body.get("customer_reference")
    state, reason = decode_support(fields, reference)
    return DecodedEvent(
        system_id="support_platform",
        data_category="SUPPORT_MESSAGE",
        result=(state, reason),
        identifiers=_identifiers(*fields.values(), reference, body.get("lookup_key")),
        state_inputs={key: "" if value is None else str(value) for key, value in fields.items()},
        pii_exposed=_pii(*fields.values()),
        provenance=Provenance.READBACK,
    )


def _simple(
    system_id: str,
    data_category: str,
    result: StateResult,
    body: dict[str, str],
    *,
    identifiers: tuple[str, ...] = (),
    state_inputs: dict[str, str] | None = None,
    pii_exposed: bool = False,
    provenance: Provenance = Provenance.EXPLICIT_FIELD,
) -> DecodedEvent:
    return DecodedEvent(
        system_id=system_id,
        data_category=data_category,
        result=result,
        identifiers=identifiers,
        state_inputs=state_inputs or {},
        pii_exposed=pii_exposed,
        provenance=provenance,
    )


def decode_event(event: str, body: dict[str, str]) -> DecodedEvent | None:
    """Map a state-bearing event to an explicit decoder; None means ignore."""
    if event == "profile_lookup_completed":
        return _readback_account(body)
    if event == "support_ticket_read_completed":
        return _support_readback(body)
    if event == "contact_query_completed":
        state, reason = decode_row_count(body.get("rows"))
        return _simple(
            "support_platform",
            "SUPPORT_MESSAGE",
            (state, reason),
            body,
            identifiers=_identifiers(body.get("lookup_key")),
            state_inputs={"rows": body.get("rows", "")},
            provenance=Provenance.READBACK,
        )
    if event in {"message_pii_scan", "attachment_pii_scan"}:
        state, reason = decode_matched_value(body.get("matched_value"))
        category = "SUPPORT_MESSAGE" if event == "message_pii_scan" else "SUPPORT_ATTACHMENT"
        return _simple(
            "support_platform",
            category,
            (state, reason),
            body,
            identifiers=_identifiers(body.get("matched_value")),
            state_inputs={"matched_value": body.get("matched_value", "")},
            pii_exposed=state is ObservationState.PRESENT,
        )
    if event in {
        "connector_config_read_completed",
        "connector_config_loaded",
        "connector_heartbeat",
    }:
        return _simple(
            "integration_service",
            "DATA_FLOW",
            decode_enabled(body.get("enabled")),
            body,
            identifiers=_identifiers(
                body.get("customer_email"),
                body.get("customer_reference"),
                body.get("subject_selector"),
            ),
            state_inputs={"enabled": body.get("enabled", "")},
            pii_exposed=_pii(body.get("customer_email")),
        )
    if event == "restore_policy_read_completed":
        return _simple(
            "backup_service",
            "BACKUP_ARCHIVE",
            decode_restore_allowed(body.get("restore_allowed")),
            body,
            identifiers=_identifiers(body.get("customer_email"), body.get("customer_reference")),
            state_inputs={"restore_allowed": body.get("restore_allowed", "")},
            pii_exposed=_pii(body.get("customer_email")),
        )
    if event == "restore_candidate_evaluated":
        eligible = clean(body.get("eligible"))
        deletion_block = clean(body.get("deletion_block"))
        if deletion_block is not None and deletion_block.lower() == "false" and eligible == "true":
            result: StateResult = (ObservationState.ACTIVE, "eligible=true,deletion_block=false")
        elif deletion_block is not None and deletion_block.lower() == "true":
            result = (ObservationState.UNKNOWN, "deletion_block_true_unmapped")
        elif eligible is not None and eligible.lower() == "false":
            result = (ObservationState.UNKNOWN, "eligible_false_unmapped")
        else:
            result = (ObservationState.UNKNOWN, "missing_field:eligible_or_deletion_block")
        return _simple(
            "backup_service",
            "BACKUP_ARCHIVE",
            result,
            body,
            state_inputs={
                "eligible": body.get("eligible", ""),
                "deletion_block": body.get("deletion_block", ""),
            },
        )
    if event == "restore_authorization_completed":
        return _simple(
            "backup_service",
            "BACKUP_ARCHIVE",
            decode_restore_decision(body.get("decision")),
            body,
            state_inputs={"decision": body.get("decision", "")},
        )
    if event == "index_query_completed":
        return _simple(
            "search_service",
            "SEARCH_INDEX_ENTRY",
            decode_search_result(body.get("result"), body.get("total_hits")),
            body,
            identifiers=_identifiers(body.get("email"), body.get("customer_reference")),
            state_inputs={
                "result": body.get("result", ""),
                "total_hits": body.get("total_hits", ""),
            },
        )
    if event == "audit_record_read_completed":
        return _simple(
            "security_service",
            "SECURITY_AUDIT_LOG",
            decode_row_count(body.get("rows")),
            body,
            identifiers=_identifiers(body.get("subject_reference")),
            state_inputs={"rows": body.get("rows", "")},
            provenance=Provenance.READBACK,
        )
    if event in {"analytics_profile_read", "analytics_profile_read_completed"}:
        state, reason = decode_analytics(
            body.get("direct_identifiers"), {"email": body.get("email"), "phone": body.get("phone")}
        )
        return _simple(
            "analytics_platform",
            "ANALYTICS_PROFILE",
            (state, reason),
            body,
            identifiers=_identifiers(body.get("email"), body.get("phone")),
            state_inputs={
                "direct_identifiers": body.get("direct_identifiers", ""),
                "email": body.get("email", ""),
                "phone": body.get("phone", ""),
            },
            pii_exposed=_pii(body.get("email"), body.get("phone")),
        )
    if event == "analytics_identity_scan":
        state, reason = decode_matched_value(body.get("matched_value"))
        return _simple(
            "analytics_platform",
            "ANALYTICS_PROFILE",
            (state, reason),
            body,
            identifiers=_identifiers(body.get("matched_value")),
            state_inputs={"matched_value": body.get("matched_value", "")},
            pii_exposed=state is ObservationState.PRESENT,
        )
    if event == "contact_lookup_completed":
        return _simple(
            "analytics_platform",
            "ANALYTICS_PROFILE",
            decode_row_count(body.get("rows")),
            body,
            identifiers=_identifiers(body.get("correlation_key")),
            state_inputs={
                "rows": body.get("rows", ""),
                "email_opt_in": body.get("email_opt_in", ""),
            },
            provenance=Provenance.READBACK,
        )
    if event in {"export_download_check_completed", "export_metadata_read_completed"}:
        return _simple(
            "export_service",
            "USER_EXPORT",
            decode_available(body.get("available")),
            body,
            identifiers=_identifiers(body.get("owner_email")),
            state_inputs={"available": body.get("available", "")},
            pii_exposed=_pii(body.get("owner_email")),
            provenance=Provenance.READBACK,
        )
    if event == "record_lookup":
        system_id = clean(body.get("system"))
        if system_id is None:
            return _simple(
                "unknown",
                "UNKNOWN",
                (ObservationState.UNKNOWN, "missing_field:system"),
                body,
                state_inputs={"result": body.get("result", "")},
                provenance=Provenance.LEDGER_RESULT,
            )
        return _simple(
            system_id,
            clean(body.get("record_type")) or "UNKNOWN",
            decode_result(body.get("result")),
            body,
            identifiers=_identifiers(body.get("subject_reference")),
            state_inputs={
                "result": body.get("result", ""),
                "record_type": body.get("record_type", ""),
            },
            provenance=Provenance.LEDGER_RESULT,
        )
    return None


def parse_log_file(file_id: str, path: Path, captured_at: str) -> ParseOutput:
    report = ParseReport(
        file_id=file_id,
        family="log",
        captured_at=captured_at,
        sha256=file_sha256(path),
        status=ParseStatus.OK,
    )
    observations: list[EvidenceObservation] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.errors.append(f"read_error:{exc}")
        report.status = ParseStatus.PARSE_ERROR
        return observations, report
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        parsed = parse_line(line)
        if parsed is None:
            report.errors.append(f"log:{line_number}: unrecognized_line")
            continue
        _shape, body = parsed
        event = body.get("event") or ""
        decoded = decode_event(event, body)
        if decoded is None:
            report.ignored_lines += 1
            continue
        resource_id = clean(body.get("resource_id"))
        if resource_id is None:
            report.errors.append(f"log:{line_number}: {event} without resource_id")
            continue
        timestamp_match = TIMESTAMP.match(line)
        observed_at = timestamp_match.group(1) if timestamp_match else captured_at
        state, reason = decoded.result
        observations.append(
            make_observation(
                file_id=file_id,
                captured_at=observed_at,
                system_id=decoded.system_id,
                resource_id=resource_id,
                data_category=decoded.data_category,
                state=state,
                reason=reason,
                locator=f"line:{line_number}",
                provenance=decoded.provenance,
                identifiers=decoded.identifiers,
                state_inputs=decoded.state_inputs,
                pii_exposed=decoded.pii_exposed,
            )
        )
    report.status = finalize_status(report.errors, observations)
    return observations, report
