"""Unit tests for the SQL evidence parser (P3.4)."""

from pathlib import Path

from src.loaders.sql_parser import parse_sql_file, sql_family
from src.models import ObservationState, ParseStatus

CAPTURED = "2026-09-16T08:37:39Z"

INVENTORY_DDL = """
PRAGMA foreign_keys=ON;
CREATE TABLE snapshot_scope (origin_system TEXT PRIMARY KEY, captured_at TEXT NOT NULL);
CREATE TABLE customer_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, full_name TEXT, email TEXT, phone TEXT, email_hash TEXT, account_status TEXT, updated_at TEXT);
CREATE TABLE customer_search_documents (resource_id TEXT PRIMARY KEY, customer_reference TEXT, display_name TEXT, email TEXT, phone TEXT, email_hash TEXT, index_name TEXT, updated_at TEXT);
CREATE TABLE customer_analytics_profiles (resource_id TEXT PRIMARY KEY, customer_reference TEXT, email TEXT, phone TEXT, email_hash TEXT, audience_cohort TEXT, updated_at TEXT);
CREATE TABLE support_records (resource_id TEXT PRIMARY KEY, customer_reference TEXT, requester_name TEXT, requester_email TEXT, requester_phone TEXT, message_excerpt TEXT, updated_at TEXT);
CREATE TABLE customer_exports (resource_id TEXT PRIMARY KEY, customer_reference TEXT, owner_email TEXT, owner_phone TEXT, object_key TEXT, updated_at TEXT);
CREATE TABLE connector_subscriptions (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, connector_name TEXT, enabled INTEGER, last_delivery_status TEXT, updated_at TEXT);
CREATE TABLE backup_restore_entries (resource_id TEXT PRIMARY KEY, customer_reference TEXT, customer_email TEXT, archive_key TEXT, restore_allowed INTEGER, updated_at TEXT);
CREATE TABLE security_audit_records (resource_id TEXT PRIMARY KEY, subject_reference TEXT, event_code TEXT, retention_until TEXT, updated_at TEXT);
"""


def inventory_sql(*inserts: str, ddl: str = INVENTORY_DDL) -> str:
    return ddl + "\n".join(inserts)


def write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_sql_family_detection() -> None:
    assert sql_family("evidence/databases/customer_data_inventory_20260916.sql") == "inventory"
    assert sql_family("x/customer_data_read_replica_20260613.sql") == "generic_replica"
    assert sql_family("x/customer_data_regional_replicas_20260330.sql") == "generic_replica"
    assert sql_family("x/customer_accounts_failover_replica_20260902.sql") == "accounts_failover"
    assert sql_family("x/customer_search_primary_20260910.sql") == "search_primary"
    assert sql_family("x/unknown_thing.sql") == "unknown"


def test_inventory_states_and_scope(tmp_path: Path) -> None:
    path = write(
        tmp_path / "customer_data_inventory_20260916.sql",
        inventory_sql(
            "INSERT INTO snapshot_scope VALUES ('account_service','2026-09-16T08:37:39Z');",
            "INSERT INTO customer_profiles VALUES ('account_1','user_1','A','a@x','+1',NULL,'ACTIVE','t');",
            "INSERT INTO customer_profiles VALUES ('account_2','user_2',NULL,NULL,NULL,NULL,'DELETED','t');",
            "INSERT INTO customer_search_documents VALUES ('search_1','user_1','A','a@x',NULL,NULL,'idx','t');",
            "INSERT INTO customer_analytics_profiles VALUES ('analytics_1',NULL,NULL,NULL,NULL,'cohort','t');",
            "INSERT INTO support_records VALUES ('support_1',NULL,NULL,NULL,NULL,'excerpt','t');",
            "INSERT INTO support_records VALUES ('support_2','user_2','B','b@x',NULL,'excerpt','t');",
            "INSERT INTO customer_exports VALUES ('export_1','user_1','a@x',NULL,'key','t');",
            "INSERT INTO connector_subscriptions VALUES ('data_flow_1','user_1','a@x','c',0,'stopped','t');",
            "INSERT INTO connector_subscriptions VALUES ('data_flow_2','user_1','a@x','c',1,'running','t');",
            "INSERT INTO backup_restore_entries VALUES ('backup_1','user_1','a@x','key',1,'t');",
            "INSERT INTO backup_restore_entries VALUES ('backup_2','user_1','a@x','key',0,'t');",
            "INSERT INTO security_audit_records VALUES ('audit_record_1','user_1','closed','2027-01-01T00:00:00Z','t');",
        ),
    )
    observations, report = parse_sql_file("evidence_93", path, CAPTURED)
    states = {obs.resource_id: obs.state for obs in observations}
    assert report.status is ParseStatus.OK
    assert report.scope == {"account_service": "2026-09-16T08:37:39Z"}
    assert states["account_1"] is ObservationState.PRESENT
    assert states["account_2"] is ObservationState.REDACTED
    assert states["search_1"] is ObservationState.PRESENT
    assert states["analytics_1"] is ObservationState.ANONYMIZED
    assert states["support_1"] is ObservationState.REDACTED
    assert states["support_2"] is ObservationState.PRESENT
    assert states["export_1"] is ObservationState.PRESENT
    assert states["data_flow_1"] is ObservationState.DISABLED
    assert states["data_flow_2"] is ObservationState.ACTIVE
    assert states["backup_1"] is ObservationState.ACTIVE
    assert states["backup_2"] is ObservationState.BLOCKED
    assert states["audit_record_1"] is ObservationState.PRESENT
    by_id = {obs.resource_id: obs for obs in observations}
    assert by_id["support_2"].data_category == "SUPPORT_MESSAGE"
    assert by_id["data_flow_1"].pii_exposed is True
    assert by_id["account_1"].captured_at == CAPTURED


def test_inventory_missing_table_reported(tmp_path: Path) -> None:
    ddl = "\n".join(
        line
        for line in INVENTORY_DDL.splitlines()
        if "support_records" not in line and line.strip()
    )
    path = write(
        tmp_path / "customer_data_inventory_20260101.sql",
        inventory_sql(
            "INSERT INTO snapshot_scope VALUES ('account_service','2026-01-01T00:00:00Z');",
            "INSERT INTO customer_profiles VALUES ('account_1','user_1','A','a@x',NULL,NULL,'ACTIVE','t');",
            ddl=ddl,
        ),
    )
    observations, report = parse_sql_file("evidence_x", path, CAPTURED)
    assert any("missing_inventory_tables:support_records" in error for error in report.errors)
    assert report.status is ParseStatus.UNKNOWN_STATE
    assert len(observations) == 1


GENERIC_DDL = (
    "CREATE TABLE customer_data_primary (resource_id TEXT, origin_system TEXT, "
    "collection_name TEXT, record_json TEXT, updated_at TEXT);"
)


def generic_sql(*inserts: str, extra_ddl: str = "") -> str:
    return GENERIC_DDL + extra_ddl + "\n".join(inserts)


def test_generic_replica_decodes_by_collection(tmp_path: Path) -> None:
    account_json = (
        '{"resource_id":"account_10","customer_reference":"user_10",'
        '"full_name":"A","email":"a@x","phone":null}'
    )
    analytics_json = '{"resource_id":"analytics_10","email":null,"phone":null,"email_hash":null}'
    path = write(
        tmp_path / "customer_data_read_replica_20260613.sql",
        generic_sql(
            "INSERT INTO customer_data_primary VALUES "
            f"('account_10','account_service','customer_profiles','{account_json}','t');",
            "INSERT INTO customer_data_primary VALUES "
            f"('analytics_10','analytics_platform','customer_analytics_reports',"
            f"'{analytics_json}','t');",
            "INSERT INTO customer_data_primary VALUES "
            "('weird_1','account_service','weird_collection','{}','t');",
            "INSERT INTO customer_data_primary VALUES "
            "('account_11','account_service','customer_profiles','{broken','t');",
        ),
    )
    observations, report = parse_sql_file("evidence_24", path, CAPTURED)
    states = {obs.resource_id: obs.state for obs in observations}
    assert states["account_10"] is ObservationState.PRESENT
    assert states["analytics_10"] is ObservationState.ANONYMIZED
    assert any("unknown_collection:weird_collection" in error for error in report.errors)
    assert any("invalid record_json" in error for error in report.errors)
    assert report.status is ParseStatus.UNKNOWN_STATE


def test_generic_replica_multiple_tables(tmp_path: Path) -> None:
    extra = (
        "CREATE TABLE customer_data_read_replica (resource_id TEXT, origin_system TEXT, "
        "collection_name TEXT, record_json TEXT, updated_at TEXT);"
    )
    record = (
        '{"resource_id":"account_20","customer_reference":"user_20",'
        '"full_name":"B","email":"b@x","phone":null}'
    )
    path = write(
        tmp_path / "customer_data_regional_replicas_20260330.sql",
        generic_sql(
            "INSERT INTO customer_data_primary VALUES "
            f"('account_20','account_service','customer_profiles','{record}','t');",
            "INSERT INTO customer_data_read_replica VALUES "
            f"('account_20','account_service','customer_profiles','{record}','t');",
            extra_ddl=extra,
        ),
    )
    observations, report = parse_sql_file("evidence_25", path, CAPTURED)
    assert report.status is ParseStatus.OK
    assert [obs.locator for obs in observations] == [
        "customer_data_primary:account_20",
        "customer_data_read_replica:account_20",
    ]


def test_accounts_failover_family(tmp_path: Path) -> None:
    path = write(
        tmp_path / "customer_accounts_failover_replica_20260902.sql",
        "CREATE TABLE customer_profiles_failover_replica (resource_id TEXT, user_id TEXT, "
        "full_name TEXT, email TEXT, phone TEXT, account_status TEXT, updated_at TEXT);"
        "INSERT INTO customer_profiles_failover_replica VALUES "
        "('account_5','user_5','Leila','l@x','+1','ACTIVE','t');"
        "INSERT INTO customer_profiles_failover_replica VALUES "
        "('account_6','user_6',NULL,NULL,NULL,'DELETED','t');",
    )
    observations, report = parse_sql_file("evidence_54", path, CAPTURED)
    states = {obs.resource_id: obs.state for obs in observations}
    assert report.direct_systems == ("account_service",)
    assert states["account_5"] is ObservationState.PRESENT
    assert states["account_6"] is ObservationState.REDACTED


def test_search_primary_family(tmp_path: Path) -> None:
    path = write(
        tmp_path / "customer_search_primary_20260910.sql",
        "CREATE TABLE search_documents_primary (resource_id TEXT, display_name TEXT, email TEXT, "
        "source_resource_id TEXT, indexed_at TEXT);"
        "INSERT INTO search_documents_primary VALUES ('search_1','Jonas','j@x','account_6','t');",
    )
    observations, report = parse_sql_file("evidence_57", path, CAPTURED)
    assert report.direct_systems == ("search_service",)
    assert observations[0].resource_id == "search_1"
    assert observations[0].state is ObservationState.PRESENT
    assert observations[0].pii_exposed is True


def test_malformed_sql_is_parse_error(tmp_path: Path) -> None:
    path = write(tmp_path / "customer_data_inventory_20260101.sql", "CREATE TABLE broken (")
    observations, report = parse_sql_file("evidence_bad", path, CAPTURED)
    assert observations == []
    assert report.status is ParseStatus.PARSE_ERROR
    assert any("sqlite_error" in error for error in report.errors)


def test_unknown_family_is_unknown_state(tmp_path: Path) -> None:
    path = write(tmp_path / "random_snapshot.sql", "CREATE TABLE t (x TEXT);")
    observations, report = parse_sql_file("evidence_random", path, CAPTURED)
    assert observations == []
    assert report.status is ParseStatus.UNKNOWN_STATE
    assert any("unrecognized_sql_family" in error for error in report.errors)
