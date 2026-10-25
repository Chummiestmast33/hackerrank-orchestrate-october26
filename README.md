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

### 2. Run the Deletion-Audit Agent

Run the Python entry point from the repository root:

```bash
python3 code/main.py
```

The first run automatically builds `code/cache/parsed_evidence.json` from `dataset/evidence_files.csv` using deterministic parsers (`SQL`, `JSON`, `LOG`, `TXT`, `PDF`) and the committed offline transcription store `code/data/multimodal_transcriptions.json`. No API key or network access is required at runtime (0 model calls, \$0.000000 runtime cost). The cache is gitignored and excluded from `code.zip`; it is rebuilt automatically on a clean checkout.

Useful options:

```bash
python3 code/main.py --sample
python3 code/main.py --sample --diff
python3 code/main.py --rebuild-cache
python3 code/main.py --cache /tmp/parsed_evidence.json
python3 code/evaluation/full_run.py
python3 -m pytest code/tests -q
```

The blank template at `dataset/output.csv` is provided as a reference. Your final generated file for submission must be the root-level `output.csv`.

---

## Solution Architecture

The solution in `code/` implements a **two-stage deterministic deletion-audit architecture** with strict temporal cutoff enforcement (`captured_at <= audit_at`) and 100% reproducibility:

1. **Stage 1 — Evidence Ingestion & Offline Cache Bootstrap (`code/src/loaders/`, `code/src/parsers/`):**
   - `cache_bootstrap.py` validates `code/cache/parsed_evidence.json` against `PARSER_VERSION = "phase4-v2"` and all 94 files in `dataset/evidence_files.csv` (extracting 2,912 structured `EvidenceObservation` records with 0 parse errors).
   - Dedicated parsers handle SQLite snapshot dumps (`sql_parser.py` across `primary`, `eu_replica`, `us_replica`, `reporting_replica`, and `failover_replica`), structured JSON exports (`json_parser.py`), operational/sync/backup logs (`log_parser.py`), plain-text notes (`txt_parser.py`), PDF documents (`pdf_parser.py`), and PNG screenshots (`png_parser.py` backed by the committed offline transcription store `code/data/multimodal_transcriptions.json`).

2. **Stage 2 — Seven-Module Core Audit Engine (`code/src/core/`):**
   - **`IntentClassifier` (`intent_classifier.py`):** Deterministic multilingual classifier supporting 9+ languages (EN, ES, PT, FR, DE, JA, KO, AR, ZH) that distinguishes authorized deletion requests from access, export, correction, marketing opt-out, or account pause requests (`NOT_APPLICABLE` -> `steps_json=[]`).
   - **`IdentityResolver` (`identity_resolver.py`):** Case-insensitive email/identifier normalization joining `dataset/user_identities.csv` and historical mutations in `dataset/user_audit_log.csv` (filtered to `changed_at <= audit_at`) to recover current and historical emails, names, phones, and SHA-256 email hashes.
   - **`WorkflowResolver` (`workflow_resolver.py`):** Reconstructs active data flows (`SYNC_DELETION`, `SYNC_REPLICA`, `EXPORT_GENERATE`, `SEARCH_INDEX_SYNC`, `ANALYTICS_LOAD`) and backup/restore risks (`BACKUP_RESTORE`, `SNAPSHOT_CREATE`, `ARCHIVE_RETENTION`) from `system_activity.csv` and parsed evidence at `audit_at`.
   - **`InventoryBuilder` (`inventory_builder.py`) & `StateReconstructor` (`state_reconstructor.py`):** Matches resources across all systems to the subject's `IdentityGraph`, enforces the `audit_at` cutoff, detects SQL replica drift (`eu_replica`, `us_replica`, `reporting_replica`, `failover_replica`), and reconciles workflow claims against concrete file/audit/activity evidence.
   - **`RulesEngine` (`rules_engine.py`):** Applies `dataset/deletion_rules.csv` (`DELETE`, `REDACT`, `ANONYMIZE`, `RETAIN`, `ACCOUNT_TOMBSTONE`), verifying that tombstones retain only `user_id` while stripping `name`, `email`, `phone`, and `email_hash`, and that policy-retained records (`order_service`, `payment_service`, `security_service`) remain `PRESENT`.
   - **`PlannerSorter` (`planner_sorter.py`):** Orders `FINDING`, `REMEDIATION` (`DISABLE_DATA_FLOW` and `BLOCK_RESTORE` before record mutations), and `VERIFICATION` steps by canonical phase, operation priority, `system_id`, and `resource_id` with consecutive `step_no` starting at `1`.

### Evaluation & Evidence-Gap Summary

Complete evaluation metrics, custom synthetic cases, and token/cost breakdowns are written to both [`code/evaluation/evaluation_report.md`](./code/evaluation/evaluation_report.md) and [`evaluation/evaluation_report.md`](./evaluation/evaluation_report.md) (and [`code/evaluation/usage_report.md`](./code/evaluation/usage_report.md) / [`evaluation/usage_report.md`](./evaluation/usage_report.md)):

- **Full 518-Case Run (`dataset/deletion_requests.csv` -> `output.csv`):** 518 rows (`COMPLETE=157`, `INCOMPLETE=354`, `NOT_APPLICABLE=7`), 3,166 total steps, 1,139 grounded evidence citations, 0 future (`> audit_at`) citations, 18/18 automated sanity checks passed, 100% deterministic across independent runs, 0 runtime model calls.
- **Public 32-Case Sample (`dataset/sample_deletion_requests.csv`):** **100.00% (`32/32`)** status accuracy, **93.75% (`30/32`)** exact sequence accuracy, **99.48%** step-set F1, **97.58%** overall field accuracy.
- **Documented Sample Evidence Gap (`case_18` & `case_20`):** The only 2 sample sequence diffs are `case_18` (`audit_record_6645` at gold step 11) and `case_20` (`audit_record_5569` at gold step 7). Neither identifier exists anywhere in `dataset/` (`evidence_94` capped at `target_count=28` point-in-time queries). Per `AGENTS.md` §4.3 and §6.7, gold-only identifiers are never fabricated or hardcoded; see [`docs/findings/phase_07_sample_evidence_gap.md`](./docs/findings/phase_07_sample_evidence_gap.md) and `evaluation_report.md` §5 for the step-by-step comparison and root-cause analysis.
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
| `output.csv` | Blank output template |

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
```

- `evaluation_report.md` must cover case, row, field, and sequence accuracy, at least three additional evaluation cases created by you, failures found, and improvements made.
- `usage_report.md` must cover the final full-dataset run, including model providers and names, model calls, input and output tokens, total and average tokens per request, and estimated total and per-request cost. Include per-model and overall totals when using multiple models.

**Important:** Place `evaluation_report.md` and `usage_report.md` inside `code/evaluation/` (matching `code/evaluation/main.py` in this starter layout), write your complete evaluation metrics, custom evaluation test cases, and token/cost breakdowns directly inside those Markdown files, and keep prompts in source code or Markdown files. Automated code evaluation ignores raw data files (`.csv`, `.tsv`, `.json`, `.jsonl`, `.sql`, `.log`), so content stored only in those formats will not be visible to the code judge or AI interviewer.

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
| `code.zip` | Runnable solution, prompts, configuration, `README.md`, and `evaluation/` reports |
| `output.csv` | One answer row for each of the 518 requests in `dataset/deletion_requests.csv` |
| `chat_transcript` | The root `log.txt` file generated by your coding agent |
| AI interview | Live explanation of your architecture, approach, and evaluation |

You may use any programming language, model, framework, or retrieval approach. Include clear setup and execution instructions in `README.md` inside `code.zip`.

To package `code.zip` from the repository root without bundling the dataset:

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

When packaging `code.zip`:

- Keep your evaluation reports in `code/evaluation/` so they are bundled automatically with `code` (or add `evaluation` to the archive command above if you placed them in a top-level `evaluation/` directory).
- Do **not** include `dataset/`, virtual environments (`.venv`, `venv`, `node_modules`), or build caches (`__pycache__`, `code/cache`). On Windows, keep `.venv` at the repository root (outside `code/`) and remove any `code/__pycache__` folders and `code/cache` before running `Compress-Archive`.
- Do include the committed offline transcription store at `code/data/multimodal_transcriptions.json`; it is required to decode PNG evidence without model calls.
- Do **not** include nested archives (`.zip`, `.tar`, `.gz`, `.tgz`, `.7z`, `.rar`) inside `code.zip` — submissions containing nested archive files will be rejected.

Before submitting, confirm that:

- `output.csv` has the exact header `case_id,deletion_status,steps_json` and contains all 518 data rows sorted by `case_id`;
- every `steps_json` value is a valid JSON array with consecutive step numbers starting at `1`;
- findings cite valid evidence IDs, and `COMPLETE` verification steps cite evidence proving the current state;
- proposed remediation and future verification steps use an empty `evidence_id` (`""`);
- `code.zip` includes your runnable code, `README.md`, `code/evaluation/evaluation_report.md`, and `code/evaluation/usage_report.md`;
- `log.txt` follows the `AGENTS.md` turn format and is uploaded to the `chat_transcript` slot; and
- no API keys, credentials, real personal data, or sensitive configuration values are included.
