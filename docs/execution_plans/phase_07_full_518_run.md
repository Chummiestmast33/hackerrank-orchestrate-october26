# Phase 7 Full 518-Case Run Plan

**Status:** Planned. P1 cleanup is complete and committed. Packaging is intentionally out of scope.

## Goal

Run the deterministic audit pipeline for all 518 evaluation requests, produce root `output.csv`, validate the output contract and evidence citations, and generate:

- `evaluation/evaluation_report.md`
- `evaluation/usage_report.md`
- `evaluation/sanity_checks.json`

The hidden 518-case gold answers are unavailable. The report must not claim full-dataset accuracy; full-run reporting is limited to sanity checks and coverage statistics.

## Inputs

- `dataset/deletion_requests.csv` (518 requests)
- `dataset/evidence_files.csv` and `dataset/evidence/`
- `dataset/sample_deletion_requests.csv` and `dataset/sample_output.csv` for the separate public sample evaluation
- `code/src/evaluation/synthetic_cases.py` for the four custom cases
- `code/cache/usage_log.jsonl` for the one-time Phase 4 extraction usage
- `.pricing.json` (committed public pricing values)

## Tasks

### P7.1 Full audit run

- Rebuild the evidence cache after the `phase4-v2` parser-version change.
- Run `python code/main.py --output output.csv`.
- Record branch, commit, timestamp, cache statistics, runtime, exit code, and output hash.
- Run a second full audit to a temporary file and require byte-identical output.

### P7.2 Sanity checks

Add a Phase 7 runner (`code/evaluation/full_run.py`) that checks:

- exact header and 518 unique rows;
- expected case IDs exactly match `deletion_requests.csv`;
- schema violations = 0;
- valid JSON, consecutive `step_no`, phase order, allowed operation/state pairs;
- `COMPLETE` rows contain only evidence-backed verification;
- `INCOMPLETE` findings cite evidence; remediation/future verification use empty evidence;
- every non-empty citation exists in `evidence_files.csv`;
- every cited evidence file was captured at or before the case `audit_at`;
- status and step distributions, findings/remediation/verification counts, empty-step cases, and system coverage;
- deterministic rerun equality;
- zero audit-time model calls.

### P7.3 Reports

`evaluation/evaluation_report.md` must include:

- run metadata and full-run sanity results;
- full-run coverage statistics with an explicit hidden-gold limitation;
- public sample metrics: status 32/32, sequence 30/32, documented evidence gap;
- the four synthetic cases and outcomes;
- failures and improvements from P0/P1;
- metric definitions and limitations.

`evaluation/usage_report.md` must include:

- full 518-case run: 0 calls, 0 tokens, $0;
- one-time Phase 4 extraction separately: 22 calls, `qwen/qwen3-vl-plus`, 50,784 input / 7,702 output tokens, and computed cost from `.pricing.json`;
- no secrets or invented prices.

`evaluation/sanity_checks.json` must contain the machine-readable check results and run metadata.

### P7.4 Packaging

Intentionally skipped.

## Acceptance Criteria

- `output.csv` has exactly 518 schema-valid rows sorted by `case_id`.
- Sanity checks pass with zero schema or citation violations.
- Reports are regenerated from the actual run and do not claim 100% sample or hidden full-dataset accuracy.
- The documented evidence gap remains the only sample sequence difference.
- No packaging artifacts are created.

## Risks

- The sample CLI exits `1` because sequence accuracy is 0.9375 by design after P1; this is documented in `docs/findings/phase_07_sample_evidence_gap.md`.
- Parser code changes require `PARSER_VERSION` invalidation; otherwise a stale cache can hide parser fixes.
- Full-run metrics cannot be compared to hidden truth; only structural and evidence-consistency checks are possible.