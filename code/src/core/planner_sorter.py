"""Plan generator and canonical 4-key step sorter (AGENTS.md section 6.3, 6.4, 6.5).

Builds finding, remediation, and verification steps according to the Ghost Data Still Exists
specification. Enforces citation rules (proves at audit_at, empty for future remediation/verification),
applies canonical 4-key sorting, and outputs consecutively numbered steps (1..N).
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from ..models import AuditStep, CaseAuditResult, PolicyViolation, ReconstructedResourceState

PHASE_ORDER: dict[str, int] = {
    "FINDING": 1,
    "REMEDIATION": 2,
    "VERIFICATION": 3,
}

OP_ORDER: dict[str, int] = {
    # Findings
    "REPORT_REMAINING_RECORD": 1,
    "REPORT_EXPOSED_PII": 2,
    "REPORT_ACTIVE_DATA_FLOW": 3,
    "REPORT_RESTORE_RISK": 4,
    # Remediation
    "DISABLE_DATA_FLOW": 10,
    "BLOCK_RESTORE": 11,
    "DELETE_RECORD": 12,
    "REDACT_RECORD": 13,
    "ANONYMIZE_RECORD": 14,
    # Verification
    "VERIFY_RECORD_ABSENT": 20,
    "VERIFY_RECORD_PRESENT": 21,
    "VERIFY_RECORD_REDACTED": 22,
    "VERIFY_RECORD_ANONYMIZED": 23,
    "VERIFY_DATA_FLOW_DISABLED": 24,
    "VERIFY_RESTORE_BLOCKED": 25,
}


def _target_verification(system_id: str, data_category: str) -> tuple[str, str]:
    """Return (verification_operation, target_state) for a resource category."""
    if data_category in ("SECURITY_AUDIT_LOG", "LEGAL_HOLD_RECORD"):
        return "VERIFY_RECORD_PRESENT", "PRESENT"
    if data_category == "ACCOUNT_TOMBSTONE" or data_category in ("SUPPORT_MESSAGE", "EMAIL_DELIVERY_LOG"):
        return "VERIFY_RECORD_REDACTED", "REDACTED"
    if data_category in ("ANALYTICS_PROFILE", "PRODUCT_TELEMETRY"):
        return "VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"
    if data_category == "BACKUP_ARCHIVE" or system_id == "backup_service":
        return "VERIFY_RESTORE_BLOCKED", "BLOCKED"
    if data_category == "DATA_FLOW" or system_id == "integration_service":
        return "VERIFY_DATA_FLOW_DISABLED", "DISABLED"
    return "VERIFY_RECORD_ABSENT", "ABSENT"


class PlannerSorter:
    """Generates and sorts compliant audit steps for a case."""

    def build_case_result(
        self,
        case_id: str,
        deletion_status: str,
        states: Sequence[ReconstructedResourceState],
        violations: Sequence[PolicyViolation],
    ) -> CaseAuditResult:
        """Construct full CaseAuditResult with sorted, numbered steps."""
        if deletion_status == "NOT_APPLICABLE":
            return CaseAuditResult(
                case_id=case_id,
                deletion_status="NOT_APPLICABLE",
                steps=(),
                steps_json="[]",
            )

        raw_steps: list[dict[str, str]] = []

        if deletion_status == "COMPLETE":
            # Verification steps only, citing proving evidence_id
            for state in states:
                verif_op, target_st = _target_verification(state.system_id, state.data_category)
                raw_steps.append({
                    "phase": "VERIFICATION",
                    "system_id": state.system_id,
                    "resource_id": state.resource_id,
                    "operation": verif_op,
                    "state": target_st,
                    "evidence_id": state.evidence_id,
                })
        else:
            # INCOMPLETE: Findings, Remediation, and Verification
            # 1. Findings
            for viol in violations:
                finding_state = "ACTIVE" if viol.finding_operation in ("REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK") else "PRESENT"
                raw_steps.append({
                    "phase": "FINDING",
                    "system_id": viol.system_id,
                    "resource_id": viol.resource_id,
                    "operation": viol.finding_operation,
                    "state": finding_state,
                    "evidence_id": viol.evidence_id,
                })

            # 2. Remediation (evidence_id is empty)
            for viol in violations:
                raw_steps.append({
                    "phase": "REMEDIATION",
                    "system_id": viol.system_id,
                    "resource_id": viol.resource_id,
                    "operation": viol.remediation_operation,
                    "state": viol.target_state,
                    "evidence_id": "",
                })

            # 3. Verification for all resources (evidence_id is empty)
            for state in states:
                verif_op, target_st = _target_verification(state.system_id, state.data_category)
                raw_steps.append({
                    "phase": "VERIFICATION",
                    "system_id": state.system_id,
                    "resource_id": state.resource_id,
                    "operation": verif_op,
                    "state": target_st,
                    "evidence_id": "",
                })

        # Canonical 4-Key Sort
        raw_steps.sort(
            key=lambda s: (
                PHASE_ORDER.get(s["phase"], 99),
                OP_ORDER.get(s["operation"], 99),
                s["system_id"],
                s["resource_id"],
            )
        )

        # Consecutive 1-based numbering
        final_steps: list[AuditStep] = []
        for idx, s in enumerate(raw_steps, start=1):
            final_steps.append(
                AuditStep(
                    step_no=idx,
                    phase=s["phase"],
                    system_id=s["system_id"],
                    resource_id=s["resource_id"],
                    operation=s["operation"],
                    state=s["state"],
                    evidence_id=s["evidence_id"],
                )
            )

        steps_json = json.dumps([s.to_dict() for s in final_steps], separators=(",", ":"))

        return CaseAuditResult(
            case_id=case_id,
            deletion_status=deletion_status,
            steps=tuple(final_steps),
            steps_json=steps_json,
        )
