"""P1.2 sample case dump + P1.3 vocabulary census.

Joins dataset/sample_deletion_requests.csv with dataset/sample_output.csv,
explodes steps_json into out/sample_steps.csv, prints per-case summaries and
a vocabulary census (systems, resource prefixes, operation x state pairs,
cited evidence ids), and writes out/vocabulary.json.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from _paths import (
    OUT_DIR,
    SAMPLE_OUTPUT_CSV,
    SAMPLE_REQUESTS_CSV,
    STEP_FIELDS,
    ensure_out_dir,
    read_csv,
)

REQUIRED_STEP_KEYS = {
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
}


def load_samples() -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    requests = {row["case_id"]: row for row in read_csv(SAMPLE_REQUESTS_CSV)}
    outputs = {row["case_id"]: row for row in read_csv(SAMPLE_OUTPUT_CSV)}
    return requests, outputs


def explode_steps(
    requests: dict[str, dict[str, str]], outputs: dict[str, dict[str, str]]
) -> tuple[list[dict[str, str]], list[str]]:
    flat: list[dict[str, str]] = []
    problems: list[str] = []
    for case_id in sorted(outputs):
        row = outputs[case_id]
        if case_id not in requests:
            problems.append(f"{case_id}: missing from sample requests")
        try:
            steps = json.loads(row["steps_json"])
        except json.JSONDecodeError as exc:
            problems.append(f"{case_id}: bad JSON: {exc}")
            continue
        if not isinstance(steps, list):
            problems.append(f"{case_id}: steps_json is not a list")
            continue
        for i, step in enumerate(steps, start=1):
            keys = set(step)
            if keys != REQUIRED_STEP_KEYS:
                problems.append(f"{case_id} step {i}: keys {sorted(keys)}")
            if step.get("step_no") != i:
                problems.append(f"{case_id} step {i}: step_no={step.get('step_no')}")
            flat.append(
                {field: str(step.get(field, "")) for field in STEP_FIELDS} | {"case_id": case_id}
            )
    missing = sorted(set(requests) - set(outputs))
    for case_id in missing:
        problems.append(f"{case_id}: missing from sample output")
    return flat, problems


def write_flat_steps(flat: list[dict[str, str]]) -> Path:
    ensure_out_dir()
    out_path = OUT_DIR / "sample_steps.csv"
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=STEP_FIELDS)
        writer.writeheader()
        writer.writerows(flat)
    return out_path


def vocabulary(flat: list[dict[str, str]], outputs: dict[str, dict[str, str]]) -> dict[str, object]:
    systems = Counter(row["system_id"] for row in flat)
    prefixes = Counter(row["resource_id"].split("_")[0] + "_" for row in flat if row["resource_id"])
    op_state = Counter((row["operation"], row["state"]) for row in flat)
    phase_op = Counter((row["phase"], row["operation"]) for row in flat)
    evidence = Counter(row["evidence_id"] for row in flat if row["evidence_id"])
    empty_evidence = Counter(row["phase"] for row in flat if not row["evidence_id"])
    statuses = Counter(row["deletion_status"] for row in outputs.values())
    return {
        "statuses": dict(statuses),
        "systems": dict(systems.most_common()),
        "resource_prefixes": dict(prefixes.most_common()),
        "operation_state_pairs": {
            f"{op}|{state}": n for (op, state), n in sorted(op_state.items())
        },
        "phase_operation_pairs": {f"{ph}|{op}": n for (ph, op), n in sorted(phase_op.items())},
        "cited_evidence_ids": dict(sorted(evidence.items())),
        "empty_evidence_by_phase": dict(empty_evidence),
    }


def per_case_summary(
    requests: dict[str, dict[str, str]], outputs: dict[str, dict[str, str]]
) -> None:
    print(f"{'case':8} {'status':17} {'steps':>5}  phases(F/R/V)  audit_at")
    for case_id in sorted(outputs):
        steps = json.loads(outputs[case_id]["steps_json"])
        phases = Counter(s["phase"] for s in steps)
        req = requests.get(case_id, {})
        print(
            f"{case_id:8} {outputs[case_id]['deletion_status']:17} {len(steps):5}  "
            f"{phases.get('FINDING', 0)}/{phases.get('REMEDIATION', 0)}/{phases.get('VERIFICATION', 0)}"
            f"        {req.get('audit_at', '?')}"
        )


def main() -> None:
    requests, outputs = load_samples()
    flat, problems = explode_steps(requests, outputs)
    out_path = write_flat_steps(flat)
    per_case_summary(requests, outputs)
    vocab = vocabulary(flat, outputs)
    vocab_path = OUT_DIR / "vocabulary.json"
    vocab_path.write_text(json.dumps(vocab, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {out_path.relative_to(OUT_DIR.parent.parent)} ({len(flat)} step rows)")
    print(f"wrote {vocab_path.name}")
    print("\n== Vocabulary ==")
    print(json.dumps(vocab, indent=1, sort_keys=True))
    if problems:
        print("\n== Invariant problems ==")
        for problem in problems:
            print(f"- {problem}")
    else:
        print("\nInvariants OK: 32 cases, 7 keys per step, step_no contiguous.")


if __name__ == "__main__":
    main()
