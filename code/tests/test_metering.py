"""Tests for token/cost accounting and usage reporting (P2.9)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.config import ModelPricing
from src.evaluation import metering


def gemini_response() -> SimpleNamespace:
    return SimpleNamespace(
        usage_metadata=SimpleNamespace(prompt_token_count=100, candidates_token_count=50)
    )


def openai_response() -> SimpleNamespace:
    return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=200, completion_tokens=80))


def openai_responses_api() -> SimpleNamespace:
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=300, output_tokens=90))


def anthropic_response() -> SimpleNamespace:
    return SimpleNamespace(usage=SimpleNamespace(input_tokens=400, output_tokens=120))


def test_asymmetric_pricing_cost_exact(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    meter = metering.Meter(log_path=log, run_id="run-p")
    meter.record("openai", "gpt-5", "vlm", 2_000_000, 1_000_000)
    pricing = {"openai/gpt-5": ModelPricing(input_per_1m=2.0, output_per_1m=5.0)}
    summary = metering.summarize(log_path=log, request_count=4, pricing=pricing)
    model = summary.models[0]
    assert model.cost_usd == pytest.approx(2_000_000 / 1e6 * 2.0 + 1_000_000 / 1e6 * 5.0)
    assert summary.total_cost_usd == pytest.approx(9.0)
    assert summary.cost_per_request_usd == pytest.approx(9.0 / 4)


def test_track_call_cached_records_zero_tokens(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    meter = metering.Meter(log_path=log, run_id="run-c")
    with meter.track_call("gemini", "gemini-2.5-pro", "intent", cached=True) as handle:
        handle.capture(gemini_response())
    entry = json.loads(log.read_text(encoding="utf-8").strip())
    assert entry["cached"] is True and entry["input_tokens"] == 0 and entry["output_tokens"] == 0
    summary = metering.summarize(log_path=log, request_count=10)
    assert summary.calls == 1 and summary.cached_calls == 1 and summary.total_tokens == 0


def test_report_contains_exact_token_lines(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    _seed(log)
    summary = metering.summarize(log_path=log, request_count=518, pricing={})
    path = metering.render_usage_report(summary, tmp_path / "usage_report.md")
    text = path.read_text(encoding="utf-8")
    assert "- Input tokens: 3000" in text
    assert "- Output tokens: 1300" in text
    assert "- Total tokens: 4300" in text
    assert "- Total calls: 3" in text
    assert "- Uncached calls: 2" in text
    assert "- Cache-hit calls (0 tokens recorded): 1" in text
    assert "| gemini | gemini-2.5-pro | 2 | 1 | 1000 | 500 | 1500 | null |" in text


def test_zero_request_count_no_division_error(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    _seed(log)
    summary = metering.summarize(log_path=log, request_count=0, pricing={})
    assert summary.avg_tokens_per_request == 0.0
    assert summary.cost_per_request_usd is None


def test_record_appends_jsonl(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    meter = metering.Meter(log_path=log, run_id="run-x")
    meter.record("gemini", "gemini-2.5-pro", "intent", 10, 5)
    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["run_id"] == "run-x" and entry["input_tokens"] == 10 and entry["cached"] is False


def test_extract_usage_provider_shapes() -> None:
    assert metering.extract_usage(gemini_response()) == (100, 50)
    assert metering.extract_usage(openai_response()) == (200, 80)
    assert metering.extract_usage(openai_responses_api()) == (300, 90)
    assert metering.extract_usage(anthropic_response()) == (400, 120)
    assert metering.extract_usage({"usage": {"prompt_tokens": 7, "completion_tokens": 3}}) == (7, 3)


def test_extract_usage_unknown_raises() -> None:
    with pytest.raises(ValueError):
        metering.extract_usage(SimpleNamespace(nothing=True))


def test_track_call_captures_tokens(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    meter = metering.Meter(log_path=log, run_id="run-y")
    with meter.track_call("openai", "gpt-5", "vlm") as handle:
        handle.capture(openai_response())
    entry = json.loads(log.read_text(encoding="utf-8").strip())
    assert entry["input_tokens"] == 200 and entry["output_tokens"] == 80


def test_cached_calls_record_zero_tokens(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    meter = metering.Meter(log_path=log, run_id="run-z")
    meter.record("gemini", "gemini-2.5-pro", "intent", 100, 50, cached=True)
    entry = json.loads(log.read_text(encoding="utf-8").strip())
    assert entry["input_tokens"] == 0 and entry["cached"] is True


def _seed(log: Path) -> None:
    meter = metering.Meter(log_path=log, run_id="run-a")
    meter.record("gemini", "gemini-2.5-pro", "intent", 1000, 500)
    meter.record("gemini", "gemini-2.5-pro", "intent", 0, 0, cached=True)
    meter.record("openai", "gpt-5", "vlm", 2000, 800)


def test_summarize_multi_model_and_cost(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    _seed(log)
    pricing = {
        "gemini/gemini-2.5-pro": ModelPricing(input_per_1m=1.25, output_per_1m=10.0),
        "openai/gpt-5": ModelPricing(input_per_1m=1.25, output_per_1m=10.0),
    }
    summary = metering.summarize(log_path=log, request_count=518, pricing=pricing)
    assert summary.calls == 3 and summary.cached_calls == 1
    gemini = [m for m in summary.models if m.provider == "gemini"][0]
    assert gemini.input_tokens == 1000 and gemini.output_tokens == 500
    assert gemini.cost_usd == pytest.approx(1000 / 1e6 * 1.25 + 500 / 1e6 * 10.0)
    assert summary.total_tokens == 4300
    assert summary.avg_tokens_per_request == pytest.approx(4300 / 518)
    assert summary.total_cost_usd == pytest.approx(3000 / 1e6 * 1.25 + 1300 / 1e6 * 10.0)
    assert summary.cost_per_request_usd == pytest.approx((summary.total_cost_usd or 0) / 518)


def test_summarize_unpriced_models(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    _seed(log)
    summary = metering.summarize(log_path=log, request_count=518, pricing={})
    assert summary.unpriced_models == ["gemini/gemini-2.5-pro", "openai/gpt-5"]
    assert summary.total_cost_usd is None


def test_summarize_run_id_filter_and_empty(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    _seed(log)
    filtered = metering.summarize(log_path=log, run_id="nope")
    assert filtered.calls == 0
    empty = metering.summarize(log_path=tmp_path / "missing.jsonl")
    assert empty.calls == 0 and empty.models == []


def test_render_usage_report_sections(tmp_path: Path) -> None:
    log = tmp_path / "usage_log.jsonl"
    _seed(log)
    summary = metering.summarize(log_path=log, request_count=518, pricing={})
    path = metering.render_usage_report(summary, tmp_path / "usage_report.md")
    text = path.read_text(encoding="utf-8")
    for heading in (
        "## Model providers and model names",
        "## Model-call counts",
        "## Input and output tokens",
        "## Tokens per request",
        "## Estimated cost",
        "## Per-model totals",
        "## Overall totals",
    ):
        assert heading in text
    assert "null" in text


def test_render_usage_report_empty_log_states_deterministic(tmp_path: Path) -> None:
    summary = metering.summarize(log_path=tmp_path / "none.jsonl", request_count=518, pricing={})
    path = metering.render_usage_report(summary, tmp_path / "usage_report.md")
    text = path.read_text(encoding="utf-8")
    assert "Deterministic-only run: 0 model calls." in text


def test_report_contains_no_secret_like_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-value")
    log = tmp_path / "usage_log.jsonl"
    _seed(log)
    summary = metering.summarize(log_path=log, request_count=518, pricing={})
    path = metering.render_usage_report(summary, tmp_path / "usage_report.md")
    assert "super-secret-value" not in path.read_text(encoding="utf-8")
