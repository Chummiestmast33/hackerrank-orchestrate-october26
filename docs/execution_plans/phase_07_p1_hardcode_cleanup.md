# P1 Hardcode Cleanup Plan

**Goal:** remove sample-specific literals and shortcuts from production logic while preserving the 32/32 sample convergence result and the P0 clean-run guarantee.

## Scope

Remove or replace:

- `InventoryBuilder.handover_map`
- `InventoryBuilder.batch_rules` and request-date split branches
- `InventoryBuilder.workflow_analytics_map`
- per-email account fixes and per-user audit-record map
- `StateReconstructor` hardcoded `evidence_51` / `evidence_54` selection
- fabricated `PRESENT` state for unobserved retained records
- `Pipeline` hardcoded `evidence_92` path and ticket injection
- `support_001` / `support_002` special casing

## Workstreams

### P1.1 Workflow account resolution

New resolver fed by all requests, identities, audit history, observations, log traces, and activity events.

1. Resolve direct account candidates from evidence identifiers current at `audit_at`.
2. Prefer a direct candidate that also appears in the deletion-worker account window.
3. For unresolved accounts, group requests by `reported_at`, collect deletion-worker account events in the workflow window, filter by result/status compatibility, and assign by deterministic request/event ordering.
4. Use canonical `account_NNN` only when supported by observed evidence or activity.
5. Never invent an account ID that has no evidence or workflow linkage.

### P1.2 Downstream resource correlation

1. Discover support, backup, export, search, analytics, and connector resources through direct identifiers first.
2. For anonymous analytics records, associate to cases using deletion-worker analytics events in the same workflow window and deterministic batch ordering.
3. Do not assign downstream resources that are already owned by another identity.

### P1.3 State reconstruction

1. Remove fixed evidence IDs; choose scoped absence proofs from reports covering the target system at or before `audit_at`.
2. Keep unknown/unproven states explicit; never fabricate `PRESENT` for retained records.
3. Preserve the P0 rule that `COMPLETE` emits only evidence-backed verification steps.

### P1.4 Pipeline evidence ingestion

1. Discover service-export files from the manifest and parse support tickets from their exported collections.
2. Remove fixed evidence paths and file IDs.

### P1.5 Guard tests

1. Static scan forbids sample case IDs, sample emails, and known account/analytics/audit IDs in production modules.
2. Renamed-case test re-runs sample requests with remapped case IDs and requires identical statuses and step fields.
3. Gold-isolation test confirms production code never reads `sample_output.csv`.
4. Add independent synthetic holdout cases; remove the tautological synthetic self-comparison.
5. Re-run clean-cache, sample convergence, 518-case schema, pytest, ruff, and mypy.

## Risk

Some sample gold rows contain retained security-audit records that are not present in participant-visible evidence (`case_18`, `case_20`). The engine cannot derive those exact IDs without a shortcut. P1 will first remove all sample-specific literals and measure the honest gap; any remaining discrepancy will be documented and resolved only with a general evidence-backed rule, not a case/email literal.

## Investigation: case_18 / case_20 audit IDs

After removing the literals, P1 reaches 32/32 status accuracy and 30/32 sequence accuracy. The only remaining differences are the two retained audit-record verification steps:

- `case_18` expects `audit_record_6645`
- `case_20` expects `audit_record_5569`

Searches performed across participant-visible files:

- exact string search across `dataset/` (CSV, JSON, SQL, TXT, LOG);
- parsed evidence cache (`code/cache/parsed_evidence.json`);
- all PDF text (`pypdf`);
- the committed PNG transcription store (`code/data/multimodal_transcriptions.json`);
- identity, audit-log, activity, snapshot, replica, and service-export records.

Neither audit-record identifier appears anywhere. `6645` and `5569` occur only as `account_6645` and `support_5569`, which do not identify `user_48` / `user_50` and do not link to a security record. No participant-visible evidence maps either user to a retained audit-record ID.

Conclusion: the two IDs are gold-only. They cannot be derived honestly from the supplied evidence; producing them requires a hardcoded exception or reading the sample gold file. All other sample rows match through generic evidence-driven resolution.