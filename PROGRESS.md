# Project Progress & Plan Tracker

Shared memory and status tracking for the Deletion Audit Agent. Phase numbers match [Plan.md](Plan.md) §4 exactly (Phase 0 = environment setup, added before Plan.md Phase 1).

**Detailed execution plans:** [docs/execution_plans/](docs/execution_plans/README.md)
- Phase 1 & 2 → [phase_01_02_inspection_and_eval_harness.md](docs/execution_plans/phase_01_02_inspection_and_eval_harness.md) (Planned)

---

## Phase 0: Environment & Setup — ✅ Complete
- [x] Analyze challenge requirements (`AGENTS.md`, `agent_trace_instructions.md`)
- [x] `.gitignore` (venv, `.env`, caches, zip files, linter/mutation caches)
- [x] `.env.example` and local `.env` template (Gemini, OpenAI, Anthropic, QwenCloud)
- [x] Python 3.15.1 virtual environment (`.venv`)
- [x] Quality tooling: `pytest`, `ruff`, `mypy`, `cosmic-ray` (Windows), `mutmut` (WSL/Linux/CI); config in [`pyproject.toml`](pyproject.toml)
- [x] Evidence processing libraries installed and import-verified: `pandas`, `pydantic`, `python-dotenv`, `pypdf`, `pdfplumber`, `Pillow`, `sqlite3`, `google-genai`, `openai`, `anthropic`
- [x] `ruff check code/` and `mypy code/` clean
- [x] `PROGRESS.md` shared memory; `docs/execution_plans/` folder

---

## Phase 1: Deep Inspection & Ground-Truth Alignment — ✅ Complete
- [x] P1.1 Scaffold `code/scripts/` exploration utilities (`_paths.py`)
- [x] P1.2 Dump 32 sample cases + flattened golden steps (`out/sample_steps.csv`, 193 rows)
- [x] P1.3 Vocabulary census (9 systems, 9 resource prefixes, 15 op/state pairs all legal, 13 cited evidence ids; `out/vocabulary.json`)
- [x] P1.4 Identity tracing (32/32 samples + 518/518 eval resolved; 3 samples & 100 eval via audit-log email history; sha256(lower(email))==email_hash; `out/identity_resolution.csv`)
- [x] P1.5 Resource → user linkage audit (88 evidence-content, 14 activity, 14 workflow-window accounts; exceptions: post-audit-only linkage in 5 cases, `case_04` PNG-dependent; `out/resource_linkage.csv`)
- [x] P1.6 Evidence format inspection (all 24 families; `out/evidence_formats.md`; PDF text extracted; `evidence_37`/`evidence_42` PNGs reviewed manually)
- [x] P1.7 Evidence-citation selection rule (71/75 latest-containing; 4 ABSENT-proofs via scoped replicas/bundles; `out/citation_audit.csv`)
- [x] P1.8 Policy edge cases (case_12 opt-in→MARKETING hypothesis; compliant flows listed in COMPLETE; tombstone REDACTED; attachment vs message; retention PRESENT) — see findings §8
- [x] P1.9 Ordering rule validation (Rule 6 4-key sort reproduces 32/32 golden orders)
- [x] P1.10 Temporal rule check (0 future citations; 3 in-window recreation events; 40 post-audit mention triples; `out/temporal_audit.csv`)
- [x] P1.11 Intent census + fixtures (541 deletion-language, 6 non-deletion eval texts, 10 CLASSIFY events; 16 fixtures in `out/intent_fixtures.json`)
- [x] P1.12 Findings doc `docs/findings/phase_01_ground_truth.md`

## Phase 2: Evaluation & Metering Harness (TDD) — ✅ Complete
- [x] P2.1 `code/src/config.py` (paths, empty PRICING + `DELETION_AUDIT_PRICING_JSON` override)
- [x] P2.2–2.3 `code/src/evaluation/schema.py` + `code/tests/test_schema.py` (golden sample = 0 violations)
- [x] P2.4–2.6 `code/src/evaluation/evaluator.py` (status/sequence/positional/set-based/field metrics + diffs) + tests
- [x] P2.7–2.9 `code/src/evaluation/metering.py` (JSONL log, provider usage extraction, summarize, usage report) + tests
- [x] P2.10 `code/evaluation/main.py` CLI; self-comparison reports 100% on every metric
- [x] P2.11 Synthetic scaffold: 6 grounded cases in `code/tests/fixtures/synthetic/synthetic_cases.json` + `test_synthetic_cases.py`
- [x] P2.12 Quality gates: ruff/mypy/pytest green (62 tests); cosmic-ray on `code/src/evaluation`: run 1 = 696/1195 killed (58.2%); after mutation-driven test hardening run 2 = 758/1195 killed (63.4%). Target ≥80% not met; remaining survivors are dominated by operator swaps in message/format branches and near-equivalent comparisons. Non-blocking per decision; sessions kept in `code/cache/cr_eval_session*.sqlite` (gitignored).

## Phase 3: Deterministic Evidence Parsers (Structured Files)
- [ ] `code/src/models.py` (`IdentityGraph`, `ResourceItem`, `EvidenceObservation`, `AuditStep`)
- [ ] Task 3.1 `code/src/loaders/csv_loader.py` (all CSVs)
- [ ] Task 3.2 `code/src/loaders/sql_parser.py` (24 `.sql` files, `snapshot_scope`)
- [ ] Task 3.3 `code/src/loaders/json_txt_parser.py` (28 `.json` + 1 `.txt`)
- [ ] Task 3.4 `code/src/loaders/log_parser.py` (26 `.log` files)
- [ ] Parser unit tests

## Phase 4: One-Time Multimodal Extraction (4 PDFs + 11 PNGs)
- [ ] Task 4.1 PDF extraction (`pypdf` / `pdfplumber`)
- [ ] Task 4.2 VLM extraction of 11 PNGs → `code/cache/multimodal_evidence.json` (metered)

## Phase 5: Core Audit Engine
- [ ] Task 5.1 `intent_classifier.py` (CLASSIFY_REQUEST events + batched LLM, injection-safe, cached)
- [ ] Task 5.2 `identity_resolver.py`
- [ ] Task 5.3 `inventory_builder.py` + `state_reconstructor.py`
- [ ] Task 5.4 `rules_engine.py` + `planner_sorter.py`

## Phase 6: Sample Validation & Convergence
- [ ] Task 6.1 Run pipeline on 32 sample cases + evaluator
- [ ] Task 6.2 Debug to 100% sample accuracy
- [ ] Task 6.3 ≥3 synthetic evaluation cases in the suite

## Phase 7: Full 518-Case Run & Packaging
- [ ] Task 7.1 `code/main.py` → root `output.csv`
- [ ] Task 7.2 Output sanity checks (518 rows, sorted, valid JSON, evidence rules)
- [ ] Task 7.3 `evaluation/evaluation_report.md` + `evaluation/usage_report.md`
- [ ] Task 7.4 `code.zip` + `agent-trace.zip`; final `README.md`

---

## Current Status & Next Steps
- **Current milestone:** Phase 1 + Phase 2 complete. Harness validated: golden sample self-comparison = 100% on all metrics; `evaluation/evaluation_report.md` + `evaluation/usage_report.md` skeletons generated (deterministic-only usage).
- **Next step:** Phases 3–5 (deterministic parsers and audit engine), then Phase 6 convergence using the harness.
