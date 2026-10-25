"""Synthetic evaluation cases for Ghost Data Still Exists (AGENTS.md section 6.8).

Defines 4 comprehensive synthetic cases designed to test edge cases outside the
public 32-sample set:
1. case_synth_01: Multilingual non-deletion request (Spanish GDPR access/rectification) -> NOT_APPLICABLE.
2. case_synth_02: Compliant deletion with tombstone preservation & legal hold retention (German request) -> COMPLETE.
3. case_synth_03: Incomplete deletion with active sync connector & restore risk -> INCOMPLETE.
4. case_synth_04: Cross-system replication drift between primary and read replica -> INCOMPLETE.
"""

from __future__ import annotations

from ..loaders.csv_loader import (
    DeletionRequestRow,
    DeletionRuleRow,
    IdentityRow,
)
from ..models import (
    CaseAuditResult,
    EvidenceObservation,
    ObservationState,
    ParseStatus,
    Provenance,
)
from .evaluator import CaseOutput, canonical_step

# ---------------------------------------------------------------------------
# Synthetic Requests (4 cases)
# ---------------------------------------------------------------------------

SYNTHETIC_REQUESTS: tuple[DeletionRequestRow, ...] = (
    DeletionRequestRow(
        case_id="case_synth_01",
        email="carlos.mendez@empresa.es",
        requested_at="2026-09-10T10:00:00Z",
        reported_status="NOT_STARTED",
        reported_at="2026-09-10T10:00:00Z",
        audit_at="2026-09-12T12:00:00Z",
        request_text=(
            "Hola, deseo acceder a una copia de mis datos personales y corregir mis "
            "datos de contacto conforme al RGPD. No deseo cancelar mi suscripción."
        ),
    ),
    DeletionRequestRow(
        case_id="case_synth_02",
        email="elena.rostova@techcorp.de",
        requested_at="2026-09-14T09:00:00Z",
        reported_status="COMPLETE",
        reported_at="2026-09-15T14:00:00Z",
        audit_at="2026-09-16T12:00:00Z",
        request_text=(
            "Bitte löschen Sie mein Benutzerkonto und alle personenbezogenen Daten unwiderruflich."
        ),
    ),
    DeletionRequestRow(
        case_id="case_synth_03",
        email="david.okafor@lagoscommerce.ng",
        requested_at="2026-09-02T08:00:00Z",
        reported_status="COMPLETE",
        reported_at="2026-09-04T10:00:00Z",
        audit_at="2026-09-05T12:00:00Z",
        request_text=(
            "Please permanently delete all my personal data and cancel my registration immediately."
        ),
    ),
    DeletionRequestRow(
        case_id="case_synth_04",
        email="sora.takahashi@tokyomail.jp",
        requested_at="2026-09-05T11:00:00Z",
        reported_status="PARTIALLY_COMPLETE",
        reported_at="2026-09-07T12:00:00Z",
        audit_at="2026-09-08T18:00:00Z",
        request_text="アカウントの完全な削除および個人データの抹消を希望します。",
    ),
)

# ---------------------------------------------------------------------------
# Synthetic Identity Context
# ---------------------------------------------------------------------------

SYNTHETIC_IDENTITIES: tuple[IdentityRow, ...] = (
    IdentityRow(
        user_id="user_synth_01",
        email="carlos.mendez@empresa.es",
        name="Carlos Mendez",
        phone="+34612345678",
        email_hash="hash_synth_01",
        updated_at="2026-08-01T00:00:00Z",
    ),
    IdentityRow(
        user_id="user_synth_02",
        email="elena.rostova@techcorp.de",
        name="Elena Rostova",
        phone="+491701234567",
        email_hash="hash_synth_02",
        updated_at="2026-08-01T00:00:00Z",
    ),
    IdentityRow(
        user_id="user_synth_03",
        email="david.okafor@lagoscommerce.ng",
        name="David Okafor",
        phone="+2348012345678",
        email_hash="hash_synth_03",
        updated_at="2026-08-01T00:00:00Z",
    ),
    IdentityRow(
        user_id="user_synth_04",
        email="sora.takahashi@tokyomail.jp",
        name="Sora Takahashi",
        phone="+819012345678",
        email_hash="hash_synth_04",
        updated_at="2026-08-01T00:00:00Z",
    ),
)

# ---------------------------------------------------------------------------
# Synthetic Observations
# ---------------------------------------------------------------------------

SYNTHETIC_OBSERVATIONS: tuple[EvidenceObservation, ...] = (
    # Case Synth 02 (Absent User Profile + Compliant Tombstone + Legal Hold)
    EvidenceObservation(
        file_id="evidence_synth_02a",
        captured_at="2026-09-05T14:30:00Z",
        system_id="account_service",
        resource_id="account_synth_02",
        data_category="USER_PROFILE",
        state=ObservationState.ABSENT,
        parse_status=ParseStatus.OK,
        reason="primary user account removed from account store",
        locator="account_synth_02",
        provenance=Provenance.SCOPE_IMPLICIT,
        identifiers=("user_synth_02", "elena.rostova@techcorp.de"),
        pii_exposed=False,
    ),
    EvidenceObservation(
        file_id="evidence_synth_02b",
        captured_at="2026-09-05T15:00:00Z",
        system_id="identity_service",
        resource_id="tombstone_synth_02",
        data_category="ACCOUNT_TOMBSTONE",
        state=ObservationState.REDACTED,
        parse_status=ParseStatus.OK,
        reason="account tombstone active, PII redacted",
        locator="tombstone_synth_02",
        provenance=Provenance.READBACK,
        identifiers=("user_synth_02", "elena.rostova@techcorp.de"),
        pii_exposed=False,
    ),
    EvidenceObservation(
        file_id="evidence_synth_02c",
        captured_at="2026-09-05T15:30:00Z",
        system_id="compliance_service",
        resource_id="legal_hold_synth_02",
        data_category="LEGAL_HOLD_RECORD",
        state=ObservationState.PRESENT,
        parse_status=ParseStatus.OK,
        reason="statutory retention for active litigation",
        locator="legal_hold_synth_02",
        provenance=Provenance.EXPLICIT_FIELD,
        identifiers=("user_synth_02", "elena.rostova@techcorp.de"),
        pii_exposed=False,
    ),
    # Case Synth 03 (Active Data Flow + Backup Risk + Deleted Primary)
    EvidenceObservation(
        file_id="evidence_synth_03a",
        captured_at="2026-09-04T11:00:00Z",
        system_id="integration_service",
        resource_id="sync_stream_synth_03",
        data_category="DATA_FLOW",
        state=ObservationState.ACTIVE,
        parse_status=ParseStatus.OK,
        reason="live sync stream actively copying data",
        locator="sync_stream_synth_03",
        provenance=Provenance.EXPLICIT_FIELD,
        identifiers=("user_synth_03", "david.okafor@lagoscommerce.ng"),
        pii_exposed=True,
    ),
    EvidenceObservation(
        file_id="evidence_synth_03b",
        captured_at="2026-09-04T11:30:00Z",
        system_id="backup_service",
        resource_id="backup_synth_03",
        data_category="BACKUP_ARCHIVE",
        state=ObservationState.ACTIVE,
        parse_status=ParseStatus.OK,
        reason="backup snapshot ready for automatic restoration",
        locator="backup_synth_03",
        provenance=Provenance.EXPLICIT_FIELD,
        identifiers=("user_synth_03", "david.okafor@lagoscommerce.ng"),
        pii_exposed=True,
    ),
    EvidenceObservation(
        file_id="evidence_synth_03c",
        captured_at="2026-09-04T12:00:00Z",
        system_id="account_service",
        resource_id="account_synth_03",
        data_category="USER_PROFILE",
        state=ObservationState.ABSENT,
        parse_status=ParseStatus.OK,
        reason="primary record deleted",
        locator="account_synth_03",
        provenance=Provenance.SCOPE_IMPLICIT,
        identifiers=("user_synth_03", "david.okafor@lagoscommerce.ng"),
        pii_exposed=False,
    ),
    # Case Synth 04 (Replication Drift)
    EvidenceObservation(
        file_id="evidence_synth_04a",
        captured_at="2026-09-07T13:00:00Z",
        system_id="account_service",
        resource_id="account_synth_04",
        data_category="USER_PROFILE",
        state=ObservationState.ABSENT,
        parse_status=ParseStatus.OK,
        reason="primary user record absent",
        locator="account_synth_04",
        provenance=Provenance.SCOPE_IMPLICIT,
        identifiers=("user_synth_04", "sora.takahashi@tokyomail.jp"),
        pii_exposed=False,
    ),
    EvidenceObservation(
        file_id="evidence_synth_04b",
        captured_at="2026-09-07T14:00:00Z",
        system_id="reporting_replica",
        resource_id="account_synth_04",
        data_category="USER_PROFILE",
        state=ObservationState.PRESENT,
        parse_status=ParseStatus.OK,
        reason="replication lag drift left record present",
        locator="account_synth_04",
        provenance=Provenance.EXPLICIT_FIELD,
        identifiers=("user_synth_04", "sora.takahashi@tokyomail.jp"),
        pii_exposed=True,
    ),
)

# ---------------------------------------------------------------------------
# Synthetic Rules
# ---------------------------------------------------------------------------

SYNTHETIC_RULES: tuple[DeletionRuleRow, ...] = (
    DeletionRuleRow(
        rule_id="synth_rule_01",
        data_category="USER_PROFILE",
        condition="NONE",
        required_action="DELETE",
    ),
    DeletionRuleRow(
        rule_id="synth_rule_02",
        data_category="ACCOUNT_TOMBSTONE",
        condition="ACTIVE_TOMBSTONE",
        required_action="REDACT",
    ),
    DeletionRuleRow(
        rule_id="synth_rule_03",
        data_category="LEGAL_HOLD_RECORD",
        condition="LITIGATION_HOLD",
        required_action="RETAIN",
    ),
    DeletionRuleRow(
        rule_id="synth_rule_04",
        data_category="DATA_FLOW",
        condition="LIVE_CONNECTOR",
        required_action="DISABLE",
    ),
    DeletionRuleRow(
        rule_id="synth_rule_05",
        data_category="BACKUP_ARCHIVE",
        condition="RESTORABLE_IMAGE",
        required_action="BLOCK",
    ),
)

# ---------------------------------------------------------------------------
# Golden Target Outputs for Synthetic Cases
# ---------------------------------------------------------------------------

SYNTHETIC_GOLD_CASES: dict[str, CaseOutput] = {
    "case_synth_01": CaseOutput(
        deletion_status="NOT_APPLICABLE",
        steps=(),
    ),
    "case_synth_02": CaseOutput(
        deletion_status="COMPLETE",
        steps=(
            canonical_step({
                "step_no": 1,
                "phase": "VERIFICATION",
                "system_id": "account_service",
                "resource_id": "account_synth_02",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": "evidence_synth_02a",
            }),
            canonical_step({
                "step_no": 2,
                "phase": "VERIFICATION",
                "system_id": "compliance_service",
                "resource_id": "legal_hold_synth_02",
                "operation": "VERIFY_RECORD_PRESENT",
                "state": "PRESENT",
                "evidence_id": "evidence_synth_02c",
            }),
            canonical_step({
                "step_no": 3,
                "phase": "VERIFICATION",
                "system_id": "identity_service",
                "resource_id": "tombstone_synth_02",
                "operation": "VERIFY_RECORD_REDACTED",
                "state": "REDACTED",
                "evidence_id": "evidence_synth_02b",
            }),
        ),
    ),
    "case_synth_03": CaseOutput(
        deletion_status="INCOMPLETE",
        steps=(
            canonical_step({
                "step_no": 1,
                "phase": "FINDING",
                "system_id": "integration_service",
                "resource_id": "sync_stream_synth_03",
                "operation": "REPORT_ACTIVE_DATA_FLOW",
                "state": "ACTIVE",
                "evidence_id": "evidence_synth_03a",
            }),
            canonical_step({
                "step_no": 2,
                "phase": "FINDING",
                "system_id": "backup_service",
                "resource_id": "backup_synth_03",
                "operation": "REPORT_RESTORE_RISK",
                "state": "ACTIVE",
                "evidence_id": "evidence_synth_03b",
            }),
            canonical_step({
                "step_no": 3,
                "phase": "REMEDIATION",
                "system_id": "integration_service",
                "resource_id": "sync_stream_synth_03",
                "operation": "DISABLE_DATA_FLOW",
                "state": "DISABLED",
                "evidence_id": "",
            }),
            canonical_step({
                "step_no": 4,
                "phase": "REMEDIATION",
                "system_id": "backup_service",
                "resource_id": "backup_synth_03",
                "operation": "BLOCK_RESTORE",
                "state": "BLOCKED",
                "evidence_id": "",
            }),
            canonical_step({
                "step_no": 5,
                "phase": "VERIFICATION",
                "system_id": "account_service",
                "resource_id": "account_synth_03",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": "",
            }),
            canonical_step({
                "step_no": 6,
                "phase": "VERIFICATION",
                "system_id": "integration_service",
                "resource_id": "sync_stream_synth_03",
                "operation": "VERIFY_DATA_FLOW_DISABLED",
                "state": "DISABLED",
                "evidence_id": "",
            }),
            canonical_step({
                "step_no": 7,
                "phase": "VERIFICATION",
                "system_id": "backup_service",
                "resource_id": "backup_synth_03",
                "operation": "VERIFY_RESTORE_BLOCKED",
                "state": "BLOCKED",
                "evidence_id": "",
            }),
        ),
    ),
    "case_synth_04": CaseOutput(
        deletion_status="INCOMPLETE",
        steps=(
            canonical_step({
                "step_no": 1,
                "phase": "FINDING",
                "system_id": "reporting_replica",
                "resource_id": "account_synth_04",
                "operation": "REPORT_REMAINING_RECORD",
                "state": "PRESENT",
                "evidence_id": "evidence_synth_04b",
            }),
            canonical_step({
                "step_no": 2,
                "phase": "REMEDIATION",
                "system_id": "reporting_replica",
                "resource_id": "account_synth_04",
                "operation": "DELETE_RECORD",
                "state": "ABSENT",
                "evidence_id": "",
            }),
            canonical_step({
                "step_no": 3,
                "phase": "VERIFICATION",
                "system_id": "account_service",
                "resource_id": "account_synth_04",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": "",
            }),
            canonical_step({
                "step_no": 4,
                "phase": "VERIFICATION",
                "system_id": "reporting_replica",
                "resource_id": "account_synth_04",
                "operation": "VERIFY_RECORD_ABSENT",
                "state": "ABSENT",
                "evidence_id": "",
            }),
        ),
    ),
}


def case_audit_result_to_case_output(result: CaseAuditResult) -> CaseOutput:
    """Convert an engine CaseAuditResult into an evaluator CaseOutput."""
    steps_list = [canonical_step(s.to_dict()) for s in result.steps]
    return CaseOutput(
        deletion_status=result.deletion_status,
        steps=tuple(steps_list),
    )
