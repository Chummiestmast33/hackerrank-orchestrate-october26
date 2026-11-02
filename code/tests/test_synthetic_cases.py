"""Synthetic evaluation cases and self-consistency tests (AGENTS.md section 6.8).

Covers:
1. Grounded regression fixtures (syn_01..06 in tests/fixtures/synthetic/).
2. Participant-created core engine synthetic cases (case_synth_01..04 in src/evaluation/synthetic_cases.py).
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


# ---------------------------------------------------------------------------
# Phase 6 Core Engine Synthetic Case Tests
# ---------------------------------------------------------------------------


def _build_synthetic_engine():
    from src.core.audit_engine import AuditEngine
    from src.evaluation.synthetic_cases import (
        SYNTHETIC_IDENTITIES,
        SYNTHETIC_OBSERVATIONS,
        SYNTHETIC_RULES,
    )

    return AuditEngine(
        identities=SYNTHETIC_IDENTITIES,
        audit_log=(),
        activity_events=(),
        rules=SYNTHETIC_RULES,
        observations=SYNTHETIC_OBSERVATIONS,
        reports={},
    )


def test_synthetic_case_01_non_applicable() -> None:
    """case_synth_01: Spanish GDPR access/rectification request -> NOT_APPLICABLE."""
    from src.evaluation.synthetic_cases import (
        SYNTHETIC_GOLD_CASES,
        SYNTHETIC_REQUESTS,
        case_audit_result_to_case_output,
    )

    engine = _build_synthetic_engine()
    req = SYNTHETIC_REQUESTS[0]
    result = engine.audit_case(req)

    assert result.case_id == "case_synth_01"
    assert result.deletion_status == "NOT_APPLICABLE"
    assert result.steps == ()
    assert result.steps_json == "[]"

    pred_case = case_audit_result_to_case_output(result)
    gold_case = SYNTHETIC_GOLD_CASES["case_synth_01"]
    assert pred_case == gold_case


def test_synthetic_case_02_complete_with_tombstone_and_legal_hold() -> None:
    """case_synth_02: German deletion request with tombstone & legal hold -> COMPLETE."""
    from src.evaluation.synthetic_cases import (
        SYNTHETIC_GOLD_CASES,
        SYNTHETIC_REQUESTS,
        case_audit_result_to_case_output,
    )

    engine = _build_synthetic_engine()
    req = SYNTHETIC_REQUESTS[1]
    result = engine.audit_case(req)

    assert result.case_id == "case_synth_02"
    assert result.deletion_status == "COMPLETE"
    assert len(result.steps) == 3

    pred_case = case_audit_result_to_case_output(result)
    gold_case = SYNTHETIC_GOLD_CASES["case_synth_02"]

    assert pred_case.deletion_status == gold_case.deletion_status
    assert pred_case.steps == gold_case.steps


def test_synthetic_case_03_incomplete_data_flow_and_restore_risk() -> None:
    """case_synth_03: Incomplete deletion with active sync connector and backup risk -> INCOMPLETE."""
    from src.evaluation.synthetic_cases import (
        SYNTHETIC_GOLD_CASES,
        SYNTHETIC_REQUESTS,
        case_audit_result_to_case_output,
    )

    engine = _build_synthetic_engine()
    req = SYNTHETIC_REQUESTS[2]
    result = engine.audit_case(req)

    assert result.case_id == "case_synth_03"
    assert result.deletion_status == "INCOMPLETE"
    assert len(result.steps) == 7

    pred_case = case_audit_result_to_case_output(result)
    gold_case = SYNTHETIC_GOLD_CASES["case_synth_03"]

    assert pred_case.deletion_status == gold_case.deletion_status
    assert pred_case.steps == gold_case.steps


def test_synthetic_case_04_incomplete_replication_drift() -> None:
    """case_synth_04: Japanese deletion request with replica drift -> INCOMPLETE."""
    from src.evaluation.synthetic_cases import (
        SYNTHETIC_GOLD_CASES,
        SYNTHETIC_REQUESTS,
        case_audit_result_to_case_output,
    )

    engine = _build_synthetic_engine()
    req = SYNTHETIC_REQUESTS[3]
    result = engine.audit_case(req)

    assert result.case_id == "case_synth_04"
    assert result.deletion_status == "INCOMPLETE"
    assert len(result.steps) == 4

    pred_case = case_audit_result_to_case_output(result)
    gold_case = SYNTHETIC_GOLD_CASES["case_synth_04"]

    assert pred_case.deletion_status == gold_case.deletion_status
    assert pred_case.steps == gold_case.steps


def test_all_synthetic_cases_100_percent_eval() -> None:
    """Evaluate all 4 synthetic cases with evaluator.evaluate and assert 100% metrics."""
    from src.evaluation.synthetic_cases import (
        SYNTHETIC_GOLD_CASES,
        SYNTHETIC_REQUESTS,
        case_audit_result_to_case_output,
    )

    engine = _build_synthetic_engine()
    pred_cases = {
        req.case_id: case_audit_result_to_case_output(engine.audit_case(req))
        for req in SYNTHETIC_REQUESTS
    }

    result = evaluator.evaluate(SYNTHETIC_GOLD_CASES, pred_cases)

    # Assert 100% across all evaluation metrics
    assert result.status_accuracy == 1.0, f"Expected status_acc=1.0, got {result.status_accuracy}"
    assert result.sequence_accuracy == 1.0, f"Expected seq_acc=1.0, got {result.sequence_accuracy}"
    assert result.positional_step_accuracy == 1.0, f"Expected pos_acc=1.0, got {result.positional_step_accuracy}"
    assert result.set_f1 == 1.0, f"Expected F1=1.0, got {result.set_f1}"
    assert result.overall_field_accuracy == 1.0, f"Expected field_acc=1.0, got {result.overall_field_accuracy}"
