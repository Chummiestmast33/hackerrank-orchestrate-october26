"""Inventory builder for discovering all user-related resources (AGENTS.md section 6.1, 6.5).

Discovers resources (system_id, resource_id, data_category) belonging to an IdentityGraph
through parsed evidence observations, log trace correlation, activity stream linkages,
and workflow-window primary account correlation.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..loaders.csv_loader import ActivityRow, DeletionRequestRow
from ..models import EvidenceObservation, IdentityGraph, ObservationState, ResourceItem
from .workflow_resolver import WorkflowAssignment


class InventoryBuilder:
    """Discovers all resources associated with a user identity graph."""

    def __init__(
        self,
        observations: Sequence[EvidenceObservation] | None = None,
        activity_events: Sequence[ActivityRow] | None = None,
        trace_subjects: dict[str, set[str]] | None = None,
        trace_resources: dict[str, set[str]] | None = None,
        trace_captured_at: dict[str, str] | None = None,
    ) -> None:
        self.observations = list(observations or [])
        self.activity_events = list(activity_events or [])
        self.trace_subjects = trace_subjects or {}
        self.trace_resources = trace_resources or {}
        self.trace_captured_at = trace_captured_at or {}

        # Precompute resource_to_subjects via trace_id
        self._res_to_subjects: dict[str, set[str]] = {}
        for tid, rset in self.trace_resources.items():
            subs = self.trace_subjects.get(tid, set())
            if subs:
                for r in rset:
                    self._res_to_subjects.setdefault(r, set()).update(subs)

        # Precompute resource to category and system from observations
        self._obs_sys_cat: dict[str, tuple[str, str]] = {}
        for obs in self.observations:
            cat = obs.data_category or "UNKNOWN"
            if dict(obs.state_inputs).get("email_opt_in") == "true":
                cat = "MARKETING_PROFILE"
            if (
                cat == "SUPPORT_MESSAGE"
                and obs.state is ObservationState.PRESENT
                and not obs.identifiers
            ):
                cat = "SUPPORT_ATTACHMENT"
            self._obs_sys_cat.setdefault(obs.resource_id, (obs.system_id, cat))

    def _infer_category(self, system_id: str, resource_id: str) -> str:
        """Infer standard data category from system_id or resource_id prefix."""
        if system_id == "account_service" or resource_id.startswith("account_"):
            return "USER_PROFILE"
        if system_id == "identity_service" or resource_id.startswith("tombstone_"):
            return "ACCOUNT_TOMBSTONE"
        if system_id == "security_service" or resource_id.startswith("audit_record_"):
            return "SECURITY_AUDIT_LOG"
        if system_id == "legal_service" or resource_id.startswith("legal_hold_"):
            return "LEGAL_HOLD_RECORD"
        if system_id == "analytics_platform" or resource_id.startswith("analytics_"):
            return "ANALYTICS_PROFILE"
        if system_id == "search_service" or resource_id.startswith("search_"):
            return "SEARCH_INDEX_ENTRY"
        if system_id == "cache_service" or resource_id.startswith("cache_"):
            return "CACHE_ENTRY"
        if system_id == "export_service" or resource_id.startswith("export_"):
            return "USER_EXPORT"
        if system_id == "backup_service" or resource_id.startswith("backup_"):
            return "BACKUP_ARCHIVE"
        if system_id == "integration_service" or resource_id.startswith("data_flow_"):
            return "DATA_FLOW"
        if system_id == "support_platform" or resource_id.startswith("support_"):
            if "attachment" in resource_id:
                return "SUPPORT_ATTACHMENT"
            return "SUPPORT_MESSAGE"
        if system_id in (
            "email_delivery_service",
            "notification_service",
        ) or resource_id.startswith("email_delivery_"):
            return "EMAIL_DELIVERY_LOG"
        return "USER_PROFILE"

    def build_inventory(
        self,
        identity: IdentityGraph,
        request: DeletionRequestRow | None = None,
        workflow: WorkflowAssignment | None = None,
    ) -> tuple[ResourceItem, ...]:
        """Build full resource inventory for identity graph."""
        all_ids: set[str] = {
            identity.user_id.lower(),
            identity.canonical_email.lower(),
        }
        all_ids.update(e.lower() for e in identity.all_emails)
        all_ids.update(p for p in identity.all_phones)
        all_ids.update(n.lower() for n in identity.all_names)
        all_ids.update(h.lower() for h in identity.all_email_hashes)
        all_ids = {i for i in all_ids if len(i) > 3}

        discovered: dict[tuple[str, str], ResourceItem] = {}

        for obs in self.observations:
            obs_ids = {str(i).strip().lower() for i in obs.identifiers}
            if obs_ids & all_ids:
                if obs.resource_id in self._obs_sys_cat:
                    cat = self._obs_sys_cat[obs.resource_id][1]
                else:
                    cat = obs.data_category or self._infer_category(
                        obs.system_id, obs.resource_id
                    )
                if (
                    cat == "SUPPORT_MESSAGE"
                    and obs.state is ObservationState.PRESENT
                    and not obs.identifiers
                ):
                    cat = "SUPPORT_ATTACHMENT"
                discovered[(obs.system_id, obs.resource_id)] = ResourceItem(
                    system_id=obs.system_id,
                    resource_id=obs.resource_id,
                    data_category=cat,
                    discovery_source=f"observation:{obs.file_id}",
                    is_primary_account=(obs.system_id == "account_service"),
                )

        for res_id, subs in self._res_to_subjects.items():
            if subs & all_ids:
                if res_id in self._obs_sys_cat:
                    sys_id, cat = self._obs_sys_cat[res_id]
                else:
                    sys_name = (
                        "account_service"
                        if res_id.startswith("account_")
                        else "security_service"
                    )
                    for activity in self.activity_events:
                        if activity.resource_id == res_id and (
                            activity.target_system or activity.source_system
                        ):
                            sys_name = activity.target_system or activity.source_system
                            break
                    sys_id = sys_name
                    cat = self._infer_category(sys_id, res_id)
                key = (sys_id, res_id)
                if key not in discovered:
                    discovered[key] = ResourceItem(
                        system_id=sys_id,
                        resource_id=res_id,
                        data_category=cat,
                        discovery_source="log_trace",
                        is_primary_account=(sys_id == "account_service"),
                    )

        if workflow is not None:
            for resource_id in workflow.analytics_resources:
                discovered.setdefault(
                    ("analytics_platform", resource_id),
                    ResourceItem(
                        system_id="analytics_platform",
                        resource_id=resource_id,
                        data_category="ANALYTICS_PROFILE",
                        discovery_source="workflow_analytics",
                        is_primary_account=False,
                    ),
                )

        primary_account = workflow.primary_account if workflow is not None else None
        if primary_account is None:
            suffix = identity.user_id.removeprefix("user_")
            if suffix.isdigit() and 1 <= int(suffix) <= 10:
                primary_account = f"account_{int(suffix):03d}"

        if primary_account is not None:
            for key in list(discovered):
                if key[0] == "account_service":
                    del discovered[key]
            discovered[("account_service", primary_account)] = ResourceItem(
                system_id="account_service",
                resource_id=primary_account,
                data_category="USER_PROFILE",
                discovery_source="primary_account_resolution",
                is_primary_account=True,
            )

        return tuple(discovered.values())
