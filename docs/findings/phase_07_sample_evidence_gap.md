# Phase 7 Sample Evidence Gap: Detailed Breakdown of `case_18` (`audit_record_6645`) and `case_20` (`audit_record_5569`)

**Scope:** Public 32-case sample evaluation (`dataset/sample_deletion_requests.csv` vs `dataset/sample_output.csv`), not the 518-case evaluation.  
**P1 Commit:** `0c5e876` (`feat: Implement evidence-driven workflow resolver for primary accounts and analytics`).

---

## 1. Executive Summary

The generic, evidence-driven audit engine matches **32/32 sample deletion statuses (`1.0000`)** and **30/32 exact step sequences (`0.9375`)**, achieving **191/193 set-based true positives (`P=1.0000, R=0.9896, F1=0.9948`)**.

The **only** differences across the entire 32-case sample benchmark are two post-remediation `VERIFICATION` steps for retained security-audit records whose resource IDs exist in `dataset/sample_output.csv` (organizer gold) but are **completely absent from every participant-visible data source**:

| Case | Subject Identity | `audit_at` | Gold Step | System | Missing Gold Resource | Operation | State | Evidence ID |
|---|---|---|---|---|---|---|---|---|
| `case_18` | `mori.ren@gmail.com` (`user_50`) | `2026-09-26T11:00:00Z` | 11 of 14 | `security_service` | `audit_record_6645` | `VERIFY_RECORD_PRESENT` | `PRESENT` | `""` |
| `case_20` | `akosua.gyasi@gmail.com` (`user_48`) | `2026-09-26T11:00:00Z` | 7 of 8 | `security_service` | `audit_record_5569` | `VERIFY_RECORD_PRESENT` | `PRESENT` | `""` |

Every other step (191 of 193 gold steps) matches 100% across all six semantic fields (`phase`, `system_id`, `resource_id`, `operation`, `state`, `evidence_id`).

---

## 2. Detailed Case-by-Case Step Breakdown

### 2.1 Breakdown of `case_18` (`mori.ren@gmail.com` / `user_50`)

- **Request:** `case_18`, `email=mori.ren@gmail.com`, `requested_at=2026-09-06T11:00:00Z`, `reported_status=PARTIALLY_COMPLETE`, `reported_at=2026-09-09T11:00:00Z`, `audit_at=2026-09-26T11:00:00Z`.
- **Deletion Status:** Predicted `INCOMPLETE` == Gold `INCOMPLETE` (**MATCH**).
- **Primary Account Resolved:** `account_5521` via `system_activity.csv` (`activity_3732`, `2026-09-09T09:52:26Z`).
- **Observed Evidence:** `evidence_94` (`dataset/evidence/logs/resource_lookup_trace_20260926_103856.log`, captured `2026-09-26T10:38:56Z`).

| Gold `#` | Pred `#` | Phase | System ID | Resource ID | Operation | State | Evidence ID | Alignment |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | `FINDING` | `search_service` | `search_4013` | `REPORT_REMAINING_RECORD` | `PRESENT` | `evidence_94` | Exact match |
| 2 | 2 | `FINDING` | `analytics_platform` | `analytics_037` | `REPORT_EXPOSED_PII` | `PRESENT` | `evidence_94` | Exact match |
| 3 | 3 | `FINDING` | `support_platform` | `support_5569` | `REPORT_EXPOSED_PII` | `PRESENT` | `evidence_94` | Exact match |
| 4 | 4 | `FINDING` | `integration_service` | `data_flow_4890` | `REPORT_ACTIVE_DATA_FLOW` | `ACTIVE` | `evidence_94` | Exact match |
| 5 | 5 | `REMEDIATION` | `integration_service` | `data_flow_4890` | `DISABLE_DATA_FLOW` | `DISABLED` | `""` | Exact match |
| 6 | 6 | `REMEDIATION` | `search_service` | `search_4013` | `DELETE_RECORD` | `ABSENT` | `""` | Exact match |
| 7 | 7 | `REMEDIATION` | `support_platform` | `support_5569` | `REDACT_RECORD` | `REDACTED` | `""` | Exact match |
| 8 | 8 | `REMEDIATION` | `analytics_platform` | `analytics_037` | `ANONYMIZE_RECORD` | `ANONYMIZED` | `""` | Exact match |
| 9 | 9 | `VERIFICATION` | `account_service` | `account_5521` | `VERIFY_RECORD_ABSENT` | `ABSENT` | `""` | Exact match |
| 10 | 10 | `VERIFICATION` | `search_service` | `search_4013` | `VERIFY_RECORD_ABSENT` | `ABSENT` | `""` | Exact match |
| **11** | — | `VERIFICATION` | `security_service` | **`audit_record_6645`** | `VERIFY_RECORD_PRESENT` | `PRESENT` | `""` | **Gold-only (absent from corpus)** |
| 12 | 11 | `VERIFICATION` | `support_platform` | `support_5569` | `VERIFY_RECORD_REDACTED` | `REDACTED` | `""` | Semantic match (index -1) |
| 13 | 12 | `VERIFICATION` | `analytics_platform` | `analytics_037` | `VERIFY_RECORD_ANONYMIZED` | `ANONYMIZED` | `""` | Semantic match (index -1) |
| 14 | 13 | `VERIFICATION` | `integration_service` | `data_flow_4890` | `VERIFY_DATA_FLOW_DISABLED` | `DISABLED` | `""` | Semantic match (index -1) |

### 2.2 Breakdown of `case_20` (`akosua.gyasi@gmail.com` / `user_48`)

- **Request:** `case_20`, `email=akosua.gyasi@gmail.com`, `requested_at=2026-09-08T11:00:00Z`, `reported_status=PARTIALLY_COMPLETE`, `reported_at=2026-09-09T11:00:00Z`, `audit_at=2026-09-26T11:00:00Z`.
- **Deletion Status:** Predicted `INCOMPLETE` == Gold `INCOMPLETE` (**MATCH**).
- **Primary Account Resolved:** `account_5037` via `system_activity.csv` (`activity_3734`, `2026-09-09T10:14:55Z`) and `evidence_04` (`account_admin_console_20260926.png`).
- **Observed Evidence:** `evidence_94` (`dataset/evidence/logs/resource_lookup_trace_20260926_103856.log`, captured `2026-09-26T10:38:56Z`).

| Gold `#` | Pred `#` | Phase | System ID | Resource ID | Operation | State | Evidence ID | Alignment |
|---|---|---|---|---|---|---|---|---|
| 1 | 1 | `FINDING` | `search_service` | `search_4262` | `REPORT_REMAINING_RECORD` | `PRESENT` | `evidence_94` | Exact match |
| 2 | 2 | `FINDING` | `integration_service` | `data_flow_1770` | `REPORT_ACTIVE_DATA_FLOW` | `ACTIVE` | `evidence_94` | Exact match |
| 3 | 3 | `REMEDIATION` | `integration_service` | `data_flow_1770` | `DISABLE_DATA_FLOW` | `DISABLED` | `""` | Exact match |
| 4 | 4 | `REMEDIATION` | `search_service` | `search_4262` | `DELETE_RECORD` | `ABSENT` | `""` | Exact match |
| 5 | 5 | `VERIFICATION` | `account_service` | `account_5037` | `VERIFY_RECORD_ABSENT` | `ABSENT` | `""` | Exact match |
| 6 | 6 | `VERIFICATION` | `search_service` | `search_4262` | `VERIFY_RECORD_ABSENT` | `ABSENT` | `""` | Exact match |
| **7** | — | `VERIFICATION` | `security_service` | **`audit_record_5569`** | `VERIFY_RECORD_PRESENT` | `PRESENT` | `""` | **Gold-only (absent from corpus)** |
| 8 | 7 | `VERIFICATION` | `integration_service` | `data_flow_1770` | `VERIFY_DATA_FLOW_DISABLED` | `DISABLED` | `""` | Semantic match (index -1) |

*(Note: Why does positional step accuracy report `187/193` while set-based recall reports `191/193`? Because omitting step 11 in `case_18` shifts steps 12–14 by 1 position [4 positional misses], and omitting step 7 in `case_20` shifts step 8 by 1 position [2 positional misses], totaling $4 + 2 = 6$ positional misses out of 193 steps, whereas set-based comparison recognizes that 191 of 193 steps are present with 0 false positives.)*

---

## 3. Root Cause in the Dataset Generator (`evidence_94` 28-Query Cap)

Both `case_18` (`user_50`) and `case_20` (`user_48`) belong to the `2026-09-26` audit cohort whose point-in-time readback trace is `evidence_94` (`dataset/evidence/logs/resource_lookup_trace_20260926_103856.log`, captured at `2026-09-26T10:38:56Z`).

Inspecting `evidence_94` reveals:
- Line 1: `2026-09-26T07:49:50Z level=INFO service=readback_collector event=export_started target_count=28 mode=point_in_time`
- Line 58: `2026-09-26T10:38:56Z level=INFO service=readback_collector event=export_completed queries=28 dropped=0`

Within those 28 point-in-time queries:
- Cohort peers `user_42` (`audit_record_1105`, lines 12–13), `user_43` (`audit_record_2016`, lines 34–35), and `user_49` (`audit_record_3308`, lines 54–55) received explicit `security_service` `audit_record_read_completed` log pairs.
- `user_50` (`mori.ren@gmail.com`) received 4 readback queries for its non-compliant resources (`support_5569`, `analytics_037`, `data_flow_4890`, `search_4013`), and `user_48` (`akosua.gyasi@gmail.com`) received 2 readback queries (`search_4262`, `data_flow_1770`), **but neither user's `security_service` audit record query was included in the 28-query log file**, nor was any `RETAIN_RECORD` or `LINK_RESOURCE_IDENTITY` row emitted for `audit_record_6645` or `audit_record_5569` in `system_activity.csv`.
- Because `case_18` and `case_20` have `deletion_status=INCOMPLETE`, their post-remediation `VERIFICATION` steps carry `evidence_id=""` by contract (AGENTS.md §6.3, §6.6). Consequently, when `sample_output.csv` was generated from private structured truth, the absence of participant-facing evidence for `audit_record_6645` and `audit_record_5569` did not trigger an empty-citation validation error.

---

## 4. Exhaustive Corpus Search Proof

The following participant-visible sources were searched for `6645`, `5569`, `audit_record_6645`, and `audit_record_5569`:
- All CSVs in `dataset/` (`deletion_requests.csv`, `sample_deletion_requests.csv`, `user_identities.csv`, `user_audit_log.csv`, `system_activity.csv`, `evidence_files.csv`, `deletion_rules.csv`);
- All 79 structured evidence files under `dataset/evidence/` (`.sql`, `.json`, `.txt`, `.log`);
- Text extracted from all 4 PDF documents (`evidence_18`, `evidence_27`, `evidence_55`, `evidence_58`) via `pypdf` and `pdfplumber`;
- All 11 PNG console screenshots via the committed two-pass transcription store `code/data/multimodal_transcriptions.json`;
- The full parsed evidence cache `code/cache/parsed_evidence.json` (94 files, 2,912 observations).

**Exact Search Command & Output:**
```bash
rg -n "audit_record_6645|audit_record_5569|6645|5569" dataset code/cache/parsed_evidence.json code/data/multimodal_transcriptions.json
```
- `6645` appears only as `account_6645` in `system_activity.csv:562` and `application_trace_eu_north_20260302.log:38` (an unrelated profile deleted in February 2026).
- `5569` appears only as `support_5569` (`case_18`'s support ticket in `system_activity.csv:3745` and `evidence_94:10-11`), as a 4-digit hex substring inside unrelated SHA-256 hashes (`user_93`, `user_298`, `user_83`), in `requestId=tr-5569590`, and in `ticket_id="CS-5569"` (`support_6569` for `user_405`).
- Neither `audit_record_6645` nor `audit_record_5569` exists anywhere outside `dataset/sample_output.csv`.

---

## 5. Governance & Contract Compliance (`AGENTS.md` §4.3, §6.6, §6.7)

Producing `audit_record_6645` or `audit_record_5569` during prediction would require either:
1. Reading `dataset/sample_output.csv` at runtime, or
2. Hardcoding the strings `"audit_record_6645"` and `"audit_record_5569"` mapped to `mori.ren@gmail.com` and `akosua.gyasi@gmail.com`.

Both are strictly prohibited by **AGENTS.md**:
- **§4.3:** *"The solution must use only participant-facing data under `dataset/`. Organizer-only truth, golden answers, review files, and generator internals must never be used for predictions."*
- **§6.7:** *"Do not use organizer-only files, hardcoded golden labels, or case-family shortcuts."*

Therefore, the engine honestly and deterministically reports only evidence-backed resources, achieving **32/32 status accuracy (`1.0000`)**, **30/32 sequence accuracy (`0.9375`)**, and **0.9948 set-based F1** without fabrication.
