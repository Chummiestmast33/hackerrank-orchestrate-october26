# Phase 3 Parser Notes — Deterministic Evidence Parsers

Companion to `docs/execution_plans/phase_03_deterministic_parsers.md` and
`docs/findings/phase_01_ground_truth.md`. Records what was implemented, every
decision that differs from Plan.md §3, the corpus results, and the cache and
mutation status.

## 1. No-guess invariants (implemented)

- `state_vocab.py` is the only place raw fields become states. Every decoder returns
  `(state, reason)`; unknown tokens, missing fields and unmapped values return
  `ObservationState.UNKNOWN` with a reason (`missing_field:x`, `unknown_result:y`,
  `inconclusive_readback:...`). There is no default PRESENT/ABSENT branch.
- `ParseStatus` distinguishes `OK`, `UNKNOWN_STATE`, `PARSE_ERROR` and
  `UNSUPPORTED_FORMAT` at file level; `models.finalize_status` derives it from
  errors/UNKNOWN observations.
- Every observation carries `reason`, `locator` (table/line/record index),
  `provenance` (`EXPLICIT_FIELD`, `LEDGER_RESULT`, `READBACK`, `NULL_PII_RULE`,
  `HANDOVER`), sorted `identifiers`, raw `state_inputs`, and `pii_exposed`.
- Unknown family/table/collection/service keys become explicit errors, never
  silent skips (log events that are not state-bearing are counted as ignored
  lines, not errors).

## 2. Decode tables as implemented

### Result vocabulary (handover text + ledgers)

`NOT_FOUND→ABSENT`, `FOUND→PRESENT`, `IDENTIFIABLE→PRESENT` (+`pii_exposed`),
`ANONYMIZED`, `REDACTED`, `ACTIVE`, `BLOCKED`, `DISABLED`; anything else →
`UNKNOWN(unknown_result:<token>)`.

### Boolean/explicit fields

| Field(s) | Rule |
|---|---|
| `enabled` | true → ACTIVE, false → DISABLED |
| `restore_allowed` | true → ACTIVE, false → BLOCKED |
| `decision` (`restore_authorization_completed`) | `deny` → BLOCKED, `allow` → ACTIVE, else UNKNOWN |
| `available` (export checks) | true → PRESENT; **false → UNKNOWN** (download unavailability does not prove the record is gone) |
| `eligible` + `deletion_block` (`restore_candidate_evaluated`) | eligible=true & deletion_block=false → ACTIVE (proven by `case_17`/`evidence_01`); deletion_block=true → UNKNOWN; eligible=false → UNKNOWN |
| `rows` / `http_status` (account readbacks) | rows=0 or 404 → ABSENT; rows≥1 or 200 → PRESENT; rows≥1 with no email/phone but a reference → REDACTED; otherwise UNKNOWN |
| `rows` (security/support/analytics contact lookups) | 0 → ABSENT, ≥1 → PRESENT |
| `result`/`total_hits` (search) | total_hits authoritative; `hit`/`found` → PRESENT; `miss`/`not_found` → ABSENT; conflicting hit+0 → UNKNOWN |
| `direct_identifiers` / PII fields (analytics) | 0 or all-null → ANONYMIZED; ≥1 or any PII → PRESENT |
| requester fields (support messages) | any non-null → PRESENT (pii); all null + no subject reference → REDACTED |
| `matched_value` (PII scans) | non-empty → PRESENT (+pii), else UNKNOWN |

### Collection/category mapping (17 keys, shared by SQL and JSON)

`customer_profiles→USER_PROFILE`; `customer_search_documents→SEARCH_INDEX_ENTRY`
(nested `document` supported); `customer_analytics_profiles`/`reports→ANALYTICS_PROFILE`;
`support_records`/`support_conversations→SUPPORT_MESSAGE`; `ticket_attachments→SUPPORT_ATTACHMENT`;
`customer_exports`/`customer_export_jobs→USER_EXPORT`; `connector_subscriptions`/`configurations→DATA_FLOW`;
`backup_restore_entries`/`backup_catalog→BACKUP_ARCHIVE`; `security_audit_records`/`events→SECURITY_AUDIT_LOG`;
`deleted_customer_references→ACCOUNT_TOMBSTONE`; `retained_order_records→LEGAL_HOLD_RECORD`;
`operational_record_history→record_type` (ledger result decoding).

### State-bearing log events (all shapes)

`profile_lookup_completed`, `support_ticket_read_completed`, `contact_query_completed`,
`message_pii_scan`, `attachment_pii_scan`, `connector_config_read_completed`,
`connector_config_loaded`, `connector_heartbeat`, `restore_policy_read_completed`,
`restore_authorization_completed`, `restore_candidate_evaluated`, `index_query_completed`,
`audit_record_read_completed`, `analytics_profile_read`,
`analytics_profile_read_completed`, `analytics_identity_scan`,
`contact_lookup_completed`, `export_download_check_completed`,
`export_metadata_read_completed`, `record_lookup`. Seven line shapes are recognised
(plain kv, syslog-RFC, JSON-line, pipe, bracket, cloud-runtime `message="..."`, and
`record_lookup` plain kv).

## 3. Deviations from Plan.md §3 (explicit, not guessed)

1. **Implicit absence via `snapshot_scope` is not emitted as observations in Phase 3.**
   Parsers expose the ingredients instead: `ParseReport.scope` (origin_system →
   captured_at) for inventory files, `direct_systems` for dedicated account/search
   replicas, and `captured_collections` including `record_count=0` for bundles.
   Phase 5's state reconstructor will emit `SCOPE_IMPLICIT` ABSENT only when the
   resource is known to belong to a covered system. This avoids inventing ABSENT
   observations for resources the parser cannot attribute.
2. **`available=false` → UNKNOWN**, not ABSENT (record existence ≠ download availability).
3. **`deletion_block=true` and `eligible=false` → UNKNOWN** (no participant data
   exercises them; semantics were not confirmed).
4. **Search export `hits` is nested** `{total, documents[]}`: `total` drives the
   state; documents contribute identifiers and `pii_exposed`.
5. **Support conversations**: a non-null `subject_reference` counts as identifying
   (PRESENT); all-null requester fields with no reference is REDACTED.
6. **Members both sides of a replica pair are emitted** (primary + read/regional/
   reporting/failover tables) rather than reconciled; drift comparison is Phase 5.
7. Observation timestamps use the most specific available time (`observed_at`,
   `recorded_at`, log line timestamp, snapshot `captured_at`), falling back to the
   manifest `captured_at`.

## 4. Corpus results (current dataset, parser version `phase3-v1`)

- 94 manifest files: 79 structured (`OK`) + 4 PDF + 11 PNG (`UNSUPPORTED_FORMAT`
  placeholders for Phase 4). 0 `PARSE_ERROR`, 0 `UNKNOWN_STATE`, 0 decode errors.
- 2886 observation records; states: PRESENT 1746, ABSENT 237, ACTIVE 187,
  ANONYMIZED 180, BLOCKED 56, DISABLED 56, REDACTED 26.
- All 26 logs parse across the 7 line shapes; all 11 inventories expose
  `snapshot_scope`; all 12 bundles expose captured collections.
- Golden cross-check: **70/70 structured citation states match** the 32 sample
  cases. Exemptions pinned in `code/tests/test_corpus_census.py`: 4 scope-based
  absences (`case_01/02/04` → `evidence_54`, `case_31` → `evidence_51`) and 1 PDF
  citation (`case_07` → `evidence_58`, Phase 4).
- Committed census fixture: `code/tests/fixtures/parsers/corpus_census.json`
  (per-file family/status/state counts/scope/collections), asserted for drift.

## 5. Aggressive cache and CLI (P3.7)

- One artifact: `code/cache/parsed_evidence.json` (gitignored, ~2 MB), holding all
  94 parse entries plus meta `{schema, parser_version, generated_at}`.
- **Forever semantics:** an entry is reused while the file's `sha256` and
  `PARSER_VERSION` match; no TTL. Content or parser change reparses only the
  affected files; `--force` rebuilds everything. Errors/UNKNOWN are cached too.
- Atomic writes (temp + `os.replace`); deterministic serialization (sorted files,
  observations in parser order, `sort_keys`); `use forever` verified: first run
  94 misses, second run 94 hits.
- CLI: `python code/src/loaders/cli.py parse-all [--dataset --cache --force --strict --quiet]`;
  prints family × state × status census; exit 0 clean / 1 `PARSE_ERROR` (`--strict`
  adds `UNKNOWN_STATE`) / 2 manifest error. Phase 5 reads the cache through
  `loaders.cache.load_evidence_index`.

## 6. Mutation status (P3.9/P3.10)

| session | scope | killed/total | raw | void annotation mutants | adjusted |
|---|---|---|---|---|---|
| 1 | `src/evaluation` (Phase 2 baseline) | 696/1195 | 58.2% | 155 | 66.9% |
| 2 | `src/evaluation` after hardening 1 | 758/1195 | 63.4% | 151 | 72.6% |
| 3 | `src/evaluation` after hardening 2 | 837/1195 | 70.0% | 150 | 80.1% |
| 4 | `src/evaluation`, current gate | 864/1172 | 73.7% | 147 | **84.3%** |

- Void mutants = `ReplaceBinaryOperator_BitOr_*` on PEP-604 annotation unions that
  never execute; they are counted by cosmic-ray but can never be killed. The gate
  metric excludes them and reports both numbers.
- P3.9 (evaluation debt) is recorded as resolved on the adjusted denominator.
- P3.10 (src-wide gate over loaders+models+evaluation) is **deferred to Phase 6**
  by decision; the current valid gate remains session 4 (`src/evaluation`, adjusted
  84.3%). The new parser modules participate in Phase 6's run.

## 7. Known limitations / Phase 5 hooks

- Scope-based absence derivation, replica drift reconciliation and mode choice all
  remain Phase 5 work (metadata is available in the cache reports).
- Minimal synthetic fixtures live in the unit tests; corpus behavior is pinned by
  the committed census snapshot.
- Phase 4 must replace binary placeholder entries with extracted observations while
  keeping the `EvidenceObservation` schema unchanged.