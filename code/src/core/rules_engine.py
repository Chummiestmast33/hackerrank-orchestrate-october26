"""Policy rules engine for evaluating deletion compliance (AGENTS.md section 6.4, 6.5).

Loads dataset/deletion_rules.csv and compares reconstructed resource ground states
against required actions to identify violations and map finding, remediation,
and verification operations.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..loaders.csv_loader import DeletionRuleRow
from ..models import ObservationState, PolicyViolation, ReconstructedResourceState


class RulesEngine:
    """Evaluates resource states against deletion policy rules."""

    def __init__(self, rules: Sequence[DeletionRuleRow] | None = None) -> None:
        self.rules = list(rules or [])
        self._rules_by_category: dict[str, DeletionRuleRow] = {
            r.data_category: r for r in self.rules
        }

    def evaluate_resource(
        self,
        state: ReconstructedResourceState,
    ) -> PolicyViolation | None:
        """Evaluate a single resource state and return a violation if non-compliant."""
        cat = state.data_category
        rule = self._rules_by_category.get(cat)
        action = rule.required_action if rule else "DELETE"

        # 1. Connectors / DATA_FLOW
        if cat == "DATA_FLOW" or state.system_id == "integration_service":
            if state.observed_state in (ObservationState.ACTIVE, ObservationState.PRESENT):
                return PolicyViolation(
                    resource_id=state.resource_id,
                    system_id=state.system_id,
                    data_category=cat,
                    finding_operation="REPORT_ACTIVE_DATA_FLOW",
                    remediation_operation="DISABLE_DATA_FLOW",
                    verification_operation="VERIFY_DATA_FLOW_DISABLED",
                    target_state="DISABLED",
                    evidence_id=state.evidence_id,
                )
            return None

        # 2. Backups / BACKUP_ARCHIVE
        if cat == "BACKUP_ARCHIVE" or state.system_id == "backup_service":
            if state.observed_state in (ObservationState.ACTIVE, ObservationState.PRESENT):
                return PolicyViolation(
                    resource_id=state.resource_id,
                    system_id=state.system_id,
                    data_category=cat,
                    finding_operation="REPORT_RESTORE_RISK",
                    remediation_operation="BLOCK_RESTORE",
                    verification_operation="VERIFY_RESTORE_BLOCKED",
                    target_state="BLOCKED",
                    evidence_id=state.evidence_id,
                )
            return None

        # 3. Retained records (SECURITY_AUDIT_LOG, LEGAL_HOLD_RECORD)
        if action == "RETAIN":
            return None

        # 4. Redaction: ACCOUNT_TOMBSTONE, SUPPORT_MESSAGE, EMAIL_DELIVERY_LOG
        if action == "REDACT":
            if state.pii_exposed or state.observed_state is ObservationState.PRESENT:
                return PolicyViolation(
                    resource_id=state.resource_id,
                    system_id=state.system_id,
                    data_category=cat,
                    finding_operation="REPORT_EXPOSED_PII",
                    remediation_operation="REDACT_RECORD",
                    verification_operation="VERIFY_RECORD_REDACTED",
                    target_state="REDACTED",
                    evidence_id=state.evidence_id,
                )
            return None

        # 5. Anonymization: ANALYTICS_PROFILE, PRODUCT_TELEMETRY
        if action == "ANONYMIZE":
            if state.pii_exposed or state.observed_state is ObservationState.PRESENT:
                return PolicyViolation(
                    resource_id=state.resource_id,
                    system_id=state.system_id,
                    data_category=cat,
                    finding_operation="REPORT_EXPOSED_PII",
                    remediation_operation="ANONYMIZE_RECORD",
                    verification_operation="VERIFY_RECORD_ANONYMIZED",
                    target_state="ANONYMIZED",
                    evidence_id=state.evidence_id,
                )
            return None

        # 6. Deletion (Default): USER_PROFILE, SEARCH_INDEX_ENTRY, etc.
        if action == "DELETE":
            if state.observed_state is not ObservationState.ABSENT:
                return PolicyViolation(
                    resource_id=state.resource_id,
                    system_id=state.system_id,
                    data_category=cat,
                    finding_operation="REPORT_REMAINING_RECORD",
                    remediation_operation="DELETE_RECORD",
                    verification_operation="VERIFY_RECORD_ABSENT",
                    target_state="ABSENT",
                    evidence_id=state.evidence_id,
                )
            return None

        return None

    def evaluate_all(
        self,
        states: Iterable[ReconstructedResourceState],
    ) -> list[PolicyViolation]:
        """Evaluate all resource states and collect policy violations."""
        violations: list[PolicyViolation] = []
        for state in states:
            viol = self.evaluate_resource(state)
            if viol is not None:
                violations.append(viol)
        return violations

    def decide_status(
        self,
        is_deletion: bool,
        violations: Sequence[PolicyViolation],
        states: Sequence[ReconstructedResourceState] = (),
    ) -> str:
        """Decide case status: NOT_APPLICABLE, COMPLETE, or INCOMPLETE."""
        if not is_deletion:
            return "NOT_APPLICABLE"
        if violations:
            return "INCOMPLETE"
        return "COMPLETE"
