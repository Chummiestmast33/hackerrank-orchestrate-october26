# Project Progress & Plan Tracker

Shared memory and status tracking for the Deletion Audit Agent implementation based on [Plan.md](file:///c:/Users/corte/Downloads/hackerrank-orchestrate-october26/Plan.md).

---

## 1. Environment & Setup (Phase 0)
- [x] Analyze challenge requirements and guidelines (`AGENTS.md`, `agent_trace_instructions.md`)
- [x] Configure repository [`.gitignore`](file:///c:/Users/corte/Downloads/hackerrank-orchestrate-october26/.gitignore) (protecting `.venv`, `.env`, caches, zip files, linter/mutation caches)
- [x] Set up [`.env.example`](file:///c:/Users/corte/Downloads/hackerrank-orchestrate-october26/.env.example) and local [`.env`](file:///c:/Users/corte/Downloads/hackerrank-orchestrate-october26/.env) template
- [x] Set up Python environment & virtual environment (`.venv` with Python 3.15.1)
- [x] Install base dependencies, test frameworks, and code quality tools:
  - Base: `pytest`
  - Linters: `ruff` (fast linter/formatter) and `mypy` (static type checking)
  - Mutation Testing: `cosmic-ray` (cross-platform & Windows native) and `mutmut` (WSL/Linux/CI)
- [x] Create centralized tool configuration in [`pyproject.toml`](file:///c:/Users/corte/Downloads/hackerrank-orchestrate-october26/pyproject.toml) (ruff, mypy, pytest, mutmut, cosmic-ray)
- [x] Verify linters (`ruff check code/`, `mypy code/`) pass cleanly
- [x] Initialize `PROGRESS.md` as shared state memory

---

## 2. Core Data Models & Config (Phase 1)
- [ ] Implement `code/src/config.py` (paths, sorting order constants, pricing table)
- [ ] Implement `code/src/models.py` (`IdentityGraph`, `ResourceItem`, `EvidenceObservation`, `AuditStep`)
- [ ] Create unit tests and verify mutation score for data models

---

## 3. Data Loaders & Evidence Parsers (Phase 2)
- [ ] Implement `code/src/loaders/csv_loader.py` (all CSVs under `dataset/`)
- [ ] Implement `code/src/loaders/sql_parser.py` (in-memory SQLite loading, snapshot inspection)
- [ ] Implement `code/src/loaders/json_txt_parser.py` (JSON dumps and handover text parser)
- [ ] Implement `code/src/loaders/log_parser.py` (trace logs, syslog, service events)
- [ ] Implement `code/src/loaders/multimodal_parser.py` (PDF & PNG structured parser with disk caching)
- [ ] Unit & regression tests for parsers

---

## 4. Business Logic & Deletion Audit Pipeline (Phase 3)
- [ ] Implement `code/src/core/identity_resolver.py` (exact transitive identity resolution with SHA-256 hash recovery)
- [ ] Implement `code/src/core/intent_classifier.py` (hybrid deterministic rules + batched LLM classification with prompt-injection defense)
- [ ] Implement `code/src/core/inventory_builder.py` (linking resources to identity graph across activity and snapshots)
- [ ] Implement `code/src/core/state_reconstructor.py` (temporal filtering `<= audit_at`, state extraction per resource)
- [ ] Implement `code/src/core/rules_engine.py` (evaluating state against `deletion_rules.csv`)
- [ ] Implement `code/src/core/planner_sorter.py` (generating FINDING, REMEDIATION, VERIFICATION steps with canonical 4-key sort)

---

## 5. Main Runner, Evaluation & Reports (Phase 4)
- [ ] Implement `code/main.py` (full pipeline execution generating root `output.csv` matching 518 cases)
- [ ] Implement `code/src/evaluation/evaluator.py` (metrics vs `sample_output.csv` + 3 synthetic validation cases)
- [ ] Implement `code/src/evaluation/metering.py` (token accounting and cost calculation)
- [ ] Generate `evaluation/evaluation_report.md`
- [ ] Generate `evaluation/usage_report.md`
- [ ] Write final `code/README.md` with complete setup and execution instructions

---

## Current Status & Next Steps
- **Current Milestone:** Phase 0 (Environment Setup, Linters, and Mutation Testing harness) is 100% complete.
- **Immediate Next Step:** Proceed to Phase 1 by implementing `code/src/config.py` and `code/src/models.py`.
