"""Shared fixtures/helpers for the evaluation harness tests."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
SAMPLE_OUTPUT_CSV = DATASET_DIR / "sample_output.csv"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
SYNTHETIC_CASES_JSON = FIXTURES_DIR / "synthetic" / "synthetic_cases.json"

HEADER = ["case_id", "deletion_status", "steps_json"]


def make_step(
    step_no: int = 1,
    phase: str = "VERIFICATION",
    system_id: str = "account_service",
    resource_id: str = "account_001",
    operation: str = "VERIFY_RECORD_ABSENT",
    state: str = "ABSENT",
    evidence_id: str = "evidence_54",
) -> dict[str, Any]:
    return {
        "step_no": step_no,
        "phase": phase,
        "system_id": system_id,
        "resource_id": resource_id,
        "operation": operation,
        "state": state,
        "evidence_id": evidence_id,
    }


def write_output_csv(path: Path, rows: list[tuple[str, str, list[dict[str, Any]]]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADER)
        for case_id, status, steps in rows:
            writer.writerow([case_id, status, json.dumps(steps)])
    return path


def load_synthetic_cases() -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = json.loads(SYNTHETIC_CASES_JSON.read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="session")
def sample_gold_path() -> Path:
    if not SAMPLE_OUTPUT_CSV.exists():
        pytest.skip("dataset/sample_output.csv not available")
    return SAMPLE_OUTPUT_CSV


@pytest.fixture()
def tmp_output(tmp_path: Path) -> Path:
    return tmp_path / "output.csv"
