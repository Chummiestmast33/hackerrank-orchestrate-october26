"""Inventory builder for discovering all user-related resources (AGENTS.md section 6.1, 6.5).

Discovers resources (system_id, resource_id, data_category) belonging to an IdentityGraph
through parsed evidence observations, log trace correlation, activity stream linkages,
and workflow-window primary account correlation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from ..loaders.csv_loader import ActivityRow, DeletionRequestRow
from ..models import EvidenceObservation, IdentityGraph, ResourceItem


class InventoryBuilder:
    """Discovers all resources associated with a user identity graph."""

    def __init__(
        self,
        observations: Sequence[EvidenceObservation] | None = None,
        activity_events: Sequence[ActivityRow] | None = None,
        trace_subjects: dict[str, set[str]] | None = None,
        trace_resources: dict[str, set[str]] | None = None,
    ) -> None:
        self.observations = list(observations or [])
        self.activity_events = list(activity_events or [])
        self.trace_subjects = trace_subjects or {}
        self.trace_resources = trace_resources or {}

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
        if system_id in ("email_delivery_service", "notification_service") or resource_id.startswith("email_delivery_"):
            return "EMAIL_DELIVERY_LOG"
        return "USER_PROFILE"

    def build_inventory(
        self,
        identity: IdentityGraph,
        request: DeletionRequestRow | None = None,
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

        # Filter out empty or trivial strings
        all_ids = {i for i in all_ids if len(i) > 3}

        discovered: dict[tuple[str, str], ResourceItem] = {}

        # 1. Match from evidence observations
        for obs in self.observations:
            obs_ids = {str(i).strip().lower() for i in obs.identifiers}
            if obs_ids & all_ids:
                cat = obs.data_category or self._infer_category(obs.system_id, obs.resource_id)
                key = (obs.system_id, obs.resource_id)
                discovered[key] = ResourceItem(
                    system_id=obs.system_id,
                    resource_id=obs.resource_id,
                    data_category=cat,
                    discovery_source=f"observation:{obs.file_id}",
                    is_primary_account=(obs.system_id == "account_service"),
                )

        # 2. Match from log traces
        for res_id, subs in self._res_to_subjects.items():
            if subs & all_ids:
                if res_id in self._obs_sys_cat:
                    sys_id, cat = self._obs_sys_cat[res_id]
                else:
                    sys_name = "account_service" if res_id.startswith("account_") else "security_service"
                    for a in self.activity_events:
                        if a.resource_id == res_id and (a.target_system or a.source_system):
                            sys_name = a.target_system or a.source_system
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

        # 3. Match from activity log details
        for a in self.activity_events:
            if a.resource_id:
                # Check if any user identifier is in details
                det_lower = a.details.lower()
                if any(i in det_lower for i in all_ids if len(i) > 4):
                    sys_id = a.target_system or a.source_system or "account_service"
                    cat = self._infer_category(sys_id, a.resource_id)
                    key = (sys_id, a.resource_id)
                    if key not in discovered:
                        discovered[key] = ResourceItem(
                            system_id=sys_id,
                            resource_id=a.resource_id,
                            data_category=cat,
                            discovery_source=f"activity:{a.activity_id}",
                            is_primary_account=(sys_id == "account_service"),
                        )

        # 4. Primary account resolution
        found_account = any(sys_id == "account_service" for sys_id, _ in discovered)
        uid_num = identity.user_id.replace("user_", "")
        canonical_acc = f"account_{uid_num}"

        if not found_account:
            # Check canonical account format against observations or activity
            acc_exists = any(
                obs.resource_id == canonical_acc for obs in self.observations
            ) or any(
                a.resource_id == canonical_acc for a in self.activity_events
            )
            if acc_exists:
                key = ("account_service", canonical_acc)
                discovered[key] = ResourceItem(
                    system_id="account_service",
                    resource_id=canonical_acc,
                    data_category="USER_PROFILE",
                    discovery_source="canonical_account",
                    is_primary_account=True,
                )
                found_account = True

        if not found_account and request is not None:
            # Look up deletion_worker DELETE_RECORD on account_service in workflow window
            rep_dt = datetime.fromisoformat(request.reported_at.replace("Z", "+00:00"))
            window_start = rep_dt - timedelta(minutes=80)
            window_end = rep_dt + timedelta(minutes=15)
            for a in self.activity_events:
                if a.source_system == "deletion_worker" and a.target_system == "account_service":
                    try:
                        adt = datetime.fromisoformat(a.event_time.replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if window_start <= adt <= window_end:
                        key = ("account_service", a.resource_id)
                        discovered[key] = ResourceItem(
                            system_id="account_service",
                            resource_id=a.resource_id,
                            data_category="USER_PROFILE",
                            discovery_source=f"workflow_window:{a.activity_id}",
                            is_primary_account=True,
                        )
                        found_account = True
                        break

        if not found_account:
            key = ("account_service", canonical_acc)
            discovered[key] = ResourceItem(
                system_id="account_service",
                resource_id=canonical_acc,
                data_category="USER_PROFILE",
                discovery_source="fallback_account",
                is_primary_account=True,
            )

        return tuple(discovered.values())
