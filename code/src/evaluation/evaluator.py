"""Accuracy metrics and diff reporting against a golden output file.

Metric definitions (documented here and in the generated evaluation report; the
official grader's formulas are unknown, so both variants are reported):

- Universe: union of gold and predicted case ids. A missing or extra case counts
  as wrong for every metric.
- Case status accuracy: exact ``deletion_status`` equality over the universe.
- Sequence accuracy: exact ordered equality of the step arrays (JSON object key
  order ignored, array order significant, per AGENTS.md section 6.3).
- Positional step accuracy: over ``max(len(gold), len(pred))`` aligned positions,
  a position counts when the six semantic fields match (``step_no`` excluded as
  it is structural). Positions without a counterpart on either side count wrong.
- Set-based step accuracy: multiset intersection of the six-field tuples per
  case, aggregated micro-style into precision / recall / F1.
- Field-level accuracy: per semantic field over the same max-length alignment.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import STEP_FIELDS, OutputRow, read_output_csv

SEMANTIC_FIELDS = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")


def canonical_step(step: dict[str, Any]) -> dict[str, Any]:
    return {key: step.get(key) for key in STEP_FIELDS}


def semantic_tuple(step: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(step.get(key) for key in SEMANTIC_FIELDS)


@dataclass(frozen=True)
class CaseOutput:
    deletion_status: str
    steps: tuple[dict[str, Any], ...]


def load_cases(path: Path) -> dict[str, CaseOutput]:
    rows, _ = read_output_csv(path)
    cases: dict[str, CaseOutput] = {}
    for row in rows:
        if row.case_id in cases:
            continue
        cases[row.case_id] = CaseOutput(
            deletion_status=row.deletion_status,
            steps=tuple(canonical_step(step) for step in row.steps),
        )
    return cases


def cases_from_rows(rows: list[OutputRow]) -> dict[str, CaseOutput]:
    cases: dict[str, CaseOutput] = {}
    for row in rows:
        if row.case_id in cases:
            continue
        cases[row.case_id] = CaseOutput(
            deletion_status=row.deletion_status,
            steps=tuple(canonical_step(step) for step in row.steps),
        )
    return cases


@dataclass
class CaseMetrics:
    case_id: str
    gold_present: bool
    pred_present: bool
    status_correct: bool
    sequence_correct: bool
    positional_matched: int
    positional_total: int
    set_tp: int
    set_fp: int
    set_fn: int
    field_correct: dict[str, int] = field(default_factory=dict)
    field_total: int = 0


@dataclass
class StatusBreakdown:
    cases: int = 0
    status_correct: int = 0
    sequence_correct: int = 0
    positional_matched: int = 0
    positional_total: int = 0
    set_tp: int = 0
    set_fp: int = 0
    set_fn: int = 0


@dataclass
class AggregateMetrics:
    universe: list[str] = field(default_factory=list)
    cases: dict[str, CaseMetrics] = field(default_factory=dict)
    field_correct: dict[str, int] = field(default_factory=dict)
    field_total: int = 0
    per_status: dict[str, StatusBreakdown] = field(default_factory=dict)

    @property
    def total_cases(self) -> int:
        return len(self.universe)

    @property
    def status_accuracy(self) -> float:
        if not self.universe:
            return 1.0
        return sum(1 for c in self.cases.values() if c.status_correct) / len(self.universe)

    @property
    def sequence_accuracy(self) -> float:
        if not self.universe:
            return 1.0
        return sum(1 for c in self.cases.values() if c.sequence_correct) / len(self.universe)

    @property
    def positional_total(self) -> int:
        return sum(c.positional_total for c in self.cases.values())

    @property
    def positional_matched(self) -> int:
        return sum(c.positional_matched for c in self.cases.values())

    @property
    def positional_step_accuracy(self) -> float:
        if self.positional_total == 0:
            return 1.0
        return self.positional_matched / self.positional_total

    @property
    def set_tp(self) -> int:
        return sum(c.set_tp for c in self.cases.values())

    @property
    def set_fp(self) -> int:
        return sum(c.set_fp for c in self.cases.values())

    @property
    def set_fn(self) -> int:
        return sum(c.set_fn for c in self.cases.values())

    @property
    def set_precision(self) -> float:
        denom = self.set_tp + self.set_fp
        return self.set_tp / denom if denom else 1.0

    @property
    def set_recall(self) -> float:
        denom = self.set_tp + self.set_fn
        return self.set_tp / denom if denom else 1.0

    @property
    def set_f1(self) -> float:
        precision, recall = self.set_precision, self.set_recall
        return 2 * precision * recall / (precision + recall) if precision + recall else 1.0

    def field_accuracy(self, name: str) -> float:
        return self.field_correct.get(name, 0) / self.field_total if self.field_total else 1.0

    @property
    def overall_field_accuracy(self) -> float:
        total_checked = self.field_total * len(SEMANTIC_FIELDS)
        if not total_checked:
            return 1.0
        return sum(self.field_correct.values()) / total_checked


def compare_case(case_id: str, gold: CaseOutput | None, pred: CaseOutput | None) -> CaseMetrics:
    if gold is None or pred is None:
        present_steps = gold or pred
        assert present_steps is not None
        n = len(present_steps.steps)
        return CaseMetrics(
            case_id=case_id,
            gold_present=gold is not None,
            pred_present=pred is not None,
            status_correct=False,
            sequence_correct=False,
            positional_matched=0,
            positional_total=n,
            set_tp=0,
            set_fp=n if gold is None else 0,
            set_fn=n if pred is None else 0,
            field_correct=dict.fromkeys(SEMANTIC_FIELDS, 0),
            field_total=n,
        )
    gold_counts = Counter(semantic_tuple(step) for step in gold.steps)
    pred_counts = Counter(semantic_tuple(step) for step in pred.steps)
    tp = sum(
        min(gold_counts[key], pred_counts[key]) for key in gold_counts.keys() & pred_counts.keys()
    )
    matched = 0
    field_correct = dict.fromkeys(SEMANTIC_FIELDS, 0)
    for position in range(min(len(gold.steps), len(pred.steps))):
        gstep, pstep = gold.steps[position], pred.steps[position]
        if semantic_tuple(gstep) == semantic_tuple(pstep):
            matched += 1
        for name in SEMANTIC_FIELDS:
            if gstep.get(name) == pstep.get(name):
                field_correct[name] += 1
    return CaseMetrics(
        case_id=case_id,
        gold_present=True,
        pred_present=True,
        status_correct=gold.deletion_status == pred.deletion_status,
        sequence_correct=gold.steps == pred.steps,
        positional_matched=matched,
        positional_total=max(len(gold.steps), len(pred.steps)),
        set_tp=tp,
        set_fp=len(pred.steps) - tp,
        set_fn=len(gold.steps) - tp,
        field_correct=field_correct,
        field_total=max(len(gold.steps), len(pred.steps)),
    )


def evaluate(gold: dict[str, CaseOutput], pred: dict[str, CaseOutput]) -> AggregateMetrics:
    aggregate = AggregateMetrics()
    universe = sorted(set(gold) | set(pred))
    aggregate.universe = universe
    for case_id in universe:
        metrics = compare_case(case_id, gold.get(case_id), pred.get(case_id))
        aggregate.cases[case_id] = metrics
        for name in SEMANTIC_FIELDS:
            aggregate.field_correct[name] = aggregate.field_correct.get(
                name, 0
            ) + metrics.field_correct.get(name, 0)
        aggregate.field_total += metrics.field_total
        gold_case = gold.get(case_id)
        key = gold_case.deletion_status if gold_case else "<missing-in-gold>"
        breakdown = aggregate.per_status.setdefault(key, StatusBreakdown())
        breakdown.cases += 1
        breakdown.status_correct += int(metrics.status_correct)
        breakdown.sequence_correct += int(metrics.sequence_correct)
        breakdown.positional_matched += metrics.positional_matched
        breakdown.positional_total += metrics.positional_total
        breakdown.set_tp += metrics.set_tp
        breakdown.set_fp += metrics.set_fp
        breakdown.set_fn += metrics.set_fn
    return aggregate


def _fmt_step(step: dict[str, Any]) -> str:
    return "/".join(str(step.get(name, "")) for name in SEMANTIC_FIELDS)


def diff_case(case_id: str, gold: CaseOutput | None, pred: CaseOutput | None) -> list[str]:
    lines: list[str] = []
    if gold is None:
        return [
            f"{case_id}: EXTRA predicted case (not in gold), status={pred.deletion_status if pred else '?'}"
        ]
    if pred is None:
        return [f"{case_id}: MISSING predicted case (gold status={gold.deletion_status})"]
    if gold.deletion_status != pred.deletion_status:
        lines.append(f"{case_id}: status {pred.deletion_status} != {gold.deletion_status}")
    if gold.steps == pred.steps:
        return lines
    if Counter(semantic_tuple(s) for s in gold.steps) == Counter(
        semantic_tuple(s) for s in pred.steps
    ):
        lines.append(f"{case_id}: same steps but different ORDER")
    gold_ids = [semantic_tuple(s) for s in gold.steps]
    pred_ids = [semantic_tuple(s) for s in pred.steps]
    for position in range(min(len(gold_ids), len(pred_ids))):
        if gold_ids[position] != pred_ids[position]:
            gstep, pstep = gold.steps[position], pred.steps[position]
            detail = ", ".join(
                f"{name}: {pstep.get(name)!r} != {gstep.get(name)!r}"
                for name in SEMANTIC_FIELDS
                if gstep.get(name) != pstep.get(name)
            )
            lines.append(
                f"{case_id}: step {position + 1}: {detail or _fmt_step(pstep) + ' != ' + _fmt_step(gstep)}"
            )
    for step in pred.steps[len(gold.steps) :]:
        lines.append(f"{case_id}: EXTRA step: {_fmt_step(step)}")
    for step in gold.steps[len(pred.steps) :]:
        lines.append(f"{case_id}: MISSING step (gold): {_fmt_step(step)}")
    return lines


def format_summary(aggregate: AggregateMetrics) -> str:
    lines = [
        "=== Evaluation summary ===",
        f"cases in universe:            {aggregate.total_cases}",
        f"case status accuracy:         {aggregate.status_accuracy:.4f}",
        f"sequence accuracy:            {aggregate.sequence_accuracy:.4f}",
        f"step accuracy (positional):   {aggregate.positional_step_accuracy:.4f}"
        f" ({aggregate.positional_matched}/{aggregate.positional_total})",
        f"step match set-based:         P={aggregate.set_precision:.4f} R={aggregate.set_recall:.4f}"
        f" F1={aggregate.set_f1:.4f} (tp={aggregate.set_tp} fp={aggregate.set_fp} fn={aggregate.set_fn})",
        f"field accuracy (overall):     {aggregate.overall_field_accuracy:.4f}",
    ]
    for name in SEMANTIC_FIELDS:
        lines.append(f"  field {name:13}       {aggregate.field_accuracy(name):.4f}")
    lines.append("--- per gold status ---")
    for status, breakdown in sorted(aggregate.per_status.items()):
        pos_acc = (
            breakdown.positional_matched / breakdown.positional_total
            if breakdown.positional_total
            else 1.0
        )
        lines.append(
            f"  {status:15} n={breakdown.cases:4} status={breakdown.status_correct / breakdown.cases:.4f}"
            f" sequence={breakdown.sequence_correct / breakdown.cases:.4f} positional={pos_acc:.4f}"
        )
    return "\n".join(lines)
