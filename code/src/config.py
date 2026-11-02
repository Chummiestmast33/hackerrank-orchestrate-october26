"""Minimal runtime configuration for the deletion-audit agent.

Paths are resolved relative to this file (AGENTS.md section 8). Official provider
pricing values for Qwen models are configured by default and can be overridden via
a JSON file pointed to by DELETION_AUDIT_PRICING_JSON or .pricing.json.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parent
CODE_DIR = _SRC_DIR.parent
REPO_ROOT = CODE_DIR.parent
DATASET_DIR = REPO_ROOT / "dataset"
EVIDENCE_DIR = DATASET_DIR / "evidence"
CACHE_DIR = CODE_DIR / "cache"
DATA_DIR = CODE_DIR / "data"

SAMPLE_REQUESTS_CSV = DATASET_DIR / "sample_deletion_requests.csv"
SAMPLE_OUTPUT_CSV = DATASET_DIR / "sample_output.csv"
EVAL_REQUESTS_CSV = DATASET_DIR / "deletion_requests.csv"
DEFAULT_PRICING_PATH = REPO_ROOT / ".pricing.json"
COMMITTED_USAGE_LOG_PATH = DATA_DIR / "usage_log.jsonl"

DEFAULT_REQUEST_COUNT = 518


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv  # optional dependency
    except ImportError:  # pragma: no cover - exercised only without python-dotenv
        return
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file)


_load_dotenv()

EVALUATION_DIR = Path(os.environ.get("DELETION_AUDIT_REPORT_DIR", str(REPO_ROOT / "evaluation")))
EVALUATION_REPORT_PATH = EVALUATION_DIR / "evaluation_report.md"
USAGE_REPORT_PATH = EVALUATION_DIR / "usage_report.md"

_env_usage_log = os.environ.get("DELETION_AUDIT_USAGE_LOG")
if _env_usage_log:
    USAGE_LOG_PATH = Path(_env_usage_log)
elif (CACHE_DIR / "usage_log.jsonl").exists():
    USAGE_LOG_PATH = CACHE_DIR / "usage_log.jsonl"
else:
    USAGE_LOG_PATH = COMMITTED_USAGE_LOG_PATH


@dataclass(frozen=True)
class ModelPricing:
    """USD per 1M tokens; values must come from official provider pricing pages."""

    input_per_1m: float
    output_per_1m: float


PRICING: dict[str, ModelPricing] = {
    "qwen/qwen3.7-max": ModelPricing(input_per_1m=2.50000, output_per_1m=7.500000),
    "qwen/qwen3-vl-plus": ModelPricing(input_per_1m=0.200000, output_per_1m=1.600000),
    "qwen/deepseek-v4.1-flash": ModelPricing(input_per_1m=0.150000, output_per_1m=0.600000),
    "qwen3.7-max": ModelPricing(input_per_1m=2.50000, output_per_1m=7.500000),
    "qwen3-vl-plus": ModelPricing(input_per_1m=0.200000, output_per_1m=1.600000),
    "deepseek-v4.1-flash": ModelPricing(input_per_1m=0.150000, output_per_1m=0.600000),
}


def load_pricing(path: str | Path | None = None) -> dict[str, ModelPricing]:
    """Return the pricing table merged with optional JSON overrides.

    The JSON shape is ``{"<provider>/<model>": {"input_per_1m": x, "output_per_1m": y}}``.
    Unknown models simply stay unpriced; no value is ever fabricated.
    """
    pricing = dict(PRICING)
    override = path or os.environ.get("DELETION_AUDIT_PRICING_JSON")
    if not override and DEFAULT_PRICING_PATH.exists():
        override = DEFAULT_PRICING_PATH
    if override:
        data = json.loads(Path(override).read_text(encoding="utf-8"))
        for key, value in data.items():
            pricing[key] = ModelPricing(
                input_per_1m=float(value["input_per_1m"]),
                output_per_1m=float(value["output_per_1m"]),
            )
    return pricing


def resolve_pricing(
    pricing: Mapping[str, ModelPricing], provider: str, model: str
) -> ModelPricing | None:
    stripped = model.split("/", 1)[-1] if "/" in model else model
    for key in (
        f"{provider}/{model}",
        f"{provider}/{stripped}",
        f"{provider} {model}",
        model,
        stripped,
    ):
        found = pricing.get(key)
        if found is not None:
            return found
    return None
