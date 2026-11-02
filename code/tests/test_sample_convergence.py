"""Sample convergence with the documented evidence gap (Phase 6/P1).

The generic engine matches all 32 sample statuses and 30/32 exact sequences.
The only mismatches are the two retained audit-record verification steps that
exist only in the sample gold file; see
docs/findings/phase_07_sample_evidence_gap.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sample_expectations import (
    EXPECTED_POSITIONAL_MATCHED,
    EXPECTED_POSITIONAL_TOTAL,
    EXPECTED_SAMPLE_CASES,
    EXPECTED_SEQUENCE_CORRECT,
    EXPECTED_SET_FN,
    EXPECTED_SET_FP,
    EXPECTED_SET_TP,
    EXPECTED_STATUS_CORRECT,
    GAP_RECORD_BY_CASE,
    KNOWN_EVIDENCE_GAP,
)
from src.core.pipeline import Pipeline
from src.evaluation.evaluator import diff_case, evaluate, load_cases
from src.evaluation.schema import validate_file

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
SAMPLE_REQUESTS = DATASET_DIR / "sample_deletion_requests.csv"
SAMPLE_GOLD = DATASET_DIR / "sample_output.csv"


@pytest.fixture(scope="module")
def sample_audit_results(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Run the pipeline once with an isolated, fresh evidence cache."""
    out_dir = tmp_path_factory.mktemp("sample_convergence")
    cache_path = out_dir / "parsed_evidence.json"
    if cache_path.exists():
        cache_path.unlink()
    out_csv = out_dir / "sample_output_pred.csv"

    pipeline = Pipeline(dataset_dir=DATASET_DIR, cache_path=cache_path)
    pipeline.run(input_path=SAMPLE_REQUESTS, output_path=out_csv)
    return out_csv, SAMPLE_GOLD


def test_sample_output_schema_validity(sample_audit_results: tuple[Path, Path]) -> None:
    """Validate that the predicted output satisfies all strict CSV schema rules."""
    out_csv, _ = sample_audit_results
    validation = validate_file(out_csv)

    assert len(validation.rows) == EXPECTED_SAMPLE_CASES
    assert validation.violations == [], f"Schema violations found: {validation.violations}"
    assert validation.detected_sort in ("case_id", "both")


def test_sample_convergence_with_documented_evidence_gap(
    sample_audit_results: tuple[Path, Path],
) -> None:
    """Assert the documented 32/32 status and 30/32 sequence result."""
    out_csv, gold_csv = sample_audit_results

    gold_cases = load_cases(gold_csv)
    pred_cases = load_cases(out_csv)

    assert len(gold_cases) == EXPECTED_SAMPLE_CASES
    assert len(pred_cases) == EXPECTED_SAMPLE_CASES

    metrics = evaluate(gold_cases, pred_cases)

    assert sum(case.status_correct for case in metrics.cases.values()) == EXPECTED_STATUS_CORRECT
    assert metrics.status_accuracy == 1.0

    mismatched = {case_id for case_id, case in metrics.cases.items() if not case.sequence_correct}
    assert mismatched == KNOWN_EVIDENCE_GAP
    assert sum(case.sequence_correct for case in metrics.cases.values()) == (
        EXPECTED_SEQUENCE_CORRECT
    )
    assert metrics.sequence_accuracy == pytest.approx(
        EXPECTED_SEQUENCE_CORRECT / EXPECTED_SAMPLE_CASES
    )

    assert metrics.positional_matched == EXPECTED_POSITIONAL_MATCHED
    assert metrics.positional_total == EXPECTED_POSITIONAL_TOTAL
    assert metrics.set_tp == EXPECTED_SET_TP
    assert metrics.set_fp == EXPECTED_SET_FP
    assert metrics.set_fn == EXPECTED_SET_FN
    assert metrics.set_f1 == pytest.approx(0.9948, abs=1e-4)
    assert metrics.overall_field_accuracy == pytest.approx(0.9758, abs=1e-4)

    for case_id, record_id in GAP_RECORD_BY_CASE.items():
        diffs = diff_case(case_id, gold_cases.get(case_id), pred_cases.get(case_id))
        assert any(record_id in line for line in diffs), (case_id, diffs)
