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

## Phase 1: Deep Inspection & Ground-Truth Alignment — ⏳ Planned
- [ ] P1.1 Scaffold `code/scripts/` exploration utilities
- [ ] P1.2 Dump 32 sample cases + flattened golden steps
- [ ] P1.3 Vocabulary census (systems, resource prefixes, operation/state pairs, cited evidence)
- [ ] P1.4 Identity tracing (current + historical identifiers)
- [ ] P1.5 Resource → user linkage audit
- [ ] P1.6 Evidence format inspection (all file families)
- [ ] P1.7 Evidence-citation selection rule
- [ ] P1.8 Policy edge cases (`case_12` DELETE vs ANONYMIZE, tombstones, retention)
- [ ] P1.9 Ordering rule validation (4-key sort vs golden)
- [ ] P1.10 Temporal rule check (`captured_at <= audit_at`, recreation events)
- [ ] P1.11 Intent census + `NOT_APPLICABLE` fixtures
- [ ] P1.12 Findings doc `docs/findings/phase_01_ground_truth.md`

## Phase 2: Evaluation & Metering Harness (TDD) — ⏳ Planned
- [ ] P2.1 Minimal `code/src/config.py` (paths, pricing table from config)
- [ ] P2.2–2.3 `code/src/evaluation/schema.py` output-contract validator + tests
- [ ] P2.4–2.6 `code/src/evaluation/evaluator.py` metrics, diff printer + tests
- [ ] P2.7–2.9 `code/src/evaluation/metering.py` token/cost accounting, usage report + tests
- [ ] P2.10 `code/evaluation/main.py` evaluation CLI
- [ ] P2.11 Synthetic case scaffold (≥3 cases + NOT_APPLICABLE + prompt injection)
- [ ] P2.12 Quality gates (ruff, mypy, pytest, cosmic-ray score)

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
- **Current milestone:** Phase 0 complete. Plan.md corrected to the real evidence inventory (24 sql / 28 json / 26 log / 4 pdf / 11 png / 1 txt = 94).
- **Next step:** Execute Phase 1 and Phase 2 (P2.1–P2.10 can run in parallel with Phase 1).
