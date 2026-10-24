# MASTER TECHNICAL SPECIFICATION: Deletion Audit Agent (Northstar Shop)

## 1. System Overview & Core Objective
Build a deterministic-first, AI-assisted **Deletion Audit Agent** that audits 518 data deletion requests (`dataset/deletion_requests.csv`) against multi-format system evidence (`dataset/evidence/`) and policy rules (`dataset/deletion_rules.csv`), producing `dataset/output.csv` (and/or root `output.csv`), `evaluation/evaluation_report.md`, and `evaluation/usage_report.md`.

### Core Architectural Principle: "Index Everything Once, Audit Deterministically"
Do NOT use an LLM in a per-case tool-calling loop over the 94 evidence files.
Instead:
1. **Stage 1 (Static Evidence Indexing):** Parse all 94 evidence files (`.sql`, `.json`, `.log`, `.txt`, `.pdf`, `.png`) ONCE into a unified in-memory relational index (and cache the parsed output of the 4 PDFs and 11 PNGs to disk as JSON).
2. **Stage 2 (Deterministic Case Execution):** Resolve all 518 cases deterministically in seconds using the in-memory index, using the LLM only for:
   - One-time OCR/VLM structured extraction of the 11 PNG console screenshots (and 4 PDFs if text extraction requires structure).
   - Batched intent classification of `request_text` for `NOT_APPLICABLE` detection (with strict prompt-injection isolation).

### Verified Evidence Inventory (`dataset/evidence_files.csv`, 94 rows)

| Folder | Ext | Count | File families (count) | Captured range |
|---|---|---|---|---|
| `databases/` | `.sql` | 24 | `customer_data_inventory_*` (11), `customer_data_read_replica_*` (5), `customer_data_regional_replicas_*` (3), `customer_data_reporting_replica_*` (2), `customer_data_failover_replica_20260920` (1), `customer_accounts_failover_replica_20260902` (1), `customer_search_primary_20260910` (1) | 2026-02-08 → 2026-09-21 |
| `records/` | `.json` | 28 | `customer_data_snapshot_bundle_*` (12), `service_resource_export_*` (11), `connector_configurations_20260812`, `customer_export_manifest_20260409`, `security_audit_ledger_20261001`, `customer_analytics_report_20260907`, `customer_export_jobs_20260914` | 2026-01-29 → 2026-10-01 |
| `records/` | `.txt` | 1 | `customer_account_handover_20261001` (`evidence_03`) | 2026-10-01 |
| `logs/` | `.log` | 26 | `resource_lookup_trace_*` (11), `service_events_*` (2), `structured_service_events_*` (2), `syslog_archive_*` (2), `application_trace_*` (2), `operations_stream_*` (2), `cloud_runtime_export_*` (2), `notification_delivery_20260315`, `search_index_diagnostic_20260906`, `support_replica` | 2026-02-03 → 2026-09-30 |
| `documents/` | `.pdf` | 4 | `evidence_18`, `evidence_27`, `evidence_55`, `evidence_58` | — |
| `images/` | `.png` | 11 | `evidence_04`, `09`, `14`, `19`, `23`, `28`, `32`, `37`, `42`, `46`, `60` | — |

> Dates come from file names; the authoritative capture time is `captured_at` in `evidence_files.csv`. `sample_output.csv` contains 10 `COMPLETE` and 22 `INCOMPLETE` cases and **no** `NOT_APPLICABLE` cases.

---

## 2. Final Repository Structure

```text
code/
├── main.py                          # Main CLI entry point (runs full pipeline & writes output.csv)
├── requirements.txt                 # Dependencies (pandas/polars, pypdf, pdfplumber, openai/anthropic/google-genai, pytest)
├── README.md                        # Setup, architecture, run, and evaluation instructions
├── cache/
│   ├── multimodal_evidence.json     # Cached structured extraction of the 11 PNGs & 4 PDFs
│   └── intent_classifications.json  # Cached intent decisions for deletion_requests
├── src/
│   ├── __init__.py
│   ├── config.py                    # Paths, model names, pricing table, sorting rank constants
│   ├── models.py                    # Dataclasses: IdentityGraph, ResourceItem, EvidenceObservation, AuditStep
│   ├── loaders/
│   │   ├── csv_loader.py            # Loads all CSVs (requests, identities, audit_log, activity, rules, evidence_files)
│   │   ├── sql_parser.py            # Loads .sql files into in-memory SQLite & extracts observations + snapshot_scope
│   │   ├── json_txt_parser.py       # Parses records/*.json and records/*.txt (shift handovers, bundles, exports)
│   │   ├── log_parser.py            # Parses logs/*.log (resource_lookup_trace, service_events, syslog, cloud_runtime_export, support_replica, ...)
│   │   └── multimodal_parser.py     # Extracts documents/*.pdf and images/*.png (with disk caching & token metering)
│   ├── core/
│   │   ├── intent_classifier.py     # Hybrid deterministic + LLM batch classifier (anti-prompt-injection)
│   │   ├── identity_resolver.py     # Exact case-insensitive email/phone/hash/user_id transitive resolution
│   │   ├── inventory_builder.py     # Discovers all (system_id, resource_id, data_category) per user
│   │   ├── state_reconstructor.py   # Finds latest observation <= audit_at per resource & cites evidence_id
│   │   ├── rules_engine.py          # Evaluates observed state vs deletion_rules.csv
│   │   └── planner_sorter.py        # Builds FINDING, REMEDIATION, VERIFICATION steps & applies 4-key canonical sort
│   └── evaluation/
│       ├── evaluator.py             # Computes accuracy metrics vs sample_output.csv + runs 3 synthetic test cases
│       └── metering.py              # Tracks model calls, input/output tokens, and costs -> writes usage_report.md
├── evaluation/
│   ├── main.py                      # Entry point to run evaluation suite and generate reports
│   ├── evaluation_report.md         # Auto-generated accuracy & error analysis report
│   └── usage_report.md              # Auto-generated token usage and cost report for the 518-case run
└── tests/
    ├── test_identity.py
    ├── test_parsers.py
    ├── test_rules_planner.py
    └── test_synthetic_cases.py

```

---

## 3. Business Rules & Domain Logic (Exact Specification)

### Rule 1: Identity Resolution (`identity_resolver.py`)

* **Normalization:** Match emails case-insensitively (`email.strip().lower()`), because evidence files contain uppercase emails (e.g., `CHOI.JIHOON94@GMAIL.COM`, `JULES-LAURENT@PROTON.ME`). Do NOT use fuzzy/substring matching (to avoid false matches on similar emails like `case_28`).
* **Transitive Lookup:**
1. Given `request.email`, look up `user_identities.csv` by normalized `email`.
2. If not found in `user_identities.csv` (because the user changed their email prior to deletion, as in `case_10`), search `user_audit_log.csv` where `field_name == 'email'` and `old_value` or `new_value` matches `request.email` to find `user_id`.
3. Once `user_id` is known, collect all current identifiers from `user_identities.csv` (`user_id`, `name`, `email`, `phone`, `email_hash`) AND all historical `old_value` and `new_value` entries for that `user_id` from `user_audit_log.csv` (where `event_time <= audit_at`).
4. Compute SHA-256 hex digests of any historical emails if needed to match `email_hash` fields.



### Rule 2: Resource Inventory Discovery (`inventory_builder.py`)

A resource `(system_id, resource_id)` belongs to the user if ANY of the following hold (for events/captures `<= audit_at`):

1. `system_activity.csv` links the `resource_id` to any identifier in the user's `IdentityGraph` (via `LINK_RESOURCE_IDENTITY` or details/resource_id references).
2. Any evidence file (`<= audit_at`) contains a record for `resource_id` whose `customer_reference`, `subject_reference`, `email`, `requester_email`, `owner_email`, `customer_email`, `phone`, `email_hash`, or `lookup_key` matches any identifier in the user's `IdentityGraph`.
3. **Crucial Anonymized/Deleted Link Rule:** Once a `resource_id` (e.g., `analytics_9406`, `account_7566`, `support_6334`) is linked to the user via `system_activity.csv` or an earlier snapshot, we MUST look up that exact `resource_id` in newer evidence files (`<= audit_at`) even when its `email` and `customer_reference` have been set to `null` (anonymized/redacted) or when it returns `404` / `NOT_FOUND` (deleted).

### Rule 3: Evidence Parsing & State Reconstruction (`state_reconstructor.py`)

Only consider evidence files from `evidence_files.csv` where `captured_at <= request.audit_at` (and `system_activity.csv` events where `event_time <= request.audit_at`).
Never trust `reported_status` in `deletion_requests.csv` or `reported_result` in `system_activity.csv` as proof of completion—they are claims.

#### How Each Evidence Format Encodes State:

1. **Readback Logs (`resource_lookup_trace_*.log`):**
* Pair `*_started` and `*_completed` lines by `trace_id` and `resource_id`.
* `account_service`: `rows=0 http_status=404` -> `ABSENT`. If `rows=1` or profile fields present -> `PRESENT` (or `REDACTED` if tombstone with only `user_id`).
* `integration_service`: `enabled=false` -> `DISABLED`; `enabled=true` -> `ACTIVE`.
* `backup_service`: `restore_allowed=false` -> `BLOCKED`; `restore_allowed=true` -> `ACTIVE`.
* `search_service`: `result=hit` / `total_hits=1` -> `PRESENT`; `total_hits=0` / `miss` -> `ABSENT`.
* `support_platform`: if `requester_name`, `requester_email`, `requester_phone` are not all null -> `PRESENT` (with exposed PII); if all direct PII fields are null/redacted -> `REDACTED`.
* `security_service`: `rows=1` with `subject_reference=user_XX` and `retention_until` -> `PRESENT`.
* `analytics_platform`: if `email`/`phone`/`email_hash`/`customer_reference` are all null -> `ANONYMIZED`; otherwise `PRESENT` (exposed PII).


2. **Shift Handover Text (`customer_account_handover_20261001.txt` - `evidence_03`):**
* Format: `- <timestamp> | <system_id> | <resource_id> | <data_category> | <status> | <identifier_info>`
* Status mapping:
* `NOT_FOUND` -> `ABSENT`
* `IDENTIFIABLE` -> `PRESENT` (Exposed PII)
* `ANONYMIZED` -> `ANONYMIZED`
* `REDACTED` -> `REDACTED`
* `ACTIVE` -> `ACTIVE`
* `BLOCKED` -> `BLOCKED`
* `DISABLED` -> `DISABLED`
* `PRESENT` / `FOUND` / `RETAINED` -> `PRESENT`




3. **Service Resource Exports (`service_resource_export_*.json` & `customer_data_snapshot_bundle_*.json`):**
* `account_service.profile_lookups`: `status_code == 404` or `profile is None` -> `ABSENT`.
* `analytics_platform.profiles`: if `customer_reference`, `email`, `email_hash`, `phone` are all `null` -> `ANONYMIZED`; else `PRESENT` (Exposed PII).
* `backup_service.restore_entries`: `restore_allowed == True` -> `ACTIVE` (`REPORT_RESTORE_RISK`); `restore_allowed == False` -> `BLOCKED`.
* `integration_service.connectors`: `enabled == True` -> `ACTIVE` (`REPORT_ACTIVE_DATA_FLOW`); `enabled == False` -> `DISABLED`.
* Check all other keys (`search_service`, `support_platform`, `export_service`, `security_service`, `marketing_platform`, etc.) following the same null-PII vs present-PII logic.


4. **SQLite Database Snapshots (`*.sql`):**
* Execute the `.sql` script into an in-memory `sqlite3` connection.
* **Explicit Presence:** If a row exists in `customer_profiles`, `customer_search_documents`, `customer_analytics_profiles`, `support_records`, `customer_exports`, `connector_subscriptions`, `backup_restore_entries`, or `security_audit_records`, evaluate its columns:
* `customer_analytics_profiles`: if `customer_reference`, `email`, `phone`, `email_hash` are all `NULL` -> `ANONYMIZED`; else `PRESENT` (Exposed PII).
* `support_records`: if `requester_name`, `requester_email`, `requester_phone` are all `NULL` -> `REDACTED`; else `PRESENT`.
* `connector_subscriptions`: `enabled == 1` -> `ACTIVE`; `enabled == 0` -> `DISABLED`.
* `backup_restore_entries`: `restore_allowed == 1` -> `ACTIVE`; `restore_allowed == 0` -> `BLOCKED`.
* `security_audit_records`: row exists -> `PRESENT`.


* **Implicit Absence via `snapshot_scope`:** If a resource belonging to `system_X` (known from the user's inventory) is NOT present in the corresponding table of the SQL snapshot, AND `system_X` is listed in `snapshot_scope` (or the SQL file is a dedicated replica for `system_X`, like `customer_accounts_failover_replica_20260902.sql` for `account_service`), then that SQL file proves the resource state is `ABSENT` at `captured_at`!



### Rule 4: Policy Mapping (`deletion_rules.csv` -> Operations)

For every resource in the user's inventory, compare its latest observed state (`<= audit_at`) against the required policy treatment:

| Resource Type / Category | Required Target State | Violation Condition | FINDING Operation & State | REMEDIATION Operation & State | VERIFICATION Operation & State |
| --- | --- | --- | --- | --- | --- |
| `USER_PROFILE`, `SECONDARY_IDENTIFIER`, `SEARCH_INDEX_ENTRY`, `CACHE_ENTRY`, `USER_EXPORT`, `MARKETING_PROFILE`, `SUPPORT_ATTACHMENT` (single-subject) | `ABSENT` | Observed `PRESENT` | `REPORT_REMAINING_RECORD` (`PRESENT`) | `DELETE_RECORD` (`ABSENT`) | `VERIFY_RECORD_ABSENT` (`ABSENT`) |
| `SUPPORT_MESSAGE` (shared context), `EMAIL_DELIVERY_LOG`, `ACCOUNT_TOMBSTONE` | `REDACTED` | Observed `PRESENT` with direct PII (`name`, `email`, `phone`, `email_hash`) | `REPORT_EXPOSED_PII` (`PRESENT`) | `REDACT_RECORD` (`REDACTED`) | `VERIFY_RECORD_REDACTED` (`REDACTED`) |
| `ANALYTICS_PROFILE`, `PRODUCT_TELEMETRY` | `ANONYMIZED` | Observed `PRESENT` with any user link/PII (unless rule requires `DELETE_RECORD`) | `REPORT_EXPOSED_PII` (`PRESENT`) | `ANONYMIZE_RECORD` (`ANONYMIZED`) | `VERIFY_RECORD_ANONYMIZED` (`ANONYMIZED`) |
| `SECURITY_AUDIT_LOG`, `LEGAL_HOLD_RECORD` | `PRESENT` | Must remain `PRESENT` (and without unauthorized PII) | (If PII exposed: `REPORT_EXPOSED_PII`) | (If PII exposed: `REDACT_RECORD`) | `VERIFY_RECORD_PRESENT` (`PRESENT`) |
| `data_flow_*` (`integration_service`) | `DISABLED` | Observed `ACTIVE` (`enabled=true`) | `REPORT_ACTIVE_DATA_FLOW` (`ACTIVE`) | `DISABLE_DATA_FLOW` (`DISABLED`) | `VERIFY_DATA_FLOW_DISABLED` (`DISABLED`) |
| `backup_*` (`backup_service`) | `BLOCKED` | Observed `ACTIVE` (`restore_allowed=true`) | `REPORT_RESTORE_RISK` (`ACTIVE`) | `BLOCK_RESTORE` (`BLOCKED`) | `VERIFY_RESTORE_BLOCKED` (`BLOCKED`) |

*(Note: Check `case_12` where `analytics_9914` uses `REPORT_REMAINING_RECORD` + `DELETE_RECORD` + `VERIFY_RECORD_ABSENT`. Inspect `evidence_01` and `system_activity.csv` for `analytics_9914` to see the exact event/category that triggers `DELETE_RECORD` vs `ANONYMIZE_RECORD` on `analytics_platform`!)*

### Rule 5: Plan Construction & Evidence Citation Rules

1. **If `NOT_APPLICABLE`:**
* `deletion_status = "NOT_APPLICABLE"`
* `steps_json = "[]"`


2. **If zero violations exist across all user resources:**
* `deletion_status = "COMPLETE"`
* Generate ONLY `VERIFICATION` steps for all relevant resources in the user's inventory (note: inactive `data_flow` or `backup` that were already disabled/blocked and never violated may or may not be included—verify against `sample_output.csv` cases `case_01` to `case_04` and `case_21`).
* Every `VERIFICATION` step in a `COMPLETE` case MUST cite the `evidence_id` (e.g., `"evidence_54"`, `"evidence_94"`).


3. **If 1 or more violations exist:**
* `deletion_status = "INCOMPLETE"`
* **Phase 1 (`FINDING`):** One step per violating resource. `evidence_id` MUST be the actual `file_id` (or `activity_id`/`audit_id`) proving the violation.
* **Phase 2 (`REMEDIATION`):** One step per violating resource with the corrective action. `evidence_id` MUST be `""` (empty string).
* **Phase 3 (`VERIFICATION`):** One step for **EVERY** resource in the user's active audit scope (both the resources that had violations AND the resources that were already compliant, such as `account_service` already `ABSENT` and `security_service` `audit_record_*` `PRESENT`). `evidence_id` MUST be `""` (empty string) for ALL verification steps in an `INCOMPLETE` case.



### Rule 6: Canonical 4-Key Sorting

Sort the `steps` list before assigning `step_no = 1, 2, ...`:

```python
PHASE_ORDER = {"FINDING": 1, "REMEDIATION": 2, "VERIFICATION": 3}

OP_ORDER = {
    # FINDING
    "REPORT_REMAINING_RECORD": 1,
    "REPORT_EXPOSED_PII": 2,
    "REPORT_ACTIVE_DATA_FLOW": 3,
    "REPORT_RESTORE_RISK": 4,
    # REMEDIATION
    "DISABLE_DATA_FLOW": 1,
    "BLOCK_RESTORE": 2,
    "DELETE_RECORD": 3,
    "REDACT_RECORD": 4,
    "ANONYMIZE_RECORD": 5,
    # VERIFICATION
    "VERIFY_RECORD_ABSENT": 1,
    "VERIFY_RECORD_PRESENT": 2,
    "VERIFY_RECORD_REDACTED": 3,
    "VERIFY_RECORD_ANONYMIZED": 4,
    "VERIFY_DATA_FLOW_DISABLED": 5,
    "VERIFY_RESTORE_BLOCKED": 6,
}

steps.sort(key=lambda s: (
    PHASE_ORDER[s.phase],
    OP_ORDER[s.operation],
    s.system_id,
    s.resource_id
))

```

---

## 4. Step-by-Step Implementation To-Do List

### Phase 1: Deep Inspection & Ground-Truth Alignment (First 30 mins)

* [ ] **Task 1.1:** Write a quick exploration script to inspect all 32 rows of `dataset/sample_deletion_requests.csv` alongside `dataset/sample_output.csv`.
* [ ] **Task 1.2:** Inspect the remaining log/JSON formats referenced in `sample_output.csv`, specifically:
* `evidence_01` (`service_events_ap_south_20260915.log`) — used in `case_12`, `case_15`, `case_17`, `case_19`.
* `evidence_54` (`customer_accounts_failover_replica_20260902.sql`), `evidence_56` (`customer_analytics_report_20260907.json`), `evidence_57` (`customer_search_primary_20260910.sql`), `evidence_59` (`customer_export_jobs_20260914.json`), `evidence_61` (`support_replica.log`).
* Check why `case_12` (`analytics_9914`) uses `DELETE_RECORD` instead of `ANONYMIZE_RECORD`.
* Check how `NOT_APPLICABLE` cases look in `sample_deletion_requests.csv` and `system_activity.csv`.



### Phase 2: Build the Evaluation & Metering Harness First (TDD)

* [ ] **Task 2.1:** Implement `src/evaluation/metering.py` to wrap any LLM/VLM calls, logging provider, model name, call count, input tokens, output tokens, and cost to a local JSONL log, with a method to render `evaluation/usage_report.md`.
* [ ] **Task 2.2:** Implement `src/evaluation/evaluator.py` to compare any generated DataFrame against `dataset/sample_output.csv` and compute:
* Case-level `deletion_status` accuracy (%).
* Step-level exact match accuracy (%).
* Field-level accuracy (`phase`, `system_id`, `resource_id`, `operation`, `state`, `evidence_id`).
* Sequence accuracy (exact ordered array match).
* Diff printer showing exact mismatches per `case_id`.



### Phase 3: Build Deterministic Evidence Parsers (Structured Files)

* [ ] **Task 3.1:** Implement `src/loaders/csv_loader.py` to load all CSV manifests.
* [ ] **Task 3.2:** Implement `src/loaders/sql_parser.py` using Python's built-in `sqlite3` (`:memory:`) to parse all 24 `.sql` files (`customer_data_read_replica_*` ×5, `customer_data_regional_replicas_*` ×3, `customer_data_reporting_replica_*` ×2, `customer_data_failover_replica_20260920` + `customer_accounts_failover_replica_20260902`, `customer_search_primary_20260910`, `customer_data_inventory_*` ×11), recording both table rows and `snapshot_scope`.
* [ ] **Task 3.3:** Implement `src/loaders/json_txt_parser.py` to parse all 28 `.json` files (`customer_data_snapshot_bundle_*` ×12, `service_resource_export_*` ×11, `connector_configurations_20260812`, `customer_export_manifest_20260409`, `security_audit_ledger_20261001`, `customer_analytics_report_20260907`, `customer_export_jobs_20260914`) and `customer_account_handover_20261001.txt` (`evidence_03`).
* [ ] **Task 3.4:** Implement `src/loaders/log_parser.py` to parse all 26 `.log` files (`resource_lookup_trace_*` ×11, `service_events_*` ×2, `structured_service_events_*` ×2, `syslog_archive_*` ×2, `application_trace_*` ×2, `operations_stream_*` ×2, `cloud_runtime_export_*` ×2, `notification_delivery_20260315`, `search_index_diagnostic_20260906`, `support_replica.log`).

### Phase 4: One-Time Multimodal Extraction (4 PDFs + 11 PNGs)

* [ ] **Task 4.1:** Implement PDF extraction in `src/loaders/multimodal_parser.py` using `pypdf`/`pdfplumber` for the 4 PDFs (`evidence_18`, `evidence_27`, `evidence_55`, `evidence_58`). Inspect the extracted text directly; if structured tables exist, parse them into `EvidenceObservation` objects.
* [ ] **Task 4.2:** Implement VLM extraction for the 11 PNG images (`evidence_04`, `evidence_09`, `evidence_14`, `evidence_19`, `evidence_23`, `evidence_28`, `evidence_32`, `evidence_37`, `evidence_42`, `evidence_46`, `evidence_60`). Send each image ONCE with a strict JSON schema prompt to extract every row/record visible on the admin console, save to `cache/multimodal_evidence.json`, and log tokens in `metering.py`.

### Phase 5: Core Audit Engine (Identity, Inventory, State, Rules, Planner)

* [ ] **Task 5.1:** Implement `src/core/intent_classifier.py`. Check `system_activity.csv` for `CLASSIFY_REQUEST` events first; for remaining or ambiguous requests, run a batched, prompt-injection-safe LLM classifier and cache results in `cache/intent_classifications.json`.
* [ ] **Task 5.2:** Implement `src/core/identity_resolver.py` (case-insensitive exact matching + historical audit log traversal).
* [ ] **Task 5.3:** Implement `src/core/inventory_builder.py` & `src/core/state_reconstructor.py` (link resources to user, filter evidence `<= audit_at`, pick latest observation per resource, handle `snapshot_scope` implicit absence).
* [ ] **Task 5.4:** Implement `src/core/rules_engine.py` & `src/core/planner_sorter.py` (generate `FINDING`, `REMEDIATION`, `VERIFICATION` steps, apply `evidence_id` citation rules, sort by the 4 canonical keys).

### Phase 6: Sample Validation & 100% Convergence

* [ ] **Task 6.1:** Run the pipeline on `dataset/sample_deletion_requests.csv` (32 cases) and run `evaluator.py`.
* [ ] **Task 6.2:** Debug any discrepancies in status, missing resources, wrong `evidence_id`, or step ordering until achieving **100% accuracy** across all 32 sample cases.
* [ ] **Task 6.3:** Create 3+ synthetic evaluation cases (e.g., historical email chain mutation, tombstone with leaked phone number, active data flow with restore risk) and add them to the evaluation suite to fulfill the `evaluation_report.md` requirement.

### Phase 7: Full 518-Case Run & Final Packaging

* [ ] **Task 7.1:** Run `main.py` on `dataset/deletion_requests.csv` (518 cases) to produce `output.csv`.
* [ ] **Task 7.2:** Run automated sanity checks on `output.csv`:
* Exactly 518 data rows + 1 header row (`case_id,deletion_status,steps_json`).
* Sorted by `case_id`.
* Every `steps_json` parses as valid JSON.
* `NOT_APPLICABLE` rows have `[]`.
* `COMPLETE` rows have only `VERIFICATION` steps with non-empty `evidence_id`.
* `INCOMPLETE` rows have non-empty `evidence_id` ONLY on `FINDING` steps and `""` on `REMEDIATION` and `VERIFICATION` steps.
* `step_no` starts at `1` and increments by `1`.


* [ ] **Task 7.3:** Generate final `evaluation/evaluation_report.md` and `evaluation/usage_report.md`.
* [ ] **Task 7.4:** Package `code.zip` (excluding `dataset/`, `.env`, credentials, `__pycache__`, `.git`) and export `agent-trace.zip` from Antigravity and OpenCode following `agent_trace_instructions.md`.