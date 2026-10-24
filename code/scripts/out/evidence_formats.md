# P1.6 Evidence formats (auto-draft)

## family `account_admin_console.png` (1 files, ext .png)
- file_ids: evidence_04
- captured_at range: 2026-09-26T11:00:00Z .. 2026-09-26T11:00:00Z
- origin(s): ['account_admin_portal']
- representative: `evidence/images/account_admin_console_20260926.png` (evidence_04)
- binary .png: manual review required (size 124989 bytes)

## family `account_history_report.pdf` (1 files, ext .pdf)
- file_ids: evidence_18
- captured_at range: 2026-07-18T11:00:00Z .. 2026-07-18T11:00:00Z
- origin(s): ['account_history_service']
- representative: `evidence/documents/account_history_report_20260718.pdf` (evidence_18)
- binary .pdf: manual review required (size 65704 bytes)

## family `analytics_profile_view.png` (1 files, ext .png)
- file_ids: evidence_19
- captured_at range: 2026-07-13T10:00:00Z .. 2026-07-13T10:00:00Z
- origin(s): ['analytics_platform']
- representative: `evidence/images/analytics_profile_view_20260713.png` (evidence_19)
- binary .png: manual review required (size 129362 bytes)

## family `application_trace_ap_northeast.log` (1 files, ext .log)
- file_ids: evidence_16
- captured_at range: 2026-07-30T08:53:12Z .. 2026-07-30T08:53:12Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/application_trace_ap_northeast_20260730.log` (evidence_16)
- log structure: `{"n_lines": 93, "services": {}, "events": {}}`
- first line: `2026-07-28T05:51:16Z [DEBUG] [log_router] [collector-9] export_started: instance="collector-9" sources="platform_services" expected_source_events="87"`

## family `application_trace_eu_north.log` (1 files, ext .log)
- file_ids: evidence_44
- captured_at range: 2026-03-02T10:59:23Z .. 2026-03-02T10:59:23Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/application_trace_eu_north_20260302.log` (evidence_44)
- log structure: `{"n_lines": 125, "services": {}, "events": {}}`
- first line: `2026-02-22T10:58:43Z [DEBUG] [log_router] [collector-3] export_started: instance="collector-3" sources="platform_services" expected_source_events="119"`

## family `backup_restore_console.png` (1 files, ext .png)
- file_ids: evidence_32
- captured_at range: 2026-04-29T09:00:00Z .. 2026-04-29T09:00:00Z
- origin(s): ['backup_service']
- representative: `evidence/images/backup_restore_console_20260429.png` (evidence_32)
- binary .png: manual review required (size 155587 bytes)

## family `cloud_runtime_export_af_south.log` (1 files, ext .log)
- file_ids: evidence_53
- captured_at range: 2026-09-30T11:59:44Z .. 2026-09-30T11:59:44Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/cloud_runtime_export_af_south_20260930.log` (evidence_53)
- log structure: `{"n_lines": 305, "services": {}, "events": {"\\\"profile_lookup_completed\\\"": 300, "\\\"export_started\\\"": 1, "\\\"cache_refresh\\\"": 1, "\\\"lease_extended\\\"": 1, "\\\"delivery_abandoned\\\"": 1, "\\\"telemetry_flushed\\\"": 1}}`
- first line: `2026-09-30T11:51:01Z requestId=collector-4 level=DEBUG function=log_router message="instance=\"collector-4\" event=\"export_started\" sources=\"platform_services\" expected_source_events=\"300\""`

## family `cloud_runtime_export_us_west.log` (1 files, ext .log)
- file_ids: evidence_25
- captured_at range: 2026-06-08T09:58:28Z .. 2026-06-08T09:58:28Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/cloud_runtime_export_us_west_20260608.log` (evidence_25)
- log structure: `{"n_lines": 128, "services": {}, "events": {"\\\"connection_acquired\\\"": 16, "\\\"cache_lookup\\\"": 11, "\\\"profile_lookup_started\\\"": 10, "\\\"dependency_retry\\\"": 10, "\\\"dependency_recovered\\\"": 10, "\\\"profile_lookup_completed\\\"": 10, "\\\"audit_record_read_completed\\\"": 10, "\\\"index_query_completed\\\"": 8, "\\\"audit_record_query_started\\\"": 7, "\\\"index_query_started\\\"": 5, "\\\"message_scan_started\\\"": 4, "\\\"message_pii_scan\\\"": 4, "\\\"connector_config_read_started\\\"": 3, "\\\"connector_heartbeat\\\"": 3, "\\\"analytics_profile_scan_started\\\"": 2}}`
- first line: `2026-06-08T06:52:07Z requestId=collector-1 level=DEBUG function=log_router message="instance=\"collector-1\" event=\"export_started\" sources=\"platform_services\" expected_source_events=\"123\""`

## family `connector_configurations.json` (1 files, ext .json)
- file_ids: evidence_13
- captured_at range: 2026-08-12T09:00:00Z .. 2026-08-12T09:00:00Z
- origin(s): ['integration_management_service']
- representative: `evidence/records/connector_configurations_20260812.json` (evidence_13)
- top structure: `{"exported_at": "str", "origin": "str", "record_count": "int", "records": ["dict"]}`

## family `connector_management_console.png` (1 files, ext .png)
- file_ids: evidence_14
- captured_at range: 2026-08-07T08:00:00Z .. 2026-08-07T08:00:00Z
- origin(s): ['integration_admin']
- representative: `evidence/images/connector_management_console_20260807.png` (evidence_14)
- binary .png: manual review required (size 130271 bytes)

## family `customer_account_handover.txt` (1 files, ext .txt)
- file_ids: evidence_03
- captured_at range: 2026-10-01T12:00:00Z .. 2026-10-01T12:00:00Z
- origin(s): ['customer_account_service']
- representative: `evidence/records/customer_account_handover_20261001.txt` (evidence_03)
- record lines starting with '-': 41
- example: `- 2026-10-01T12:00:00Z | account_service | account_146 | USER_PROFILE | NOT_FOUND | e.lindberg18@yahoo.com`
- cited by samples: evidence_03

## family `customer_accounts_failover_replica.sql` (1 files, ext .sql)
- file_ids: evidence_54
- captured_at range: 2026-09-02T23:00:00Z .. 2026-09-02T23:00:00Z
- origin(s): ['customer_account_failover_replica_capture']
- representative: `evidence/databases/customer_accounts_failover_replica_20260902.sql` (evidence_54)
- tables/row counts: {"customer_profiles_failover_replica": 4, "customer_profiles_primary": 3}
- columns[customer_profiles_failover_replica]: ['resource_id', 'user_id', 'full_name', 'email', 'phone', 'account_status', 'updated_at']
- cited by samples: evidence_54

## family `customer_analytics_report.json` (1 files, ext .json)
- file_ids: evidence_56
- captured_at range: 2026-09-07T09:45:00Z .. 2026-09-07T09:45:00Z
- origin(s): ['analytics_platform']
- representative: `evidence/records/customer_analytics_report_20260907.json` (evidence_56)
- top structure: `{"captured_at": "str", "source": "str", "collection": "str", "records": ["dict"]}`
- cited by samples: evidence_56

## family `customer_data_failover_replica.sql` (1 files, ext .sql)
- file_ids: evidence_52
- captured_at range: 2026-09-20T12:00:00Z .. 2026-09-20T12:00:00Z
- origin(s): ['customer_data_failover_replica_capture']
- representative: `evidence/databases/customer_data_failover_replica_20260920.sql` (evidence_52)
- tables/row counts: {"customer_data_failover_replica": 16, "customer_data_primary": 16}
- columns[customer_data_failover_replica]: ['resource_id', 'origin_system', 'collection_name', 'record_json', 'updated_at']

## family `customer_data_inventory.sql` (11 files, ext .sql)
- file_ids: evidence_63, evidence_66, evidence_69, evidence_72, evidence_75, evidence_78, evidence_81, evidence_84, evidence_87, evidence_90, evidence_93
- captured_at range: 2026-02-13T07:43:27Z .. 2026-09-16T08:37:39Z
- origin(s): ['customer_data_inventory_capture']
- representative: `evidence/databases/customer_data_inventory_20260213.sql` (evidence_63)
- tables/row counts: {"snapshot_scope": 7, "customer_profiles": 2, "customer_search_documents": 4, "customer_analytics_profiles": 3, "support_records": 2, "customer_exports": 0, "connector_subscriptions": 1, "backup_restore_entries": 1, "security_audit_records": 4}
- snapshot_scope: [{"origin_system": "account_service", "captured_at": "2026-02-13T07:43:27Z"}, {"origin_system": "analytics_platform", "captured_at": "2026-02-13T07:43:27Z"}, {"origin_system": "backup_service", "captured_at": "2026-02-13T07:43:27Z"}, {"origin_system": "integration_service", "captured_at": "2026-02-13T07:43:27Z"}, {"origin_system": "search_service", "captured_at": "2026-02-13T07:43:27Z"}, {"origin_system": "security_service", "captured_at": "2026-02-13T07:43:27Z"}]
- columns[snapshot_scope]: ['origin_system', 'captured_at']
- cited by samples: evidence_93

## family `customer_data_read_replica.sql` (5 files, ext .sql)
- file_ids: evidence_05, evidence_10, evidence_15, evidence_20, evidence_24
- captured_at range: 2026-06-13T11:00:00Z .. 2026-09-21T10:00:00Z
- origin(s): ['customer_data_read_replica_capture']
- representative: `evidence/databases/customer_data_read_replica_20260921.sql` (evidence_05)
- tables/row counts: {"customer_data_primary": 30, "customer_data_read_replica": 31}
- columns[customer_data_primary]: ['resource_id', 'origin_system', 'collection_name', 'record_json', 'updated_at']
- cited by samples: evidence_05

## family `customer_data_regional_replicas.sql` (3 files, ext .sql)
- file_ids: evidence_29, evidence_33, evidence_38
- captured_at range: 2026-03-30T10:00:00Z .. 2026-05-19T06:00:00Z
- origin(s): ['customer_data_regional_replicas_capture']
- representative: `evidence/databases/customer_data_regional_replicas_20260519.sql` (evidence_29)
- tables/row counts: {"customer_data_primary": 28, "customer_data_replica_ap_south": 29, "customer_data_replica_eu_west": 28}
- columns[customer_data_primary]: ['resource_id', 'origin_system', 'collection_name', 'record_json', 'updated_at']

## family `customer_data_reporting_replica.sql` (2 files, ext .sql)
- file_ids: evidence_43, evidence_47
- captured_at range: 2026-02-08T07:00:00Z .. 2026-03-05T12:00:00Z
- origin(s): ['customer_data_reporting_replica_capture']
- representative: `evidence/databases/customer_data_reporting_replica_20260305.sql` (evidence_43)
- tables/row counts: {"customer_data_primary": 25, "customer_data_reporting_replica": 26}
- columns[customer_data_primary]: ['resource_id', 'origin_system', 'collection_name', 'record_json', 'updated_at']

## family `customer_data_snapshot_bundle.json` (12 files, ext .json)
- file_ids: evidence_02, evidence_07, evidence_12, evidence_17, evidence_22, evidence_26, evidence_31, evidence_35, evidence_40, evidence_45, evidence_49, evidence_51
- captured_at range: 2026-01-31T15:00:00Z .. 2026-09-17T12:00:00Z
- origin(s): ['records_assurance_snapshot_bundle']
- representative: `evidence/records/customer_data_snapshot_bundle_20260917.json` (evidence_02)
- top structure: `{"exported_at": "str", "source": "str", "snapshots": ["dict"]}`
- cited by samples: evidence_51

## family `customer_export_console.png` (1 files, ext .png)
- file_ids: evidence_23
- captured_at range: 2026-06-18T12:00:00Z .. 2026-06-18T12:00:00Z
- origin(s): ['export_service']
- representative: `evidence/images/customer_export_console_20260618.png` (evidence_23)
- binary .png: manual review required (size 134597 bytes)

## family `customer_export_jobs.json` (1 files, ext .json)
- file_ids: evidence_59
- captured_at range: 2026-09-14T15:40:00Z .. 2026-09-14T15:40:00Z
- origin(s): ['export_service']
- representative: `evidence/records/customer_export_jobs_20260914.json` (evidence_59)
- top structure: `{"captured_at": "str", "source": "str", "collection": "str", "records": ["dict"]}`
- cited by samples: evidence_59

## family `customer_export_manifest.json` (1 files, ext .json)
- file_ids: evidence_36
- captured_at range: 2026-04-09T12:00:00Z .. 2026-04-09T12:00:00Z
- origin(s): ['customer_export_service']
- representative: `evidence/records/customer_export_manifest_20260409.json` (evidence_36)
- top structure: `{"exported_at": "str", "origin": "str", "record_count": "int", "records": ["dict"]}`

## family `customer_search_primary.sql` (1 files, ext .sql)
- file_ids: evidence_57
- captured_at range: 2026-09-10T08:45:00Z .. 2026-09-10T08:45:00Z
- origin(s): ['customer_search_primary_capture']
- representative: `evidence/databases/customer_search_primary_20260910.sql` (evidence_57)
- tables/row counts: {"search_documents_primary": 3}
- columns[search_documents_primary]: ['resource_id', 'display_name', 'email', 'source_resource_id', 'indexed_at']
- cited by samples: evidence_57

## family `deleted_account_reference.png` (1 files, ext .png)
- file_ids: evidence_42
- captured_at range: 2026-03-10T06:00:00Z .. 2026-03-10T06:00:00Z
- origin(s): ['identity_service']
- representative: `evidence/images/deleted_account_reference_20260310.png` (evidence_42)
- binary .png: manual review required (size 136696 bytes)

## family `delivery_correction_attachment.pdf` (1 files, ext .pdf)
- file_ids: evidence_58
- captured_at range: 2026-09-12T07:30:00Z .. 2026-09-12T07:30:00Z
- origin(s): ['support_platform']
- representative: `evidence/documents/delivery_correction_attachment.pdf` (evidence_58)
- binary .pdf: manual review required (size 66039 bytes)
- cited by samples: evidence_58

## family `legal_retention_register.pdf` (1 files, ext .pdf)
- file_ids: evidence_27
- captured_at range: 2026-05-29T08:00:00Z .. 2026-05-29T08:00:00Z
- origin(s): ['legal_retention_service']
- representative: `evidence/documents/legal_retention_register_20260529.pdf` (evidence_27)
- binary .pdf: manual review required (size 65857 bytes)

## family `marketing_profile_console.png` (1 files, ext .png)
- file_ids: evidence_60
- captured_at range: 2026-09-16T07:20:00Z .. 2026-09-16T07:20:00Z
- origin(s): ['marketing_platform']
- representative: `evidence/images/marketing_profile_console.png` (evidence_60)
- binary .png: manual review required (size 129711 bytes)

## family `notification_delivery.log` (1 files, ext .log)
- file_ids: evidence_41
- captured_at range: 2026-03-15T07:00:00Z .. 2026-03-15T07:00:00Z
- origin(s): ['downstream_delivery_service']
- representative: `evidence/logs/notification_delivery_20260315.log` (evidence_41)
- log structure: `{"n_lines": 39, "services": {"downstream_delivery_service": 39}, "events": {"record_lookup": 39}}`
- first line: `2026-03-15T07:00:00Z INFO service=downstream_delivery_service event=record_lookup seq=1 system="account_service" resource_id="account_022" record_type="USER_PROFILE" result="NOT_FOUND" subject_reference="zofia-novak@gmai`

## family `object_storage_browser.png` (1 files, ext .png)
- file_ids: evidence_46
- captured_at range: 2026-02-13T08:00:00Z .. 2026-02-13T08:00:00Z
- origin(s): ['object_storage']
- representative: `evidence/images/object_storage_browser_20260213.png` (evidence_46)
- binary .png: manual review required (size 154193 bytes)

## family `operations_stream_eu_central.log` (1 files, ext .log)
- file_ids: evidence_21
- captured_at range: 2026-07-05T07:54:27Z .. 2026-07-05T07:54:27Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/operations_stream_eu_central_20260705.log` (evidence_21)
- log structure: `{"n_lines": 128, "services": {}, "events": {}}`
- first line: `2026-07-03T07:51:30Z | DEBUG | log_router | collector-5 | export_started | instance="collector-5" sources="platform_services" expected_source_events="122"`

## family `operations_stream_me_central.log` (1 files, ext .log)
- file_ids: evidence_48
- captured_at range: 2026-02-03T05:59:42Z .. 2026-02-03T05:59:42Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/operations_stream_me_central_20260203.log` (evidence_48)
- log structure: `{"n_lines": 103, "services": {}, "events": {}}`
- first line: `2026-02-03T05:51:23Z | DEBUG | security_service | tr-4612767 | audit_record_query_started | instance="security-1" pod="security-5049" region="eu-west-1" subject_ref="user_517" attempt="1"`

## family `resource_lookup_trace.log` (11 files, ext .log)
- file_ids: evidence_64, evidence_67, evidence_70, evidence_73, evidence_76, evidence_79, evidence_82, evidence_85, evidence_88, evidence_91, evidence_94
- captured_at range: 2026-02-18T08:39:11Z .. 2026-09-26T10:38:56Z
- origin(s): ['service_readback_logs']
- representative: `evidence/logs/resource_lookup_trace_20260218_083911.log` (evidence_64)
- log structure: `{"n_lines": 54, "services": {"search_service": 14, "support_platform": 10, "analytics_platform": 8, "account_service": 8, "integration_service": 4, "security_service": 4, "readback_collector": 2, "export_service": 2}, "events": {"index_query_started": 7, "index_query_completed": 7, "support_ticket_read_started": 5, "support_ticket_read_completed": 5, "analytics_profile_read_started": 4, "analytics_profile_read_completed": 4, "profile_lookup_started": 4, "profile_lookup_completed": 4, "connector_config_read_started": 2, "connector_config_read_completed": 2, "audit_record_read_started": 2, "audi`
- first line: `2026-02-18T05:47:12Z level=INFO service=readback_collector event=export_started target_count=26 mode=point_in_time`
- cited by samples: evidence_94

## family `search_index_diagnostic.log` (1 files, ext .log)
- file_ids: evidence_08
- captured_at range: 2026-09-06T07:00:00Z .. 2026-09-06T07:00:00Z
- origin(s): ['search_index_service']
- representative: `evidence/logs/search_index_diagnostic_20260906.log` (evidence_08)
- log structure: `{"n_lines": 36, "services": {"search_index_service": 36}, "events": {"record_lookup": 36}}`
- first line: `2026-08-31T07:00:00Z INFO service=search_index_service event=record_lookup seq=1 system="account_service" resource_id="account_8473" record_type="USER_PROFILE" result="FOUND" subject_reference="marek.zielinski@gmail.com"`

## family `search_index_inspector.png` (1 files, ext .png)
- file_ids: evidence_09
- captured_at range: 2026-09-01T06:00:00Z .. 2026-09-01T06:00:00Z
- origin(s): ['search_index_admin']
- representative: `evidence/images/search_index_inspector_20260901.png` (evidence_09)
- binary .png: manual review required (size 121101 bytes)

## family `security_audit_explorer.png` (1 files, ext .png)
- file_ids: evidence_37
- captured_at range: 2026-09-05T07:00:00Z .. 2026-09-05T07:00:00Z
- origin(s): ['security_service']
- representative: `evidence/images/security_audit_explorer_20260905.png` (evidence_37)
- binary .png: manual review required (size 147699 bytes)

## family `security_audit_ledger.json` (1 files, ext .json)
- file_ids: evidence_50
- captured_at range: 2026-10-01T12:00:00Z .. 2026-10-01T12:00:00Z
- origin(s): ['security_audit_service']
- representative: `evidence/records/security_audit_ledger_20261001.json` (evidence_50)
- top structure: `{"exported_at": "str", "origin": "str", "record_count": "int", "records": ["dict"]}`

## family `security_retention_extract.pdf` (1 files, ext .pdf)
- file_ids: evidence_55
- captured_at range: 2026-09-05T06:30:00Z .. 2026-09-05T06:30:00Z
- origin(s): ['security_service']
- representative: `evidence/documents/security_retention_extract.pdf` (evidence_55)
- binary .pdf: manual review required (size 64847 bytes)

## family `service_events_ap_south.log` (1 files, ext .log)
- file_ids: evidence_01
- captured_at range: 2026-09-15T11:59:39Z .. 2026-09-15T11:59:39Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/service_events_ap_south_20260915.log` (evidence_01)
- log structure: `{"n_lines": 104, "services": {"account_service": 28, "security_service": 25, "search_service": 15, "backup_service": 8, "integration_service": 8, "support_platform": 7, "analytics_platform": 4, "export_service": 3}, "events": {"connection_acquired": 16, "profile_lookup_completed": 10, "audit_record_read_completed": 10, "profile_lookup_started": 9, "index_query_completed": 7, "audit_record_query_started": 7, "cache_lookup": 7, "dependency_retry": 6, "dependency_recovered": 6, "index_query_started": 3, "restore_policy_check_started": 2, "connector_config_read_started": 2, "restore_candidate_eval`
- first line: `2026-09-15T08:51:43Z level=DEBUG service=log_router instance=collector-3 event=export_started sources=platform_services expected_source_events=98`
- cited by samples: evidence_01

## family `service_events_sa_east.log` (1 files, ext .log)
- file_ids: evidence_30
- captured_at range: 2026-05-16T11:58:25Z .. 2026-05-16T11:58:25Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/service_events_sa_east_20260516.log` (evidence_30)
- log structure: `{"n_lines": 110, "services": {"security_service": 30, "account_service": 27, "analytics_platform": 17, "search_service": 12, "integration_service": 9, "support_platform": 9, "backup_service": 1, "queue_consumer": 1}, "events": {"connection_acquired": 15, "cache_lookup": 12, "profile_lookup_completed": 11, "audit_record_read_completed": 10, "audit_record_query_started": 8, "profile_lookup_started": 7, "index_query_completed": 5, "analytics_profile_scan_started": 5, "dependency_retry": 5, "dependency_recovered": 5, "index_query_started": 4, "analytics_profile_read": 4, "connector_config_read_sta`
- first line: `2026-05-14T11:51:20Z level=INFO service=account_service instance=account-4 pod=account-e506 region=us-east-2 trace_id=tr-4210650 resource_id=account_1530 event=profile_lookup_completed rows=0 http_status=404 duration_ms=`

## family `service_resource_export.json` (11 files, ext .json)
- file_ids: evidence_62, evidence_65, evidence_68, evidence_71, evidence_74, evidence_77, evidence_80, evidence_83, evidence_86, evidence_89, evidence_92
- captured_at range: 2026-01-29T11:44:59Z .. 2026-09-15T11:44:55Z
- origin(s): ['service_resource_export']
- representative: `evidence/records/service_resource_export_20260129_114459.json` (evidence_62)
- top structure: `{"exported_at": "str", "region": "str", "service_exports": {"account_service": "dict", "analytics_platform": "dict", "backup_service": "dict", "export_service": "dict", "integration_service": "dict", "search_service": "dict", "security_service": "dict", "support_platform": "dict"}, "source": "str"}`
- cited by samples: evidence_92

## family `structured_service_events_ca_central.log` (1 files, ext .log)
- file_ids: evidence_34
- captured_at range: 2026-04-19T06:59:43Z .. 2026-04-19T06:59:43Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/structured_service_events_ca_central_20260419.log` (evidence_34)
- log structure: `{"n_lines": 136, "services": {}, "events": {}}`
- first line: `2026-04-19T06:51:11Z {"severity":"DEBUG","logger":"log_router","service":"log_router","instance":"collector-2","event":"export_started","sources":"platform_services","expected_source_events":"130"}`

## family `structured_service_events_eu_west.log` (1 files, ext .log)
- file_ids: evidence_06
- captured_at range: 2026-09-18T11:55:24Z .. 2026-09-18T11:55:24Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/structured_service_events_eu_west_20260918.log` (evidence_06)
- log structure: `{"n_lines": 112, "services": {}, "events": {}}`
- first line: `2026-09-10T08:56:15Z {"severity":"DEBUG","logger":"log_router","service":"log_router","instance":"collector-8","event":"export_started","sources":"platform_services","expected_source_events":"106"}`

## family `support_replica.log` (1 files, ext .log)
- file_ids: evidence_61
- captured_at range: 2026-09-17T22:00:19Z .. 2026-09-17T22:00:19Z
- origin(s): ['support_platform']
- representative: `evidence/logs/support_replica.log` (evidence_61)
- log structure: `{"n_lines": 10, "services": {"support_replica": 8, "attachment_preview": 1, "queue_consumer": 1}, "events": {"contact_query_completed": 3, "contact_query_started": 2, "batch_started": 1, "deletion_marker_check": 1, "thumbnail_failed": 1, "consumer_lag": 1, "checkpoint_saved": 1}}`
- first line: `2026-09-17T22:00:00Z level=DEBUG service=support_replica instance=support-eu-03 pod=replica-7c9f event=batch_started batch=rp-7718 source=legacy_contact_index cursor=884019`
- cited by samples: evidence_61

## family `support_ticket_console.png` (1 files, ext .png)
- file_ids: evidence_28
- captured_at range: 2026-05-24T07:00:00Z .. 2026-05-24T07:00:00Z
- origin(s): ['support_platform']
- representative: `evidence/images/support_ticket_console_20260524.png` (evidence_28)
- binary .png: manual review required (size 135008 bytes)

## family `syslog_archive_ap_southeast.log` (1 files, ext .log)
- file_ids: evidence_39
- captured_at range: 2026-03-25T08:59:44Z .. 2026-03-25T08:59:44Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/syslog_archive_ap_southeast_20260325.log` (evidence_39)
- log structure: `{"n_lines": 114, "services": {}, "events": {"\"connection_acquired\"": 15, "\"dependency_retry\"": 11, "\"dependency_recovered\"": 11, "\"profile_lookup_completed\"": 10, "\"index_query_completed\"": 10, "\"audit_record_read_completed\"": 10, "\"index_query_started\"": 8, "\"audit_record_query_started\"": 8, "\"profile_lookup_started\"": 7, "\"cache_lookup\"": 5, "\"message_pii_scan\"": 3, "\"connector_heartbeat\"": 3, "\"analytics_identity_scan\"": 2, "\"export_started\"": 1, "\"message_scan_started\"": 1}}`
- first line: `2026-03-25T08:51:13Z <15>1 node-8 log_router collector-7 - - level=DEBUG instance="collector-7" event="export_started" sources="platform_services" expected_source_events="109"`

## family `syslog_archive_us_east.log` (1 files, ext .log)
- file_ids: evidence_11
- captured_at range: 2026-08-24T13:56:43Z .. 2026-08-24T13:56:43Z
- origin(s): ['central_observability_export']
- representative: `evidence/logs/syslog_archive_us_east_20260824.log` (evidence_11)
- log structure: `{"n_lines": 118, "services": {}, "events": {"\"connection_acquired\"": 19, "\"profile_lookup_completed\"": 10, "\"audit_record_read_completed\"": 10, "\"cache_lookup\"": 10, "\"audit_record_query_started\"": 9, "\"dependency_retry\"": 9, "\"dependency_recovered\"": 9, "\"profile_lookup_started\"": 8, "\"index_query_completed\"": 8, "\"index_query_started\"": 7, "\"message_scan_started\"": 2, "\"message_pii_scan\"": 2, "\"analytics_profile_read\"": 2, "\"connector_config_read_started\"": 2, "\"connector_heartbeat\"": 2}}`
- first line: `2026-08-22T10:51:11Z <15>1 node-1 account_service tr-4973247 - - level=DEBUG instance="account-2" pod="account-0525" region="eu-west-1" event="profile_lookup_started" lookup_key="nana.b9576@outlook.com" attempt="1"`
