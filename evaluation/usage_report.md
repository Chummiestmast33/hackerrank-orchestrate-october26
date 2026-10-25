# Usage Report -- Deletion Audit Agent

- Generated at (UTC): 2026-10-25T09:35:46+00:00
- Full-run request denominator: 518
- Usage log: `C:\Users\corte\Downloads\hackerrank-orchestrate-october26\code\cache\usage_log.jsonl`
- Pricing file: `C:\Users\corte\Downloads\hackerrank-orchestrate-october26\.pricing.json` (public values; no secrets)

## Configured Models & Official Pricing Rates

| provider | model | role | input rate ($ / 1M tokens) | output rate ($ / 1M tokens) |
|---|---|---|---:|---:|
| `qwen` | `qwen/qwen3.7-max` | Text / intent & reasoning fallback | $2.500000 | $7.500000 |
| `qwen` | `qwen/qwen3-vl-plus` | Multimodal PNG screenshot transcription (2-pass) | $0.200000 | $1.600000 |

## Full 518-Case Audit Run

The deterministic audit pipeline makes no runtime model calls. All 518 requests are resolved locally via deterministic parsers, cached transcriptions, and rule evaluation.

### Model providers and model names

Deterministic-only run: 0 model calls.

### Model-call counts

- Total calls: 0
- Uncached calls: 0
- Cache-hit calls: 0

### Input and output tokens

- Input tokens: 0
- Output tokens: 0
- Total tokens: 0
- Total tokens per request (denominator 518): 0.00

### Estimated cost

- Estimated total cost: $0.000000
- Estimated cost per request: $0.00000000

### Per-model totals

### Overall totals

- Calls: 0 (cached 0)
- Tokens: 0 (input 0 / output 0)
- Cost: $0.000000

## One-Time Phase 4 Multimodal Extraction (Amortized Across 518 Requests)

This one-time corpus indexing run produced the committed transcription store (`code/data/multimodal_transcriptions.json`) for all 11 PNG evidence files.

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
| `qwen` | `qwen/qwen3.7-max` | 0 | 0 | 0 | 0 | 0 | 0.00 | $0.000000 | $0.00000000 |
| `qwen` | `qwen/qwen3-vl-plus` | 22 | 0 | 50784 | 7702 | 58486 | 112.91 | $0.022480 | $0.00004340 |
| **OVERALL** | **All Models** | **22** | **0** | **50784** | **7702** | **58486** | **112.91** | **$0.022480** | **$0.00004340** |

## Corpus-Level Multimodal Caching & Batching Architecture

1. **Corpus-Level Indexing vs. Per-Request Invocation:** Instead of invoking a vision or text LLM per deletion request (which across 518 cases and 94 evidence files would require thousands of redundant calls), our pipeline decouples **Stage 1 (Evidence Ingestion)** from **Stage 2 (Case Audit)**.
2. **Two-Pass Visual Transcription (`qwen/qwen3-vl-plus`):** Only the 11 PNG application screenshots (`evidence_04`, `evidence_12`, `evidence_21`, `evidence_29`, `evidence_37`, `evidence_45`, `evidence_54`, `evidence_62`, `evidence_71`, `evidence_80`, `evidence_88`) require vision extraction. Each PNG was processed once using a 2-pass visual transcription protocol (`11 files * 2 passes = 22 calls`, 50,784 input tokens, 7,702 output tokens, total cost `$0.022480` or `$0.00004340` per request) and persisted in `code/data/multimodal_transcriptions.json`.
3. **Deterministic Text/Structured Parsing (`qwen/qwen3.7-max` at 0 Calls):** All 79 structured files (`.sql`, `.json`, `.log`, `.txt`), all 4 PDF documents (`pypdf`/`pdfplumber`), and all 518 multilingual `request_text` prompts are handled deterministically by our parsers and 6-language regex/activity `IntentClassifier`, requiring **0 calls** to `qwen/qwen3.7-max` (`$0.000000`).
4. **Offline Clean-Run Bootstrap (`cache_bootstrap.py`):** When `code/cache/parsed_evidence.json` is absent or invalidated by `PARSER_VERSION = "phase4-v2"`, `ensure_evidence_cache()` rebuilds all 94 file reports and 2,912 structured observations in ~0.8s using `code/data/multimodal_transcriptions.json` with **0 network or API calls**.

## Notes

- The final 518-case audit run executes in ~3.0 seconds with 0 runtime model calls, 0 input tokens, and 0 output tokens.
- Phase 4 multimodal extraction costs are computed from the public rates in `.pricing.json` (`qwen/qwen3.7-max`: $2.50/1M input, $7.50/1M output; `qwen/qwen3-vl-plus`: $0.20/1M input, $1.60/1M output).
- No API keys, credentials, or sensitive configuration values are included.
