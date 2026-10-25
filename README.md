# HackerRank Orchestrate - October 2026

## Ghost Data Still Exists

Build an AI agent that audits whether a user's personal data was actually deleted.

A deletion workflow may report **Complete** while data still exists in databases, logs, support attachments, exports, search indexes, archives, or backups. Sync and restore processes may also bring deleted data back.

For each request, the agent must first determine whether deletion was actually requested. It then returns `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`, reports any remaining data or recreation risk, and produces the ordered remediation and verification steps required to finish an authorized deletion safely.

Read [`problem_statement.md`](./problem_statement.md) for the complete challenge contract.

---

## Quick Start & Setup

Clone the repository and move into the project directory:

```bash
git clone https://github.com/interviewstreet/hackerrank-orchestrate-october26.git
cd hackerrank-orchestrate-october26
```

Start your AI coding tool from the **repository root** so it automatically reads [`AGENTS.md`](./AGENTS.md) and logs your session turns to `log.txt` in the root directory.

Build your solution in `code/main.py`, or use another language and document its setup and run command clearly in your README.

Your solution must:

- Read the input files from `dataset/`
- Generate one prediction row for every request in `dataset/deletion_requests.csv`
- Write the final predictions to `output.csv` in the repository root

### 1. Environment Setup

Requires **Python 3.10+**. Create a virtual environment at the repository root and install the pinned dependencies:

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r code/requirements.txt
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r code/requirements.txt
```

Configure `.env` from `.env.example` (`DASHSCOPE_API_KEY`, `QWEN_BASE_URL`, `QWEN_MODEL=qwen3.7-max`, `QWEN_VISION_MODEL=qwen3-vl-plus`, `DELETION_AUDIT_PRICING_JSON=.pricing.json`).

### 2. Run the Deletion-Audit Agent

Run the Python entry point from the repository root:

```bash
python3 code/main.py
```

Or run with live Qwen agent orchestration (`qwen3.7-max` + `qwen3-vl-plus`) and full evaluation/usage reporting:

```bash
python3 code/main.py --agent-llm
python3 code/evaluation/full_run.py
```

The first run automatically builds `code/cache/parsed_evidence.json` from `dataset/evidence_files.csv` using our structured parsers (`SQL`, `JSON`, `LOG`, `TXT`, `PDF`) and `MultimodalVisionAgent` (`qwen3-vl-plus`, backed by `code/data/multimodal_transcriptions.json`). When `DASHSCOPE_API_KEY` is configured, `AuditOrchestratorAgent` (`qwen3.7-max`) and `MultimodalVisionAgent` (`qwen3-vl-plus`) execute batched intent classification, unstructured document analysis, multimodal screenshot verification, and tool-calling cohort orchestration, logging every call and token count to `code/data/usage_log.jsonl` via `code/src/evaluation/metering.py`. If run in an offline grading sandbox without network access, the agent seamlessly falls back to its cached transcriptions and deterministic tool guardrails.

Useful options:

```bash
python3 code/main.py --sample
python3 code/main.py --sample --diff
python3 code/main.py --agent-llm
python3 code/main.py --rebuild-cache
python3 code/main.py --cache /tmp/parsed_evidence.json
python3 code/evaluation/full_run.py
python3 -m pytest code/tests -q
```

The final generated file for submission is written to both the root-level `output.csv` and `dataset/output.csv`.

---

## Solution Architecture: Hybrid AI Audit Agent (AI Proposal -> Deterministic Verification -> Canonical Output)

The solution in `code/` implements a **Hybrid AI Audit Agent (`code/src/core/agent.py`)** powered by **`qwen3.7-max`** and **`qwen3-vl-plus`**, operating on an explicit **AI-proposal -> deterministic-verification -> canonical-output** flow so that AI reasoning materially drives case proposals while deterministic tools remain the authority that validates evidence, enforces policy, and guarantees the output contract:

1. **Tier 1 — Multimodal Vision Agent (`qwen3-vl-plus` in `agent.py`, `vlm_extractor.py`, `multimodal_parser.py`):**
   - Processes all 11 PNG application screenshots in `dataset/evidence/images/` (`account_admin_console`, `search_index_inspector`, `connector_management_console`, `analytics_cohort_console`, `export_job_console`, `support_desk_console`, `backup_restore_console`, `identity_reference_registry`, `security_sentinel_console`, `cloud_object_browser`, `marketing_preferences_console`) by default when live vision is enabled (`max_files=None`, configurable).
   - Validates every extracted transcription against per-family schemas (`transcription_validator.py`) and rule decoding (`multimodal_rules.py`) so extracted IDs, badges, and timestamps remain 100% accurate.
   - Alongside vision extraction, `cache_bootstrap.py` validates `code/cache/parsed_evidence.json` against `PARSER_VERSION = "phase4-v2"` across all 94 files in `dataset/evidence_files.csv` (2,912 structured `EvidenceObservation` records with 0 parse errors).

2. **Tier 2 — Intent & Unstructured Document Agent (`qwen3.7-max` in `agent.py` & `intent_classifier.py`):**
   - Classifies all 375 distinct multilingual and nuanced `request_text` prompts across the 518 cases in smart batches (`DELETE` vs `NOT_APPLICABLE` across English, Spanish, Portuguese, French, German, Japanese, Korean, marketing opt-outs, data-access requests, and profile corrections) and persists verified verdicts to `code/cache/intent_classifications.json` via `IntentClassifier._save_cache()`.
   - Analyzes all 5 unstructured evidence documents: 1 handover `.txt` (`customer_account_handover_20261001.txt`) plus all 4 `.pdf` compliance/statement/support documents (`evidence_18`, `evidence_27`, `evidence_55`, `evidence_58`) extracted via `code/src/loaders/pdf_extractor.py`.

3. **Tier 3 — Audit Orchestrator Agent (`qwen3.7-max` with Tool-Calling) & `DeterministicProposalVerifier` (`code/src/core/agent.py`):**
   - Exposes the core audit modules as 4 structured OpenAI-compatible agent tools (`resolve_subject_identities`, `query_system_inventory`, `reconstruct_resource_states`, `build_compliant_remediation_plan`), persists every tool call output, and generates a typed `AgentCaseProposal` for each case across cohort tool-calling and batched plan adjudication (`batch_size=65`).
   - Validates every `AgentCaseProposal` through `DeterministicProposalVerifier`:
     - **Schema & Phase Rules:** Validates allowed statuses (`COMPLETE`, `INCOMPLETE`, `NOT_APPLICABLE`), legal operation/phase/state triples, and canonical 4-key step ordering (`FINDING` -> `REMEDIATION` -> `VERIFICATION`).
     - **Manifest & Temporal Cutoffs:** Confirms every cited `evidence_id` exists in `dataset/evidence_files.csv` and satisfies `captured_at <= audit_at`.
     - **Semantic Proof Rules:** Confirms every `COMPLETE` verification step cites an observation (or scoped absence report) proving its target state (`is_target_state_proven`), every `INCOMPLETE` finding cites `PRESENT`/`ACTIVE` violation evidence, and future remediation/verification steps use `evidence_id=""`.
     - **Policy Completeness & Fallback:** Accepts validated proposals into `output.csv`; any invalid or unverified proposal (or offline run via `--offline`) is rejected with a traceable per-case reason (`invalid_evidence_id`, `future_evidence`, `state_mismatch`, `schema_violation`, `malformed_model_json`, `model_call_error`, or `offline_mode_no_live_llm`) and falls back to the deterministic engine (`AuditEngine`). All per-case outcomes and `AgentInfluenceSummary` metrics are persisted in `code/cache/agent_decisions.json`.

### Evaluation, Metering & Evidence-Gap Summary

Complete evaluation metrics, AI influence statistics, custom synthetic cases, and real metered token/cost breakdowns are written to both [`code/evaluation/evaluation_report.md`](./code/evaluation/evaluation_report.md) and [`evaluation/evaluation_report.md`](./evaluation/evaluation_report.md) (and [`code/evaluation/usage_report.md`](./code/evaluation/usage_report.md) / [`evaluation/usage_report.md`](./evaluation/usage_report.md)):

- **Full 518-Case Run (`dataset/deletion_requests.csv` -> `output.csv` & `dataset/output.csv`):** 518 rows (`COMPLETE=152`, `INCOMPLETE=356`, `NOT_APPLICABLE=10`), SHA-256 `1740be44af3d597ea111b9da3094e91e2112efa81cd4c75ea57c996cfc52beac`, 0 schema violations, 0 future (`> audit_at`) citations, 0 unproven `COMPLETE` verification steps, 21/21 automated sanity checks passed, 518/518 AI proposals evaluated and verified (`11/11` PNGs verified, `5/5` TXT+PDF documents analyzed, `375` unique request texts classified, `8` tool calls persisted), and 100% deterministic across live and offline reruns.
- **Metered AI Token & Cost Summary:**
  - **Current 518-Case Agent Run (`__full_518_audit__`):** `39` calls (`11` `qwen3-vl-plus` + `28` `qwen3.7-max`), `161,741` tokens (`140,936` input / `20,805` output), `$0.434657` USD (`$0.00083911` / request).
  - **Phase 4 Two-Pass Vision Setup (`phase4-extraction`):** `22` calls (`qwen3-vl-plus`), `58,486` tokens (`50,784` input / `7,702` output), `$0.022480` USD.
  - **Combined Total:** `61` calls, `220,227` tokens (`425.15` avg tokens / request), `$0.457137` USD (`$0.00088250` / request).
- **Public 32-Case Sample (`dataset/sample_deletion_requests.csv`):** **100.00% (`32/32`)** status accuracy, **93.75% (`30/32`)** exact sequence accuracy, **99.48%** step-set F1, **97.58%** overall field accuracy, with **zero sample-specific hardcoding** (verified by `code/tests/test_p1_hardcode_guard.py`).
- **Documented Sample Evidence Gap (`case_18` & `case_20`):** The only 2 sample sequence diffs are `case_18` (`audit_record_6645` at gold step 11) and `case_20` (`audit_record_5569` at gold step 7). Neither identifier exists anywhere in `dataset/` (`evidence_94` capped at `target_count=28` point-in-time queries). Per `AGENTS.md` §4.3 and §6.7, gold-only identifiers are never fabricated or hardcoded; see [`docs/findings/phase_07_sample_evidence_gap.md`](./docs/findings/phase_07_sample_evidence_gap.md) and `evaluation_report.md` for the step-by-step comparison and root-cause analysis.
- **Custom Synthetic Evaluation Cases:** **100.00% (`4/4`)** status & sequence accuracy on the 4 standalone custom synthetic cases (`case_synth_01`–`case_synth_04`) and **100.00% (`6/6`)** on the 6 synthetic regression fixtures (`syn_01`–`syn_06`).

---

## Dataset

All participant-facing files are in `dataset/`:

| File | Contents |
| --- | --- |
| `deletion_requests.csv` | 518 requests |
| `sample_deletion_requests.csv` | 32 sample requests |
| `sample_output.csv` | Correct sample answers |
| `user_identities.csv` | Current user identities |
| `user_audit_log.csv` | Historical identity changes |
| `system_activity.csv` | Activity across services and data processes |
| `deletion_rules.csv` | Required treatment for each data category |
| `evidence_files.csv` | Manifest of supplied evidence files |
| `output.csv` | Populated 518-row output file |

Evidence is stored under `dataset/evidence/` and may include PDFs, images, logs, JSON, plain text, or SQL snapshot exports. SQL captures may contain a primary database, regional replicas, a reporting replica, or a failover replica so replication drift can be investigated directly. The `.sql` files are readable as text and executable with SQLite.

Only `deletion_requests.csv` requires answers. The other files provide evidence and context.

---

## Output

Create `output.csv` with these columns in this exact order:

```text
case_id,deletion_status,steps_json
```

Produce exactly one row per request. `deletion_status` is `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`. `steps_json` is an ordered JSON array containing findings, remediation actions, and verification checks. Use an empty array (`[]`) for `NOT_APPLICABLE`. Evidence references may be a `file_id`, `activity_id`, or `audit_id`. Determine the resource state at `audit_at` from the available evidence; reported workflow statuses and operation results are claims. Use `dataset/sample_output.csv` as the format reference.

The final file must contain 518 data rows sorted by `case_id` (plus the header row). The grader parses `steps_json` as JSON, so object-key order and whitespace do not matter; array order does. Order findings, remediation, and verification in that phase order. Within a phase, follow the operation order in the problem statement, then sort by `system_id` and `resource_id`.

---

## Evaluation

`output.csv` will be compared with hidden canonical answers. Scoring considers:

- deletion assessment accuracy;
- current and historical identity resolution;
- discovery of remaining data and recreation risks;
- correct policy application and evidence references; and
- completeness and ordering of remediation and verification steps.

Your `code.zip` must include:

```text
code/evaluation/evaluation_report.md
code/evaluation/usage_report.md
evaluation/evaluation_report.md
evaluation/usage_report.md
```

- `evaluation_report.md` must cover case, row, field, and sequence accuracy, at least three additional evaluation cases created by you, failures found, and improvements made.
- `usage_report.md` must cover the final full-dataset run, including model providers and names, model calls, input and output tokens, total and average tokens per request, and estimated total and per-request cost. Include per-model and overall totals when using multiple models.

---

## Chat Transcript

This repository includes [`AGENTS.md`](./AGENTS.md), which instructs compatible AI coding tools to append conversation summaries to `log.txt` in the repository root:

| Platform | Path |
| --- | --- |
| macOS / Linux | `<repo root>/log.txt` |
| Windows | `<repo root>\log.txt` |

- Always launch your AI coding agent from the repository root (or explicitly ask it to read `./AGENTS.md` first) so every turn is logged to `log.txt` with the required `User Prompt`, `Agent Response Summary`, `Actions`, and `Context` sections.
- Upload `log.txt` directly as your `chat_transcript` submission on HackerRank.
- Do not include API keys, tokens, credentials, or secrets in prompts, code, configuration, or `log.txt`.

---

## Packaging `code.zip` and Submission

| Item | Description |
| --- | --- |
| `code.zip` | Runnable solution (`code/src/core/`, `code/src/`, `code/prompts/`, etc.), configuration, `README.md`, and `evaluation/` reports |
| `output.csv` | One answer row for each of the 518 requests in `dataset/deletion_requests.csv` |
| `chat_transcript` | The root `log.txt` file generated by your coding agent |
| AI interview | Live explanation of your architecture, approach, and evaluation |

To package `code.zip` from the repository root without bundling the dataset or secrets:

**macOS / Linux:**

```bash
zip -r code.zip README.md code evaluation .pricing.json .env.example -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/node_modules/*" "*/.git/*" "*/.DS_Store" "code/cache/*"
```

**Windows (PowerShell):**

```powershell
Get-ChildItem -Path code -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Remove-Item -Path code\cache\parsed_evidence.json -Force -ErrorAction SilentlyContinue
Compress-Archive -Path README.md, code, evaluation, .pricing.json, .env.example -DestinationPath code.zip -Force
```
