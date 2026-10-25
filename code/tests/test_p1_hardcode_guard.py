"""Guards against case-specific shortcuts in production code."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from src.core.pipeline import Pipeline
from src.evaluation.evaluator import load_cases

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
SRC_DIR = REPO_ROOT / "code" / "src"
SAMPLE_REQUESTS = DATASET_DIR / "sample_deletion_requests.csv"
SAMPLE_GOLD = DATASET_DIR / "sample_output.csv"


def _sample_literals() -> set[str]:
    literals: set[str] = set()
    with SAMPLE_REQUESTS.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            literals.add(row["case_id"])
            literals.add(row["email"])
    with SAMPLE_GOLD.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            for step in json.loads(row["steps_json"]):
                literals.add(step["resource_id"])
                if step["evidence_id"]:
                    literals.add(step["evidence_id"])
    return {literal for literal in literals if literal}


def test_production_source_has_no_sample_literals() -> None:
    literals = _sample_literals()
    offenders: list[str] = []
    for path in SRC_DIR.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for literal in literals:
            if literal in text:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {literal}")
        if re.search(r"\bcase_\d+\b", text):
            offenders.append(f"{path.relative_to(REPO_ROOT)}: case_id literal")
    assert offenders == []


def test_core_does_not_read_sample_gold() -> None:
    audit_modules = (
        "audit_engine.py",
        "identity_resolver.py",
        "intent_classifier.py",
        "inventory_builder.py",
        "planner_sorter.py",
        "rules_engine.py",
        "state_reconstructor.py",
        "workflow_resolver.py",
    )
    for name in audit_modules:
        path = SRC_DIR / "core" / name
        assert "sample_output" not in path.read_text(encoding="utf-8")


def test_case_renaming_does_not_change_audit_output(tmp_path: Path) -> None:
    pipeline = Pipeline(dataset_dir=DATASET_DIR)
    baseline_path = tmp_path / "baseline.csv"
    pipeline.run(SAMPLE_REQUESTS, baseline_path)

    renamed_requests = tmp_path / "renamed_requests.csv"
    mapping: dict[str, str] = {}
    with SAMPLE_REQUESTS.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    for row in rows:
        renamed_case_id = f"holdout_{row['case_id'].removeprefix('case_')}"
        mapping[renamed_case_id] = row["case_id"]
        row["case_id"] = renamed_case_id
    with renamed_requests.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    renamed_path = tmp_path / "renamed.csv"
    pipeline.run(renamed_requests, renamed_path)

    baseline = load_cases(baseline_path)
    renamed = load_cases(renamed_path)
    assert set(renamed) == set(mapping)
    for renamed_id, original_id in mapping.items():
        assert renamed[renamed_id] == baseline[original_id]

    gold = load_cases(SAMPLE_GOLD)
    assert set(gold) == set(baseline)
    for case_id, output in gold.items():
        if case_id in {"case_18", "case_20"}:
            continue
        assert baseline[case_id] == output
