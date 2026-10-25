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
        intent_classifier: IntentClassifier | None = None,
    ) -> None:
        self.identities = list(identities)
        self.audit_log = list(audit_log)
        self.activity_events = list(activity_events)
        self.rules = list(rules)
        self.observations = list(observations)
        self.reports = reports or {}

        # Initialize sub-components
        self.intent_classifier = intent_classifier or IntentClassifier()
        self.identity_resolver = IdentityResolver(self.identities, self.audit_log)
        self.inventory_builder = InventoryBuilder(
            self.observations,
            self.activity_events,
            trace_subjects=trace_subjects,
            trace_resources=trace_resources,
        )
        self.state_reconstructor = StateReconstructor(
            self.observations,
            self.reports,
            self.activity_events,
        )
        self.rules_engine = RulesEngine(self.rules)
        self.planner_sorter = PlannerSorter()

    def audit_case(self, request: DeletionRequestRow) -> CaseAuditResult:
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
        resources = self.inventory_builder.build_inventory(identity, request)

        # 4. State reconstruction
        states = self.state_reconstructor.reconstruct_states(resources, request.audit_at)

        # 5. Policy rules evaluation
        violations = self.rules_engine.evaluate_all(states)
        status = self.rules_engine.decide_status(intent.is_deletion, violations)

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
        return [self.audit_case(r) for r in sorted_requests]
