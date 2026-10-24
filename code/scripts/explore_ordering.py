"""P1.9 ordering rule validation.

Applies the Plan.md Rule 6 canonical 4-key sort (phase, operation rank,
system_id, resource_id) to every golden sample step list and checks whether it
reproduces the golden order exactly. Counterexamples are listed.
"""

from __future__ import annotations

import json

from _paths import SAMPLE_OUTPUT_CSV, read_csv

PHASE_ORDER = {"FINDING": 1, "REMEDIATION": 2, "VERIFICATION": 3}

OP_ORDER = {
    "REPORT_REMAINING_RECORD": 1,
    "REPORT_EXPOSED_PII": 2,
    "REPORT_ACTIVE_DATA_FLOW": 3,
    "REPORT_RESTORE_RISK": 4,
    "DISABLE_DATA_FLOW": 1,
    "BLOCK_RESTORE": 2,
    "DELETE_RECORD": 3,
    "REDACT_RECORD": 4,
    "ANONYMIZE_RECORD": 5,
    "VERIFY_RECORD_ABSENT": 1,
    "VERIFY_RECORD_PRESENT": 2,
    "VERIFY_RECORD_REDACTED": 3,
    "VERIFY_RECORD_ANONYMIZED": 4,
    "VERIFY_DATA_FLOW_DISABLED": 5,
    "VERIFY_RESTORE_BLOCKED": 6,
}


def sort_key(step: dict[str, object]) -> tuple[int, int, str, str]:
    return (
        PHASE_ORDER[str(step["phase"])],
        OP_ORDER[str(step["operation"])],
        str(step["system_id"]),
        str(step["resource_id"]),
    )


def main() -> None:
    rows = read_csv(SAMPLE_OUTPUT_CSV)
    failures = 0
    for row in sorted(rows, key=lambda r: r["case_id"]):
        steps = json.loads(row["steps_json"])
        expected = sorted(steps, key=sort_key)
        got_ids = [(s["phase"], s["operation"], s["system_id"], s["resource_id"]) for s in expected]
        gold_ids = [(s["phase"], s["operation"], s["system_id"], s["resource_id"]) for s in steps]
        ok = got_ids == gold_ids
        stepnos_ok = [s["step_no"] for s in steps] == list(range(1, len(steps) + 1))
        print(
            f"{row['case_id']}: 4-key sort reproduces golden order: {ok} (step_no contiguous: {stepnos_ok})"
        )
        if not ok:
            failures += 1
            for i, (g, e) in enumerate(zip(gold_ids, got_ids, strict=True), start=1):
                if g != e:
                    print(f"    first divergence at position {i}: golden={g} sorted={e}")
            print(f"    golden : {gold_ids}")
            print(f"    sorted : {got_ids}")
    print(f"\ncases passing Rule 6 sort: {len(rows) - failures}/{len(rows)}")


if __name__ == "__main__":
    main()
