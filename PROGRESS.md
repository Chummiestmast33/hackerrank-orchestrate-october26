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

## Phase 3: Deterministic Evidence Parsers (Structured Files) — ✅ Complete (branch `phase-03-evidence-parsers`)
- [x] P3.0 Branch + plan md (`docs/execution_plans/phase_03_deterministic_parsers.md`) + cosmic-ray feasibility probe — verdict: raw 73.7% (864/1172), adjusted 84.3% (864/1025) after excluding 147 void PEP-604-annotation mutants cosmic-ray counts in the denominator; ≥80% reachable on the adjusted denominator, not on raw. Sessions: `code/cache/cr_eval_session3.sqlite`, `cr_eval_session4.sqlite`.
- [x] P3.1 `code/src/models.py` — `ObservationState`/`ParseStatus`/`Provenance` enums, `EvidenceObservation` (reason, locator, identifiers, state_inputs, pii flag), `ParseReport` (errors, scope, captured collections, direct systems), `finalize_status`
- [x] P3.2 `code/src/loaders/state_vocab.py` + `collection_rules.py` — explicit decoder table (result/boolean/readback/count/search/analytics/profile/support/matched/available/existence); every unknown token or missing field ⇒ `UNKNOWN` with reason; no default state branches
- [x] P3.3 `code/src/loaders/csv_loader.py` — manifest, requests, identities, audit log, activity, rules; ISO-8601 validation, duplicate-key and missing-column detection
- [x] P3.4 `code/src/loaders/sql_parser.py` — inventory typed tables + `snapshot_scope`, generic `record_json` replicas keyed by `collection_name`, dedicated account/search replicas; unknown family/table/collection ⇒ explicit error
- [x] P3.5 `code/src/loaders/json_txt_parser.py` — bundles (incl. empty-collection metadata), service exports (all 8 services, nested search `hits`), ledgers, export jobs, analytics report, handover text; malformed JSON/line ⇒ `PARSE_ERROR`
- [x] P3.6 `code/src/loaders/log_parser.py` — 7 line shapes, state-bearing event table (account/support/connector/backup/search/security/analytics/export/record_lookup/restore_candidate_evaluated); unmapped values ⇒ `UNKNOWN`, broken lines ⇒ line errors
- [x] Parser unit tests — `test_state_vocab`, `test_csv_loader`, `test_sql_parser`, `test_json_txt_parser`, `test_log_parser` (138 total tests green repo-wide after P3.7/P3.8)
- [x] P3.7 Aggressive all-in-one cache + parse CLI — `code/src/loaders/cache.py` (sha256+PARSER_VERSION reuse forever, atomic deterministic writes, `UNSUPPORTED_FORMAT` placeholders) and `cli.py parse-all` (family census, cache stats, exit codes); verified first run 94 misses → second run 94 hits, cache 2 MB gitignored
- [x] P3.8 Corpus tests — committed census snapshot `code/tests/fixtures/parsers/corpus_census.json` (94 files), drift test, double-parse determinism, golden-citation cross-check (70 matched / 0 mismatched / 4 documented scope exemptions / 1 PDF)
- [x] P3.9 Evaluation mutation debt — resolved on the adjusted denominator (session 4: 864/1025 = 84.3%); void annotation-mutant exclusion documented in `docs/findings/phase_03_parser_notes.md` §6
- [x] P3.10 Src-wide cosmic-ray gate — **deferred to Phase 6** by decision; loader/model modules join that run; current valid gate remains session 4
- [x] P3.11 `docs/findings/phase_03_parser_notes.md` — implemented decode tables, deviations, corpus results, cache semantics, mutation status
- [x] P3.12 Closeout — trackers updated, mutation byproducts purged, gates green, single Phase 3 commit on the branch
- [x] Corpus results: 79 structured files `OK` + 15 binary placeholders, 0 errors, 0 UNKNOWN, 2886 observation records, 70/70 structured golden citations matching

## Phase 4: One-Time Multimodal Extraction (4 PDFs + 11 PNGs) — ✅ Complete (branch `phase-04-multimodal-extraction`)
- [x] P4.0 Visual inventory + DB relations → `docs/findings/phase_04_multimodal_notes.md` (11 PNG families, 4 PDFs, per-family `ExtractedRecord` schemas, verified cache/LINK relations incl. 2 conflicts + 1 drift; metadata-only policy)
- [x] P4.1 Additive model changes (`Provenance.DOCUMENT_TEXT`/`VISION_TRANSCRIPTION`, frozen `ExtractedRecord`, `ParseReport.extracted_records` with `phase3-v1` cache back-compat) + `test_models.py`
- [x] P4.2 `pdf_extractor.py` (pypdf → pdfplumber fallback, split-time rejoin, label stripping, header-only family detection) + real-PDF tests (4/4)
- [x] P4.3 PDF decode tables + relations helper (`support_001` PRESENT+PII, `audit_record_003` PRESENT+retention, `evidence_18`/`27` facts only, diagnostics for missing fields, `relate_to_structured`) + tests
- [x] P4.4 `vlm_extractor.py` (QwenCloud VL via openai SDK, transcription-only prompts, metered) + `metered_call` alias + pass-B env keys + 11 prompt files (p4-v1)
- [x] P4.5 Two-pass agreement (second model via `QWEN_VISION_MODEL_PASS_B`, reversed-order fallback) + `transcription_store.py` (sha256+version+models keyed, both passes + merged) + tests
- [x] P4.6 `transcription_validator.py` (schema/format errors, identity cross-check flags, no drops) + tests
- [x] P4.7 PNG decode tables (explicit status vocabulary, presence+PII, health labels ⇒ UNKNOWN, LINK-resolved registry, sentinel existence; no real calls) + tests
- [x] P4.8 `multimodal_parser.py` + cache/CLI integration (`--extract-images` opt-in, offline-strict default, `--transcription-store`, `PARSER_VERSION → phase4-v1`, census multimodal summary)
- [x] P4.9 Extraction run: 11 images × 2 passes = 22 calls / 50,784 in / 7,702 out tokens (`qwen3-vl-plus`, dashscope-intl); manual review passed (one `Live` badge omission recorded); store committed (47 KB); offline rerun 94/94 hits, 0 calls
- [x] P4.10 Tests/census: 94 files OK, 0 errors, 2912 observations; corpus fixture regenerated; golden cross-check 71 matched + 4 scope-deferred; double offline parse byte-identical
- [x] P4.11 Quality gates green (205 tests); cosmic-ray record run on the 5 multimodal modules: 681/956 killed = 71.2% raw, 79.6% adjusted (101 void BitOr-annotation mutants excluded); session `code/cache/cr_multimodal.sqlite`
- [x] P4.12 Notes §6 (review, usage, mutation record) + tracker closeout + single P4.8–P4.12 commit

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
- **Current milestone:** Phase 1 + Phase 2 complete on `main`; **Phase 3 complete** on branch `phase-03-evidence-parsers`. **Phase 4 complete** on branch `phase-04-multimodal-extraction` (all 94 evidence files parse: 79 structured + 4 PDF + 11 PNG; committed transcription store; 205 tests green; golden citations 71/71; multimodal mutation 71.2% raw / 79.6% adjusted).
- **Next step:** Phase 5 (identity resolver, inventory builder, state reconstruction, rules engine and planner), consuming the Phase 3/4 observation index.
