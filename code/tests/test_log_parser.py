"""Unit tests for the log evidence parser (P3.6)."""

from pathlib import Path

from src.loaders.log_parser import parse_line, parse_log_file, parse_tokens
from src.models import ObservationState, ParseStatus

CAPTURED = "2026-09-30T11:59:44Z"


def write_log(tmp_path: Path, *lines: str) -> Path:
    path = tmp_path / "service_events_test.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_parse_tokens_quoted_and_null() -> None:
    tokens = parse_tokens('a="x y" b=null c=3 d="q\\"z"')
    assert tokens == {"a": "x y", "b": "null", "c": "3", "d": 'q"z'}


def test_plain_shape_account_readback(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z level=INFO service=account_service "
        "event=profile_lookup_completed resource_id=account_1 rows=0 http_status=404",
        "2026-09-01T00:00:00Z level=INFO service=account_service "
        'event=profile_lookup_completed resource_id=account_2 rows=1 http_status=200 email="a@x"',
        "2026-09-01T00:00:00Z level=INFO service=account_service "
        "event=profile_lookup_completed resource_id=account_3 rows=1 http_status=200 "
        'email=null phone=null customer_reference="user_9"',
    )
    observations, report = parse_log_file("evidence_01", path, CAPTURED)
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["account_1"].state is ObservationState.ABSENT
    assert by_id["account_2"].state is ObservationState.PRESENT
    assert by_id["account_2"].pii_exposed is True
    assert by_id["account_3"].state is ObservationState.REDACTED
    assert by_id["account_1"].provenance.value == "READBACK"
    assert report.status is ParseStatus.OK


def test_support_events(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z level=INFO service=support_platform "
        "event=support_ticket_read_completed resource_id=support_1 "
        "requester_name=null requester_email=null requester_phone=null customer_reference=null",
        "2026-09-01T00:00:00Z level=INFO service=support_platform "
        "event=support_ticket_read_completed resource_id=support_2 "
        'requester_name=null requester_email="b@x" requester_phone=null',
        "2026-09-01T00:00:00Z level=INFO service=support_platform "
        'event=message_pii_scan resource_id=support_3 matched_value="c@x" detector=direct_identifier',
        "2026-09-01T00:00:00Z level=INFO service=support_replica "
        'event=contact_query_completed resource_id=support_4 rows=1 lookup_key="d@x"',
    )
    observations, report = parse_log_file("evidence_61", path, CAPTURED)
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["support_1"].state is ObservationState.REDACTED
    assert by_id["support_2"].state is ObservationState.PRESENT
    assert by_id["support_3"].state is ObservationState.PRESENT
    assert by_id["support_3"].pii_exposed is True
    assert by_id["support_4"].state is ObservationState.PRESENT
    assert report.status is ParseStatus.OK


def test_connector_backup_search_security_analytics(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z level=INFO service=integration_service "
        "event=connector_config_loaded resource_id=data_flow_1 enabled=true",
        "2026-09-01T00:00:00Z level=INFO service=backup_service "
        "event=restore_policy_read_completed resource_id=backup_1 restore_allowed=false",
        "2026-09-01T00:00:00Z level=INFO service=search_service "
        "event=index_query_completed resource_id=search_1 result=miss",
        "2026-09-01T00:00:00Z level=INFO service=security_service "
        'event=audit_record_read_completed resource_id=audit_record_1 rows=1 retention_until="2027-01-01"',
        "2026-09-01T00:00:00Z level=INFO service=analytics_platform "
        "event=analytics_profile_read resource_id=analytics_1 direct_identifiers=0",
        "2026-09-01T00:00:00Z level=INFO service=analytics_platform "
        "event=contact_lookup_completed resource_id=analytics_2 rows=1 email_opt_in=true",
        "2026-09-01T00:00:00Z level=INFO service=export_service "
        "event=export_download_check_completed resource_id=export_1 available=true",
        "2026-09-01T00:00:00Z level=INFO service=backup_service "
        "event=restore_authorization_completed resource_id=backup_2 decision=deny",
    )
    observations, _report = parse_log_file("evidence_x", path, CAPTURED)
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["data_flow_1"].state is ObservationState.ACTIVE
    assert by_id["backup_1"].state is ObservationState.BLOCKED
    assert by_id["search_1"].state is ObservationState.ABSENT
    assert by_id["audit_record_1"].state is ObservationState.PRESENT
    assert by_id["analytics_1"].state is ObservationState.ANONYMIZED
    assert by_id["analytics_2"].state is ObservationState.PRESENT
    assert by_id["export_1"].state is ObservationState.PRESENT
    assert by_id["backup_2"].state is ObservationState.BLOCKED


def test_generic_shapes(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z [INFO] [backup_service] [backup-1] "
        'restore_policy_read_completed: resource_id="backup_9" restore_allowed="true"',
        "2026-09-01T00:00:00Z | INFO | search_service | tr-1 | index_query_completed | "
        'resource_id="search_9" result="hit" total_hits="1"',
        '2026-09-01T00:00:00Z {"severity":"INFO","logger":"integration_service",'
        '"event":"connector_config_read_completed","resource_id":"data_flow_9","enabled":"true"}',
        "2026-09-01T00:00:00Z <15>1 node-1 security_service tr-1 - - level=INFO "
        'event="audit_record_read_completed" resource_id="audit_record_9" rows="1"',
    )
    observations, report = parse_log_file("evidence_y", path, CAPTURED)
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["backup_9"].state is ObservationState.ACTIVE
    assert by_id["search_9"].state is ObservationState.PRESENT
    assert by_id["data_flow_9"].state is ObservationState.ACTIVE
    assert by_id["audit_record_9"].state is ObservationState.PRESENT
    assert report.status is ParseStatus.OK


def test_cloud_runtime_shape_with_escaped_quotes(tmp_path: Path) -> None:
    line = (
        "2026-09-01T00:00:00Z requestId=collector-1 level=INFO function=log_router "
        'message="instance=\\"collector-1\\" event=\\"profile_lookup_completed\\" '
        'resource_id=\\"account_2\\" rows=\\"1\\" http_status=\\"200\\""'
    )
    path = write_log(tmp_path, line)
    shape_body = parse_line(line)
    assert shape_body is not None and shape_body[0] == "cloud"
    observations, report = parse_log_file("evidence_53", path, CAPTURED)
    assert report.status is ParseStatus.OK
    assert observations[0].resource_id == "account_2"
    assert observations[0].state is ObservationState.PRESENT


def test_restore_candidate_evaluated(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z level=ERROR service=backup_service "
        "event=restore_candidate_evaluated resource_id=backup_1 eligible=true deletion_block=false",
        "2026-09-01T00:00:00Z level=ERROR service=backup_service "
        "event=restore_candidate_evaluated resource_id=backup_2 eligible=true deletion_block=true",
        "2026-09-01T00:00:00Z level=ERROR service=backup_service "
        "event=restore_candidate_evaluated resource_id=backup_3 eligible=false deletion_block=false",
        "2026-09-01T00:00:00Z level=ERROR service=backup_service "
        "event=restore_candidate_evaluated resource_id=backup_4",
    )
    observations, report = parse_log_file("evidence_01", path, CAPTURED)
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["backup_1"].state is ObservationState.ACTIVE
    assert by_id["backup_2"].state is ObservationState.UNKNOWN
    assert by_id["backup_3"].state is ObservationState.UNKNOWN
    assert by_id["backup_4"].state is ObservationState.UNKNOWN
    assert report.status is ParseStatus.UNKNOWN_STATE


def test_analytics_read_completed_event(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z level=INFO service=analytics_platform "
        "event=analytics_profile_read_completed resource_id=analytics_1 "
        "customer_reference=null email=null phone=null email_hash=null",
        "2026-09-01T00:00:00Z level=INFO service=analytics_platform "
        "event=analytics_profile_read_completed resource_id=analytics_2 "
        'customer_reference=null email="b@x" phone=null email_hash=null',
    )
    observations, report = parse_log_file("evidence_94", path, CAPTURED)
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["analytics_1"].state is ObservationState.ANONYMIZED
    assert by_id["analytics_2"].state is ObservationState.PRESENT
    assert by_id["analytics_2"].pii_exposed is True
    assert report.status is ParseStatus.OK


def test_record_lookup_lines(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z INFO service=downstream_delivery_service event=record_lookup "
        'seq=1 system="account_service" resource_id="account_9" '
        'record_type="USER_PROFILE" result="NOT_FOUND" subject_reference="z@x"',
        "2026-09-01T00:00:00Z INFO service=search_index_service event=record_lookup "
        'seq=2 system="search_service" resource_id="search_9" '
        'record_type="SEARCH_INDEX_ENTRY" result="FOUND" subject_reference="z@x"',
        "2026-09-01T00:00:00Z INFO service=search_index_service event=record_lookup "
        'seq=3 resource_id="search_8" record_type="SEARCH_INDEX_ENTRY" result="FOUND"',
    )
    observations, _report = parse_log_file("evidence_z", path, CAPTURED)
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["account_9"].state is ObservationState.ABSENT
    assert by_id["account_9"].provenance.value == "LEDGER_RESULT"
    assert by_id["search_9"].state is ObservationState.PRESENT
    assert by_id["search_8"].state is ObservationState.UNKNOWN
    assert by_id["search_8"].system_id == "unknown"


def test_unknown_event_ignored_and_missing_fields_unknown(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z level=DEBUG service=account_service event=cache_lookup result=miss",
        "2026-09-01T00:00:00Z level=INFO service=account_service "
        "event=profile_lookup_completed resource_id=account_5",
    )
    observations, report = parse_log_file("evidence_w", path, CAPTURED)
    assert report.ignored_lines == 1
    assert len(observations) == 1
    assert observations[0].state is ObservationState.UNKNOWN
    assert observations[0].parse_status is ParseStatus.UNKNOWN_STATE
    assert report.status is ParseStatus.UNKNOWN_STATE


def test_missing_resource_id_and_broken_lines(tmp_path: Path) -> None:
    path = write_log(
        tmp_path,
        "2026-09-01T00:00:00Z level=INFO service=account_service "
        "event=profile_lookup_completed rows=0 http_status=404",
        "this line matches no shape at all",
        '2026-09-01T00:00:00Z {"broken": }',
    )
    observations, report = parse_log_file("evidence_v", path, CAPTURED)
    assert observations == []
    assert any("without resource_id" in error for error in report.errors)
    assert any("unrecognized_line" in error for error in report.errors)
    assert report.status is ParseStatus.UNKNOWN_STATE
