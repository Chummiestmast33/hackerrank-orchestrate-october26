"""Output-contract validator for `output.csv` (AGENTS.md sections 6.3 and 6.4).

Only rules stated explicitly in AGENTS.md section 6.3/6.4 are enforced: allowed
statuses, NOT_APPLICABLE => empty steps, exactly seven step fields, allowed
phase/operation/state triples, consecutive step_no, phase ordering, COMPLETE rows
being evidence-backed verification only, and INCOMPLETE rows citing evidence only
on FINDING steps. No invented minimum-step or required-phase rules.
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HEADER = ["case_id", "deletion_status", "steps_json"]
ALLOWED_STATUSES = ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE")
STEP_FIELDS = ("step_no", "phase", "system_id", "resource_id", "operation", "state", "evidence_id")
STEP_KEY_SET = frozenset(STEP_FIELDS)
PHASE_ORDER = {"FINDING": 1, "REMEDIATION": 2, "VERIFICATION": 3}

# operation -> (phase, state) exactly as tabled in AGENTS.md section 6.4
OPERATION_PHASE_STATE: dict[str, tuple[str, str]] = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}

_CASE_ID_RE = re.compile(r"^(?P<prefix>\D*)(?P<num>\d+)(?P<suffix>.*)$")


@dataclass
class OutputRow:
    case_id: str
    deletion_status: str
    steps: list[dict[str, Any]]
    raw_steps_json: str
    line_no: int


@dataclass
class FileValidation:
    violations: list[str] = field(default_factory=list)
    rows: list[OutputRow] = field(default_factory=list)
    detected_sort: str | None = None
    duplicate_ids: list[str] = field(default_factory=list)
    missing_ids: list[str] = field(default_factory=list)
    extra_ids: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.violations


def natural_key(case_id: str) -> tuple[object, ...]:
    match = _CASE_ID_RE.match(case_id)
    if not match:
        return (case_id, 0, "")
    return (match.group("prefix"), int(match.group("num")), match.group("suffix"))


def detect_sort(ids: list[str]) -> str | None:
    if len(ids) <= 1:
        return "trivial"
    lexicographic = ids == sorted(ids)
    natural = ids == sorted(ids, key=natural_key)
    if lexicographic and natural:
        return "both"
    if lexicographic:
        return "lexicographic"
    if natural:
        return "natural"
    return None


def validate_step(step: Any, position: int, case_id: str) -> list[str]:
    violations: list[str] = []
    context = f"{case_id}: step {position}"
    if not isinstance(step, dict):
        return [f"{context}: not a JSON object"]
    keys = set(step)
    missing = STEP_KEY_SET - keys
    extra = keys - STEP_KEY_SET
    if missing:
        violations.append(f"{context}: missing fields {sorted(missing)}")
    if extra:
        violations.append(f"{context}: unexpected fields {sorted(extra)}")
    for key in STEP_FIELDS:
        if key not in keys:
            continue
        if key == "step_no":
            if not isinstance(step[key], int) or isinstance(step[key], bool):
                violations.append(f"{context}: step_no must be an integer")
        elif not isinstance(step[key], str):
            violations.append(f"{context}: {key} must be a string")
    operation = str(step.get("operation"))
    phase = str(step.get("phase"))
    state = str(step.get("state"))
    if phase not in PHASE_ORDER:
        violations.append(f"{context}: unknown phase {phase!r}")
    if operation not in OPERATION_PHASE_STATE:
        violations.append(f"{context}: unknown operation {operation!r}")
    else:
        want_phase, want_state = OPERATION_PHASE_STATE[operation]
        if phase != want_phase:
            violations.append(
                f"{context}: operation {operation} belongs to phase {want_phase}, got {phase!r}"
            )
        if state != want_state:
            violations.append(
                f"{context}: operation {operation} requires state {want_state}, got {state!r}"
            )
    return violations


def validate_row(case_id: str, deletion_status: str, steps: list[dict[str, Any]]) -> list[str]:
    violations: list[str] = []
    if deletion_status not in ALLOWED_STATUSES:
        violations.append(f"{case_id}: unknown deletion_status {deletion_status!r}")
        return violations
    if deletion_status == "NOT_APPLICABLE":
        if steps:
            violations.append(
                f"{case_id}: NOT_APPLICABLE rows must have steps_json=[], got {len(steps)} steps"
            )
        return violations
    for position, step in enumerate(steps, start=1):
        violations.extend(validate_step(step, position, case_id))
    for position, step in enumerate(steps, start=1):
        if step.get("step_no") != position:
            violations.append(
                f"{case_id}: step_no must run 1..n; position {position} has {step.get('step_no')!r}"
            )
    ranks = [PHASE_ORDER.get(str(step.get("phase")), 99) for step in steps]
    if any(after < before for before, after in zip(ranks, ranks[1:], strict=False)):
        violations.append(
            f"{case_id}: phases must appear in order FINDING, REMEDIATION, VERIFICATION"
        )
    if deletion_status == "COMPLETE":
        for position, step in enumerate(steps, start=1):
            if str(step.get("phase")) != "VERIFICATION":
                violations.append(
                    f"{case_id}: step {position} of a COMPLETE row must be VERIFICATION"
                )
            if not str(step.get("evidence_id")):
                violations.append(
                    f"{case_id}: step {position} of a COMPLETE row must cite evidence"
                )
    elif deletion_status == "INCOMPLETE":
        for position, step in enumerate(steps, start=1):
            phase = str(step.get("phase"))
            cited = bool(str(step.get("evidence_id")))
            if phase == "FINDING" and not cited:
                violations.append(
                    f"{case_id}: FINDING step {position} must cite participant-visible evidence"
                )
            if phase != "FINDING" and cited:
                violations.append(
                    f'{case_id}: {phase} step {position} describes future work and must use evidence_id=""'
                )
    return violations


def read_output_csv(path: Path) -> tuple[list[OutputRow], list[str]]:
    violations: list[str] = []
    rows: list[OutputRow] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != HEADER:
            violations.append(f"{path.name}: header {reader.fieldnames} != {HEADER}")
            return rows, violations
        for line_no, row in enumerate(reader, start=2):
            case_id = row.get("case_id") or ""
            status = row.get("deletion_status") or ""
            raw = row.get("steps_json") or ""
            steps: list[dict[str, Any]] = []
            try:
                parsed = json.loads(raw) if raw else []
            except json.JSONDecodeError as exc:
                violations.append(f"{path.name}:{line_no}: invalid JSON in steps_json ({exc})")
                parsed = None
            if parsed is not None:
                if not isinstance(parsed, list):
                    violations.append(f"{path.name}:{line_no}: steps_json must be a JSON array")
                else:
                    steps = [step for step in parsed if isinstance(step, dict)]
                    if len(steps) != len(parsed):
                        violations.append(
                            f"{path.name}:{line_no}: steps_json contains non-object entries"
                        )
            rows.append(
                OutputRow(
                    case_id=case_id,
                    deletion_status=status,
                    steps=steps,
                    raw_steps_json=raw,
                    line_no=line_no,
                )
            )
    return rows, violations


def validate_file(path: Path, expected_case_ids: list[str] | None = None) -> FileValidation:
    validation = FileValidation()
    rows, structural = read_output_csv(path)
    validation.rows = rows
    validation.violations.extend(structural)

    ids = [row.case_id for row in rows]
    duplicates = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
    validation.duplicate_ids = duplicates
    if duplicates:
        validation.violations.append(f"{path.name}: duplicate case_ids {duplicates}")

    if expected_case_ids is not None:
        expected = list(expected_case_ids)
        missing = sorted(set(expected) - set(ids))
        extra = sorted(set(ids) - set(expected))
        validation.missing_ids = missing
        validation.extra_ids = extra
        if missing:
            shown = ", ".join(missing[:10]) + ("..." if len(missing) > 10 else "")
            validation.violations.append(f"{path.name}: missing {len(missing)} case_ids: {shown}")
        if extra:
            shown = ", ".join(extra[:10]) + ("..." if len(extra) > 10 else "")
            validation.violations.append(f"{path.name}: unexpected {len(extra)} case_ids: {shown}")

    validation.detected_sort = detect_sort(ids)
    if validation.detected_sort is None and len(ids) > 1:
        validation.violations.append(
            f"{path.name}: case_ids are sorted neither lexicographically nor naturally"
        )

    for row in rows:
        validation.violations.extend(validate_row(row.case_id, row.deletion_status, row.steps))
    return validation
