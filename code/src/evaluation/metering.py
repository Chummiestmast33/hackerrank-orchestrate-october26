"""LLM/VLM call accounting and usage reporting (AGENTS.md section 6.8).

Records provider, model, purpose and token usage per model call to a JSONL log,
summarises per model and overall, and renders ``evaluation/usage_report.md``.
Cached calls are counted separately and excluded from token/cost totals. No
secrets or configuration values are ever written to the reports.
"""

import json
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import (
    DEFAULT_REQUEST_COUNT,
    USAGE_LOG_PATH,
    ModelPricing,
    load_pricing,
    resolve_pricing,
)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class UsageRecord:
    run_id: str
    timestamp: str
    provider: str
    model: str
    purpose: str
    input_tokens: int
    output_tokens: int
    cached: bool

    def to_json(self) -> str:
        return json.dumps(
            {
                "run_id": self.run_id,
                "timestamp": self.timestamp,
                "provider": self.provider,
                "model": self.model,
                "purpose": self.purpose,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "cached": self.cached,
            }
        )

    @classmethod
    def from_json(cls, line: str) -> "UsageRecord":
        data = json.loads(line)
        return cls(
            run_id=data["run_id"],
            timestamp=data["timestamp"],
            provider=data["provider"],
            model=data["model"],
            purpose=data["purpose"],
            input_tokens=int(data["input_tokens"]),
            output_tokens=int(data["output_tokens"]),
            cached=bool(data["cached"]),
        )


def _attr(obj: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if isinstance(obj, Mapping):
            if name in obj:
                return obj[name]
        elif hasattr(obj, name):
            return getattr(obj, name)
    return None


def extract_usage(response: Any) -> tuple[int, int]:
    """Read (input_tokens, output_tokens) from Gemini/OpenAI/Anthropic responses."""
    meta = _attr(response, ("usage_metadata",))
    usage = _attr(response, ("usage",))
    if meta is not None:
        input_tokens = _attr(meta, ("prompt_token_count", "input_tokens"))
        output_tokens = _attr(meta, ("candidates_token_count", "output_tokens"))
        if input_tokens is None or output_tokens is None:
            raise ValueError(f"unrecognised Gemini usage_metadata payload: {meta!r}")
        return int(input_tokens), int(output_tokens)
    if usage is not None:
        input_tokens = _attr(usage, ("prompt_tokens", "input_tokens"))
        output_tokens = _attr(usage, ("completion_tokens", "output_tokens"))
        if input_tokens is None or output_tokens is None:
            raise ValueError(f"unrecognised usage payload: {usage!r}")
        return int(input_tokens), int(output_tokens)
    raise ValueError(f"response object carries no usage information: {type(response).__name__}")


@dataclass
class CallHandle:
    provider: str
    model: str
    purpose: str
    cached: bool = False
    input_tokens: int = 0
    output_tokens: int = 0

    def capture(self, response: Any) -> None:
        self.input_tokens, self.output_tokens = extract_usage(response)

    def set_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class Meter:
    """Append-only JSONL usage logger."""

    def __init__(self, log_path: Path | None = None, run_id: str | None = None) -> None:
        self.log_path = log_path or USAGE_LOG_PATH
        self.run_id = run_id or f"run-{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}"

    def record(
        self,
        provider: str,
        model: str,
        purpose: str,
        input_tokens: int,
        output_tokens: int,
        cached: bool = False,
    ) -> UsageRecord:
        entry = UsageRecord(
            run_id=self.run_id,
            timestamp=_now_iso(),
            provider=provider,
            model=model,
            purpose=purpose,
            input_tokens=0 if cached else int(input_tokens),
            output_tokens=0 if cached else int(output_tokens),
            cached=cached,
        )
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(entry.to_json() + "\n")
        return entry

    @contextmanager
    def track_call(
        self, provider: str, model: str, purpose: str, cached: bool = False
    ) -> Iterator[CallHandle]:
        handle = CallHandle(provider=provider, model=model, purpose=purpose, cached=cached)
        try:
            yield handle
        finally:
            self.record(
                provider,
                model,
                purpose,
                handle.input_tokens,
                handle.output_tokens,
                cached=handle.cached or cached,
            )


@contextmanager
def metered_call(
    meter: Meter, provider: str, model: str, purpose: str, cached: bool = False
) -> Iterator[CallHandle]:
    """Plan-facing alias for :meth:`Meter.track_call`."""
    with meter.track_call(provider=provider, model=model, purpose=purpose, cached=cached) as handle:
        yield handle


@dataclass
class ModelSummary:
    provider: str
    model: str
    calls: int = 0
    cached_calls: int = 0
    uncached_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    priced: bool = False
    cost_usd: float | None = None

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class UsageSummary:
    run_id: str | None
    generated_at: str
    request_count: int
    models: list[ModelSummary] = field(default_factory=list)
    unpriced_models: list[str] = field(default_factory=list)

    @property
    def calls(self) -> int:
        return sum(m.calls for m in self.models)

    @property
    def cached_calls(self) -> int:
        return sum(m.cached_calls for m in self.models)

    @property
    def input_tokens(self) -> int:
        return sum(m.input_tokens for m in self.models)

    @property
    def output_tokens(self) -> int:
        return sum(m.output_tokens for m in self.models)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def fully_priced(self) -> bool:
        return not self.unpriced_models and all(m.priced for m in self.models)

    @property
    def total_cost_usd(self) -> float | None:
        if not self.fully_priced:
            return None
        return sum(m.cost_usd or 0.0 for m in self.models)

    @property
    def avg_tokens_per_request(self) -> float:
        return self.total_tokens / self.request_count if self.request_count else 0.0

    @property
    def cost_per_request_usd(self) -> float | None:
        total = self.total_cost_usd
        if total is None or not self.request_count:
            return None
        return total / self.request_count


def summarize(
    log_path: Path | None = None,
    run_id: str | None = None,
    request_count: int = DEFAULT_REQUEST_COUNT,
    pricing: Mapping[str, ModelPricing] | None = None,
) -> UsageSummary:
    path = log_path or USAGE_LOG_PATH
    active_pricing = load_pricing() if pricing is None else pricing
    summary = UsageSummary(run_id=run_id, generated_at=_now_iso(), request_count=request_count)
    by_model: dict[tuple[str, str], ModelSummary] = {}
    if path.exists():
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                entry = UsageRecord.from_json(line)
                if run_id is not None and entry.run_id != run_id:
                    continue
                model_summary = by_model.setdefault(
                    (entry.provider, entry.model),
                    ModelSummary(provider=entry.provider, model=entry.model),
                )
                model_summary.calls += 1
                if entry.cached:
                    model_summary.cached_calls += 1
                else:
                    model_summary.uncached_calls += 1
                    model_summary.input_tokens += entry.input_tokens
                    model_summary.output_tokens += entry.output_tokens
    models = sorted(by_model.values(), key=lambda m: (m.provider, m.model))
    for model_summary in models:
        price = resolve_pricing(active_pricing, model_summary.provider, model_summary.model)
        if price is None:
            summary.unpriced_models.append(f"{model_summary.provider}/{model_summary.model}")
        else:
            model_summary.priced = True
            model_summary.cost_usd = (
                model_summary.input_tokens / 1_000_000 * price.input_per_1m
                + model_summary.output_tokens / 1_000_000 * price.output_per_1m
            )
    summary.models = models
    return summary


def render_usage_report(summary: UsageSummary, path: Path) -> Path:
    lines = [
        "# Usage Report -- Deletion Audit Agent",
        "",
        f"- Run id: `{summary.run_id or 'all runs'}`",
        f"- Generated at (UTC): {summary.generated_at}",
        f"- Request denominator: {summary.request_count}",
        "",
        "## Model providers and model names",
        "",
    ]
    if not summary.models:
        lines += ["Deterministic-only run: 0 model calls.", ""]
    else:
        for model in summary.models:
            lines.append(f"- `{model.provider}` / `{model.model}`")
        lines.append("")
    lines += [
        "## Model-call counts",
        "",
        f"- Total calls: {summary.calls}",
        f"- Uncached calls: {summary.calls - summary.cached_calls}",
        f"- Cache-hit calls (0 tokens recorded): {summary.cached_calls}",
        "",
        "## Input and output tokens",
        "",
        f"- Input tokens: {summary.input_tokens}",
        f"- Output tokens: {summary.output_tokens}",
        f"- Total tokens: {summary.total_tokens}",
        "",
        "## Tokens per request",
        "",
        f"- Total tokens per request (denominator {summary.request_count}): {summary.avg_tokens_per_request:.2f}",
        "",
        "## Estimated cost",
        "",
    ]
    total_cost = summary.total_cost_usd
    if total_cost is None:
        unpriced = ", ".join(summary.unpriced_models) if summary.unpriced_models else "n/a"
        lines.append(
            f"- Estimated total cost: null (unpriced models: {unpriced}; "
            "supply official provider pricing via DELETION_AUDIT_PRICING_JSON)"
        )
        lines.append("- Estimated cost per request: null")
    else:
        lines.append(f"- Estimated total cost: ${total_cost:.6f}")
        lines.append(f"- Estimated cost per request: ${summary.cost_per_request_usd or 0.0:.8f}")
    lines += ["", "## Per-model totals", ""]
    if summary.models:
        lines += [
            "| provider | model | calls | cached | input tokens | output tokens | total tokens | cost (USD) |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for model in summary.models:
            cost = "null" if model.cost_usd is None else f"{model.cost_usd:.6f}"
            lines.append(
                f"| {model.provider} | {model.model} | {model.calls} | {model.cached_calls} "
                f"| {model.input_tokens} | {model.output_tokens} | {model.total_tokens} | {cost} |"
            )
        lines.append("")
    lines += [
        "## Overall totals",
        "",
        f"- Calls: {summary.calls} (cached {summary.cached_calls})",
        f"- Tokens: {summary.total_tokens} (input {summary.input_tokens} / output {summary.output_tokens})",
        f"- Cost: {'null' if total_cost is None else f'${total_cost:.6f}'}",
        "",
        "_No API keys, credentials or sensitive configuration values are included in this report._",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
