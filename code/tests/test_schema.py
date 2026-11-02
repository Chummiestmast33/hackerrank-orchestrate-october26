"""Tests for the output-contract validator (P2.3)."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import load_synthetic_cases, make_step, write_output_csv
from src.evaluation import schema


def test_complete_row_valid() -> None:
    steps = [make_step(1), make_step(2, resource_id="account_002")]
    assert schema.validate_row("case_01", "COMPLETE", steps) == []


def test_incomplete_row_valid() -> None:
    steps = [
        make_step(1, "FINDING", operation="REPORT_REMAINING_RECORD", state="PRESENT"),
        make_step(2, "REMEDIATION", operation="DELETE_RECORD", state="ABSENT", evidence_id=""),
        make_step(3, evidence_id=""),
    ]
    assert schema.validate_row("case_05", "INCOMPLETE", steps) == []


def test_not_applicable_empty_steps_valid() -> None:
    assert schema.validate_row("case_99", "NOT_APPLICABLE", []) == []


def test_not_applicable_with_steps_violation() -> None:
    violations = schema.validate_row("case_99", "NOT_APPLICABLE", [make_step(1)])
    assert any("NOT_APPLICABLE" in v for v in violations)


def test_unknown_status_violation() -> None:
    assert schema.validate_row("case_01", "MAYBE", []) != []


def test_extra_step_key_violation() -> None:
    step = make_step(1) | {"bonus": "x"}
    assert any("unexpected fields" in v for v in schema.validate_row("c", "COMPLETE", [step]))


def test_missing_step_key_violation() -> None:
    step = make_step(1)
    del step["system_id"]
    assert any("missing fields" in v for v in schema.validate_row("c", "COMPLETE", [step]))


def test_wrong_state_for_operation_violation() -> None:
    step = make_step(1, operation="DELETE_RECORD", state="PRESENT")
    assert any("requires state" in v for v in schema.validate_row("c", "INCOMPLETE", [step]))


def test_operation_phase_mismatch_violation() -> None:
    step = make_step(1, phase="FINDING", operation="DELETE_RECORD", state="ABSENT")
    assert any("belongs to phase" in v for v in schema.validate_row("c", "INCOMPLETE", [step]))


def test_unknown_operation_violation() -> None:
    step = make_step(1, operation="EXPLODE_RECORD", state="ABSENT")
    assert any("unknown operation" in v for v in schema.validate_row("c", "INCOMPLETE", [step]))


def test_step_no_not_contiguous_violation() -> None:
    steps = [make_step(1), make_step(5, resource_id="account_002")]
    assert any("step_no must run" in v for v in schema.validate_row("c", "COMPLETE", steps))


def test_phase_order_violation() -> None:
    steps = [
        make_step(1, evidence_id=""),
        make_step(2, "FINDING", operation="REPORT_REMAINING_RECORD", state="PRESENT"),
    ]
    assert any(
        "phases must appear in order" in v for v in schema.validate_row("c", "INCOMPLETE", steps)
    )


def test_complete_requires_verification_only() -> None:
    steps = [make_step(1, "FINDING", operation="REPORT_REMAINING_RECORD", state="PRESENT")]
    assert any("must be VERIFICATION" in v for v in schema.validate_row("c", "COMPLETE", steps))


def test_complete_requires_evidence() -> None:
    steps = [make_step(1, evidence_id="")]
    assert any("must cite evidence" in v for v in schema.validate_row("c", "COMPLETE", steps))


def test_incomplete_finding_requires_evidence() -> None:
    steps = [
        make_step(
            1, "FINDING", operation="REPORT_REMAINING_RECORD", state="PRESENT", evidence_id=""
        )
    ]
    assert any(
        "FINDING step 1 must cite" in v for v in schema.validate_row("c", "INCOMPLETE", steps)
    )


def test_incomplete_non_finding_must_not_cite() -> None:
    steps = [
        make_step(1, "FINDING", operation="REPORT_REMAINING_RECORD", state="PRESENT"),
        make_step(
            2, "REMEDIATION", operation="DELETE_RECORD", state="ABSENT", evidence_id="evidence_01"
        ),
    ]
    assert any("must use evidence_id" in v for v in schema.validate_row("c", "INCOMPLETE", steps))


def test_step_no_boolean_rejected() -> None:
    step = make_step(1)
    step["step_no"] = True
    assert any(
        "step_no must be an integer" in v for v in schema.validate_row("c", "COMPLETE", [step])
    )


def test_missing_and_extra_key_same_step() -> None:
    step = make_step(1)
    del step["state"]
    step["bonus"] = "x"
    violations = schema.validate_row("c", "COMPLETE", [step])
    assert any("missing fields ['state']" in v for v in violations)
    assert any("unexpected fields ['bonus']" in v for v in violations)


def test_steps_json_non_object_entries(tmp_path: Path) -> None:
    path = tmp_path / "o.csv"
    path.write_text(
        'case_id,deletion_status,steps_json\ncase_01,NOT_APPLICABLE,"[1, 2]"\n', encoding="utf-8"
    )
    validation = schema.validate_file(path)
    assert any("non-object entries" in v for v in validation.violations)


def test_bad_json_reports_csv_line_number(tmp_path: Path) -> None:
    path = tmp_path / "o.csv"
    path.write_text(
        "case_id,deletion_status,steps_json\ncase_01,NOT_APPLICABLE,{broken\n", encoding="utf-8"
    )
    validation = schema.validate_file(path)
    assert any(":2:" in v for v in validation.violations)


def test_extra_ids_reported(tmp_path: Path) -> None:
    path = write_output_csv(
        tmp_path / "o.csv", [("case_01", "NOT_APPLICABLE", []), ("case_77", "NOT_APPLICABLE", [])]
    )
    validation = schema.validate_file(path, expected_case_ids=["case_01"])
    assert validation.extra_ids == ["case_77"]
    assert validation.missing_ids == []


def test_missing_ids_message_ellipsises_after_ten(tmp_path: Path) -> None:
    path = write_output_csv(tmp_path / "o.csv", [])
    expected = [f"case_{n:02d}" for n in range(1, 13)]
    validation = schema.validate_file(path, expected_case_ids=expected)
    head = ", ".join(expected[:10])
    assert any(v.endswith(f"missing 12 case_ids: {head}...") for v in validation.violations)
    short = schema.validate_file(path, expected_case_ids=["case_01", "case_02"])
    assert any(v.endswith("missing 2 case_ids: case_01, case_02") for v in short.violations)
    assert not any("..." in v for v in short.violations)


def test_unsorted_message_exact(tmp_path: Path) -> None:
    path = write_output_csv(
        tmp_path / "o.csv", [("case_b", "NOT_APPLICABLE", []), ("case_a", "NOT_APPLICABLE", [])]
    )
    validation = schema.validate_file(path)
    assert validation.detected_sort is None
    assert (
        "o.csv: case_ids are sorted neither lexicographically nor naturally"
        in validation.violations
    )


def test_extra_ids_message_ellipsises_after_ten(tmp_path: Path) -> None:
    rows: list[tuple[str, str, list[dict[str, object]]]] = [
        (f"case_{n:03d}", "NOT_APPLICABLE", []) for n in range(1, 13)
    ]
    path = write_output_csv(tmp_path / "o.csv", rows)
    validation = schema.validate_file(path, expected_case_ids=[])
    head = ", ".join(f"case_{n:03d}" for n in range(1, 11))
    assert any(v.endswith(f"unexpected 12 case_ids: {head}...") for v in validation.violations)


def test_single_row_file_sort_trivial(tmp_path: Path) -> None:
    path = write_output_csv(tmp_path / "o.csv", [("case_550", "NOT_APPLICABLE", [])])
    validation = schema.validate_file(path)
    assert validation.detected_sort == "trivial"
    assert validation.violations == []


def test_key_order_variation_still_valid() -> None:
    step = make_step(1)
    reordered = {k: step[k] for k in reversed(list(step))}
    assert schema.validate_row("case_01", "COMPLETE", [reordered]) == []


def test_validate_file_detects_bad_header(tmp_path: Path) -> None:
    path = tmp_path / "bad.csv"
    path.write_text("case_id,status,steps\ncase_01,COMPLETE,[]\n", encoding="utf-8")
    assert schema.validate_file(path).violations


def test_validate_file_expected_ids(tmp_path: Path) -> None:
    path = write_output_csv(tmp_path / "o.csv", [("case_02", "NOT_APPLICABLE", [])])
    validation = schema.validate_file(path, expected_case_ids=["case_01", "case_02"])
    assert validation.missing_ids == ["case_01"]
    assert validation.extra_ids == []


def test_validate_file_duplicate_and_sort(tmp_path: Path) -> None:
    path = write_output_csv(
        tmp_path / "o.csv",
        [
            ("case_10", "NOT_APPLICABLE", []),
            ("case_09", "NOT_APPLICABLE", []),
            ("case_10", "NOT_APPLICABLE", []),
        ],
    )
    validation = schema.validate_file(path)
    assert validation.duplicate_ids == ["case_10"]
    assert validation.detected_sort is None


def test_validate_file_detects_natural_sort(tmp_path: Path) -> None:
    path = write_output_csv(
        tmp_path / "o.csv",
        [(f"case_{n}", "NOT_APPLICABLE", []) for n in (33, 100, 550)],
    )
    validation = schema.validate_file(path)
    assert validation.detected_sort == "natural"


def test_validate_file_golden_sample_has_zero_violations(sample_gold_path: Path) -> None:
    validation = schema.validate_file(sample_gold_path)
    assert validation.violations == []
    assert validation.detected_sort == "both"


def test_synthetic_expected_rows_are_schema_valid() -> None:
    for case in load_synthetic_cases():
        expected = case["expected"]
        violations = schema.validate_row(
            case["case_id"], expected["deletion_status"], expected["steps"]
        )
        assert violations == [], violations
        assert json.dumps(expected["steps"])  # serialisable
        assert expected["steps"] == sorted(
            expected["steps"],
            key=lambda s: (
                schema.PHASE_ORDER[s["phase"]],
                _op_rank(s),
                s["system_id"],
                s["resource_id"],
            ),
        )


def _op_rank(step: dict[str, object]) -> int:
    ranks = {
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
    return ranks[str(step["operation"])]
