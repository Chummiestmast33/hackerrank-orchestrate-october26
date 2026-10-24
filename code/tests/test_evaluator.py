"""Tests for the evaluator metrics and diff printer (P2.6)."""

from __future__ import annotations

from pathlib import Path

from conftest import make_step, write_output_csv
from src.evaluation import evaluator


def cases(
    status: str, steps: list[dict], case_id: str = "case_01"
) -> dict[str, evaluator.CaseOutput]:
    return {
        case_id: evaluator.CaseOutput(
            deletion_status=status, steps=tuple(evaluator.canonical_step(s) for s in steps)
        )
    }


def test_exact_counts_with_partial_overlap() -> None:
    gold_steps = [
        make_step(1, resource_id="account_a"),
        make_step(2, resource_id="account_b"),
        make_step(3, resource_id="account_c"),
    ]
    pred_steps = [
        make_step(1, resource_id="account_a"),
        make_step(2, resource_id="account_z"),
        make_step(3, resource_id="account_y"),
    ]
    result = evaluator.evaluate(cases("COMPLETE", gold_steps), cases("COMPLETE", pred_steps))
    metrics = result.cases["case_01"]
    assert (metrics.set_tp, metrics.set_fp, metrics.set_fn) == (1, 2, 2)
    assert metrics.positional_matched == 1 and metrics.positional_total == 3
    assert metrics.field_correct["resource_id"] == 1
    assert metrics.field_correct["phase"] == 3
    assert metrics.field_total == 3
    assert result.field_correct["resource_id"] == 1
    assert result.field_total == 3


def test_diff_numbers_steps_from_one() -> None:
    gold_steps = [make_step(1, resource_id="a"), make_step(2, resource_id="b")]
    pred_steps = [make_step(1, resource_id="x"), make_step(2, resource_id="y")]
    lines = evaluator.diff_case(
        "case_01",
        cases("COMPLETE", gold_steps)["case_01"],
        cases("COMPLETE", pred_steps)["case_01"],
    )
    assert any("step 1:" in line for line in lines)
    assert any("step 2:" in line for line in lines)


def test_aggregate_accumulates_over_cases() -> None:
    gold = cases("COMPLETE", [make_step(1)]) | cases("COMPLETE", [make_step(1)], case_id="case_02")
    pred = cases("COMPLETE", [make_step(1)]) | cases(
        "COMPLETE", [make_step(1, evidence_id="e2")], case_id="case_02"
    )
    result = evaluator.evaluate(gold, pred)
    assert result.field_correct["evidence_id"] == 1
    assert result.field_correct["phase"] == 2
    assert result.field_total == 2


def test_identical_files_score_perfect() -> None:
    steps = [make_step(1), make_step(2, resource_id="account_002")]
    gold = cases("COMPLETE", steps)
    result = evaluator.evaluate(gold, cases("COMPLETE", steps))
    assert result.status_accuracy == 1.0
    assert result.sequence_accuracy == 1.0
    assert result.positional_step_accuracy == 1.0
    assert result.set_f1 == 1.0
    assert result.overall_field_accuracy == 1.0


def test_wrong_status_zeroes_status_accuracy() -> None:
    steps = [make_step(1)]
    result = evaluator.evaluate(cases("COMPLETE", steps), cases("INCOMPLETE", steps))
    assert result.status_accuracy == 0.0
    # sequence accuracy measures step-array equality only; status is separate
    assert result.sequence_accuracy == 1.0
    mismatched = evaluator.evaluate(cases("COMPLETE", steps), cases("INCOMPLETE", [make_step(2)]))
    assert mismatched.sequence_accuracy == 0.0


def test_missing_step_penalises_positional_and_recall() -> None:
    gold_steps = [make_step(1), make_step(2, resource_id="account_002")]
    pred_steps = [make_step(1)]
    result = evaluator.evaluate(cases("INCOMPLETE", gold_steps), cases("INCOMPLETE", pred_steps))
    metrics = result.cases["case_01"]
    assert metrics.positional_total == 2 and metrics.positional_matched == 1
    assert metrics.set_fn == 1 and metrics.set_fp == 0
    assert result.set_recall == 0.5
    assert result.set_precision == 1.0


def test_swapped_order_keeps_set_match_but_breaks_sequence() -> None:
    a = make_step(1, resource_id="account_a")
    b = make_step(2, resource_id="account_b")
    result = evaluator.evaluate(cases("COMPLETE", [a, b]), cases("COMPLETE", [b, a]))
    assert result.sequence_accuracy == 0.0
    assert result.set_f1 == 1.0
    assert result.positional_step_accuracy == 0.0


def test_wrong_evidence_only_hits_one_field() -> None:
    gold_steps = [make_step(1)]
    pred_steps = [make_step(1, evidence_id="evidence_99")]
    result = evaluator.evaluate(cases("COMPLETE", gold_steps), cases("COMPLETE", pred_steps))
    assert result.field_accuracy("evidence_id") == 0.0
    assert result.field_accuracy("phase") == 1.0
    assert result.field_accuracy("operation") == 1.0


def test_extra_and_missing_cases_count_wrong() -> None:
    gold = cases("COMPLETE", [make_step(1)])
    pred = cases("COMPLETE", [make_step(1)], case_id="case_02")
    result = evaluator.evaluate(gold, pred)
    assert result.total_cases == 2
    assert result.status_accuracy == 0.0
    assert result.cases["case_01"].pred_present is False
    assert result.cases["case_02"].gold_present is False


def test_key_order_variation_matches() -> None:
    step = make_step(1)
    reordered = {k: step[k] for k in reversed(list(step))}
    result = evaluator.evaluate(cases("COMPLETE", [step]), cases("COMPLETE", [reordered]))
    assert result.sequence_accuracy == 1.0


def test_not_applicable_pairs_match() -> None:
    result = evaluator.evaluate(cases("NOT_APPLICABLE", []), cases("NOT_APPLICABLE", []))
    assert result.sequence_accuracy == 1.0
    assert result.positional_total == 0


def test_diff_reports_status_and_field_mismatches() -> None:
    gold = cases("COMPLETE", [make_step(1)])["case_01"]
    pred = cases(
        "INCOMPLETE",
        [
            make_step(
                1,
                evidence_id="evidence_77",
                operation="REPORT_REMAINING_RECORD",
                state="PRESENT",
                phase="FINDING",
            )
        ],
    )["case_01"]
    lines = evaluator.diff_case("case_01", gold, pred)
    assert any("status" in line for line in lines)
    assert any("evidence_id" in line for line in lines)


def test_diff_reports_missing_and_extra_case() -> None:
    gold = cases("COMPLETE", [make_step(1)])["case_01"]
    assert "MISSING" in evaluator.diff_case("case_01", gold, None)[0]
    assert "EXTRA" in evaluator.diff_case("case_42", None, gold)[0]


def test_per_status_breakdown_counts() -> None:
    gold = cases("COMPLETE", [make_step(1)]) | cases(
        "INCOMPLETE", [make_step(1)], case_id="case_02"
    )
    pred = cases("COMPLETE", [make_step(1)]) | cases("COMPLETE", [make_step(1)], case_id="case_02")
    result = evaluator.evaluate(gold, pred)
    assert result.per_status["COMPLETE"].cases == 1
    assert result.per_status["INCOMPLETE"].status_correct == 0


def test_load_cases_and_end_to_end_file_flow(tmp_path: Path) -> None:
    gold_path = write_output_csv(tmp_path / "gold.csv", [("case_01", "NOT_APPLICABLE", [])])
    pred_path = write_output_csv(tmp_path / "pred.csv", [("case_01", "NOT_APPLICABLE", [])])
    result = evaluator.evaluate(evaluator.load_cases(gold_path), evaluator.load_cases(pred_path))
    assert result.status_accuracy == 1.0


def test_summary_format_runs() -> None:
    result = evaluator.evaluate(
        cases("COMPLETE", [make_step(1)]), cases("COMPLETE", [make_step(1)])
    )
    text = evaluator.format_summary(result)
    assert "case status accuracy" in text
