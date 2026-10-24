"""Shared path resolution for Phase 1 exploration scripts.

Exploration-only utilities (not shipped as runtime logic). Paths are resolved
relative to this file so the scripts work from any working directory
(AGENTS.md section 8).
"""

from __future__ import annotations

import csv
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
CODE_DIR = SCRIPTS_DIR.parent
REPO_ROOT = CODE_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"
EVIDENCE_DIR = DATASET_DIR / "evidence"
OUT_DIR = SCRIPTS_DIR / "out"

SAMPLE_REQUESTS_CSV = DATASET_DIR / "sample_deletion_requests.csv"
SAMPLE_OUTPUT_CSV = DATASET_DIR / "sample_output.csv"
EVAL_REQUESTS_CSV = DATASET_DIR / "deletion_requests.csv"
IDENTITIES_CSV = DATASET_DIR / "user_identities.csv"
AUDIT_LOG_CSV = DATASET_DIR / "user_audit_log.csv"
ACTIVITY_CSV = DATASET_DIR / "system_activity.csv"
RULES_CSV = DATASET_DIR / "deletion_rules.csv"
EVIDENCE_MANIFEST_CSV = DATASET_DIR / "evidence_files.csv"

OUTPUT_HEADER = ["case_id", "deletion_status", "steps_json"]
STEP_FIELDS = [
    "case_id",
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
]


def ensure_out_dir() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUT_DIR


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
