"""Coordinating audit engine for Ghost Data Still Exists (AGENTS.md section 1, 6).

Coordinates intent classification, identity resolution, inventory discovery,
state reconstruction, policy evaluation, and canonical planning for deletion requests.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..loaders.csv_loader import (
    ActivityRow,
    AuditLogRow,
    DeletionRequestRow,
    DeletionRuleRow,
    IdentityRow,
)
from ..models import (
    CaseAuditResult,
    EvidenceObservation,
    ParseReport,
)
from .identity_resolver import IdentityResolver
from .intent_classifier import IntentClassifier
from .inventory_builder import InventoryBuilder
from .planner_sorter import PlannerSorter
from .rules_engine import RulesEngine
from .state_reconstructor import StateReconstructor
from .workflow_resolver import WorkflowAssignment, WorkflowResolver


class AuditEngine:
    """Full coordinator for evaluating deletion requests."""

    def __init__(
        self,
        identities: Sequence[IdentityRow],
        audit_log: Sequence[AuditLogRow],
        activity_events: Sequence[ActivityRow],
        rules: Sequence[DeletionRuleRow],
        observations: Sequence[EvidenceObservation],
        reports: dict[str, ParseReport] | None = None,
        trace_subjects: dict[str, set[str]] | None = None,
        trace_resources: dict[str, set[str]] | None = None,
        trace_captured_at: dict[str, str] | None = None,
        intent_classifier: IntentClassifier | None = None,
    ) -> None:
        self.identities = list(identities)
        self.audit_log = list(audit_log)
        self.activity_events = list(activity_events)
        self.rules = list(rules)
        self.observations = list(observations)
        self.reports = reports or {}
        self.trace_subjects = trace_subjects or {}
        self.trace_resources = trace_resources or {}
        self.trace_captured_at = trace_captured_at or {}

        # Initialize sub-components
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.identity_resolver = IdentityResolver(self.identities, self.audit_log)
        self.workflow_resolver = WorkflowResolver(
            identities=self.identities,
            audit_log=self.audit_log,
            activity_events=self.activity_events,
            observations=self.observations,
            trace_subjects=self.trace_subjects,
            trace_resources=self.trace_resources,
            identity_resolver=self.identity_resolver,
        )
        self.inventory_builder = InventoryBuilder(
            self.observations,
            self.activity_events,
            trace_subjects=trace_subjects,
            trace_resources=trace_resources,
            trace_captured_at=trace_captured_at,
        )
        self.state_reconstructor = StateReconstructor(
            self.observations,
            self.reports,
            self.activity_events,
        )
        self.rules_engine = RulesEngine(self.rules)
        self.planner_sorter = PlannerSorter()

    def audit_case(
        self,
        request: DeletionRequestRow,
        workflow: WorkflowAssignment | None = None,
    ) -> CaseAuditResult:
        """Run full deletion audit for a single request."""
        # 1. Intent classification
        intent = self.intent_classifier.classify(
            request.request_text,
            activity_events=self.activity_events,
            audit_at=request.audit_at,
        )
        if not intent.is_deletion:
            return self.planner_sorter.build_case_result(
                case_id=request.case_id,
                deletion_status="NOT_APPLICABLE",
                states=(),
                violations=(),
            )

        # 2. Identity resolution
        identity = self.identity_resolver.resolve(request.email, request.audit_at)

        # 3. Inventory discovery
        assignment = workflow or self.workflow_resolver.resolve_one(request)
        resources = self.inventory_builder.build_inventory(
            identity,
            request,
            workflow=assignment,
        )

        # 4. State reconstruction
        states = self.state_reconstructor.reconstruct_states(resources, request.audit_at)

        # 5. Policy rules evaluation
        violations = self.rules_engine.evaluate_all(states)
        status = self.rules_engine.decide_status(intent.is_deletion, violations, states)

        # 6. Planning and canonical sort
        return self.planner_sorter.build_case_result(
            case_id=request.case_id,
            deletion_status=status,
            states=states,
            violations=violations,
        )

    def audit_all(self, requests: Sequence[DeletionRequestRow]) -> list[CaseAuditResult]:
        """Audit a collection of requests, sorted by case_id."""
        sorted_requests = sorted(requests, key=lambda r: r.case_id)
        base_assignments = self.workflow_resolver.resolve_all(
            sorted_requests,
            include_anonymous_analytics=False,
        )
        preliminary = [
            self.audit_case(request, workflow=base_assignments.get(request.case_id))
            for request in sorted_requests
        ]
        complete_cases = {
            result.case_id
            for result in preliminary
            if result.deletion_status == "COMPLETE"
        }
        final_assignments = self.workflow_resolver.resolve_all(
            sorted_requests,
            complete_cases=complete_cases,
        )
        return [
            self.audit_case(
                request,
                workflow=final_assignments.get(request.case_id),
            )
            for request in sorted_requests
        ]
