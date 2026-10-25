# Execution Plans

Detailed, step-by-step execution plans derived from [Plan.md](../../Plan.md) §4.
Each file covers one or more Plan.md phases. Progress is tracked in [PROGRESS.md](../../PROGRESS.md).

| File | Plan.md Phases | Status |
|---|---|---|
| [phase_01_02_inspection_and_eval_harness.md](phase_01_02_inspection_and_eval_harness.md) | Phase 1 (Deep Inspection & Ground-Truth Alignment), Phase 2 (Evaluation & Metering Harness) | Complete (mutation score recorded in PROGRESS.md) |
| [phase_03_deterministic_parsers.md](phase_03_deterministic_parsers.md) | Phase 3 (Deterministic Evidence Parsers, Structured Files) | Complete on branch `phase-03-evidence-parsers` (src-wide mutation gate deferred to Phase 6) |
| [phase_04_multimodal_extraction.md](phase_04_multimodal_extraction.md) | Phase 4 (One-Time Multimodal Extraction, 4 PDFs + 11 PNGs) | Complete on branch `phase-04-multimodal-extraction` (94/94 files OK; store committed; mutation recorded) |
| [phase_05_core_audit_engine.md](phase_05_core_audit_engine.md) | Phase 5 (Core Audit Engine: Identity, Inventory, State, Rules, Planner) | Complete on branch `phase-05-core-engine` (core engine green, 217 tests passing) |
| [phase_06_sample_validation_convergence.md](phase_06_sample_validation_convergence.md) | Phase 6 (Sample Validation & 100% Convergence) | Complete on branch `phase-06-sample-convergence` (32/32 status; sample evidence gap documented in P1) |
| [phase_07_p1_hardcode_cleanup.md](phase_07_p1_hardcode_cleanup.md) | P1 hardcode cleanup | Complete on branch `phase-07-p1-hardcode-cleanup` (generic workflow resolver; 32/32 status, 30/32 sequence; gap documented) |
| [phase_07_full_518_run.md](phase_07_full_518_run.md) | Phase 7 (Full 518-Case Run & Reports) | Complete except packaging: 518 schema-valid rows, 18/18 sanity checks, reports generated |

## Conventions

- File name: `phase_<NN>[_<NN>]_<short_slug>.md`.
- Each plan has: Goal, Inputs, Tasks (with IDs `P<phase>.<n>`), Deliverables, Acceptance Criteria, Risks/Open Questions.
- Plans use only participant-facing data under `dataset/` (AGENTS.md §4.3).
- When a plan finishes, update its Status here and tick the matching items in `PROGRESS.md`.
