"""Hybrid AI Audit Agent with Tool-Calling, Proposal Verification & Guardrails (AGENTS.md §1, §6).

Implements an AI-proposal -> deterministic-verification -> canonical-output architecture:
1. MultimodalVisionAgent (qwen3-vl-plus): Processes all 11 PNG console screenshots in
   dataset/evidence/images/ by default when live vision is enabled, validating extracted
   fields against per-family schemas (transcription_validator.py).
2. IntentDocumentAgent (qwen3.7-max): Classifies all distinct multilingual/nuanced
   request_text strings in smart batches (persisting verified verdicts to
   intent_classifications.json) and analyzes both handover TXT and all 4 PDF evidence
   documents (via pdf_extractor.py).
3. AuditOrchestratorAgent (qwen3.7-max with Tools): Exposes deterministic modules as
   structured tools (resolve_subject_identities, query_system_inventory,
   reconstruct_resource_states, build_compliant_remediation_plan), persists every tool
   call output, generates structured AgentCaseProposal objects across cases, and
   validates every proposal through DeterministicProposalVerifier before accepting or
   falling back to the deterministic engine.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..evaluation.metering import Meter, metered_call
from ..evaluation.schema import (
    ALLOWED_STATUSES,
    OPERATION_PHASE_STATE,
    PHASE_ORDER,
    validate_row,
)
from ..loaders.csv_loader import DeletionRequestRow, EvidenceFileRow
from ..loaders.pdf_extractor import detect_family, extract_text, normalize_text
from ..loaders.transcription_validator import validate_transcription
from ..loaders.vlm_extractor import VisionConfig, transcribe_image
from ..models import (
    AuditStep,
    CaseAuditResult,
    EvidenceObservation,
    IntentVerdict,
    ObservationState,
    Provenance,
)
from .audit_engine import AuditEngine
from .planner_sorter import OP_ORDER

AGENT_CACHE_FILE = "agent_decisions.json"

AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "resolve_subject_identities",
            "description": (
                "Resolve current and historical subject identifiers (stable user_id, "
                "emails, phones, names, and SHA-256 email hashes) and primary account "
                "assignment up to the audit_at temporal cutoff."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Email address supplied with the deletion request.",
                    },
                    "audit_at": {
                        "type": "string",
                        "description": "ISO-8601 UTC cutoff timestamp for the audit.",
                    },
                },
                "required": ["email", "audit_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_system_inventory",
            "description": (
                "Discover all resources across primary databases, SQL replicas, logs, "
                "support tickets, exports, search indexes, analytics, integration flows, "
                "and backup archives linked to the subject at or before audit_at."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Subject email address.",
                    },
                    "audit_at": {
                        "type": "string",
                        "description": "ISO-8601 UTC cutoff timestamp.",
                    },
                },
                "required": ["email", "audit_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reconstruct_resource_states",
            "description": (
                "Reconstruct the true point-in-time state (PRESENT, ABSENT, REDACTED, "
                "ANONYMIZED, ACTIVE, DISABLED, BLOCKED) and proving evidence_id for "
                "each discovered resource at audit_at."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {
                        "type": "string",
                        "description": "Subject email address.",
                    },
                    "audit_at": {
                        "type": "string",
                        "description": "ISO-8601 UTC cutoff timestamp.",
                    },
                },
                "required": ["email", "audit_at"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "build_compliant_remediation_plan",
            "description": (
                "Apply deletion_rules.csv to reconstructed resource states and build "
                "the canonically ordered FINDING, REMEDIATION, and VERIFICATION steps."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "request_id": {
                        "type": "string",
                        "description": "Unique identifier of the deletion request.",
                    },
                    "email": {
                        "type": "string",
                        "description": "Subject email address.",
                    },
                    "request_text": {
                        "type": "string",
                        "description": "Raw user request text.",
                    },
                    "audit_at": {
                        "type": "string",
                        "description": "ISO-8601 UTC cutoff timestamp.",
                    },
                },
                "required": ["request_id", "email", "request_text", "audit_at"],
            },
        },
    },
]


@dataclass(frozen=True)
class AgentConfig:
    """Runtime configuration for the Qwen LLM and Vision agents."""

    provider: str
    text_model: str
    vision_model: str
    base_url: str
    api_key: str

    @classmethod
    def from_env(cls) -> AgentConfig:
        provider = (os.environ.get("AGENT_MODEL_PROVIDER") or "qwen").strip().lower()
        text_model = (
            os.environ.get("QWEN_MODEL")
            or os.environ.get("TEXT_MODEL")
            or "qwen3.7-max"
        ).strip()
        vision_model = (
            os.environ.get("QWEN_VISION_MODEL")
            or os.environ.get("VISION_MODEL")
            or "qwen3-vl-plus"
        ).strip()
        base_url = (
            os.environ.get("QWEN_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
        ).strip()
        api_key = (
            os.environ.get("DASHSCOPE_API_KEY")
            or os.environ.get("QWEN_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or ""
        ).strip()
        return cls(
            provider=provider,
            text_model=text_model,
            vision_model=vision_model,
            base_url=base_url,
            api_key=api_key,
        )

    def available(self) -> bool:
        return bool(self.api_key)


@dataclass
class AgentCaseProposal:
    """Structured AI audit proposal for a single request prior to deterministic verification."""

    case_id: str
    proposed_status: str
    proposed_steps: tuple[dict[str, Any], ...]
    cited_evidence_ids: tuple[str, ...]
    provider: str
    model: str
    purpose: str
    confidence: float
    rationale: str
    accepted: bool = False
    decision_outcome: str = "PENDING"
    rejection_reason: str = ""
    used_deterministic_fallback: bool = False
    final_status: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "proposed_status": self.proposed_status,
            "final_status": self.final_status or self.proposed_status,
            "step_count": len(self.proposed_steps),
            "cited_evidence_ids": list(self.cited_evidence_ids),
            "provider": self.provider,
            "model": self.model,
            "purpose": self.purpose,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "accepted": self.accepted,
            "decision_outcome": self.decision_outcome,
            "rejection_reason": self.rejection_reason,
            "used_deterministic_fallback": self.used_deterministic_fallback,
        }


@dataclass(frozen=True)
class ProposalValidationResult:
    """Outcome of validating an AgentCaseProposal with DeterministicProposalVerifier."""

    valid: bool
    reason: str
    canonical_result: CaseAuditResult | None = None


@dataclass
class AgentInfluenceSummary:
    """Aggregate metrics tracking AI proposals, deterministic verifications, and fallbacks."""

    total_cases: int
    live_llm_enabled: bool
    proposals_evaluated: int = 0
    proposals_accepted: int = 0
    proposals_rejected: int = 0
    not_applicable_proposals: int = 0
    deterministic_fallbacks: int = 0
    vision_files_verified: int = 0
    vision_files_total: int = 0
    documents_analyzed: int = 0
    txt_documents_analyzed: int = 0
    pdf_documents_analyzed: int = 0
    unique_intents_classified: int = 0
    tool_calls_executed: int = 0
    cohorts_orchestrated: int = 0
    adjudication_batches_run: int = 0
    rejection_reasons: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_cases": self.total_cases,
            "live_llm_enabled": self.live_llm_enabled,
            "proposals_evaluated": self.proposals_evaluated,
            "proposals_accepted": self.proposals_accepted,
            "proposals_rejected": self.proposals_rejected,
            "not_applicable_proposals": self.not_applicable_proposals,
            "deterministic_fallbacks": self.deterministic_fallbacks,
            "vision_files_verified": self.vision_files_verified,
            "vision_files_total": self.vision_files_total,
            "documents_analyzed": self.documents_analyzed,
            "txt_documents_analyzed": self.txt_documents_analyzed,
            "pdf_documents_analyzed": self.pdf_documents_analyzed,
            "unique_intents_classified": self.unique_intents_classified,
            "tool_calls_executed": self.tool_calls_executed,
            "cohorts_orchestrated": self.cohorts_orchestrated,
            "adjudication_batches_run": self.adjudication_batches_run,
            "rejection_reasons": dict(sorted(self.rejection_reasons.items())),
        }


def _create_openai_client(config: AgentConfig) -> Any:
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": config.api_key}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    return OpenAI(**kwargs)


def _strip_json_fence(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    return text


class DeterministicProposalVerifier:
    """Validates AI proposals against schema, manifest, temporal, semantic, and policy rules."""

    def __init__(
        self,
        engine: AuditEngine,
        manifest: Sequence[EvidenceFileRow],
    ) -> None:
        self.engine = engine
        self.manifest_by_id: dict[str, str] = {
            row.file_id: row.captured_at for row in manifest
        }
        self.obs_by_file_res: dict[tuple[str, str], list[EvidenceObservation]] = {}
        for obs in engine.observations:
            self.obs_by_file_res.setdefault((obs.file_id, obs.resource_id), []).append(obs)
        self.act_by_id: dict[str, str] = {
            act.activity_id: act.event_time for act in engine.activity_events
        }

    def validate_proposal(
        self,
        request: DeletionRequestRow,
        proposal: AgentCaseProposal,
        baseline: CaseAuditResult,
    ) -> ProposalValidationResult:
        """Validate a single AI case proposal and return a canonical CaseAuditResult if valid."""
        # 1. Status enum check
        if proposal.proposed_status not in ALLOWED_STATUSES:
            return ProposalValidationResult(
                valid=False,
                reason=f"invalid_status:{proposal.proposed_status}",
            )

        # 2. Validate raw step objects and allowed operation/phase/state pairs
        normalized_raw: list[dict[str, str]] = []
        for idx, raw_step in enumerate(proposal.proposed_steps, start=1):
            if not isinstance(raw_step, dict):
                return ProposalValidationResult(
                    valid=False,
                    reason=f"schema_violation:step_{idx}_not_dict",
                )
            phase = str(raw_step.get("phase") or "")
            system_id = str(raw_step.get("system_id") or "")
            resource_id = str(raw_step.get("resource_id") or "")
            operation = str(raw_step.get("operation") or "")
            state = str(raw_step.get("state") or "")
            evidence_id = str(raw_step.get("evidence_id") or "")

            if not system_id or not resource_id:
                return ProposalValidationResult(
                    valid=False,
                    reason=f"schema_violation:step_{idx}_missing_system_or_resource",
                )
            if phase not in PHASE_ORDER or operation not in OPERATION_PHASE_STATE:
                return ProposalValidationResult(
                    valid=False,
                    reason=f"schema_violation:unknown_phase_or_operation:{phase}:{operation}",
                )
            want_phase, want_state = OPERATION_PHASE_STATE[operation]
            if phase != want_phase or state != want_state:
                return ProposalValidationResult(
                    valid=False,
                    reason=f"schema_violation:operation_phase_state_mismatch:{operation}:{phase}:{state}",
                )
            normalized_raw.append(
                {
                    "phase": phase,
                    "system_id": system_id,
                    "resource_id": resource_id,
                    "operation": operation,
                    "state": state,
                    "evidence_id": evidence_id,
                }
            )

        # 3. Canonical 4-key sort, consecutive 1..N numbering, and schema.validate_row
        if proposal.proposed_status == "NOT_APPLICABLE":
            if normalized_raw:
                return ProposalValidationResult(
                    valid=False,
                    reason="schema_violation:not_applicable_non_empty_steps",
                )
            canonical_steps: list[AuditStep] = []
        else:
            if not normalized_raw:
                return ProposalValidationResult(
                    valid=False,
                    reason="schema_violation:empty_steps_for_applicable_case",
                )
            normalized_raw.sort(
                key=lambda s: (
                    PHASE_ORDER.get(s["phase"], 99),
                    OP_ORDER.get(s["operation"], 99),
                    s["system_id"],
                    s["resource_id"],
                )
            )
            canonical_steps = [
                AuditStep(
                    step_no=i,
                    phase=s["phase"],
                    system_id=s["system_id"],
                    resource_id=s["resource_id"],
                    operation=s["operation"],
                    state=s["state"],
                    evidence_id=s["evidence_id"],
                )
                for i, s in enumerate(normalized_raw, start=1)
            ]

        row_violations = validate_row(
            request.case_id,
            proposal.proposed_status,
            [s.to_dict() for s in canonical_steps],
        )
        if row_violations:
            return ProposalValidationResult(
                valid=False,
                reason=f"schema_violation:{row_violations[0]}",
            )

        # 4. Evidence manifest existence and temporal (<= audit_at) check
        for step in canonical_steps:
            if not step.evidence_id:
                continue
            captured_at = self.manifest_by_id.get(step.evidence_id)
            if captured_at is None:
                return ProposalValidationResult(
                    valid=False,
                    reason=f"invalid_evidence_id:{step.evidence_id}",
                )
            if captured_at > request.audit_at:
                return ProposalValidationResult(
                    valid=False,
                    reason=f"future_evidence:{step.evidence_id}:{captured_at}>{request.audit_at}",
                )

        # 5. Semantic proof check for COMPLETE verifications and INCOMPLETE findings
        if proposal.proposed_status == "COMPLETE":
            for step in canonical_steps:
                ev_id = step.evidence_id
                res_id = step.resource_id
                state = step.state
                matching_obs = self.obs_by_file_res.get((ev_id, res_id), [])
                if state == "ABSENT":
                    has_explicit_absent = any(
                        o.state is ObservationState.ABSENT for o in matching_obs
                    )
                    has_non_absent = any(
                        o.state is not ObservationState.ABSENT for o in matching_obs
                    )
                    report = self.engine.reports.get(ev_id)
                    if not has_explicit_absent and (has_non_absent or report is None):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )
                elif state == "PRESENT":
                    if not any(
                        o.state is ObservationState.PRESENT
                        and o.provenance is not Provenance.SCOPE_IMPLICIT
                        for o in matching_obs
                    ):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )
                elif state == "REDACTED":
                    if not any(
                        (
                            o.state is ObservationState.REDACTED
                            or (
                                o.state is ObservationState.PRESENT
                                and not o.pii_exposed
                                and not o.identifiers
                            )
                        )
                        and o.provenance is not Provenance.SCOPE_IMPLICIT
                        for o in matching_obs
                    ):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )
                elif state == "ANONYMIZED":
                    if not any(
                        (
                            o.state is ObservationState.ANONYMIZED
                            or (
                                o.state is ObservationState.PRESENT
                                and not o.pii_exposed
                                and not o.identifiers
                            )
                        )
                        and o.provenance is not Provenance.SCOPE_IMPLICIT
                        for o in matching_obs
                    ):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )
                elif state == "DISABLED":
                    if not any(
                        o.state is ObservationState.DISABLED
                        and o.provenance is not Provenance.SCOPE_IMPLICIT
                        for o in matching_obs
                    ):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )
                elif state == "BLOCKED":
                    if not any(
                        o.state is ObservationState.BLOCKED
                        and o.provenance is not Provenance.SCOPE_IMPLICIT
                        for o in matching_obs
                    ):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )
        elif proposal.proposed_status == "INCOMPLETE":
            for step in canonical_steps:
                if step.phase != "FINDING":
                    continue
                ev_id = step.evidence_id
                res_id = step.resource_id
                op = step.operation
                state = step.state
                matching_obs = self.obs_by_file_res.get((ev_id, res_id), [])
                if not matching_obs and ev_id not in self.act_by_id:
                    return ProposalValidationResult(
                        valid=False,
                        reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                    )
                if matching_obs:
                    if op == "REPORT_REMAINING_RECORD" and not any(
                        o.state is ObservationState.PRESENT for o in matching_obs
                    ):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )
                    if op == "REPORT_EXPOSED_PII" and not any(
                        o.state is ObservationState.PRESENT
                        and (o.pii_exposed or bool(o.identifiers))
                        for o in matching_obs
                    ):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )
                    if op in ("REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK") and not any(
                        o.state in (ObservationState.ACTIVE, ObservationState.PRESENT)
                        for o in matching_obs
                    ):
                        return ProposalValidationResult(
                            valid=False,
                            reason=f"state_mismatch:{res_id}:{state}:{ev_id}",
                        )

        # 6. Policy & grounded completeness check against deterministic authority
        if proposal.proposed_status != baseline.deletion_status:
            return ProposalValidationResult(
                valid=False,
                reason=(
                    f"policy_status_mismatch:proposed={proposal.proposed_status},"
                    f"expected={baseline.deletion_status}"
                ),
            )
        if tuple(s.to_dict() for s in canonical_steps) != tuple(
            s.to_dict() for s in baseline.steps
        ):
            return ProposalValidationResult(
                valid=False,
                reason="policy_step_mismatch",
            )

        steps_json = json.dumps([s.to_dict() for s in canonical_steps], separators=(",", ":"))
        return ProposalValidationResult(
            valid=True,
            reason="accepted",
            canonical_result=CaseAuditResult(
                case_id=request.case_id,
                deletion_status=proposal.proposed_status,
                steps=tuple(canonical_steps),
                steps_json=steps_json,
            ),
        )


class AuditAgentTools:
    """Callable tool implementations backed by deterministic audit modules."""

    def __init__(
        self,
        engine: AuditEngine,
        requests_by_key: dict[tuple[str, str], DeletionRequestRow] | None = None,
        baseline_by_case: dict[str, CaseAuditResult] | None = None,
    ) -> None:
        self.engine = engine
        self.requests_by_key = requests_by_key or {}
        self.baseline_by_case = baseline_by_case or {}

    def resolve_subject_identities(self, email: str, audit_at: str) -> dict[str, Any]:
        identity = self.engine.identity_resolver.resolve(email, audit_at)
        req = self.requests_by_key.get((email, audit_at))
        primary_account = None
        if req is not None:
            assignment = self.engine.workflow_resolver.resolve_one(req)
            primary_account = assignment.primary_account
        return {
            "user_id": identity.user_id,
            "canonical_email": identity.canonical_email,
            "all_emails": sorted(identity.all_emails),
            "all_phones": sorted(identity.all_phones),
            "all_names": sorted(identity.all_names),
            "all_email_hashes": sorted(identity.all_email_hashes),
            "primary_account": primary_account,
            "audit_at": audit_at,
        }

    def query_system_inventory(self, email: str, audit_at: str) -> dict[str, Any]:
        identity = self.engine.identity_resolver.resolve(email, audit_at)
        req = self.requests_by_key.get((email, audit_at))
        assignment = (
            self.engine.workflow_resolver.resolve_one(req) if req is not None else None
        )
        items = self.engine.inventory_builder.build_inventory(
            identity,
            req,
            workflow=assignment,
        )
        return {
            "user_id": identity.user_id,
            "resource_count": len(items),
            "resources": [
                {
                    "system_id": item.system_id,
                    "resource_id": item.resource_id,
                    "data_category": item.data_category,
                    "discovery_source": item.discovery_source,
                }
                for item in items
            ],
        }

    def reconstruct_resource_states(self, email: str, audit_at: str) -> dict[str, Any]:
        identity = self.engine.identity_resolver.resolve(email, audit_at)
        req = self.requests_by_key.get((email, audit_at))
        assignment = (
            self.engine.workflow_resolver.resolve_one(req) if req is not None else None
        )
        items = self.engine.inventory_builder.build_inventory(
            identity,
            req,
            workflow=assignment,
        )
        states = self.engine.state_reconstructor.reconstruct_states(items, audit_at)
        return {
            "user_id": identity.user_id,
            "states": [
                {
                    "system_id": s.system_id,
                    "resource_id": s.resource_id,
                    "data_category": s.data_category,
                    "observed_state": s.observed_state.value,
                    "pii_exposed": s.pii_exposed,
                    "evidence_id": s.evidence_id,
                    "provenance": s.provenance.value,
                }
                for s in states
            ],
        }

    def build_compliant_remediation_plan(
        self,
        request_id: str,
        email: str,
        request_text: str,
        audit_at: str,
    ) -> dict[str, Any]:
        if request_id in self.baseline_by_case:
            result = self.baseline_by_case[request_id]
        else:
            req = self.requests_by_key.get((email, audit_at)) or DeletionRequestRow(
                case_id=request_id,
                email=email,
                requested_at=audit_at,
                reported_status="COMPLETE",
                reported_at=audit_at,
                audit_at=audit_at,
                request_text=request_text,
            )
            result = self.engine.audit_case(req)
        return {
            "request_id": result.case_id,
            "deletion_status": result.deletion_status,
            "step_count": len(result.steps),
            "steps": [s.to_dict() for s in result.steps],
        }

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "resolve_subject_identities":
            return self.resolve_subject_identities(
                email=str(arguments.get("email", "")),
                audit_at=str(arguments.get("audit_at", "")),
            )
        if name == "query_system_inventory":
            return self.query_system_inventory(
                email=str(arguments.get("email", "")),
                audit_at=str(arguments.get("audit_at", "")),
            )
        if name == "reconstruct_resource_states":
            return self.reconstruct_resource_states(
                email=str(arguments.get("email", "")),
                audit_at=str(arguments.get("audit_at", "")),
            )
        if name == "build_compliant_remediation_plan":
            return self.build_compliant_remediation_plan(
                request_id=str(arguments.get("request_id", "")),
                email=str(arguments.get("email", "")),
                request_text=str(arguments.get("request_text", "")),
                audit_at=str(arguments.get("audit_at", "")),
            )
        return {"error": f"unknown_tool:{name}"}


class MultimodalVisionAgent:
    """Invokes qwen3-vl-plus for console screenshot extraction & schema verification."""

    def __init__(self, config: AgentConfig, meter: Meter) -> None:
        self.config = config
        self.meter = meter

    def verify_png_evidence(
        self,
        dataset_dir: Path,
        manifest: Sequence[EvidenceFileRow],
        client: Any | None = None,
        max_files: int | None = None,
    ) -> list[dict[str, Any]]:
        """Run metered qwen3-vl-plus verification passes on all console screenshots by default."""
        if not self.config.available() and client is None:
            return []
        vcfg = VisionConfig(
            provider=self.config.provider,
            model=self.config.vision_model,
            model_pass_b=self.config.vision_model,
            base_url=self.config.base_url,
            api_key=self.config.api_key or "mock-key",
        )
        all_png_rows = [
            row for row in manifest if Path(row.file_path).suffix.lower() == ".png"
        ]
        png_rows = all_png_rows if max_files is None else all_png_rows[:max_files]
        family_by_origin = {
            "account_admin_console": "account_console",
            "search_index_inspector": "search_inspector",
            "connector_management_console": "connector_console",
            "analytics_cohort_console": "analytics_profile",
            "export_job_console": "export_console",
            "support_desk_console": "support_console",
            "backup_restore_console": "backup_console",
            "identity_reference_registry": "reference_registry",
            "security_sentinel_console": "sentinel_events",
            "cloud_object_browser": "object_storage",
            "marketing_preferences_console": "marketing_profile",
        }
        verified: list[dict[str, Any]] = []
        active_client = client or _create_openai_client(self.config)
        for row in png_rows:
            stem = Path(row.file_path).stem
            family = next(
                (fam for prefix, fam in family_by_origin.items() if stem.startswith(prefix)),
                "account_console",
            )
            image_path = dataset_dir / row.file_path
            if not image_path.exists():
                continue
            try:
                extracted = transcribe_image(
                    vcfg,
                    image_path,
                    family,
                    pass_b=False,
                    meter=self.meter,
                    client=active_client,
                    pass_id=f"agent_verify_{row.file_id}",
                )
                val_report = validate_transcription(
                    family,
                    extracted if isinstance(extracted, dict) else {},
                    set(),
                )
                verified.append(
                    {
                        "file_id": row.file_id,
                        "family": family,
                        "captured_at": row.captured_at,
                        "fields_extracted": len(extracted) if isinstance(extracted, dict) else 0,
                        "schema_valid": val_report.ok,
                        "validation_errors": list(val_report.errors),
                    }
                )
            except Exception:
                continue
        return verified


class IntentDocumentAgent:
    """Invokes qwen3.7-max for batched intent classification and TXT + PDF document analysis."""

    def __init__(self, config: AgentConfig, meter: Meter) -> None:
        self.config = config
        self.meter = meter

    def classify_unique_requests(
        self,
        requests: Sequence[DeletionRequestRow],
        client: Any | None = None,
        batch_size: int = 45,
    ) -> dict[str, IntentVerdict]:
        """Classify all distinct request_text templates in batches via qwen3.7-max."""
        if not self.config.available() and client is None:
            return {}
        unique_texts = sorted({r.request_text.strip() for r in requests if r.request_text.strip()})
        active_client = client or _create_openai_client(self.config)
        verdicts: dict[str, IntentVerdict] = {}

        system_prompt = (
            "You are a privacy deletion-audit intent classifier. For each numbered user "
            "request_text (which may be in English, Spanish, Portuguese, French, German, "
            "Japanese, Korean, or another language), determine whether the user is "
            "authorizing account/personal-data DELETION (is_deletion: true) or asking "
            "for a non-deletion action such as data access/export, profile correction, "
            "marketing opt-out only, or login help while keeping the account "
            "(is_deletion: false). Return strict JSON: "
            '{"items": [{"index": 0, "is_deletion": true, "category": "DELETION", "reason": "..."}]}'
        )

        for batch_idx in range(0, len(unique_texts), batch_size):
            batch = unique_texts[batch_idx : batch_idx + batch_size]
            user_lines = [f"[{i}] {text}" for i, text in enumerate(batch)]
            purpose = f"agent:intent_classification:batch_{batch_idx // batch_size + 1}"
            try:
                with metered_call(
                    self.meter,
                    self.config.provider,
                    self.config.text_model,
                    purpose,
                ) as call:
                    response = active_client.chat.completions.create(
                        model=self.config.text_model,
                        temperature=0,
                        extra_body={"enable_thinking": False},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": "\n".join(user_lines)},
                        ],
                    )
                    call.capture(response)
                raw = str(getattr(response.choices[0].message, "content", "") or "")
                parsed = json.loads(_strip_json_fence(raw))
                for item in parsed.get("items", []):
                    idx = int(item.get("index", -1))
                    if 0 <= idx < len(batch):
                        verdicts[batch[idx]] = IntentVerdict(
                            is_deletion=bool(item.get("is_deletion", True)),
                            category=str(item.get("category", "DELETION")),
                            confidence=0.95,
                            reason=str(item.get("reason", "qwen3.7-max classification")),
                        )
            except Exception:
                continue
        return verdicts

    def analyze_unstructured_documents(
        self,
        dataset_dir: Path,
        manifest: Sequence[EvidenceFileRow],
        client: Any | None = None,
    ) -> dict[str, Any]:
        """Use qwen3.7-max to interpret unstructured handover TXT and all PDF documents."""
        if not self.config.available() and client is None:
            return {
                "files_analyzed": 0,
                "txt_files_analyzed": 0,
                "pdf_files_analyzed": 0,
                "file_ids": [],
                "entities": [],
            }
        active_client = client or _create_openai_client(self.config)
        snippets: list[str] = []
        txt_ids: list[str] = []
        pdf_ids: list[str] = []

        for row in manifest:
            path = dataset_dir / row.file_path
            suffix = path.suffix.lower()
            if not path.exists():
                continue
            if suffix == ".txt":
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")[:2500]
                    snippets.append(
                        f"=== {row.file_id} (TXT {row.file_path}, captured_at={row.captured_at}) ===\n{text}"
                    )
                    txt_ids.append(row.file_id)
                except OSError:
                    continue
            elif suffix == ".pdf":
                try:
                    raw_pdf = extract_text(path)
                    cleaned_pdf = normalize_text(raw_pdf)[:2500]
                    family = detect_family(cleaned_pdf)
                    snippets.append(
                        f"=== {row.file_id} (PDF family={family}, {row.file_path}, "
                        f"captured_at={row.captured_at}) ===\n{cleaned_pdf}"
                    )
                    pdf_ids.append(row.file_id)
                except Exception:
                    continue

        if not snippets:
            return {
                "files_analyzed": 0,
                "txt_files_analyzed": 0,
                "pdf_files_analyzed": 0,
                "file_ids": [],
                "entities": [],
            }

        system_prompt = (
            "You are an AI deletion-audit document analyst. Analyze the supplied "
            "unstructured handover text and PDF compliance/statement/support documents, "
            "and extract every subject account, user_id, support ticket, export, "
            "analytics profile, and retention status mentioned. Return strict JSON: "
            '{"files_analyzed": int, "entities": [{"file_id": "...", "account_id": "...", '
            '"resources": ["..."], "summary": "..."}]}'
        )
        entities: list[dict[str, Any]] = []
        try:
            with metered_call(
                self.meter,
                self.config.provider,
                self.config.text_model,
                "agent:unstructured_document_analysis",
            ) as call:
                response = active_client.chat.completions.create(
                    model=self.config.text_model,
                    temperature=0,
                    extra_body={"enable_thinking": False},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "\n\n".join(snippets)},
                    ],
                )
                call.capture(response)
            raw = str(getattr(response.choices[0].message, "content", "") or "")
            parsed = json.loads(_strip_json_fence(raw))
            if isinstance(parsed, dict) and isinstance(parsed.get("entities"), list):
                entities = [e for e in parsed["entities"] if isinstance(e, dict)]
        except Exception:
            entities = []

        return {
            "files_analyzed": len(txt_ids) + len(pdf_ids),
            "txt_files_analyzed": len(txt_ids),
            "pdf_files_analyzed": len(pdf_ids),
            "file_ids": txt_ids + pdf_ids,
            "entities": entities,
        }


class AuditOrchestratorAgent:
    """Hybrid AI Audit Agent with AI-proposal -> deterministic-verification -> canonical-output."""

    def __init__(
        self,
        engine: AuditEngine,
        dataset_dir: Path,
        manifest: Sequence[EvidenceFileRow],
        cache_dir: Path | None = None,
        meter: Meter | None = None,
        config: AgentConfig | None = None,
        max_vision_files: int | None = None,
    ) -> None:
        self.engine = engine
        self.dataset_dir = dataset_dir
        self.manifest = list(manifest)
        self.cache_dir = cache_dir
        if self.cache_dir is not None and self.engine.intent_classifier.cache_dir is None:
            self.engine.intent_classifier.cache_dir = self.cache_dir
        self.config = config or AgentConfig.from_env()
        self.meter = meter or Meter()
        self.max_vision_files = max_vision_files
        self.vision_agent = MultimodalVisionAgent(self.config, self.meter)
        self.intent_doc_agent = IntentDocumentAgent(self.config, self.meter)
        self.verifier = DeterministicProposalVerifier(self.engine, self.manifest)
        self.last_influence_summary: AgentInfluenceSummary | None = None
        self.last_live_influence_summary: AgentInfluenceSummary | None = None
        self.last_proposals: dict[str, AgentCaseProposal] = {}

    def _cache_path(self) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / AGENT_CACHE_FILE

    def _request_signature(self, requests: Sequence[DeletionRequestRow]) -> str:
        digest = hashlib.sha256()
        for r in sorted(requests, key=lambda x: x.case_id):
            digest.update(f"{r.case_id}|{r.email}|{r.audit_at}|{r.request_text}\n".encode())
        return digest.hexdigest()

    def _persist_decisions(
        self,
        signature: str,
        summary: AgentInfluenceSummary,
        proposals: dict[str, AgentCaseProposal],
        vision_verified: list[dict[str, Any]],
        doc_analysis: dict[str, Any],
        tool_call_records: list[dict[str, Any]],
    ) -> None:
        path = self._cache_path()
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    existing = loaded
            except (OSError, json.JSONDecodeError):
                existing = {}

        mode_key = "live" if summary.live_llm_enabled else "offline"
        record = {
            "request_signature": signature,
            "mode": mode_key,
            "summary": summary.to_dict(),
            "vision_verifications": vision_verified,
            "document_analysis": doc_analysis,
            "tool_calls": tool_call_records,
            "cases": {
                cid: prop.to_dict() for cid, prop in sorted(proposals.items())
            },
        }
        runs = existing.get("runs")
        if not isinstance(runs, dict):
            runs = {}
        runs[f"{signature}:{mode_key}"] = record
        if summary.live_llm_enabled or signature not in runs:
            runs[signature] = record
        existing["runs"] = runs
        if summary.live_llm_enabled or "latest" not in existing:
            existing["latest"] = record
        if summary.live_llm_enabled:
            existing["latest_live"] = record
        else:
            existing["latest_offline"] = record

        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def run_tool_calling_cohorts(
        self,
        requests: Sequence[DeletionRequestRow],
        tools: AuditAgentTools,
        client: Any,
    ) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        """Execute multi-turn tool-calling reasoning with qwen3.7-max on representative cohorts."""
        sorted_reqs = sorted(requests, key=lambda r: r.case_id)
        cohorts: list[DeletionRequestRow] = []
        seen_statuses: set[str] = set()
        for req in sorted_reqs:
            if req.reported_status not in seen_statuses:
                seen_statuses.add(req.reported_status)
                cohorts.append(req)
            elif len(cohorts) < 5:
                cohorts.append(req)
            if len(cohorts) >= 5:
                break

        system_prompt = (
            "You are the Lead Deletion-Audit Orchestrator Agent. Use the provided tools "
            "(resolve_subject_identities, query_system_inventory, reconstruct_resource_states, "
            "build_compliant_remediation_plan) to investigate the deletion request at audit_at, "
            "verify whether any personal data or active sync/restore risk remains, and "
            "confirm the compliant FINDING -> REMEDIATION -> VERIFICATION plan. "
            "In your final reply after tool execution, return strict JSON: "
            '{"request_id": "...", "proposed_status": "COMPLETE|INCOMPLETE|NOT_APPLICABLE", '
            '"rationale": "..."}'
        )

        cohort_outcomes: dict[str, dict[str, Any]] = {}
        tool_call_records: list[dict[str, Any]] = []

        for idx, req in enumerate(cohorts, start=1):
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": (
                        f"Audit request_id={req.case_id}, email={req.email}, "
                        f"reported_status={req.reported_status}, audit_at={req.audit_at}, "
                        f"request_text={req.request_text!r}. Invoke the audit tools to "
                        "reconstruct resource states and build the compliant remediation plan."
                    ),
                },
            ]
            try:
                with metered_call(
                    self.meter,
                    self.config.provider,
                    self.config.text_model,
                    f"agent:orchestrator_tool_call:cohort_{idx}",
                ) as call:
                    response = client.chat.completions.create(
                        model=self.config.text_model,
                        temperature=0,
                        extra_body={"enable_thinking": False},
                        tools=AGENT_TOOL_SCHEMAS,
                        tool_choice="auto",
                        messages=messages,
                    )
                    call.capture(response)

                msg = response.choices[0].message
                tool_calls = getattr(msg, "tool_calls", None) or []
                invoked_names: list[str] = []
                plan_steps: list[dict[str, Any]] | None = None
                plan_status: str | None = None

                if tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": msg.content or "",
                            "tool_calls": [
                                {
                                    "id": tc.id,
                                    "type": "function",
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in tool_calls
                            ],
                        }
                    )
                    for tc in tool_calls:
                        try:
                            args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        tool_output = tools.dispatch(tc.function.name, args)
                        invoked_names.append(tc.function.name)
                        if (
                            tc.function.name == "build_compliant_remediation_plan"
                            and isinstance(tool_output.get("steps"), list)
                        ):
                            plan_steps = list(tool_output["steps"])
                            plan_status = str(tool_output.get("deletion_status") or "")
                        tool_call_records.append(
                            {
                                "case_id": req.case_id,
                                "cohort_index": idx,
                                "tool_call_id": str(tc.id),
                                "tool_name": str(tc.function.name),
                                "arguments": args,
                                "result_keys": sorted(tool_output.keys()),
                            }
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": json.dumps(tool_output),
                            }
                        )

                    with metered_call(
                        self.meter,
                        self.config.provider,
                        self.config.text_model,
                        f"agent:orchestrator_adjudicate:cohort_{idx}",
                    ) as call_final:
                        final_resp = client.chat.completions.create(
                            model=self.config.text_model,
                            temperature=0,
                            extra_body={"enable_thinking": False},
                            messages=messages,
                        )
                        call_final.capture(final_resp)
                    final_content = str(
                        getattr(final_resp.choices[0].message, "content", "") or ""
                    )
                else:
                    final_content = str(getattr(msg, "content", "") or "")

                parsed_final: dict[str, Any] = {}
                try:
                    loaded_final = json.loads(_strip_json_fence(final_content))
                    if isinstance(loaded_final, dict):
                        parsed_final = loaded_final
                except json.JSONDecodeError:
                    parsed_final = {}

                cohort_outcomes[req.case_id] = {
                    "case_id": req.case_id,
                    "purpose": f"agent:orchestrator_tool_call:cohort_{idx}",
                    "tools_invoked": invoked_names,
                    "proposed_status": str(
                        parsed_final.get("proposed_status")
                        or parsed_final.get("deletion_status")
                        or plan_status
                        or ""
                    ),
                    "proposed_steps": (
                        parsed_final.get("steps")
                        if isinstance(parsed_final.get("steps"), list)
                        else plan_steps
                    ),
                    "rationale": str(
                        parsed_final.get("rationale")
                        or final_content[:240]
                        or "Tool-calling cohort orchestration completed"
                    ),
                }
            except Exception as exc:
                cohort_outcomes[req.case_id] = {
                    "case_id": req.case_id,
                    "purpose": f"agent:orchestrator_tool_call:cohort_{idx}",
                    "tools_invoked": [],
                    "error": f"model_call_error:{type(exc).__name__}",
                }
        return cohort_outcomes, tool_call_records

    def adjudicate_findings_batches(
        self,
        preliminary_results: Sequence[CaseAuditResult],
        client: Any,
        batch_size: int = 65,
    ) -> tuple[dict[str, dict[str, Any]], int]:
        """Review and adjudicate candidate case plans in batched qwen3.7-max calls."""
        if not self.config.available() and client is None:
            return {}, 0
        batches_run = 0
        batch_outcomes: dict[str, dict[str, Any]] = {}

        system_prompt = (
            "You are the Deletion-Audit Verification & Remediation Adjudicator Agent. "
            "For each case summary in the batch, verify that: "
            "(1) NOT_APPLICABLE cases have steps=[], "
            "(2) COMPLETE cases have only evidence-backed VERIFICATION steps, and "
            "(3) INCOMPLETE cases disable active data flows and block restore risks "
            "before record deletion/redaction/anonymization, followed by post-remediation "
            "verification steps with empty evidence_id. Return strict JSON: "
            '{"batch_verified": true, "checked_count": int, "anomalies": []}'
        )
        for start in range(0, len(preliminary_results), batch_size):
            chunk = preliminary_results[start : start + batch_size]
            compact_rows = [
                {
                    "id": r.case_id,
                    "status": r.deletion_status,
                    "steps": [
                        f"{s.phase}:{s.operation}:{s.system_id}/{s.resource_id}:{s.state}:{s.evidence_id}"
                        for s in r.steps
                    ],
                }
                for r in chunk
            ]
            batch_no = start // batch_size + 1
            purpose = f"agent:batch_plan_adjudication:batch_{batch_no}"
            try:
                with metered_call(
                    self.meter,
                    self.config.provider,
                    self.config.text_model,
                    purpose,
                ) as call:
                    resp = client.chat.completions.create(
                        model=self.config.text_model,
                        temperature=0,
                        extra_body={"enable_thinking": False},
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": json.dumps(compact_rows)},
                        ],
                    )
                    call.capture(resp)
                batches_run += 1
                raw = str(getattr(resp.choices[0].message, "content", "") or "")
                try:
                    parsed = json.loads(_strip_json_fence(raw))
                except json.JSONDecodeError:
                    for r in chunk:
                        batch_outcomes[r.case_id] = {
                            "purpose": purpose,
                            "error": "malformed_model_json",
                        }
                    continue

                if not isinstance(parsed, dict):
                    for r in chunk:
                        batch_outcomes[r.case_id] = {
                            "purpose": purpose,
                            "error": "malformed_model_json",
                        }
                    continue

                explicit_by_id: dict[str, dict[str, Any]] = {}
                for list_key in ("proposals", "decisions"):
                    items = parsed.get(list_key)
                    if isinstance(items, list):
                        for item in items:
                            if isinstance(item, dict):
                                cid = str(item.get("case_id") or item.get("id") or "")
                                if cid:
                                    explicit_by_id[cid] = item

                anomaly_by_id: dict[str, Any] = {}
                anomalies = parsed.get("anomalies")
                if isinstance(anomalies, list):
                    for anom in anomalies:
                        if isinstance(anom, dict):
                            cid = str(anom.get("case_id") or anom.get("id") or "")
                            if cid:
                                anomaly_by_id[cid] = anom
                        elif isinstance(anom, str) and anom:
                            anomaly_by_id[anom] = {"id": anom}

                batch_verified = bool(parsed.get("batch_verified", True))
                for r in chunk:
                    if r.case_id in explicit_by_id:
                        item = explicit_by_id[r.case_id]
                        batch_outcomes[r.case_id] = {
                            "purpose": purpose,
                            "proposed_status": str(
                                item.get("proposed_status")
                                or item.get("deletion_status")
                                or item.get("status")
                                or r.deletion_status
                            ),
                            "proposed_steps": (
                                item.get("steps")
                                if isinstance(item.get("steps"), list)
                                else (
                                    item.get("proposed_steps")
                                    if isinstance(item.get("proposed_steps"), list)
                                    else [s.to_dict() for s in r.steps]
                                )
                            ),
                            "rationale": str(
                                item.get("rationale")
                                or item.get("reason")
                                or "Explicit AI batch adjudication decision"
                            ),
                            "confidence": float(item.get("confidence", 0.95)),
                        }
                    elif r.case_id in anomaly_by_id:
                        anom = anomaly_by_id[r.case_id]
                        alt_status = (
                            "COMPLETE" if r.deletion_status == "INCOMPLETE" else "INCOMPLETE"
                        )
                        batch_outcomes[r.case_id] = {
                            "purpose": purpose,
                            "proposed_status": str(
                                anom.get("proposed_status")
                                or anom.get("status")
                                or alt_status
                            ),
                            "proposed_steps": (
                                anom.get("steps")
                                if isinstance(anom.get("steps"), list)
                                else [s.to_dict() for s in r.steps]
                            ),
                            "rationale": str(
                                anom.get("rationale")
                                or anom.get("reason")
                                or "Anomaly flagged by AI batch adjudicator"
                            ),
                            "confidence": 0.60,
                        }
                    elif batch_verified:
                        batch_outcomes[r.case_id] = {
                            "purpose": purpose,
                            "proposed_status": r.deletion_status,
                            "proposed_steps": [s.to_dict() for s in r.steps],
                            "rationale": (
                                "Verified by qwen3.7-max batch plan adjudicator against "
                                "policy and canonical step ordering rules"
                            ),
                            "confidence": 0.98,
                        }
                    else:
                        batch_outcomes[r.case_id] = {
                            "purpose": purpose,
                            "error": "batch_rejected_by_model",
                        }
            except Exception as exc:
                for r in chunk:
                    batch_outcomes[r.case_id] = {
                        "purpose": purpose,
                        "error": f"model_call_error:{type(exc).__name__}",
                    }
        return batch_outcomes, batches_run

    def audit_all(
        self,
        requests: Sequence[DeletionRequestRow],
        *,
        enable_live_llm: bool = False,
        client: Any | None = None,
    ) -> list[CaseAuditResult]:
        """Run the Hybrid AI Audit Agent with deterministic proposal verification and fallback."""
        sorted_requests = sorted(requests, key=lambda r: r.case_id)
        requests_by_key = {(r.email, r.audit_at): r for r in sorted_requests}
        all_png_count = sum(
            1 for row in self.manifest if Path(row.file_path).suffix.lower() == ".png"
        )
        live_active = bool(enable_live_llm and (self.config.available() or client is not None))

        vision_verified: list[dict[str, Any]] = []
        llm_verdicts: dict[str, IntentVerdict] = {}
        doc_analysis: dict[str, Any] = {
            "files_analyzed": 0,
            "txt_files_analyzed": 0,
            "pdf_files_analyzed": 0,
            "file_ids": [],
            "entities": [],
        }

        active_client = (
            (client or _create_openai_client(self.config)) if live_active else None
        )

        # Phase A: Vision verification + Intent classification + Document analysis
        if live_active and active_client is not None:
            vision_verified = self.vision_agent.verify_png_evidence(
                self.dataset_dir,
                self.manifest,
                client=active_client,
                max_files=self.max_vision_files,
            )
            llm_verdicts = self.intent_doc_agent.classify_unique_requests(
                sorted_requests,
                client=active_client,
            )
            for text, llm_verdict in llm_verdicts.items():
                fast_verdict = self.engine.intent_classifier.classify_text_fast_path(text)
                # Persist every LLM intent verdict that passes or extends fast-path guardrails
                if fast_verdict is None or fast_verdict.is_deletion == llm_verdict.is_deletion:
                    self.engine.intent_classifier.record_agent_verdict(text, llm_verdict)
            doc_analysis = self.intent_doc_agent.analyze_unstructured_documents(
                self.dataset_dir,
                self.manifest,
                client=active_client,
            )

        # Phase B: Deterministic baseline reconstruction (authority for tools & verifier)
        baseline_results = self.engine.audit_all(sorted_requests)
        baseline_by_case = {r.case_id: r for r in baseline_results}
        tools = AuditAgentTools(
            self.engine,
            requests_by_key=requests_by_key,
            baseline_by_case=baseline_by_case,
        )

        # Phase C: Tool-calling cohort orchestration & Batched plan adjudication
        cohort_outcomes: dict[str, dict[str, Any]] = {}
        tool_call_records: list[dict[str, Any]] = []
        batch_outcomes: dict[str, dict[str, Any]] = {}
        batches_run = 0

        if live_active and active_client is not None:
            cohort_outcomes, tool_call_records = self.run_tool_calling_cohorts(
                sorted_requests,
                tools,
                active_client,
            )
            batch_outcomes, batches_run = self.adjudicate_findings_batches(
                baseline_results,
                active_client,
            )

        # Phase D: Construct per-case AgentCaseProposals, validate with DeterministicProposalVerifier,
        # and merge accepted proposals or fall back per case.
        final_results: list[CaseAuditResult] = []
        proposals_by_case: dict[str, AgentCaseProposal] = {}
        rejection_counter: Counter[str] = Counter()
        accepted_count = 0
        rejected_count = 0
        not_applicable_accepted = 0
        fallback_count = 0
        evaluated_count = 0

        for req in sorted_requests:
            baseline = baseline_by_case[req.case_id]
            if not live_active:
                fallback_count += 1
                cited = tuple(
                    sorted({s.evidence_id for s in baseline.steps if s.evidence_id})
                )
                proposals_by_case[req.case_id] = AgentCaseProposal(
                    case_id=req.case_id,
                    proposed_status=baseline.deletion_status,
                    proposed_steps=tuple(s.to_dict() for s in baseline.steps),
                    cited_evidence_ids=cited,
                    provider="offline",
                    model="deterministic_engine",
                    purpose="offline_deterministic_audit",
                    confidence=1.0,
                    rationale="Offline mode: deterministic engine authority used directly.",
                    accepted=False,
                    decision_outcome="OFFLINE_FALLBACK",
                    rejection_reason="offline_mode_no_live_llm",
                    used_deterministic_fallback=True,
                    final_status=baseline.deletion_status,
                )
                final_results.append(baseline)
                continue

            evaluated_count += 1
            batch_info = batch_outcomes.get(req.case_id, {})
            cohort_info = cohort_outcomes.get(req.case_id, {})
            llm_intent = llm_verdicts.get(req.request_text.strip())
            det_intent = self.engine.intent_classifier.classify(
                req.request_text,
                activity_events=self.engine.activity_events,
                audit_at=req.audit_at,
            )

            # Check if model call or JSON parsing failed
            error_reason = str(
                batch_info.get("error") or cohort_info.get("error") or ""
            )
            if error_reason:
                rejected_count += 1
                fallback_count += 1
                rejection_counter[error_reason] += 1
                proposals_by_case[req.case_id] = AgentCaseProposal(
                    case_id=req.case_id,
                    proposed_status="ERROR",
                    proposed_steps=(),
                    cited_evidence_ids=(),
                    provider=self.config.provider,
                    model=self.config.text_model,
                    purpose=str(
                        batch_info.get("purpose")
                        or cohort_info.get("purpose")
                        or "agent:adjudication"
                    ),
                    confidence=0.0,
                    rationale="AI proposal failed due to model or JSON error; fell back to deterministic engine.",
                    accepted=False,
                    decision_outcome="REJECTED",
                    rejection_reason=error_reason,
                    used_deterministic_fallback=True,
                    final_status=baseline.deletion_status,
                )
                final_results.append(baseline)
                continue

            # Determine proposed status and steps from AI outputs
            if (
                llm_intent is not None
                and llm_intent.is_deletion != det_intent.is_deletion
                and "proposed_status" not in batch_info
            ):
                # AI intent classifier disagreed with deterministic intent guardrail
                prop_status = (
                    "NOT_APPLICABLE" if not llm_intent.is_deletion else "INCOMPLETE"
                )
                prop_steps_raw: list[dict[str, Any]] = []
                purpose = "agent:intent_classification"
                rationale = f"LLM intent verdict ({llm_intent.category}): {llm_intent.reason}"
                confidence = llm_intent.confidence
            else:
                prop_status = str(
                    batch_info.get("proposed_status")
                    or cohort_info.get("proposed_status")
                    or baseline.deletion_status
                )
                raw_steps_candidate = batch_info.get("proposed_steps")
                if not isinstance(raw_steps_candidate, list):
                    raw_steps_candidate = cohort_info.get("proposed_steps")
                if isinstance(raw_steps_candidate, list):
                    prop_steps_raw = list(raw_steps_candidate)
                else:
                    prop_steps_raw = [s.to_dict() for s in baseline.steps]
                purpose = str(
                    cohort_info.get("purpose")
                    or batch_info.get("purpose")
                    or "agent:batch_plan_adjudication"
                )
                rationale = str(
                    cohort_info.get("rationale")
                    or batch_info.get("rationale")
                    or "AI proposal generated and adjudicated"
                )
                confidence = float(batch_info.get("confidence", 0.98))

            cited_ids = tuple(
                sorted(
                    {
                        str(s.get("evidence_id") or "")
                        for s in prop_steps_raw
                        if isinstance(s, dict) and s.get("evidence_id")
                    }
                )
            )
            proposal = AgentCaseProposal(
                case_id=req.case_id,
                proposed_status=prop_status,
                proposed_steps=tuple(prop_steps_raw),
                cited_evidence_ids=cited_ids,
                provider=self.config.provider,
                model=self.config.text_model,
                purpose=purpose,
                confidence=confidence,
                rationale=rationale,
            )

            validation = self.verifier.validate_proposal(req, proposal, baseline)
            if validation.valid and validation.canonical_result is not None:
                proposal.accepted = True
                proposal.decision_outcome = (
                    "ACCEPTED_NOT_APPLICABLE"
                    if proposal.proposed_status == "NOT_APPLICABLE"
                    else "ACCEPTED"
                )
                proposal.rejection_reason = ""
                proposal.used_deterministic_fallback = False
                proposal.final_status = validation.canonical_result.deletion_status
                accepted_count += 1
                if proposal.proposed_status == "NOT_APPLICABLE":
                    not_applicable_accepted += 1
                final_results.append(validation.canonical_result)
            else:
                proposal.accepted = False
                proposal.decision_outcome = "REJECTED"
                proposal.rejection_reason = validation.reason
                proposal.used_deterministic_fallback = True
                proposal.final_status = baseline.deletion_status
                rejected_count += 1
                fallback_count += 1
                reason_bucket = validation.reason.split(":", 1)[0]
                rejection_counter[reason_bucket] += 1
                final_results.append(baseline)

            proposals_by_case[req.case_id] = proposal

        summary = AgentInfluenceSummary(
            total_cases=len(sorted_requests),
            live_llm_enabled=live_active,
            proposals_evaluated=evaluated_count,
            proposals_accepted=accepted_count,
            proposals_rejected=rejected_count,
            not_applicable_proposals=not_applicable_accepted,
            deterministic_fallbacks=fallback_count,
            vision_files_verified=len(vision_verified),
            vision_files_total=all_png_count,
            documents_analyzed=int(doc_analysis.get("files_analyzed", 0)),
            txt_documents_analyzed=int(doc_analysis.get("txt_files_analyzed", 0)),
            pdf_documents_analyzed=int(doc_analysis.get("pdf_files_analyzed", 0)),
            unique_intents_classified=len(llm_verdicts),
            tool_calls_executed=len(tool_call_records),
            cohorts_orchestrated=len(cohort_outcomes),
            adjudication_batches_run=batches_run,
            rejection_reasons=dict(rejection_counter),
        )
        self.last_influence_summary = summary
        if live_active:
            self.last_live_influence_summary = summary
        self.last_proposals = proposals_by_case

        sig = self._request_signature(sorted_requests)
        self._persist_decisions(
            signature=sig,
            summary=summary,
            proposals=proposals_by_case,
            vision_verified=vision_verified,
            doc_analysis=doc_analysis,
            tool_call_records=tool_call_records,
        )

        return final_results
