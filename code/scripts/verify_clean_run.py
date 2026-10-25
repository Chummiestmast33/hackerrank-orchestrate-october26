"""Minimal clean-run and reproducibility verification.

Usage:
    python code/scripts/verify_clean_run.py
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = CODE_DIR.parent
if str(CODE_DIR) not in sys.path:
    sys.path.insert(0, str(CODE_DIR))

from src import config  # noqa: E402
from src.core.pipeline import Pipeline  # noqa: E402
from src.evaluation import evaluator, schema  # noqa: E402
from src.loaders.csv_loader import load_deletion_requests  # noqa: E402

DATASET_DIR = REPO_ROOT / "dataset"
SAMPLE_REQUESTS = DATASET_DIR / "sample_deletion_requests.csv"
SAMPLE_GOLD = DATASET_DIR / "sample_output.csv"
FULL_REQUESTS = DATASET_DIR / "deletion_requests.csv"
KNOWN_GAP = {"case_18", "case_20"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _usage_lines() -> int:
    path = config.USAGE_LOG_PATH
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"FAIL {name}: {detail}")
    print(f"PASS {name}" + (f" ({detail})" if detail else ""))


def main() -> int:
    usage_before = _usage_lines()
    with tempfile.TemporaryDirectory(prefix="deletion_audit_clean_run_") as temp_dir:
        root = Path(temp_dir)
        cache_path = root / "parsed_evidence.json"
        sample_first = root / "sample_first.csv"
        sample_second = root / "sample_second.csv"
        full_first = root / "full_first.csv"
        full_second = root / "full_second.csv"

        check("cache absent before clean run", not cache_path.exists())
        pipeline = Pipeline(dataset_dir=DATASET_DIR, cache_path=cache_path)
        check("cache created from manifest", cache_path.exists())
        check(
            "cache census",
            pipeline.cache_result.stats.files == 94
            and pipeline.cache_result.stats.observations == 2912
            and pipeline.cache_result.stats.errors == 0,
            f"files={pipeline.cache_result.stats.files} "
            f"observations={pipeline.cache_result.stats.observations} "
            f"errors={pipeline.cache_result.stats.errors}",
        )

        pipeline.run(SAMPLE_REQUESTS, sample_first)
        sample_metrics = evaluator.evaluate(
            evaluator.load_cases(SAMPLE_GOLD),
            evaluator.load_cases(sample_first),
        )
        check(
            "sample status accuracy",
            sample_metrics.status_accuracy == 1.0,
            f"{sum(c.status_correct for c in sample_metrics.cases.values())}/32",
        )
        mismatched = {
            case_id for case_id, case in sample_metrics.cases.items() if not case.sequence_correct
        }
        check(
            "sample sequence with documented gap",
            abs(sample_metrics.sequence_accuracy - 30 / 32) < 1e-9 and mismatched == KNOWN_GAP,
            f"sequence={sample_metrics.sequence_accuracy:.4f} mismatches={sorted(mismatched)}",
        )

        second_pipeline = Pipeline(dataset_dir=DATASET_DIR, cache_path=cache_path)
        check(
            "cache reused",
            second_pipeline.cache_result.stats.hits == 94
            and second_pipeline.cache_result.stats.misses == 0,
            f"hits={second_pipeline.cache_result.stats.hits} "
            f"misses={second_pipeline.cache_result.stats.misses}",
        )
        second_pipeline.run(SAMPLE_REQUESTS, sample_second)
        check(
            "sample output byte-identical on rerun",
            sample_first.read_bytes() == sample_second.read_bytes(),
            _sha256(sample_first),
        )

        second_pipeline.run(FULL_REQUESTS, full_first)
        requests, errors = load_deletion_requests(FULL_REQUESTS)
        check("full input has 518 requests", not errors and len(requests) == 518)
        validation = schema.validate_file(
            full_first,
            expected_case_ids=[request.case_id for request in requests],
        )
        check(
            "full output is schema-valid",
            validation.violations == [] and len(validation.rows) == 518,
            f"rows={len(validation.rows)} violations={len(validation.violations)}",
        )
        second_pipeline.run(FULL_REQUESTS, full_second)
        check(
            "full output byte-identical on rerun",
            full_first.read_bytes() == full_second.read_bytes(),
            _sha256(full_first),
        )

    usage_after = _usage_lines()
    check("no model calls", usage_after == usage_before, f"delta={usage_after - usage_before}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
