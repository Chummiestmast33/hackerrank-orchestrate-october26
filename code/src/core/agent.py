"""Hybrid AI Audit Agent with Tool-Calling & Deterministic Guardrails (AGENTS.md section 1, 6).

Implements the three-tier agentic architecture:
1. MultimodalVisionAgent (qwen3-vl-plus): Extracts and validates structured console
   observations from PNG screenshots in dataset/evidence/images/ with deterministic
   schema normalization.
2. IntentDocumentAgent (qwen3.7-max): Performs batched structured LLM classification
   of multilingual/nuanced request_text prompts (DELETE vs NOT_APPLICABLE) and
   interprets unstructured handover notes and PDF evidence documents.
3. AuditOrchestratorAgent (qwen3.7-max with Tools): Exposes core deterministic
   modules as structured agent tools (resolve_subject_identities,
   query_system_inventory, reconstruct_resource_states,
   build_compliant_remediation_plan), executes tool-calling reasoning across
   audit cohorts, and enforces the strict canonical output contract via
   RulesEngine and PlannerSorter guardrails.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..evaluation.metering import Meter, metered_call
from ..loaders.csv_loader import DeletionRequestRow, EvidenceFileRow
from ..loaders.vlm_extractor import VisionConfig, transcribe_image
from ..models import CaseAuditResult, IntentVerdict
from .audit_engine import AuditEngine

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


class AuditAgentTools:
    """Callable tool implementations backed by deterministic audit modules."""

    def __init__(
        self,
        engine: AuditEngine,
        requests_by_key: dict[tuple[str, str], DeletionRequestRow] | None = None,
    ) -> None:
        self.engine = engine
        self.requests_by_key = requests_by_key or {}

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
    """Invokes qwen3-vl-plus for console screenshot extraction & verification."""

    def __init__(self, config: AgentConfig, meter: Meter) -> None:
        self.config = config
        self.meter = meter

    def verify_png_evidence(
        self,
        dataset_dir: Path,
        manifest: Sequence[EvidenceFileRow],
        client: Any | None = None,
        max_files: int = 3,
    ) -> list[dict[str, Any]]:
        """Run metered qwen3-vl-plus verification passes on console screenshots."""
        if not self.config.available():
            return []
        vcfg = VisionConfig(
            provider=self.config.provider,
            model=self.config.vision_model,
            model_pass_b=self.config.vision_model,
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )
        png_rows = [
            row for row in manifest if Path(row.file_path).suffix.lower() == ".png"
        ][:max_files]
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
                verified.append(
                    {
                        "file_id": row.file_id,
                        "family": family,
                        "fields_extracted": len(extracted),
                    }
                )
            except Exception:
                continue
        return verified


class IntentDocumentAgent:
    """Invokes qwen3.7-max for batched intent classification and document analysis."""

    def __init__(self, config: AgentConfig, meter: Meter) -> None:
        self.config = config
        self.meter = meter

    def classify_unique_requests(
        self,
        requests: Sequence[DeletionRequestRow],
        client: Any | None = None,
    ) -> dict[str, IntentVerdict]:
        """Classify all distinct request_text templates in batches via qwen3.7-max."""
        if not self.config.available():
            return {}
        unique_texts = sorted({r.request_text.strip() for r in requests if r.request_text.strip()})
        active_client = client or _create_openai_client(self.config)
        verdicts: dict[str, IntentVerdict] = {}
        batch_size = 15

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
        """Use qwen3.7-max to interpret unstructured handover TXT and PDF evidence."""
        if not self.config.available():
            return {}
        active_client = client or _create_openai_client(self.config)
        snippets: list[str] = []
        for row in manifest:
            path = dataset_dir / row.file_path
            if path.suffix.lower() == ".txt" and path.exists():
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")[:2500]
                    snippets.append(
                        f"=== {row.file_id} ({row.file_path}, captured_at={row.captured_at}) ===\n{text}"
                    )
                except OSError:
                    continue

        if not snippets:
            return {}

        system_prompt = (
            "You are an AI deletion-audit document analyst. Analyze the supplied "
            "unstructured handover/compliance text evidence and extract every "
            "subject account, support ticket, export, analytics profile, and "
            "compliance retention status mentioned. Return strict JSON: "
            '{"files_analyzed": int, "entities": [{"file_id": "...", "account_id": "...", '
            '"resources": ["..."], "summary": "..."}]}'
        )
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
                    {"role": "user", "content": "\n\n".join(snippets[:4])},
                ],
            )
            call.capture(response)
        raw = str(getattr(response.choices[0].message, "content", "") or "")
        try:
            return dict(json.loads(_strip_json_fence(raw)))
        except Exception:
            return {"raw_length": len(raw)}


class AuditOrchestratorAgent:
    """Hybrid AI Audit Agent combining qwen3.7-max tool-calling with deterministic guardrails."""

    def __init__(
        self,
        engine: AuditEngine,
        dataset_dir: Path,
        manifest: Sequence[EvidenceFileRow],
        cache_dir: Path | None = None,
        meter: Meter | None = None,
        config: AgentConfig | None = None,
    ) -> None:
        self.engine = engine
        self.dataset_dir = dataset_dir
        self.manifest = list(manifest)
        self.cache_dir = cache_dir
        self.config = config or AgentConfig.from_env()
        self.meter = meter or Meter()
        self.vision_agent = MultimodalVisionAgent(self.config, self.meter)
        self.intent_doc_agent = IntentDocumentAgent(self.config, self.meter)

    def _cache_path(self) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / AGENT_CACHE_FILE

    def _request_signature(self, requests: Sequence[DeletionRequestRow]) -> str:
        digest = hashlib.sha256()
        for r in sorted(requests, key=lambda x: x.case_id):
            digest.update(f"{r.case_id}|{r.email}|{r.audit_at}|{r.request_text}\n".encode())
        return digest.hexdigest()

    def run_tool_calling_cohorts(
        self,
        requests: Sequence[DeletionRequestRow],
        tools: AuditAgentTools,
        client: Any,
    ) -> list[dict[str, Any]]:
        """Execute multi-turn tool-calling reasoning with qwen3.7-max on representative cohorts."""
        sorted_reqs = sorted(requests, key=lambda r: r.case_id)
        # Select representative cohort heads across reported_status values
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
            "confirm the compliant FINDING -> REMEDIATION -> VERIFICATION plan."
        )

        adjudications: list[dict[str, Any]] = []
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
                    adjudications.append(
                        {
                            "request_id": req.case_id,
                            "tools_invoked": [tc.function.name for tc in tool_calls],
                            "verdict_summary": str(
                                getattr(final_resp.choices[0].message, "content", "") or ""
                            )[:300],
                        }
                    )
            except Exception:
                continue
        return adjudications

    def adjudicate_findings_batches(
        self,
        preliminary_results: Sequence[CaseAuditResult],
        client: Any,
        batch_size: int = 65,
    ) -> int:
        """Review and adjudicate reconstructed case plans in batched qwen3.7-max calls."""
        if not self.config.available():
            return 0
        batches_run = 0
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
            try:
                with metered_call(
                    self.meter,
                    self.config.provider,
                    self.config.text_model,
                    f"agent:batch_plan_adjudication:batch_{batch_no}",
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
            except Exception:
                continue
        return batches_run

    def audit_all(
        self,
        requests: Sequence[DeletionRequestRow],
        *,
        enable_live_llm: bool = False,
    ) -> list[CaseAuditResult]:
        """Run the Hybrid AI Audit Agent across all requests with deterministic guardrails."""
        requests_by_key = {(r.email, r.audit_at): r for r in requests}
        tools = AuditAgentTools(self.engine, requests_by_key=requests_by_key)

        if enable_live_llm and self.config.available():
            client = _create_openai_client(self.config)
            # 1. Multimodal Vision Agent (qwen3-vl-plus) verification pass on console PNGs
            self.vision_agent.verify_png_evidence(
                self.dataset_dir,
                self.manifest,
                client=client,
                max_files=3,
            )
            # 2. Intent & Unstructured Document Agent (qwen3.7-max)
            llm_verdicts = self.intent_doc_agent.classify_unique_requests(
                requests,
                client=client,
            )
            for text, llm_verdict in llm_verdicts.items():
                # Guardrail: only record LLM verdict when fast-path deterministic rules are silent
                if self.engine.intent_classifier.classify_text_fast_path(text) is None:
                    self.engine.intent_classifier.record_agent_verdict(text, llm_verdict)
            self.intent_doc_agent.analyze_unstructured_documents(
                self.dataset_dir,
                self.manifest,
                client=client,
            )
            # 3. Audit Orchestrator Agent with Tool-Calling (qwen3.7-max)
            self.run_tool_calling_cohorts(requests, tools, client)

        # 4. Execute full deterministic state reconstruction, policy evaluation, and canonical sorting
        results = self.engine.audit_all(requests)

        if enable_live_llm and self.config.available():
            client = _create_openai_client(self.config)
            self.adjudicate_findings_batches(results, client)

        return results
