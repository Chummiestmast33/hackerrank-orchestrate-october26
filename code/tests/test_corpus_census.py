"""Committed corpus-level tests (P3.8/P4.10).

These tests pin the current dataset's parse census, prove parse determinism and
cross-check every golden sample citation against the parsed observation states.
Four citations are explicitly exempt and documented: the scope-based absences
(case_01/case_02/case_04 on evidence_54, case_31 on evidence_51) are derived in
Phase 5 from ``report.scope`` / ``captured_collections`` metadata, not from row
observations. The former PDF exemption (case_07 -> evidence_58) is now a real
match through the multimodal parser.
"""

import csv
import json
from pathlib import Path

import pytest
from src.loaders.cache import build_census, parse_all
from src.loaders.csv_loader import load_activity, load_evidence_manifest
from src.loaders.transcription_store import DEFAULT_STORE_PATH
from src.models import ParseStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET = REPO_ROOT / "dataset"
CENSUS_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "parsers" / "corpus_census.json"

SCOPE_DEFERRED = {
    ("case_01", "evidence_54", "account_001"),
    ("case_02", "evidence_54", "account_002"),
    ("case_04", "evidence_54", "account_004"),
    ("case_31", "evidence_51", "account_4857"),
}


@pytest.fixture(scope="module")
def corpus():
    if not DATASET.exists():
        pytest.skip("dataset/ not available")
    manifest, errors = load_evidence_manifest(DATASET / "evidence_files.csv")
    assert errors == []
    activity, _activity_errors = load_activity(DATASET / "system_activity.csv")
    return parse_all(
        manifest,
        dataset_dir=DATASET,
        cache_path=None,
        persist=False,
        transcription_store_path=DEFAULT_STORE_PATH,
        activity=activity,
    )


def test_corpus_census_matches_committed_fixture(corpus) -> None:
    census = build_census(corpus.entries)
    expected = json.loads(CENSUS_FIXTURE.read_text(encoding="utf-8"))
    assert census == expected
    statuses = {
        entry.report.status for entry in corpus.entries.values() if entry.report is not None
    }
    assert statuses == {ParseStatus.OK}
    assert corpus.stats.files == 94
    assert corpus.stats.observations == 2912
    assert corpus.stats.errors == 0


def test_double_parse_is_deterministic(corpus) -> None:
    manifest, _errors = load_evidence_manifest(DATASET / "evidence_files.csv")
    activity, _activity_errors = load_activity(DATASET / "system_activity.csv")
    again = parse_all(
        manifest,
        dataset_dir=DATASET,
        cache_path=None,
        persist=False,
        transcription_store_path=DEFAULT_STORE_PATH,
        activity=activity,
    )
    first = {file_id: entry.to_dict() for file_id, entry in sorted(corpus.entries.items())}
    second = {file_id: entry.to_dict() for file_id, entry in sorted(again.entries.items())}
    assert first == second


def test_golden_citation_crosscheck(corpus) -> None:
    index: dict[str, dict[str, set[str]]] = {}
    for file_id, entry in corpus.entries.items():
        states: dict[str, set[str]] = {}
        for observation in entry.observations:
            states.setdefault(observation.resource_id, set()).add(observation.state.value)
        index[file_id] = states

    matched = mismatched = deferred = 0
    problems: list[tuple[str, str, str, str, list[str] | str]] = []
    with (DATASET / "sample_output.csv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            for step in json.loads(row["steps_json"]):
                file_id = step["evidence_id"]
                if not file_id:
                    continue
                resource_states = index.get(file_id, {}).get(step["resource_id"], set())
                if step["state"] in resource_states:
                    matched += 1
                elif (
                    not resource_states
                    and (row["case_id"], file_id, step["resource_id"]) in SCOPE_DEFERRED
                ):
                    deferred += 1
                else:
                    mismatched += 1
                    problems.append(
                        (
                            row["case_id"],
                            file_id,
                            step["resource_id"],
                            step["state"],
                            sorted(states),
                        )
                    )
    assert mismatched == 0, problems
    assert matched == 71
    assert deferred == 4


def test_all_reports_are_ok(corpus) -> None:
    for file_id, entry in corpus.entries.items():
        assert entry.report is not None
        assert entry.report.status is ParseStatus.OK, (file_id, entry.report.errors)
        assert entry.report.errors == []
