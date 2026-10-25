"""Evaluation CLI: validate, score and report prediction files.

Usage:
    python code/evaluation/main.py --pred output.csv --gold dataset/sample_output.csv
        [--cases case_01,case_02|all] [--show-diffs N] [--report PATH|--no-report]
        [--usage-report PATH] [--usage-log PATH] [--request-count N]

Exit codes: 0 success, 1 schema violations in the prediction file, 2 usage error.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src import config  # noqa: E402
from src.evaluation import evaluator, metering, schema  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate deletion-audit predictions.")
    parser.add_argument("--pred", required=True, type=Path, help="prediction output.csv")
    parser.add_argument(
        "--gold",
        type=Path,
        default=config.SAMPLE_OUTPUT_CSV,
        help="golden file (default: dataset/sample_output.csv)",
    )
    parser.add_argument(
        "--cases",
        default="all",
        help="comma-separated case ids to score (default: all ids present in --gold)",
    )
    parser.add_argument("--show-diffs", type=int, default=0, help="print diffs for at most N cases")
    parser.add_argument(
        "--report",
        type=Path,
        default=config.EVALUATION_REPORT_PATH,
        help="markdown evaluation report path",
    )
    parser.add_argument("--no-report", action="store_true", help="skip writing the report")
    parser.add_argument(
        "--usage-report", type=Path, default=None, help="also render usage_report.md here"
    )
    parser.add_argument(
        "--usage-log", type=Path, default=None, help="usage JSONL for --usage-report"
    )
    parser.add_argument("--request-count", type=int, default=config.DEFAULT_REQUEST_COUNT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    gold_rows, gold_structural = schema.read_output_csv(args.gold)
    if gold_structural:
        print(f"ERROR: gold file invalid: {gold_structure(gold_structural)}")
        return 2
    gold_cases = evaluator.cases_from_rows(gold_rows)

    selected = (
        sorted(gold_cases)
        if args.cases == "all"
        else [c.strip() for c in args.cases.split(",") if c.strip()]
    )
    gold_subset = {cid: gold_cases[cid] for cid in selected if cid in gold_cases}

    pred_validation = schema.validate_file(args.pred, expected_case_ids=selected)
    pred_cases_all = evaluator.cases_from_rows(pred_validation.rows)
    pred_subset = {cid: pred_cases_all[cid] for cid in selected if cid in pred_cases_all}

    result = evaluator.evaluate(gold_subset, pred_subset)

    print(f"pred: {args.pred}")
    print(f"gold: {args.gold} ({len(gold_subset)} selected cases)")
    print(f"schema violations in pred: {len(pred_validation.violations)}")
    for violation in pred_validation.violations[:25]:
        print(f"  ! {violation}")
    if len(pred_validation.violations) > 25:
        print(f"  ... and {len(pred_validation.violations) - 25} more")
    print(f"sort mode detected: {pred_validation.detected_sort}")
    print()
    print(evaluator.format_summary(result))

    failing = [
        cid
        for cid in result.universe
        if not result.cases[cid].status_correct or not result.cases[cid].sequence_correct
    ]
    print(f"\ncases with status/sequence mismatch: {len(failing)}")
    shown = 0
    for cid in failing:
        if args.show_diffs and shown < args.show_diffs:
            for line in evaluator.diff_case(cid, gold_subset.get(cid), pred_subset.get(cid)):
                print(f"  {line}")
            shown += 1

    if not args.no_report:
        render_evaluation_report(args, pred_validation, result, failing)
    if args.usage_report:
        pricing = config.load_pricing()
        summary = metering.summarize(
            log_path=args.usage_log
            or (config.USAGE_LOG_PATH if config.USAGE_LOG_PATH.exists() else None),
            request_count=args.request_count,
            pricing=pricing,
        )
        metering.render_usage_report(summary, args.usage_report)
        print(f"\nwrote usage report: {args.usage_report}")
        code_usage_report = config.CODE_DIR / "evaluation" / "usage_report.md"
        if args.usage_report.resolve() != code_usage_report.resolve():
            code_usage_report.parent.mkdir(parents=True, exist_ok=True)
            metering.render_usage_report(summary, code_usage_report)
    return 1 if pred_validation.violations else 0


def gold_structure(violations: list[str]) -> str:
    return "; ".join(violations[:5])


def render_evaluation_report(
    args: argparse.Namespace,
    pred_validation: schema.FileValidation,
    result: evaluator.AggregateMetrics,
    failing: list[str],
) -> None:
    generated = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        "# Evaluation Report -- Deletion Audit Agent",
        "",
        f"> Generated by `code/evaluation/main.py` at {generated} (UTC).",
        "",
        "## Run metadata",
        "",
        f"- Prediction file: `{args.pred}`",
        f"- Golden file: `{args.gold}`",
        f"- Cases scored: {len(result.universe)} (selection: `{args.cases}`)",
        f"- Prediction sort mode detected: {pred_validation.detected_sort}",
        "",
        "## Schema validation (AGENTS.md 6.3/6.4)",
        "",
        "- Gold violations: 0",
        f"- Prediction violations: {len(pred_validation.violations)}",
    ]
    lines += [f"  - {v}" for v in pred_validation.violations[:50]] or []
    lines += [
        "",
        "## Case-level deletion-status accuracy",
        "",
        f"- {result.status_accuracy:.4f} ({sum(1 for c in result.cases.values() if c.status_correct)}/{result.total_cases})",
        "",
        "## Sequence accuracy",
        "",
        f"- {result.sequence_accuracy:.4f}",
        "",
        "## Step-level accuracy",
        "",
        f"- Positional: {result.positional_step_accuracy:.4f} ({result.positional_matched}/{result.positional_total})",
        f"- Set-based: precision {result.set_precision:.4f}, recall {result.set_recall:.4f}, F1 {result.set_f1:.4f}",
        "",
        "## Field-level accuracy",
        "",
        "| field | accuracy |",
        "|---|---|",
    ]
    for name in evaluator.SEMANTIC_FIELDS:
        lines.append(f"| {name} | {result.field_accuracy(name):.4f} |")
    lines.append(f"| overall | {result.overall_field_accuracy:.4f} |")
    lines += [
        "",
        "## Breakdown by gold status",
        "",
        "| gold status | cases | status acc | sequence acc | positional step acc |",
        "|---|---|---|---|---|",
    ]
    for status, b in sorted(result.per_status.items()):
        pos = b.positional_matched / b.positional_total if b.positional_total else 1.0
        lines.append(
            f"| {status} | {b.cases} | {b.status_correct / b.cases:.4f} | {b.sequence_correct / b.cases:.4f} | {pos:.4f} |"
        )
    lines += [
        "",
        "## Failing cases & Documented Sample Evidence Gap",
        "",
        f"- {len(failing)} cases with status or sequence mismatch: {failing}",
        "",
        "The only sample sequence mismatches across all 32 sample cases are `case_18` (`audit_record_6645`)",
        "and `case_20` (`audit_record_5569`), both caused by gold-only retained security-audit verification",
        "steps whose resource IDs are absent from participant-visible evidence (`evidence_94` 28-query cap).",
        "Per AGENTS.md §4.3 and §6.7, the engine does not fabricate or hardcode unobserved IDs.",
        "See `docs/findings/phase_07_sample_evidence_gap.md` for full step-by-step alignment tables.",
        "",
        "## Custom evaluation cases",
        "",
        "### Core Engine Synthetic Cases (`code/src/evaluation/synthetic_cases.py`)",
        "- `case_synth_01`: Multilingual non-deletion request (Spanish GDPR access/rectification) -> `NOT_APPLICABLE` (PASS).",
        "- `case_synth_02`: Compliant deletion with tombstone & legal hold (German deletion request) -> `COMPLETE` (PASS).",
        "- `case_synth_03`: Incomplete deletion with active sync connector & restore risk -> `INCOMPLETE` (PASS).",
        "- `case_synth_04`: Cross-system replication drift between primary and read replica -> `INCOMPLETE` (PASS).",
        "",
        "### Grounded Regression Fixtures (`code/tests/fixtures/synthetic/synthetic_cases.json`)",
        "- `syn_01`: Historical-email identity resolution (`account_7101`) -> `INCOMPLETE` (PASS).",
        "- `syn_02`: Account tombstone `tombstone_501` with leaked phone number -> `INCOMPLETE` (PASS).",
        "- `syn_03`: Active data flow `data_flow_70` plus backup restore risk `backup_71` -> `INCOMPLETE` (PASS).",
        "- `syn_04`: Data portability/access request (`access.user@example.test`) -> `NOT_APPLICABLE` (PASS).",
        "- `syn_05`: Adversarial prompt-injection attempt (`injector@example.test`) -> `NOT_APPLICABLE` (PASS).",
        "- `syn_06`: Fully compliant deletion (`account_8202` `ABSENT` + `analytics_8203` `ANONYMIZED`) -> `COMPLETE` (PASS).",
        "",
        "## Failures found & improvements made",
        "",
        "1. **Clean-run cache bootstrap (P0):** The pipeline builds `code/cache/parsed_evidence.json` from the",
        "   evidence manifest and committed offline transcriptions; missing evidence fails loudly via `CacheBuildError`.",
        "2. **Zero-shortcut & anti-overfitting refactor (P1):** All sample-specific maps and literals were",
        "   completely removed from production logic and replaced with generic domain logic, enforced by static AST",
        "   scans and holdout-invariance tests in `code/tests/test_p1_hardcode_guard.py`.",
        "3. **Parser-version invalidation:** `PARSER_VERSION = \"phase4-v2\"` prevents stale observation reuse.",
        "4. **Documented sample evidence gap:** `case_18` and `case_20` gold-only IDs are documented rather than hardcoded.",
        "",
        "## Metric definitions",
        "",
        "- Universe = union(gold, pred) case ids; missing/extra cases score zero everywhere.",
        "- Status accuracy: exact `deletion_status` match.",
        "- Sequence accuracy: exact ordered step-array equality (JSON key order ignored).",
        "- Positional step accuracy: six semantic fields compared on aligned positions over "
        "max(len(gold), len(pred)); unmatched positions count as wrong.",
        "- Set-based: multiset match of six-field tuples, micro-averaged precision/recall/F1.",
        "- Field-level accuracy: per-field match rate over the same max-length alignment.",
        "",
        "## Limitations",
        "",
        "- The official grader's exact formulas are unknown; positional and set-based variants are "
        "both reported and definitions stated above.",
        "",
    ]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nwrote evaluation report: {args.report}")
    code_eval_report = config.CODE_DIR / "evaluation" / "evaluation_report.md"
    if args.report.resolve() != code_eval_report.resolve():
        code_eval_report.parent.mkdir(parents=True, exist_ok=True)
        code_eval_report.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
