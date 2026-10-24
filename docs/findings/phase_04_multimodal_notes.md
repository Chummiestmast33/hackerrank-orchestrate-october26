# Phase 4 Multimodal Notes — P4.0–P4.3 Slice

Scope: P4.0 visual inventory, P4.1 model additions, P4.2 PDF extractor, P4.3 PDF
decode tables. No model calls are made in this slice. **DB relations are
metadata only** — decoders never use them to assign or upgrade a state; they are
recorded here (and asserted in tests) for Phase 5 linking/drift and P4.6
verification flags.

Method: all 11 PNGs were opened and read manually; all 4 PDFs were text-extracted
with pypdf; every token was cross-checked against the Phase 3 parsed cache
(`code/cache/parsed_evidence.json`) and `system_activity.csv`
`LINK_RESOURCE_IDENTITY` rows.

---

## 1. PNG visual inventory (11 files)

| file_id | Console / System | Visible facts | Resource tokens | Identity tokens | Status-bearing labels |
|---|---|---|---|---|---|
| evidence_04 | Customer Operations (account_admin_portal) | Haruka Sato (Silver); orders ORD-20265762 Delivered, ORD-20265518 Returned; support CS-8538; address, market JP | `account_5762`, `support_9538` | `user_11`, haruka.s1838@zoho.com, +81 90 7610 2507 | row order statuses (Delivered/Returned), tier badge |
| evidence_09 | Search Console (search_index_admin) | index `customer_directory_v3`/prod-eu; 2 hits; doc panel fields | `search_428`, `search_1874` | g.silva76@gmail.com, g.silva76.jr@gmail.com, `user_13` (row 1), `user_9842` (activity) | scores/latency only |
| evidence_14 | BridgeOps Connections (integration_admin) | 12 connectors; 4 topology rows; detail panel for `data_flow_1121` | `data_flow_1121`, `data_flow_9846` | jain.aditi@gmail.com, lucia-torres@gmail.com | `Status: Healthy`, `Mode: Continuous`, `Sync mode: Continuous sync`, `Last response 200 OK` |
| evidence_19 | Pulse Analytics (analytics_platform) | profile stats; timeline; attributes | `analytics_7438` | `user_20`, darwish.omar@icloud.com | badge `Last 90 days` (window only) |
| evidence_23 | Customer Download Center (export_service) | 4 export jobs; detail for `export_1260` | `export_1261`, `export_1260`, `export_1259`, `export_1258` | ingrid.dahl@outlook.com, marcus.lee@northstar.shop, sara.kim@northstar.shop, daniel.park@northstar.shop | statuses `Collecting`, `Ready`, `Packaging`; tabs Ready/Processing/Expired |
| evidence_28 | Helpline Console (support_platform) | ticket CS-5034; conversation; order panel | `support_1034` | Kofi Agyeman, kagyeman8947@fastmail.com | SLA badge only; order `In transit` |
| evidence_32 | Vault Recovery Manager (backup_service) | 4 archives; detail for `backup_9287` | `backup_9291`, `backup_9288`, `backup_9287`, `backup_9286` | areed1433@gmail.com, bluepeakco@outlook.com, miller.logistics@company.com, summit-retail@company.com | `Healthy` badge; tier `Archive`; aggregate `Restore success 99.6%`; `Checksum Verified`; `Retention end` |
| evidence_37 | Sentinel Account events (security_service) | 6 signed events for one subject; raw event panel | `audit_record_001` … `audit_record_006` | `user_03`, oliver-bennett@gmail.com (via LINK_4010) | `Integrity: Valid`; categories/actors |
| evidence_42 | Customer Reference Registry (identity_service) | retained reference for one customer; linked records | none (`user_17` is the reference, no tombstone id) | `user_17`, leonie.g9352@outlook.com (via LINK_4011) | badge `Retained reference`; row `Status: Active` |
| evidence_46 | Nimbus Object Storage (object_storage) | bucket objects; detail for `delivery_confirmation_19.pdf` | none (`object_19` via LINK_4007) | none visible (uploader is `support-service`) | version/checksum only |
| evidence_60 | Audience Operations (marketing_platform) | profile + membership | `marketing_001` | sj.park@naver.com, +82 10-5837-9451 | badge `Live`; `Email opt-in: Yes`, `SMS opt-in: No` |

### 1.1 Status-label vocabulary and the metadata-only policy

Labels observed: `Healthy`, `Continuous`, `Continuous sync`, `Live`,
`Retained reference`, `Active` (linked-record rows), `Collecting`, `Ready`,
`Packaging`, `Delivered`, `Returned`, `In transit`, `Valid`, `Verified`, plus
numeric health/throughput indicators. None of them is a Phase 3 state token
(`DELETED`, `NOT_FOUND`, `ANONYMIZED`, `REDACTED`, `DISABLED`, `BLOCKED`).
P4.7 will treat every one of these as `UNKNOWN(unmapped_console_status:<label>)`
unless a documented row says otherwise. **No corroborated mapping is planned in
this slice**; any future mapping must cite structured evidence in the notes.

### 1.2 Proposed `ExtractedRecord` schema per PNG family

| family | fields |
|---|---|
| account_console | `name, badge, user_id, account_id, email, phone, signup_channel, market, last_contact, orders[{order_id,date,item,qty,total,status}], support_ref{ticket,resource_id}, address` |
| search_inspector | `index, environment, executed_at, result_count, results[{resource_id, display_name, email, customer_reference, score, indexed_at}]` |
| connector_console | `connector_count, connectors[{resource_id, destination, selector, mode, events_per_hour, last_contact}], detail{resource_id, status, owner, destination, selector, sync_mode, last_response}` |
| analytics_profile | `name, window_badge, user_id, analytics_id, email, metrics{sessions,products_viewed,orders,revenue}, attributes{market,audience,interest,last_activity,first_seen}` |
| export_console | `job_count, jobs[{resource_id, file_name, owner_email, status, created}]` |
| support_console | `ticket_id, resource_id, customer_name, email, assignee, tags, order_ref, order_status, messages[{time,sender,text}]` |
| backup_console | `archive_count, archives[{resource_id, account_email, region, created, size, encryption, tier}], detail{resource_id,path,created,retention_end,checksum}` |
| reference_registry | `subject_reference, reference_type, badge, links[{system, reference, created, status}], history[]` |
| sentinel_events | `subject_reference, event_count, events[{time, event_name, category, subject, actor, integrity, audit_id}]` |
| object_storage | `bucket, region, captured_at, objects[{name, size, modified, storage_class, version}], detail{name, size, version, uploader, modified}` |
| marketing_profile | `name, marketing_id, email, phone, badges, market, language, email_opt_in, sms_opt_in, last_refreshed, membership{audience, segments}` |

Values are transcribed only when visible; anything absent stays absent (never
invented). Numbers keep their visible formatting (e.g. `USD 167.42`).

---

## 2. DB relations (verified, metadata only)

`cache` column = Phase 3 parsed observation for the exact resource id or
identifier (file, state). `LINK` = `LINK_RESOURCE_IDENTITY` activity id.

| Token | Cache match | LINK | Relation note |
|---|---|---|---|
| `account_5762` | evidence_01, account_service, ABSENT | 4000 (haruka.s1838@zoho.com, user_11) | Console (09-26) shows the profile alive after the 09-15 readback → temporal drift for Phase 5, not a decode input |
| `support_9538` | evidence_01, support_platform, PRESENT (SUPPORT_ATTACHMENT) | — | same record corroborated |
| `search_428` | evidence_01, search_service, PRESENT | 4001 (g.silva76@gmail.com, user_13) | email + reference agree |
| `search_1874` | evidence_01, search_service, PRESENT | — | orphan email-only document (no customer_reference) — relation only via email |
| `data_flow_1121` | evidence_01, integration_service, ACTIVE | 4002 (jain.aditi@gmail.com, user_14) | console `Healthy/Continuous` is NOT used to assign state |
| `data_flow_9846` | evidence_01, integration_service, ACTIVE | — | selector email matches cache identifiers |
| `analytics_7438` | evidence_01, analytics_platform, PRESENT | 4003 (darwish.omar@icloud.com, user_20) | agrees |
| `export_1260` | evidence_01, export_service, PRESENT | 4004 (ingrid.dahl@outlook.com, user_18) | agrees |
| `support_1034` | evidence_02, support_platform, PRESENT (SUPPORT_MESSAGE) | 4005 (kagyeman8947@fastmail.com, user_22) | agrees |
| `backup_9287` | evidence_01, backup_service, ACTIVE | 4006 (areed1433@gmail.com, user_16) | agrees |
| `audit_record_003` | no cache match | 4010 (oliver-bennett@gmail.com, user_03) | PNG evidence_37 + PDF evidence_55 are the only state sources |
| `audit_record_001/002/004/005/006` | no cache match | — | PNG evidence_37 sole source |
| `object_19` / `delivery_confirmation_19.pdf` | no cache match | 4007 (belongs only to priya.raman@gmail.com) | **CONFLICT:** detail panel shows uploader `support-service`, not the customer |
| `marketing_001` | no cache match | 4008 (kwame-mensah@proton.me, user_09) | **CONFLICT:** console shows sj.park@naver.com; both kept, neither dropped |
| `tombstone_17` / `user_17` | no cache match for tombstone_17 | 4011 (leonie.g9352@outlook.com, user_17) | registry PNG (evidence_42) + identity data |
| `ORD-20263245`, `CS-3245`, `CS-3378`, `FIN-7742` | not in structured evidence | — | sole source (registry PNG) |
| `ORD-20265762`, `ORD-20265518`, `CS-8538` | not in structured evidence | — | sole source (account console) |
| `ORD-20265034` | not in structured evidence | — | sole source (support console) |

PDF relations:

| Token | Cache match | LINK | Relation note |
|---|---|---|---|
| `NST-2026-0718-1842` / `export_1842` | no cache match for export_1842 | 4009 (ingrid.dahl@outlook.com, user_18) | statement id equals the export job reference; sole source otherwise |
| `ORD-20261260`, statement order | not in structured evidence | — | sole source |
| `ORD-20264118` … `ORD-20264600` (register rows) | not in structured evidence | — | sole source; `user_08/12/17/21/24/29` exist in identities |
| `audit_record_003` / `user_03` | no cache match | 4010 | PDF evidence_55 + PNG evidence_37 |
| `support_001` / `CS-4827` | no cache match | — | **golden case_07 depends on this PDF**; sole source |

Cross-check helper `relate_to_structured()` in `multimodal_rules.py` returns
exactly these match/sole-source relations deterministically; conflicts are
documented here (metadata only) because resolving them would require judgment.

---

## 3. PDF inventory and expected P4.3 outcomes

| file_id | Header family | Key extracted facts | P4.3 outcome |
|---|---|---|---|
| evidence_18 | `customer_statement` | statement `NST-2026-0718-1842`; customer Ingrid Dahl; `user_18`; ingrid.dahl@outlook.com; order `ORD-20261260`; item Smart desk lamp SKU LAMP-SD-04; total EUR 71.93; address 24 Fjordgata, 7010 Trondheim, Norway | **records only, no observation** (no resource id) |
| evidence_27 | `retention_register` | register month May 2026; 6 rows (`ORD-…`, `user_XX`, reason, date, amount, retain-until, owner) | **records only, no observation** (no `legal_hold_*` id) |
| evidence_55 | `compliance_journal` | reference CJX-20260905-0630; `audit_record_003`; subject `user_03`; Account closure recorded; recorded 25 Aug 2026 04:03 UTC; retain until 25 Aug 2027 04:03 UTC; journal 2026-Q3 | `security_service` / `SECURITY_AUDIT_LOG` / **PRESENT**, `retain_until` in `state_inputs` |
| evidence_58 | `support_attachment` | `CS-4827` / `support_001`; Priya Raman; priya.raman@gmail.com; +91 98765 73142; ORD-20264827; submitted 18 Jun 2026 10:24 UTC; file delivery_address_correction.pdf | `support_platform` / `SUPPORT_ATTACHMENT` / **PRESENT**, `pii_exposed=true` |

Layout normalizations required (verified on the real files):
- split times (`10\n24 UTC`, `04\n03 UTC`, `06\n30 UTC`, `08\n00 UTC`) rejoin to
  `10:24 UTC` etc.;
- standalone `Record` / `Detail` label lines are dropped;
- header detection uses the first lines only (never file names/ids).

`evidence_18` and `evidence_27` keep all facts as `ExtractedRecord`s; Phase 5 may
link them through order references or `user_*`, which this slice does not do.

---

## 4. Manual review log

- 11/11 PNGs opened and read; no OCR model was used.
- Tokens cross-checked against `parsed_evidence.json` and `system_activity.csv`.
- Two conflicts (`marketing_001` email, `delivery_confirmation_19.pdf` uploader)
  and one drift (`account_5762`) are recorded above. They never change a decoded
  state in this phase.
- No instructions or prompt-like text were found inside any image; if future
  images contain such text, it is treated as data.