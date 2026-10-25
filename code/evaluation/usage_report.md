# Usage Report -- Deletion Audit Agent

- Generated at (UTC): 2026-10-25T13:28:24+00:00
- Full-run request denominator: 518
- Usage log: `C:\Users\corte\Downloads\hackerrank-orchestrate-october26\code\data\usage_log.jsonl`
- Pricing file: `C:\Users\corte\Downloads\hackerrank-orchestrate-october26\.pricing.json` (public values; no secrets)

## Configured Models & Official Pricing Rates

| provider | model | role | input rate ($ / 1M tokens) | output rate ($ / 1M tokens) |
|---|---|---|---:|---:|
| `qwen` | `qwen/qwen3.7-max` (`qwen3.7-max`) | Intent & Document Agent + Tool-Calling Audit Orchestrator | $2.500000 | $7.500000 |
| `qwen` | `qwen/qwen3-vl-plus` (`qwen3-vl-plus`) | Multimodal Vision Agent (PNG console extraction & verification) | $0.200000 | $1.600000 |
| `qwen` | `qwen/deepseek-v4.1-flash` (`deepseek-v4.1-flash`) | Auxiliary secondary pass model | $0.150000 | $0.600000 |

## Full 518-Case Hybrid AI Audit Agent Run (`__full_518_audit__`)

Live metered calls executed by `AuditOrchestratorAgent`, `IntentDocumentAgent` (`qwen3.7-max`), and `MultimodalVisionAgent` (`qwen3-vl-plus`) during the 518-case audit run.

### Model providers and model names

- `qwen` / `qwen3-vl-plus`
- `qwen` / `qwen3.7-max`

### Model-call counts

- Total calls: 39
- Uncached calls: 39
- Cache-hit calls: 0

### Input and output tokens

- Input tokens: 140936
- Output tokens: 20805
- Total tokens: 161741
- Total tokens per request (denominator 518): 312.24

### Estimated cost

- Estimated total cost: $0.434657
- Estimated cost per request: $0.00083911

### Per-model totals

| provider | model | calls | cached | input tokens | output tokens | total tokens | cost (USD) |
|---|---|---|---|---|---|---|---|
| qwen | qwen3-vl-plus | 11 | 0 | 26137 | 2306 | 28443 | 0.008917 |
| qwen | qwen3.7-max | 28 | 0 | 114799 | 18499 | 133298 | 0.425740 |

### Overall totals

- Calls: 39 (cached 0)
- Tokens: 161741 (input 140936 / output 20805)
- Cost: $0.434657

## Phase 4 Multimodal Screenshot Extraction (`phase4-extraction`)

Two-pass `qwen3-vl-plus` visual transcription run across all 11 PNG console screenshots in `dataset/evidence/images/`.

### Model providers and model names

- `qwen` / `qwen3-vl-plus`

### Model-call counts

- Total calls: 22
- Uncached calls: 22
- Cache-hit calls: 0

### Input and output tokens

- Input tokens: 50784
- Output tokens: 7702
- Total tokens: 58486
- Total tokens per request (denominator 518): 112.91

### Estimated cost

- Estimated total cost: $0.022480
- Estimated cost per request: $0.00004340

### Per-model totals

| provider | model | calls | cached | input tokens | output tokens | total tokens | cost (USD) |
|---|---|---|---|---|---|---|---|
| qwen | qwen3-vl-plus | 22 | 0 | 50784 | 7702 | 58486 | 0.022480 |

### Overall totals

- Calls: 22 (cached 0)
- Tokens: 58486 (input 50784 / output 7702)
- Cost: $0.022480

## Combined Multi-Model Summary (Across All 518 Evaluation Requests)

| provider | model | calls | cached calls | input tokens | output tokens | total tokens | avg tokens / req (518) | total cost (USD) | cost / req (USD) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `qwen` | `qwen3-vl-plus` | 33 | 0 | 76921 | 10008 | 86929 | 167.82 | $0.031397 | $0.00006061 |
| `qwen` | `qwen3.7-max` | 28 | 0 | 114799 | 18499 | 133298 | 257.33 | $0.425740 | $0.00082189 |
| **OVERALL** | **All Models** | **61** | **0** | **191720** | **28507** | **220227** | **425.15** | **$0.457137** | **$0.00088250** |

## Hybrid AI Agent & Smart Batching Architecture

1. **Multimodal Vision Agent (`qwen3-vl-plus`):** Extracts and verifies structured observations from the 11 PNG application screenshots (`evidence_04`, `evidence_12`, `evidence_21`, `evidence_29`, `evidence_37`, `evidence_45`, `evidence_54`, `evidence_62`, `evidence_71`, `evidence_80`, `evidence_88`) with deterministic schema validation (`transcription_validator.py`) and rule decoding (`multimodal_rules.py`).
2. **Intent & Unstructured Document Agent (`qwen3.7-max`):** Classifies all distinct multilingual/nuanced `request_text` templates in smart batches (`DELETE` vs `NOT_APPLICABLE`) and analyzes unstructured handover/compliance documents (`customer_account_handover_20261001.txt`, PDFs).
3. **Audit Orchestrator Agent with Tool-Calling (`qwen3.7-max`):** Invokes structured tools (`resolve_subject_identities`, `query_system_inventory`, `reconstruct_resource_states`, `build_compliant_remediation_plan`) across audit cohorts and adjudicates reconstructed case plans in batched calls (`batch_size=65`), while deterministic `RulesEngine` and `PlannerSorter` guardrails guarantee 100% contract compliance (`FINDING` -> `REMEDIATION` -> `VERIFICATION`).

## Notes

- All model calls and token counts are recorded in `code/data/usage_log.jsonl` via `code/src/evaluation/metering.py`.
- Costs are calculated from the official rates in `.pricing.json` (`qwen3.7-max`: $2.50/1M input, $7.50/1M output; `qwen3-vl-plus`: $0.20/1M input, $1.60/1M output).
- No API keys, credentials, or sensitive configuration values are included.
