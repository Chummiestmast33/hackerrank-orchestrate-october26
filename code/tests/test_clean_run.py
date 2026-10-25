"""Clean-run regression tests: the pipeline must bootstrap its evidence cache offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sample_expectations import (
    EXPECTED_SAMPLE_CASES,
    EXPECTED_SEQUENCE_CORRECT,
    EXPECTED_STATUS_CORRECT,
    KNOWN_EVIDENCE_GAP,
)
from src.core.pipeline import Pipeline
from src.core.planner_sorter import PlannerSorter
from src.evaluation.evaluator import evaluate, load_cases
from src.evaluation.schema import validate_file
from src.loaders import multimodal_parser
from src.loaders.cache import build_census
from src.loaders.cache_bootstrap import CacheBuildError, ensure_evidence_cache
from src.loaders.csv_loader import EvidenceFileRow, load_deletion_requests
from src.models import ObservationState, Provenance, ReconstructedResourceState

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"
SAMPLE_REQUESTS = DATASET_DIR / "sample_deletion_requests.csv"
SAMPLE_GOLD = DATASET_DIR / "sample_output.csv"
CENSUS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parsers" / "corpus_census.json"


def _assert_documented_sample_result(output_path: Path) -> None:
    metrics = evaluate(load_cases(SAMPLE_GOLD), load_cases(output_path))
    assert metrics.status_accuracy == 1.0
    assert sum(case.status_correct for case in metrics.cases.values()) == EXPECTED_STATUS_CORRECT
    assert sum(case.sequence_correct for case in metrics.cases.values()) == (
        EXPECTED_SEQUENCE_CORRECT
    )
    assert metrics.sequence_accuracy == pytest.approx(
        EXPECTED_SEQUENCE_CORRECT / EXPECTED_SAMPLE_CASES
    )
    assert {
        case_id for case_id, case in metrics.cases.items() if not case.sequence_correct
    } == KNOWN_EVIDENCE_GAP


@pytest.fixture(scope="module")
def clean_run(tmp_path_factory: pytest.TempPathFactory) -> tuple[Pipeline, Path, Path]:
    root = tmp_path_factory.mktemp("clean_run")
    cache_path = root / "parsed_evidence.json"
    if cache_path.exists():
        cache_path.unlink()
    output_path = root / "sample_output.csv"
    pipeline = Pipeline(dataset_dir=DATASET_DIR, cache_path=cache_path)
    pipeline.run(SAMPLE_REQUESTS, output_path)
    return pipeline, cache_path, output_path


def test_clean_cache_is_built_and_complete(
    clean_run: tuple[Pipeline, Path, Path],
) -> None:
    pipeline, cache_path, _output_path = clean_run
    assert cache_path.exists()
    assert pipeline.cache_result.stats.files == 94
    assert pipeline.cache_result.stats.observations == 2912
    assert pipeline.cache_result.stats.errors == 0
    assert pipeline.cache_result.stats.unsupported == 0

    census = build_census(pipeline.cache_result.entries)
    expected = json.loads(CENSUS_FIXTURE.read_text(encoding="utf-8"))
    assert census == expected


def test_clean_cache_reaches_sample_convergence(
    clean_run: tuple[Pipeline, Path, Path],
) -> None:
    _pipeline, _cache_path, output_path = clean_run
    _assert_documented_sample_result(output_path)


def test_full_dataset_output_is_schema_valid(
    clean_run: tuple[Pipeline, Path, Path],
    tmp_path: Path,
) -> None:
    pipeline, _cache_path, _output_path = clean_run
    output_path = tmp_path / "output.csv"
    pipeline.run(DATASET_DIR / "deletion_requests.csv", output_path)

    requests, _errors = load_deletion_requests(DATASET_DIR / "deletion_requests.csv")
    validation = validate_file(
        output_path,
        expected_case_ids=[request.case_id for request in requests],
    )
    assert validation.violations == []
    assert len(validation.rows) == 518


def test_complete_plan_omits_unproven_states() -> None:
    state = ReconstructedResourceState(
        resource_id="account_999",
        system_id="account_service",
        data_category="USER_PROFILE",
        observed_state=ObservationState.ABSENT,
        pii_exposed=False,
        evidence_id="",
        provenance=Provenance.SCOPE_IMPLICIT,
    )
    result = PlannerSorter().build_case_result(
        case_id="case_test",
        deletion_status="COMPLETE",
        states=[state],
        violations=[],
    )
    assert result.steps == ()


def test_second_run_reuses_cache(
    clean_run: tuple[Pipeline, Path, Path],
    tmp_path: Path,
) -> None:
    _pipeline, cache_path, first_output = clean_run
    second = Pipeline(dataset_dir=DATASET_DIR, cache_path=cache_path)
    assert second.cache_result.stats.hits == 94
    assert second.cache_result.stats.misses == 0

    second_output = tmp_path / "sample_output_second.csv"
    second.run(SAMPLE_REQUESTS, second_output)
    assert second_output.read_text(encoding="utf-8") == first_output.read_text(encoding="utf-8")


def test_malformed_cache_is_rebuilt(tmp_path: Path) -> None:
    cache_path = tmp_path / "parsed_evidence.json"
    cache_path.write_text("{broken", encoding="utf-8")
    pipeline = Pipeline(dataset_dir=DATASET_DIR, cache_path=cache_path)
    assert pipeline.cache_result.stats.misses == 94
    assert pipeline.cache_result.stats.errors == 0


def test_forced_rebuild_reparses_every_file(tmp_path: Path) -> None:
    cache_path = tmp_path / "parsed_evidence.json"
    Pipeline(dataset_dir=DATASET_DIR, cache_path=cache_path)
    rebuilt = Pipeline(
        dataset_dir=DATASET_DIR,
        cache_path=cache_path,
        rebuild_cache=True,
    )
    assert rebuilt.cache_result.stats.hits == 0
    assert rebuilt.cache_result.stats.misses == 94


def test_missing_transcription_store_fails_loudly(tmp_path: Path) -> None:
    with pytest.raises(CacheBuildError, match="transcription store missing"):
        Pipeline(
            dataset_dir=DATASET_DIR,
            cache_path=tmp_path / "parsed_evidence.json",
            transcription_store_path=tmp_path / "missing_store.json",
        )


def test_parse_error_fails_loudly(tmp_path: Path) -> None:
    manifest = [
        EvidenceFileRow(
            file_id="evidence_missing",
            file_path="evidence/missing.txt",
            origin="test",
            captured_at="2026-01-01T00:00:00Z",
        )
    ]
    with pytest.raises(CacheBuildError, match="evidence parsing failed"):
        ensure_evidence_cache(
            dataset_dir=tmp_path,
            cache_path=tmp_path / "parsed_evidence.json",
            manifest=manifest,
            activity=(),
            identities=(),
            audit_log=(),
        )


def test_clean_build_makes_no_model_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_on_model_call(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("clean cache build attempted a model call")

    monkeypatch.setattr(
        multimodal_parser,
        "transcribe_two_pass",
        fail_on_model_call,
    )
    pipeline = Pipeline(
        dataset_dir=DATASET_DIR,
        cache_path=tmp_path / "parsed_evidence.json",
    )
    assert pipeline.cache_result.stats.misses == 94
