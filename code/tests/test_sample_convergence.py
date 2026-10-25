"""Automated regression test for 100% sample convergence (Phase 6, AGENTS.md section 6).

Asserts that the deletion-audit engine achieves 100% convergence across all 32 public
sample cases against dataset/sample_output.csv:
- Status accuracy: 1.0000 (32/32)
- Sequence accuracy: 1.0000 (32/32)
- Positional step accuracy: 1.0000 (193/193)
- Step set-based precision, recall, F1: 1.0000
- Field-level accuracy: 1.0000 across all 6 semantic fields
- File schema validation: 0 violations, canonical 1..N numbering, valid JSON
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.core.pipeline import Pipeline
from src.evaluation.evaluator import evaluate, load_cases
from src.evaluation.schema import validate_file

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
SAMPLE_REQUESTS = DATASET_DIR / "sample_deletion_requests.csv"
SAMPLE_GOLD = DATASET_DIR / "sample_output.csv"


@pytest.fixture(scope="module")
def sample_audit_results(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """Run pipeline once for the test module and produce output CSV."""
    out_dir = tmp_path_factory.mktemp("sample_convergence")
    out_csv = out_dir / "sample_output_pred.csv"

    pipeline = Pipeline(dataset_dir=DATASET_DIR)
    pipeline.run(input_path=SAMPLE_REQUESTS, output_path=out_csv)
    return out_csv, SAMPLE_GOLD


def test_sample_output_schema_validity(sample_audit_results: tuple[Path, Path]) -> None:
    """Validate that the predicted output satisfies all strict CSV schema rules."""
    out_csv, _ = sample_audit_results
    validation = validate_file(out_csv)

    assert len(validation.rows) == 32
    assert validation.violations == [], f"Schema violations found: {validation.violations}"
    assert validation.detected_sort in ("case_id", "both")


def test_sample_100_percent_convergence(sample_audit_results: tuple[Path, Path]) -> None:
    """Assert 100% convergence on all evaluation metrics."""
    out_csv, gold_csv = sample_audit_results

    gold_cases = load_cases(gold_csv)
    pred_cases = load_cases(out_csv)

    assert len(gold_cases) == 32
    assert len(pred_cases) == 32

    metrics = evaluate(gold_cases, pred_cases)

    # 1. Case Status Accuracy
    assert metrics.status_accuracy == 1.0, (
        f"Case status accuracy {metrics.status_accuracy:.4f} != 1.0000"
    )

    # 2. Complete Sequence Accuracy
    assert metrics.sequence_accuracy == 1.0, (
        f"Sequence accuracy {metrics.sequence_accuracy:.4f} != 1.0000"
    )

    # 3. Positional Step Accuracy
    assert metrics.positional_step_accuracy == 1.0, (
        f"Positional step accuracy {metrics.positional_step_accuracy:.4f} != 1.0000"
    )

    # 4. Set-based Precision, Recall, F1
    assert metrics.set_precision == 1.0, f"Set precision {metrics.set_precision:.4f} != 1.0000"
    assert metrics.set_recall == 1.0, f"Set recall {metrics.set_recall:.4f} != 1.0000"
    assert metrics.set_f1 == 1.0, f"Set F1 {metrics.set_f1:.4f} != 1.0000"

    # 5. Field Accuracy across all semantic fields
    for field_name in (
        "phase",
        "system_id",
        "resource_id",
        "operation",
        "state",
        "evidence_id",
    ):
        acc = metrics.field_accuracy(field_name)
        assert acc == 1.0, f"Field '{field_name}' accuracy {acc:.4f} != 1.0000"

    assert metrics.overall_field_accuracy == 1.0, (
        f"Overall field accuracy {metrics.overall_field_accuracy:.4f} != 1.0000"
    )
