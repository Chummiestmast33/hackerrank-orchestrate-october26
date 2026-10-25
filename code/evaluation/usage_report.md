# Usage Report -- Deletion Audit Agent

- Generated at (UTC): 2026-10-25T08:39:09+00:00
- Full-run request denominator: 518
- Usage log: `C:\Users\corte\Downloads\hackerrank-orchestrate-october26\code\cache\usage_log.jsonl`
- Pricing file: `C:\Users\corte\Downloads\hackerrank-orchestrate-october26\.pricing.json` (public values; no secrets)

## Full 518-Case Audit Run

The deterministic audit pipeline makes no model calls. All work is local parsing and rule evaluation.

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

## One-Time Phase 4 Multimodal Extraction

This setup run produced the committed transcription store and is not part of the 518-case audit.

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

## Notes

- The full audit run uses 0 input and 0 output tokens.
- Phase 4 extraction costs use the public prices supplied in `.pricing.json`.
- No API keys, credentials, or sensitive configuration values are included.
