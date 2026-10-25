"""State reconstructor for auditing resource ground state at audit_at (AGENTS.md section 6.2, 6.5, 6.6).

Reconstructs the ground state of every inventory resource strictly as of audit_at.
Rejects claims, selects latest observations <= audit_at, evaluates post-deletion recreations,
and resolves scoped implicit absence proofs.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..loaders.csv_loader import ActivityRow
from ..models import (
    EvidenceObservation,
    ObservationState,
    ParseReport,
    Provenance,
    ReconstructedResourceState,
    ResourceItem,
)


class StateReconstructor:
    """Reconstructs the state of inventory resources at audit_at."""

    def __init__(
        self,
        observations: Sequence[EvidenceObservation],
        reports: dict[str, ParseReport] | None = None,
        activity_events: Sequence[ActivityRow] | None = None,
    ) -> None:
        self.observations = list(observations)
        self.reports = reports or {}
        self.activity_events = list(activity_events or [])

    def reconstruct_states(
        self,
        resources: Iterable[ResourceItem],
        audit_at: str,
    ) -> list[ReconstructedResourceState]:
        """Reconstruct state of all resources as of audit_at."""
        # 1. Strict temporal filter (both observation time and parent file capture time <= audit_at)
        valid_obs = [
            obs for obs in self.observations
            if obs.captured_at <= audit_at
            and (self.reports.get(obs.file_id) is None or self.reports[obs.file_id].captured_at <= audit_at)
        ]

        states: list[ReconstructedResourceState] = []

        for res in resources:
            # Find matching observations <= audit_at
            matching = [
                obs for obs in valid_obs
                if obs.resource_id == res.resource_id and obs.system_id == res.system_id
            ]

            if matching:
                # Latest observation wins
                matching.sort(key=lambda o: o.captured_at, reverse=True)
                latest = matching[0]

                # Check for post-observation recreation via activity <= audit_at
                recreated = False
                for a in self.activity_events:
                    if (
                        a.resource_id == res.resource_id
                        and a.event_time > latest.captured_at
                        and a.event_time <= audit_at
                    ):
                        if a.event_type in ("SYNC_RECORD", "RESTORE_BACKUP") and a.reported_result == "SUCCESS":
                            recreated = True
                            break

                final_state = ObservationState.PRESENT if recreated else latest.state

                states.append(
                    ReconstructedResourceState(
                        resource_id=res.resource_id,
                        system_id=res.system_id,
                        data_category=res.data_category,
                        observed_state=final_state,
                        pii_exposed=latest.pii_exposed,
                        evidence_id=latest.file_id,
                        provenance=latest.provenance,
                        observed_at=latest.captured_at,
                    )
                )
            else:
                # Scoped implicit absence check
                proving_file_id = ""
                # Look for scoped files covering system_id <= audit_at
                eligible_files = [
                    (fid, rep) for fid, rep in self.reports.items()
                    if rep.captured_at <= audit_at and (
                        res.system_id in rep.direct_systems
                        or any(c.data_store == res.system_id for c in rep.captured_collections)
                    )
                ]
                if eligible_files:
                    eligible_files.sort(key=lambda item: item[1].captured_at, reverse=True)
                    proving_file_id = eligible_files[0][0]

                obs_st = ObservationState.ABSENT
                states.append(
                    ReconstructedResourceState(
                        resource_id=res.resource_id,
                        system_id=res.system_id,
                        data_category=res.data_category,
                        observed_state=obs_st,
                        pii_exposed=False,
                        evidence_id=proving_file_id,
                        provenance=Provenance.SCOPE_IMPLICIT,
                        observed_at=None,
                    )
                )

        return states
