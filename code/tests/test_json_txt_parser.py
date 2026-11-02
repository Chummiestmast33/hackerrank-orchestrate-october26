"""Unit tests for the JSON and handover-text parser (P3.5)."""

import json
from pathlib import Path

from src.loaders.json_txt_parser import json_family, parse_json_txt_file
from src.models import ObservationState, ParseStatus

CAPTURED = "2026-09-15T12:00:00Z"


def write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_json_family_detection() -> None:
    assert json_family("records/customer_data_snapshot_bundle_20260915.json") == "snapshot_bundle"
    assert json_family("records/service_resource_export_20260915_114455.json") == "service_export"
    assert json_family("records/connector_configurations_20260812.json") == "ledger"
    assert json_family("records/customer_export_jobs_20260914.json") == "export_jobs"
    assert json_family("records/customer_analytics_report_20260907.json") == "analytics_report"
    assert json_family("records/customer_account_handover_20261001.txt") == "handover"
    assert json_family("records/unknown.json") == "unknown"


def test_bundle_states_and_captured_collections(tmp_path: Path) -> None:
    payload = {
        "exported_at": CAPTURED,
        "source": "records_assurance_service",
        "snapshots": [
            {
                "captured_at": CAPTURED,
                "data_store": "account_service",
                "collection": "customer_profiles",
                "records": [],
            },
            {
                "captured_at": CAPTURED,
                "data_store": "identity_service",
                "collection": "deleted_customer_references",
                "records": [
                    {
                        "resource_id": "tombstone_1",
                        "subject_reference": "user_1",
                        "name": None,
                        "email": None,
                        "phone": None,
                        "email_hash": None,
                    },
                    {
                        "resource_id": "tombstone_2",
                        "subject_reference": "user_2",
                        "name": "Leak",
                        "email": "l@x",
                        "phone": None,
                        "email_hash": None,
                    },
                ],
            },
            {
                "captured_at": CAPTURED,
                "data_store": "analytics_platform",
                "collection": "customer_analytics_reports",
                "records": [
                    {
                        "resource_id": "analytics_1",
                        "user_id": None,
                        "email": None,
                        "phone": None,
                        "email_hash": None,
                    }
                ],
            },
            {
                "captured_at": CAPTURED,
                "data_store": "x",
                "collection": "weird_collection",
                "records": [],
            },
        ],
    }
    path = write_json(tmp_path / "customer_data_snapshot_bundle_20260915.json", payload)
    observations, report = parse_json_txt_file("evidence_51", path, CAPTURED)
    states = {obs.resource_id: obs.state for obs in observations}
    assert states["tombstone_1"] is ObservationState.REDACTED
    assert states["tombstone_2"] is ObservationState.PRESENT
    assert states["analytics_1"] is ObservationState.ANONYMIZED
    assert any("unknown_collection:weird_collection" in error for error in report.errors)
    assert report.status is ParseStatus.UNKNOWN_STATE
    captured = {(c.data_store, c.collection, c.record_count) for c in report.captured_collections}
    assert ("account_service", "customer_profiles", 0) in captured
    assert any(obs.resource_id == "tombstone_2" and obs.pii_exposed for obs in observations)


def test_service_export_shapes(tmp_path: Path) -> None:
    payload = {
        "exported_at": CAPTURED,
        "service_exports": {
            "account_service": {
                "profile_lookups": [
                    {
                        "observed_at": CAPTURED,
                        "profile": None,
                        "resource_id": "account_1",
                        "status_code": 404,
                    },
                    {
                        "observed_at": CAPTURED,
                        "profile": {
                            "customer_reference": "user_2",
                            "email": "b@x",
                            "full_name": "B",
                            "phone": None,
                            "email_hash": None,
                        },
                        "resource_id": "account_2",
                        "status_code": 200,
                    },
                    {
                        "observed_at": CAPTURED,
                        "profile": None,
                        "resource_id": "account_3",
                        "status_code": 200,
                    },
                ]
            },
            "analytics_platform": {
                "profiles": [
                    {
                        "resource_id": "analytics_1",
                        "customer_reference": None,
                        "email": None,
                        "phone": None,
                        "email_hash": None,
                    }
                ]
            },
            "integration_service": {
                "connectors": [
                    {"resource_id": "data_flow_1", "enabled": True, "customer_email": "a@x"}
                ]
            },
            "backup_service": {
                "restore_entries": [{"resource_id": "backup_1", "restore_allowed": False}]
            },
            "search_service": {
                "index_queries": [
                    {"resource_id": "search_1", "hits": 0},
                    {"resource_id": "search_2", "hits": 2},
                ]
            },
            "support_platform": {
                "tickets": [
                    {
                        "resource_id": "support_1",
                        "requester_name": None,
                        "requester_email": None,
                        "requester_phone": None,
                    }
                ]
            },
            "unknown_service": {"x": []},
        },
    }
    path = write_json(tmp_path / "service_resource_export_20260915_114455.json", payload)
    observations, report = parse_json_txt_file("evidence_92", path, CAPTURED)
    states = {obs.resource_id: obs.state for obs in observations}
    assert states["account_1"] is ObservationState.ABSENT
    assert states["account_2"] is ObservationState.PRESENT
    assert states["account_3"] is ObservationState.UNKNOWN
    assert states["analytics_1"] is ObservationState.ANONYMIZED
    assert states["data_flow_1"] is ObservationState.ACTIVE
    assert states["backup_1"] is ObservationState.BLOCKED
    assert states["search_1"] is ObservationState.ABSENT
    assert states["search_2"] is ObservationState.PRESENT
    assert states["support_1"] is ObservationState.REDACTED
    assert any("unknown_service:unknown_service" in error for error in report.errors)
    assert report.status is ParseStatus.UNKNOWN_STATE


def test_search_export_nested_hits(tmp_path: Path) -> None:
    payload = {
        "exported_at": CAPTURED,
        "service_exports": {
            "search_service": {
                "index_queries": [
                    {
                        "resource_id": "search_1",
                        "observed_at": CAPTURED,
                        "hits": {
                            "total": 1,
                            "documents": [{"email": "a@x", "resource_id": "search_1"}],
                        },
                    },
                    {
                        "resource_id": "search_2",
                        "observed_at": CAPTURED,
                        "hits": {"total": 0, "documents": []},
                    },
                    {"resource_id": "search_3", "observed_at": CAPTURED},
                ]
            }
        },
    }
    path = write_json(tmp_path / "service_resource_export_20260129_114459.json", payload)
    observations, report = parse_json_txt_file("evidence_62", path, CAPTURED)
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["search_1"].state is ObservationState.PRESENT
    assert by_id["search_1"].pii_exposed is True
    assert "a@x" in by_id["search_1"].identifiers
    assert by_id["search_2"].state is ObservationState.ABSENT
    assert by_id["search_3"].state is ObservationState.UNKNOWN
    assert report.status is ParseStatus.UNKNOWN_STATE


def test_ledger_result_mapping(tmp_path: Path) -> None:
    payload = {
        "exported_at": CAPTURED,
        "origin": "security_audit_service",
        "record_count": 3,
        "records": [
            {
                "recorded_at": CAPTURED,
                "system": "account_service",
                "resource_id": "account_1",
                "record_type": "USER_PROFILE",
                "result": "FOUND",
                "subject_reference": "a@x",
            },
            {
                "recorded_at": CAPTURED,
                "system": "search_service",
                "resource_id": "search_1",
                "record_type": "SEARCH_INDEX_ENTRY",
                "result": "NOT_FOUND",
                "subject_reference": "a@x",
            },
            {
                "recorded_at": CAPTURED,
                "system": "backup_service",
                "resource_id": "backup_1",
                "record_type": "BACKUP_ARCHIVE",
                "result": "MAYBE",
                "subject_reference": "user_1",
            },
        ],
    }
    path = write_json(tmp_path / "security_audit_ledger_20261001.json", payload)
    observations, report = parse_json_txt_file("evidence_95", path, CAPTURED)
    states = {obs.resource_id: obs.state for obs in observations}
    assert states["account_1"] is ObservationState.PRESENT
    assert states["search_1"] is ObservationState.ABSENT
    assert states["backup_1"] is ObservationState.UNKNOWN
    assert all(obs.provenance.value == "LEDGER_RESULT" for obs in observations)
    assert report.status is ParseStatus.UNKNOWN_STATE


def test_export_jobs_and_analytics_report(tmp_path: Path) -> None:
    jobs = write_json(
        tmp_path / "customer_export_jobs_20260914.json",
        {
            "captured_at": CAPTURED,
            "source": "user_export_store",
            "collection": "customer_export_jobs",
            "records": [{"resource_id": "export_1", "owner_email": "a@x"}],
        },
    )
    observations, report = parse_json_txt_file("evidence_59", jobs, CAPTURED)
    assert report.status is ParseStatus.OK
    assert observations[0].state is ObservationState.PRESENT
    assert observations[0].data_category == "USER_EXPORT"
    assert observations[0].identifiers == ("a@x",)

    analytics = write_json(
        tmp_path / "customer_analytics_report_20260907.json",
        {
            "captured_at": CAPTURED,
            "source": "analytics_identity_store",
            "collection": "customer_analytics_reports",
            "records": [
                {"resource_id": "analytics_1", "email": "a@x", "phone": None, "email_hash": None},
                {"resource_id": "analytics_2", "email": None, "phone": None, "email_hash": None},
            ],
        },
    )
    observations, report = parse_json_txt_file("evidence_56", analytics, CAPTURED)
    states = {obs.resource_id: obs.state for obs in observations}
    assert states["analytics_1"] is ObservationState.PRESENT
    assert states["analytics_2"] is ObservationState.ANONYMIZED


def test_handover_text(tmp_path: Path) -> None:
    text = "\n".join(
        [
            "CUSTOMER PLATFORM - SHIFT HANDOVER",
            "Snapshot: 2026-10-01T12:00:00Z",
            "",
            "- 2026-10-01T12:00:00Z | account_service | account_1 | USER_PROFILE | NOT_FOUND | a@x",
            "- 2026-10-01T12:00:00Z | analytics_platform | analytics_1 | ANALYTICS_PROFILE | ANONYMIZED |",
            "- 2026-10-01T12:00:00Z | integration_service | data_flow_1 | DATA_FLOW | PAUSED | user_9",
            "- malformed record without pipes",
        ]
    )
    path = tmp_path / "customer_account_handover_20261001.txt"
    path.write_text(text, encoding="utf-8")
    observations, report = parse_json_txt_file("evidence_03", path, CAPTURED)
    states = {obs.resource_id: obs.state for obs in observations}
    assert states["account_1"] is ObservationState.ABSENT
    assert states["analytics_1"] is ObservationState.ANONYMIZED
    assert states["data_flow_1"] is ObservationState.UNKNOWN
    assert observations[0].provenance.value == "HANDOVER"
    assert any("malformed record line" in error for error in report.errors)
    assert report.ignored_lines == 3  # two header lines and one blank line
    assert report.status is ParseStatus.UNKNOWN_STATE


def test_invalid_json_is_parse_error(tmp_path: Path) -> None:
    path = tmp_path / "customer_data_snapshot_bundle_20260101.json"
    path.write_text("{not json", encoding="utf-8")
    observations, report = parse_json_txt_file("evidence_bad", path, CAPTURED)
    assert observations == []
    assert report.status is ParseStatus.PARSE_ERROR
    assert any("json_error" in error for error in report.errors)


def test_non_object_json_is_parse_error(tmp_path: Path) -> None:
    path = write_json(tmp_path / "connector_configurations_20260101.json", [1, 2, 3])
    observations, report = parse_json_txt_file("evidence_list", path, CAPTURED)
    assert observations == []
    assert report.status is ParseStatus.PARSE_ERROR


def test_unknown_family_json(tmp_path: Path) -> None:
    path = write_json(tmp_path / "mystery_20260101.json", {})
    observations, report = parse_json_txt_file("evidence_mystery", path, CAPTURED)
    assert observations == []
    assert report.status is ParseStatus.UNKNOWN_STATE
    assert any("unrecognized_json_family" in error for error in report.errors)
