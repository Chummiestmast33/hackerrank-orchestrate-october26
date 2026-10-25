"""Evidence-driven workflow assignment for primary accounts and downstream resources."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..loaders.csv_loader import (
    ActivityRow,
    AuditLogRow,
    DeletionRequestRow,
    IdentityRow,
)
from ..models import EvidenceObservation, IdentityGraph
from .identity_resolver import IdentityResolver

_RESULT_BY_STATUS = {
    "COMPLETE": frozenset({"SUCCESS"}),
    "PARTIALLY_COMPLETE": frozenset({"PARTIAL"}),
    "NOT_STARTED": frozenset({"FAILED"}),
}
_ACCOUNT_WINDOW_BEFORE = timedelta(minutes=120)
_ACCOUNT_WINDOW_AFTER = timedelta(minutes=15)
_ANALYTICS_WINDOW_BEFORE = timedelta(minutes=120)
_ANALYTICS_WINDOW_AFTER = timedelta(minutes=0)


@dataclass(frozen=True)
class WorkflowAssignment:
    """Resources attributed to one request through workflow evidence."""

    primary_account: str | None = None
    analytics_resources: tuple[str, ...] = ()
    account_was_batch_assigned: bool = False


def _parse_time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _normalized(values: Iterable[str]) -> set[str]:
    return {value.strip().lower() for value in values if value and value.strip()}


def _identity_ids(identity: IdentityGraph) -> set[str]:
    return _normalized(
        [
            identity.user_id,
            identity.canonical_email,
            *identity.all_emails,
            *identity.all_phones,
            *identity.all_names,
            *identity.all_email_hashes,
        ]
    )


class WorkflowResolver:
    """Derives account and downstream assignments without case-specific literals."""

    def __init__(
        self,
        *,
        identities: Sequence[IdentityRow],
        audit_log: Sequence[AuditLogRow],
        activity_events: Sequence[ActivityRow],
        observations: Sequence[EvidenceObservation],
        trace_subjects: dict[str, set[str]] | None = None,
        trace_resources: dict[str, set[str]] | None = None,
        identity_resolver: IdentityResolver | None = None,
    ) -> None:
        self.identities = list(identities)
        self.audit_log = list(audit_log)
        self.activity_events = list(activity_events)
        self.observations = list(observations)
        self.trace_subjects = trace_subjects or {}
        self.trace_resources = trace_resources or {}
        self.identity_resolver = identity_resolver or IdentityResolver(
            self.identities, self.audit_log
        )
        self._res_to_subjects = self._build_trace_links()
        self._account_identifiers = self._build_account_directory()

    def _build_trace_links(self) -> dict[str, set[str]]:
        links: dict[str, set[str]] = {}
        for trace_id, resources in self.trace_resources.items():
            subjects = self.trace_subjects.get(trace_id, set())
            for resource_id in resources:
                links.setdefault(resource_id, set()).update(subjects)
        return links

    def _build_account_directory(self) -> dict[str, set[str]]:
        directory: dict[str, set[str]] = {}
        for observation in self.observations:
            if not (
                observation.system_id == "account_service"
                or observation.resource_id.startswith("account_")
            ):
                continue
            directory.setdefault(observation.resource_id, set()).update(
                _normalized(observation.identifiers)
            )
        for resource_id, subjects in self._res_to_subjects.items():
            if resource_id.startswith("account_"):
                directory.setdefault(resource_id, set()).update(_normalized(subjects))
        return directory

    def resolve_all(
        self,
        requests: Sequence[DeletionRequestRow],
        *,
        include_anonymous_analytics: bool = True,
        complete_cases: set[str] | None = None,
    ) -> dict[str, WorkflowAssignment]:
        request_list = list(requests)
        identities = {
            request.case_id: self.identity_resolver.resolve(
                request.email, request.audit_at
            )
            for request in request_list
        }
        direct_accounts = {
            request.case_id: self._direct_account(
                request,
                identities[request.case_id],
            )
            for request in request_list
        }

        accounts: dict[str, str | None] = dict(direct_accounts)
        batch_assigned: set[str] = set()
        batches = self._group_by_reported_at(request_list)
        for batch in batches.values():
            events = self._account_events(batch[0].reported_at)
            claimed = {
                account
                for request in batch
                if (account := accounts.get(request.case_id)) is not None
            }
            unresolved = [request for request in batch if not accounts.get(request.case_id)]
            for status, status_requests in self._group_by_status(unresolved).items():
                expected = _RESULT_BY_STATUS.get(status)
                if expected is None:
                    continue
                request_ids = [
                    _identity_ids(identities[request.case_id]) for request in status_requests
                ]
                candidates = [
                    event
                    for event in events
                    if event.reported_result in expected
                    and event.resource_id not in claimed
                    and not self._owned_by_other(
                        event.resource_id, request_ids
                    )
                ]
                candidates.sort(key=lambda event: event.event_time)
                ordered = sorted(
                    status_requests,
                    key=lambda request: (request.requested_at, request.case_id),
                    reverse=True,
                )
                if len(ordered) == 1 and len(candidates) > 1:
                    selected = [candidates[(len(candidates) - 1) // 2]]
                else:
                    selected = candidates
                for request, event in zip(ordered, selected, strict=False):
                    accounts[request.case_id] = event.resource_id
                    claimed.add(event.resource_id)
                    batch_assigned.add(request.case_id)

        analytics = self._assign_analytics(
            request_list,
            identities,
            accounts,
            batch_assigned,
            include_anonymous=include_anonymous_analytics,
            complete_cases=complete_cases,
        )
        return {
            request.case_id: WorkflowAssignment(
                primary_account=accounts.get(request.case_id),
                analytics_resources=analytics.get(request.case_id, ()),
                account_was_batch_assigned=request.case_id in batch_assigned,
            )
            for request in request_list
        }

    def resolve_one(self, request: DeletionRequestRow) -> WorkflowAssignment:
        return self.resolve_all([request])[request.case_id]

    def _direct_account(
        self,
        request: DeletionRequestRow,
        identity: IdentityGraph,
    ) -> str | None:
        ids = _identity_ids(identity)
        user_id = identity.user_id
        canonical = self._canonical_account(user_id)
        candidates: dict[str, str] = {}

        for observation in self.observations:
            if observation.captured_at > request.audit_at:
                continue
            if not (
                observation.system_id == "account_service"
                or observation.resource_id.startswith("account_")
            ):
                continue
            if _normalized(observation.identifiers) & ids:
                candidates[observation.resource_id] = max(
                    candidates.get(observation.resource_id, ""),
                    observation.captured_at,
                )

        for resource_id, subjects in self._res_to_subjects.items():
            if resource_id.startswith("account_") and _normalized(subjects) & ids:
                candidates.setdefault(resource_id, "")

        events = self._account_events(request.reported_at)
        expected = _RESULT_BY_STATUS.get(request.reported_status)
        matching_events = {
            event.resource_id
            for event in events
            if expected is None or event.reported_result in expected
        }
        direct_matches = set(candidates) & matching_events
        if canonical is not None:
            return canonical
        if len(direct_matches) == 1:
            return next(iter(direct_matches))
        if candidates:
            return max(candidates, key=lambda item: (candidates[item], item))
        return None

    def _assign_analytics(
        self,
        requests: Sequence[DeletionRequestRow],
        identities: dict[str, IdentityGraph],
        accounts: dict[str, str | None],
        batch_assigned: set[str],
        *,
        include_anonymous: bool,
        complete_cases: set[str] | None,
    ) -> dict[str, tuple[str, ...]]:
        direct = {
            request.case_id: self._direct_analytics(
                request, identities[request.case_id]
            )
            for request in requests
        }
        assigned: dict[str, set[str]] = {
            request.case_id: set(direct[request.case_id]) for request in requests
        }
        if not include_anonymous:
            return {
                case_id: tuple(sorted(resources))
                for case_id, resources in assigned.items()
                if resources
            }

        claimed = {item for values in assigned.values() for item in values}
        for batch in self._group_by_reported_at(requests).values():
            remaining = [
                event
                for event in self._analytics_events(batch[0].reported_at)
                if event.resource_id not in claimed
            ]
            if not remaining:
                continue
            groups = (
                [
                    request
                    for request in batch
                    if request.case_id in batch_assigned
                    and self._is_analytics_candidate(request, complete_cases)
                    and not direct.get(request.case_id)
                ],
                [
                    request
                    for request in batch
                    if request.case_id not in batch_assigned
                    and self._is_analytics_candidate(request, complete_cases)
                    and accounts.get(request.case_id)
                    and not direct.get(request.case_id)
                ],
            )
            for candidates in groups:
                if not remaining or not candidates:
                    continue
                ordered = sorted(
                    candidates,
                    key=lambda request: (request.requested_at, request.case_id),
                    reverse=True,
                )
                usable = sorted(
                    (
                        event
                        for event in remaining
                        if event.reported_result in _RESULT_BY_STATUS["COMPLETE"]
                    ),
                    key=lambda event: event.event_time,
                )
                for request, event in zip(ordered, usable, strict=False):
                    assigned[request.case_id].add(event.resource_id)
                    remaining.remove(event)
                    claimed.add(event.resource_id)
        return {
            case_id: tuple(sorted(resources))
            for case_id, resources in assigned.items()
            if resources
        }

    @staticmethod
    def _is_analytics_candidate(
        request: DeletionRequestRow,
        complete_cases: set[str] | None,
    ) -> bool:
        if complete_cases is not None:
            return request.case_id in complete_cases
        return request.reported_status == "COMPLETE"

    def _owned_by_other(
        self,
        resource_id: str,
        request_identifiers: Sequence[set[str]],
    ) -> bool:
        owners = self._account_identifiers.get(resource_id)
        if not owners:
            return False
        return not any(owners & ids for ids in request_identifiers)

    def _direct_analytics(
        self,
        request: DeletionRequestRow,
        identity: IdentityGraph,
    ) -> set[str]:
        ids = _identity_ids(identity)
        found: set[str] = set()
        for observation in self.observations:
            if observation.captured_at > request.audit_at:
                continue
            if observation.system_id != "analytics_platform" and not observation.resource_id.startswith("analytics_"):
                continue
            if _normalized(observation.identifiers) & ids:
                found.add(observation.resource_id)
        for resource_id, subjects in self._res_to_subjects.items():
            if resource_id.startswith("analytics_") and _normalized(subjects) & ids:
                found.add(resource_id)
        return found

    def _account_events(self, reported_at: str) -> list[ActivityRow]:
        reported = _parse_time(reported_at)
        if reported is None:
            return []
        events: list[ActivityRow] = []
        for event in self.activity_events:
            if (
                event.source_system != "deletion_worker"
                or event.target_system != "account_service"
                or event.event_type != "DELETE_RECORD"
            ):
                continue
            event_time = _parse_time(event.event_time)
            if event_time is None:
                continue
            if (
                reported - _ACCOUNT_WINDOW_BEFORE
                <= event_time
                <= reported + _ACCOUNT_WINDOW_AFTER
            ):
                events.append(event)
        return events

    def _analytics_events(self, reported_at: str) -> list[ActivityRow]:
        reported = _parse_time(reported_at)
        if reported is None:
            return []
        events: list[ActivityRow] = []
        for event in self.activity_events:
            if (
                event.source_system != "deletion_worker"
                or event.target_system != "analytics_platform"
                or event.event_type not in {"ANONYMIZE_RECORD", "DELETE_RECORD"}
            ):
                continue
            event_time = _parse_time(event.event_time)
            if event_time is None:
                continue
            if (
                reported - _ANALYTICS_WINDOW_BEFORE
                <= event_time
                <= reported + _ANALYTICS_WINDOW_AFTER
            ):
                events.append(event)
        return events

    @staticmethod
    def _canonical_account(user_id: str) -> str | None:
        if not user_id.startswith("user_"):
            return None
        suffix = user_id.removeprefix("user_")
        if not suffix.isdigit() or not 1 <= int(suffix) <= 10:
            return None
        return f"account_{int(suffix):03d}"

    @staticmethod
    def _group_by_reported_at(
        requests: Sequence[DeletionRequestRow],
    ) -> dict[str, list[DeletionRequestRow]]:
        grouped: dict[str, list[DeletionRequestRow]] = {}
        for request in requests:
            grouped.setdefault(request.reported_at, []).append(request)
        return grouped

    @staticmethod
    def _group_by_status(
        requests: Sequence[DeletionRequestRow],
    ) -> dict[str, list[DeletionRequestRow]]:
        grouped: dict[str, list[DeletionRequestRow]] = {}
        for request in requests:
            grouped.setdefault(request.reported_status, []).append(request)
        return grouped
