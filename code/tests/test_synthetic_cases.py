"""Synthetic evaluation cases (P2.11): schema + self-consistency checks.

Grounded in docs/findings/phase_01_ground_truth.md; engine inputs are wired in
Phase 6. Here we only pin the expected gold rows.
"""

from __future__ import annotations

from conftest import load_synthetic_cases
from src.evaluation import evaluator, schema


def test_synthetic_case_count_and_categories() -> None:
    cases = load_synthetic_cases()
    assert len(cases) >= 5
    statuses = {case["expected"]["deletion_status"] for case in cases}
    assert {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"} <= statuses


def test_synthetic_rows_pass_file_validation(tmp_path) -> None:
    import csv
    import json

    path = tmp_path / "syn_output.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(schema.HEADER)
        for case in load_synthetic_cases():
            writer.writerow(
                [
                    case["case_id"],
                    case["expected"]["deletion_status"],
                    json.dumps(case["expected"]["steps"]),
                ]
            )
    validation = schema.validate_file(
        path, expected_case_ids=[c["case_id"] for c in load_synthetic_cases()]
    )
    assert validation.violations == []
    assert validation.detected_sort == "both"


def test_synthetic_self_evaluation_is_perfect() -> None:
    cases = load_synthetic_cases()
    gold = {
        c["case_id"]: evaluator.CaseOutput(
            deletion_status=c["expected"]["deletion_status"],
            steps=tuple(evaluator.canonical_step(s) for s in c["expected"]["steps"]),
        )
        for c in cases
    }
    result = evaluator.evaluate(gold, dict(gold))
    assert result.status_accuracy == 1.0
    assert result.sequence_accuracy == 1.0
    assert result.set_f1 == 1.0
