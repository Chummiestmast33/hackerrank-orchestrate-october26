# Phase 7 Sample Evidence Gap

**Scope:** public 32-case sample evaluation, not the hidden 518-case evaluation.

**P1 commit:** `0c5e876` (`feat: Implement evidence-driven workflow resolver for primary accounts and analytics`).

## Summary

The generic, evidence-driven engine now matches **32/32 sample deletion statuses** and **30/32 exact step sequences**.

The only differences are two retained security-audit verification steps whose resource IDs are present in the gold sample file but absent from every participant-visible data source:

| Case | Gold step | System | Resource | Operation | State | Evidence |
|---|---|---|---|---|---|---|
| `case_18` | 11 | `security_service` | `audit_record_6645` | `VERIFY_RECORD_PRESENT` | `PRESENT` | `""` |
| `case_20` | 7 | `security_service` | `audit_record_5569` | `VERIFY_RECORD_PRESENT` | `PRESENT` | `""` |

Current output omits exactly these two verification steps. Every other of the 193 gold steps matches on all six semantic fields.

## Measured result

Fresh-cache sample run:

```text
case status accuracy:         1.0000 (32/32)
sequence accuracy:            0.9375 (30/32)
step accuracy (positional):   0.9689 (187/193)
set-based:                    P=1.0000 R=0.9896 F1=0.9948 (tp=191 fp=0 fn=2)
field accuracy (overall):     0.9758
```

Per status:

```text
COMPLETE     n=10  status=1.0000  sequence=1.0000  positional=1.0000
INCOMPLETE   n=22  status=1.0000  sequence=0.9091  positional=0.9623
```

The two `INCOMPLETE` cases are `case_18` and `case_20`.

## Evidence search performed

The following participant-visible sources were searched for `6645`, `5569`, `audit_record_6645`, and `audit_record_5569`:

- `dataset/` CSVs (`deletion_requests`, `sample_deletion_requests`, `user_identities`, `user_audit_log`, `system_activity`, `evidence_files`, `deletion_rules`);
- every structured evidence file under `dataset/evidence/` (JSON, SQL, TXT, LOG);
- the parsed evidence cache `code/cache/parsed_evidence.json`;
- text extracted from all four PDFs with `pypdf`;
- the committed PNG transcription store `code/data/multimodal_transcriptions.json`;
- identity, audit-log, activity, snapshot, replica, and service-export records.

Result:

- `6645` appears only as `account_6645` in `system_activity.csv` and an unrelated profile lookup.
- `5569` appears only as `support_5569` in `system_activity.csv` and `resource_lookup_trace_20260926_103856.log`.
- Neither string appears as an `audit_record_*` resource.
- There is no evidence mapping `user_48` (`akosua.gyasi@gmail.com`) or `user_50` (`mori.ren@gmail.com`) to either audit-record ID.

The two IDs therefore exist only in `dataset/sample_output.csv`.

## Why the engine does not include them

Producing these steps would require one of:

1. hardcoding the two IDs or the two case IDs in production code; or
2. reading `dataset/sample_output.csv` during prediction.

Both violate AGENTS.md:

- §4.3: only participant-facing data may be used; golden answers must not drive predictions.
- §6.7: no hardcoded golden labels or case-family shortcuts.

The engine correctly keeps the two cases `INCOMPLETE` because their real observed findings (`search`, `analytics`, `support`, `integration`) are evidence-backed. Only the unobserved retained-audit verification steps are missing.

## Reproduction

```bash
python code/main.py --sample --rebuild-cache
```

Expected: exit code `1`, because the sample CLI treats sequence accuracy below `1.0` as a failure. The evaluation summary should show `32/32` status and `30/32` sequence.

Exact search:

```bash
rg -n "audit_record_6645|audit_record_5569|6645|5569" dataset code/cache/parsed_evidence.json code/data/multimodal_transcriptions.json
```

Inspect the two diffs:

```bash
python code/main.py --sample --diff
```

## Recommendation

Accept the documented **30/32 sample sequence** result. Do not fabricate the two resource IDs. The full 518-case output remains valid under the contract and must be reported honestly without claiming hidden-gold accuracy.