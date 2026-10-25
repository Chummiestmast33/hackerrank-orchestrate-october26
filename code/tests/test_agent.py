"""Unit tests for the Hybrid AI Audit Agent, Proposal Verifier, and Fallbacks.

Uses a fake OpenAI-compatible client (zero network calls) to verify:
1. Valid AI proposal is accepted and merged into final output.
2. Invalid evidence ID is rejected and falls back to deterministic result.
3. Future evidence (captured_at > audit_at) is rejected and falls back.
4. State mismatch is rejected and falls back.
5. Schema violation in AI proposal is rejected and falls back.
6. Malformed JSON from model is rejected and falls back.
7. Missing API key falls back to offline mode with zero model calls.
8. Model timeout/error falls back cleanly without corrupting output.
9. All 11 PNGs in dataset/evidence/images/ are processed by default when live.
10. Both PDF (4 files) and TXT (1 file) unstructured documents are analyzed.
11. Intent cache (intent_classifications.json) and agent decisions (agent_decisions.json)
    are persisted to disk and reused across instances.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.core.agent import (
    AgentConfig,
    AuditOrchestratorAgent,
    IntentDocumentAgent,
    MultimodalVisionAgent,
)
from src.core.audit_engine import AuditEngine
from src.core.intent_classifier import IntentClassifier
from src.evaluation.metering import Meter
from src.loaders.csv_loader import (
    DeletionRequestRow,
    DeletionRuleRow,
    EvidenceFileRow,
    IdentityRow,
    load_evidence_manifest,
)
from src.models import (
    EvidenceObservation,
    IntentVerdict,
    ObservationState,
    ParseStatus,
    Provenance,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATASET_DIR = REPO_ROOT / "dataset"


@dataclass
class _FakeUsage:
    prompt_tokens: int = 120
    completion_tokens: int = 45
    total_tokens: int = 165


@dataclass
class _FakeFunctionCall:
    name: str
    arguments: str


@dataclass
class _FakeToolCall:
    id: str
    function: _FakeFunctionCall


@dataclass
class _FakeMessage:
    content: str
    tool_calls: list[_FakeToolCall] | None = None


@dataclass
class _FakeChoice:
    message: _FakeMessage


@dataclass
class _FakeResponse:
    choices: list[_FakeChoice]
    usage: _FakeUsage


class _FakeCompletions:
    """Configurable fake chat.completions endpoint for deterministic unit tests."""

    def __init__(self, handler: Any) -> None:
        self._handler = handler
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        result = self._handler(kwargs, len(self.calls))
        if isinstance(result, Exception):
            raise result
        if isinstance(result, _FakeResponse):
            return result
        return _FakeResponse(
            choices=[_FakeChoice(message=_FakeMessage(content=str(result)))],
            usage=_FakeUsage(),
        )


class _FakeChat:
    def __init__(self, handler: Any) -> None:
        self.completions = _FakeCompletions(handler)


class _FakeOpenAIClient:
    def __init__(self, handler: Any) -> None:
        self.chat = _FakeChat(handler)


def _build_fixture_engine_and_manifest(
    tmp_path: Path,
) -> tuple[AuditEngine, list[EvidenceFileRow], DeletionRequestRow]:
    identities = [
        IdentityRow(
            user_id="usr_test_01",
            name="Test Subject",
            email="subject.alpha@example.org",
            phone="+15550001111",
            email_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            updated_at="2026-09-01T00:00:00Z",
        )
    ]
    rules = [
        DeletionRuleRow(
            rule_id="rule_profile",
            data_category="CUSTOMER_PROFILE",
            condition="Customer profile record in account_service",
            required_action="DELETE",
        )
    ]
    observations = [
        EvidenceObservation(
            file_id="ev_valid_01",
            captured_at="2026-09-10T10:00:00Z",
            system_id="account_service",
            resource_id="acc_test_01",
            data_category="CUSTOMER_PROFILE",
            state=ObservationState.ABSENT,
            parse_status=ParseStatus.OK,
            reason="explicit absence in primary snapshot",
            locator="accounts:acc_test_01",
            provenance=Provenance.EXPLICIT_FIELD,
            identifiers=("subject.alpha@example.org", "usr_test_01"),
            pii_exposed=False,
        ),
        EvidenceObservation(
            file_id="ev_present_02",
            captured_at="2026-09-09T10:00:00Z",
            system_id="account_service",
            resource_id="acc_test_01",
            data_category="CUSTOMER_PROFILE",
            state=ObservationState.PRESENT,
            parse_status=ParseStatus.OK,
            reason="record present before deletion",
            locator="accounts:acc_test_01",
            provenance=Provenance.EXPLICIT_FIELD,
            identifiers=("subject.alpha@example.org", "usr_test_01"),
            pii_exposed=True,
        ),
        EvidenceObservation(
            file_id="ev_future_03",
            captured_at="2026-09-25T10:00:00Z",
            system_id="account_service",
            resource_id="acc_test_01",
            data_category="CUSTOMER_PROFILE",
            state=ObservationState.ABSENT,
            parse_status=ParseStatus.OK,
            reason="captured after audit_at cutoff",
            locator="accounts:acc_test_01",
            provenance=Provenance.EXPLICIT_FIELD,
            identifiers=("subject.alpha@example.org", "usr_test_01"),
            pii_exposed=False,
        ),
    ]
    manifest = [
        EvidenceFileRow(
            file_id="ev_valid_01",
            file_path="evidence/records/valid.json",
            origin="account_service",
            captured_at="2026-09-10T10:00:00Z",
        ),
        EvidenceFileRow(
            file_id="ev_present_02",
            file_path="evidence/records/present.json",
            origin="account_service",
            captured_at="2026-09-09T10:00:00Z",
        ),
        EvidenceFileRow(
            file_id="ev_future_03",
            file_path="evidence/records/future.json",
            origin="account_service",
            captured_at="2026-09-25T10:00:00Z",
        ),
    ]
    request = DeletionRequestRow(
        case_id="req_alpha",
        email="subject.alpha@example.org",
        requested_at="2026-09-05T09:00:00Z",
        reported_status="COMPLETE",
        reported_at="2026-09-08T09:00:00Z",
        audit_at="2026-09-15T00:00:00Z",
        request_text="Please permanently delete my account and all personal data.",
    )
    engine = AuditEngine(
        identities=identities,
        audit_log=(),
        activity_events=(),
        rules=rules,
        observations=observations,
        reports={},
        intent_classifier=IntentClassifier(cache_dir=tmp_path),
    )
    return engine, manifest, request


def _live_config() -> AgentConfig:
    return AgentConfig(
        provider="qwen",
        text_model="qwen3.7-max",
        vision_model="qwen3-vl-plus",
        base_url="https://example.invalid/v1",
        api_key="test-key-not-real",
    )


def test_valid_ai_proposal_accepted_and_persisted(tmp_path: Path) -> None:
    engine, manifest, req = _build_fixture_engine_and_manifest(tmp_path)
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_valid")

    def handler(kwargs: dict[str, Any], _call_idx: int) -> Any:
        if kwargs.get("tools"):
            tc = _FakeToolCall(
                id="call_plan_1",
                function=_FakeFunctionCall(
                    name="build_compliant_remediation_plan",
                    arguments=json.dumps(
                        {
                            "request_id": req.case_id,
                            "email": req.email,
                            "request_text": req.request_text,
                            "audit_at": req.audit_at,
                        }
                    ),
                ),
            )
            return _FakeResponse(
                choices=[_FakeChoice(message=_FakeMessage(content="", tool_calls=[tc]))],
                usage=_FakeUsage(),
            )
        user_msg = str(kwargs["messages"][-1].get("content", ""))
        if "[0]" in user_msg:
            return json.dumps(
                {
                    "items": [
                        {
                            "index": 0,
                            "is_deletion": True,
                            "category": "DELETION",
                            "reason": "explicit erasure request",
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "batch_verified": True,
                "checked_count": 1,
                "proposals": [
                    {
                        "case_id": "req_alpha",
                        "proposed_status": "COMPLETE",
                        "steps": [
                            {
                                "phase": "VERIFICATION",
                                "system_id": "account_service",
                                "resource_id": "acc_test_01",
                                "operation": "VERIFY_RECORD_ABSENT",
                                "state": "ABSENT",
                                "evidence_id": "ev_valid_01",
                            }
                        ],
                        "rationale": "Confirmed absent via ev_valid_01.",
                    }
                ],
            }
        )

    client = _FakeOpenAIClient(handler)
    agent = AuditOrchestratorAgent(
        engine=engine,
        dataset_dir=tmp_path,
        manifest=manifest,
        cache_dir=tmp_path,
        meter=meter,
        config=_live_config(),
    )
    results = agent.audit_all([req], enable_live_llm=True, client=client)

    assert len(results) == 1
    assert results[0].deletion_status == "COMPLETE"
    assert len(results[0].steps) == 1
    assert results[0].steps[0].evidence_id == "ev_valid_01"

    summary = agent.last_influence_summary
    assert summary is not None
    assert summary.proposals_evaluated == 1
    assert summary.proposals_accepted == 1
    assert summary.proposals_rejected == 0
    assert summary.deterministic_fallbacks == 0
    assert summary.tool_calls_executed == 1

    prop = agent.last_proposals["req_alpha"]
    assert prop.accepted is True
    assert prop.decision_outcome == "ACCEPTED"
    assert prop.used_deterministic_fallback is False
    assert (tmp_path / "agent_decisions.json").exists()


def test_invalid_evidence_id_rejected_and_falls_back(tmp_path: Path) -> None:
    engine, manifest, req = _build_fixture_engine_and_manifest(tmp_path)
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_invalid_ev")

    def handler(_kwargs: dict[str, Any], _call_idx: int) -> str:
        return json.dumps(
            {
                "proposals": [
                    {
                        "case_id": "req_alpha",
                        "proposed_status": "COMPLETE",
                        "steps": [
                            {
                                "phase": "VERIFICATION",
                                "system_id": "account_service",
                                "resource_id": "acc_test_01",
                                "operation": "VERIFY_RECORD_ABSENT",
                                "state": "ABSENT",
                                "evidence_id": "ev_does_not_exist_999",
                            }
                        ],
                    }
                ]
            }
        )

    agent = AuditOrchestratorAgent(
        engine=engine,
        dataset_dir=tmp_path,
        manifest=manifest,
        cache_dir=tmp_path,
        meter=meter,
        config=_live_config(),
    )
    results = agent.audit_all([req], enable_live_llm=True, client=_FakeOpenAIClient(handler))

    assert results[0].deletion_status == "COMPLETE"
    assert results[0].steps[0].evidence_id == "ev_valid_01"
    prop = agent.last_proposals["req_alpha"]
    assert prop.accepted is False
    assert prop.used_deterministic_fallback is True
    assert prop.rejection_reason.startswith("invalid_evidence_id:ev_does_not_exist_999")
    assert agent.last_influence_summary is not None
    assert agent.last_influence_summary.proposals_rejected == 1
    assert agent.last_influence_summary.deterministic_fallbacks == 1


def test_future_evidence_rejected_and_falls_back(tmp_path: Path) -> None:
    engine, manifest, req = _build_fixture_engine_and_manifest(tmp_path)
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_future_ev")

    def handler(_kwargs: dict[str, Any], _call_idx: int) -> str:
        return json.dumps(
            {
                "proposals": [
                    {
                        "case_id": "req_alpha",
                        "proposed_status": "COMPLETE",
                        "steps": [
                            {
                                "phase": "VERIFICATION",
                                "system_id": "account_service",
                                "resource_id": "acc_test_01",
                                "operation": "VERIFY_RECORD_ABSENT",
                                "state": "ABSENT",
                                "evidence_id": "ev_future_03",
                            }
                        ],
                    }
                ]
            }
        )

    agent = AuditOrchestratorAgent(
        engine=engine,
        dataset_dir=tmp_path,
        manifest=manifest,
        cache_dir=tmp_path,
        meter=meter,
        config=_live_config(),
    )
    results = agent.audit_all([req], enable_live_llm=True, client=_FakeOpenAIClient(handler))

    assert results[0].steps[0].evidence_id == "ev_valid_01"
    prop = agent.last_proposals["req_alpha"]
    assert prop.accepted is False
    assert prop.used_deterministic_fallback is True
    assert prop.rejection_reason.startswith("future_evidence:ev_future_03")


def test_state_mismatch_rejected_and_falls_back(tmp_path: Path) -> None:
    engine, manifest, req = _build_fixture_engine_and_manifest(tmp_path)
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_state_mismatch")

    def handler(_kwargs: dict[str, Any], _call_idx: int) -> str:
        # Cites ev_present_02 (where state is PRESENT) to claim ABSENT
        return json.dumps(
            {
                "proposals": [
                    {
                        "case_id": "req_alpha",
                        "proposed_status": "COMPLETE",
                        "steps": [
                            {
                                "phase": "VERIFICATION",
                                "system_id": "account_service",
                                "resource_id": "acc_test_01",
                                "operation": "VERIFY_RECORD_ABSENT",
                                "state": "ABSENT",
                                "evidence_id": "ev_present_02",
                            }
                        ],
                    }
                ]
            }
        )

    agent = AuditOrchestratorAgent(
        engine=engine,
        dataset_dir=tmp_path,
        manifest=manifest,
        cache_dir=tmp_path,
        meter=meter,
        config=_live_config(),
    )
    results = agent.audit_all([req], enable_live_llm=True, client=_FakeOpenAIClient(handler))

    assert results[0].steps[0].evidence_id == "ev_valid_01"
    prop = agent.last_proposals["req_alpha"]
    assert prop.accepted is False
    assert prop.used_deterministic_fallback is True
    assert prop.rejection_reason.startswith("state_mismatch:acc_test_01:ABSENT:ev_present_02")


def test_malformed_json_rejected_and_falls_back(tmp_path: Path) -> None:
    engine, manifest, req = _build_fixture_engine_and_manifest(tmp_path)
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_malformed_json")

    def handler(_kwargs: dict[str, Any], _call_idx: int) -> str:
        return "```json\n{bad_json_without_closing_brace\n```"

    agent = AuditOrchestratorAgent(
        engine=engine,
        dataset_dir=tmp_path,
        manifest=manifest,
        cache_dir=tmp_path,
        meter=meter,
        config=_live_config(),
    )
    results = agent.audit_all([req], enable_live_llm=True, client=_FakeOpenAIClient(handler))

    assert results[0].deletion_status == "COMPLETE"
    assert results[0].steps[0].evidence_id == "ev_valid_01"
    prop = agent.last_proposals["req_alpha"]
    assert prop.accepted is False
    assert prop.used_deterministic_fallback is True
    assert prop.rejection_reason == "malformed_model_json"


def test_missing_api_key_falls_back_offline(tmp_path: Path) -> None:
    engine, manifest, req = _build_fixture_engine_and_manifest(tmp_path)
    usage_path = tmp_path / "usage.jsonl"
    meter = Meter(log_path=usage_path, run_id="test_offline")
    empty_cfg = AgentConfig(
        provider="qwen",
        text_model="qwen3.7-max",
        vision_model="qwen3-vl-plus",
        base_url="https://example.invalid/v1",
        api_key="",
    )
    agent = AuditOrchestratorAgent(
        engine=engine,
        dataset_dir=tmp_path,
        manifest=manifest,
        cache_dir=tmp_path,
        meter=meter,
        config=empty_cfg,
    )
    results = agent.audit_all([req], enable_live_llm=True, client=None)

    assert len(results) == 1
    assert results[0].deletion_status == "COMPLETE"
    assert not usage_path.exists()
    summary = agent.last_influence_summary
    assert summary is not None
    assert summary.live_llm_enabled is False
    assert summary.proposals_evaluated == 0
    assert summary.deterministic_fallbacks == 1


def test_model_timeout_or_error_falls_back_cleanly(tmp_path: Path) -> None:
    engine, manifest, req = _build_fixture_engine_and_manifest(tmp_path)
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_timeout")

    def handler(_kwargs: dict[str, Any], _call_idx: int) -> Exception:
        return TimeoutError("simulated API timeout")

    agent = AuditOrchestratorAgent(
        engine=engine,
        dataset_dir=tmp_path,
        manifest=manifest,
        cache_dir=tmp_path,
        meter=meter,
        config=_live_config(),
    )
    results = agent.audit_all([req], enable_live_llm=True, client=_FakeOpenAIClient(handler))

    assert results[0].deletion_status == "COMPLETE"
    assert results[0].steps[0].evidence_id == "ev_valid_01"
    prop = agent.last_proposals["req_alpha"]
    assert prop.accepted is False
    assert prop.used_deterministic_fallback is True
    assert prop.rejection_reason == "model_call_error:TimeoutError"


def test_schema_violation_rejected_and_falls_back(tmp_path: Path) -> None:
    engine, manifest, req = _build_fixture_engine_and_manifest(tmp_path)
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_schema_viol")

    def handler(_kwargs: dict[str, Any], _call_idx: int) -> str:
        return json.dumps(
            {
                "proposals": [
                    {
                        "case_id": "req_alpha",
                        "proposed_status": "COMPLETE",
                        "steps": [
                            {
                                "phase": "VERIFICATION",
                                "system_id": "account_service",
                                "resource_id": "acc_test_01",
                                "operation": "INVENTED_ILLEGAL_OP",
                                "state": "ABSENT",
                                "evidence_id": "ev_valid_01",
                            }
                        ],
                    }
                ]
            }
        )

    agent = AuditOrchestratorAgent(
        engine=engine,
        dataset_dir=tmp_path,
        manifest=manifest,
        cache_dir=tmp_path,
        meter=meter,
        config=_live_config(),
    )
    results = agent.audit_all([req], enable_live_llm=True, client=_FakeOpenAIClient(handler))

    assert results[0].deletion_status == "COMPLETE"
    assert results[0].steps[0].operation == "VERIFY_RECORD_ABSENT"
    prop = agent.last_proposals["req_alpha"]
    assert prop.accepted is False
    assert prop.used_deterministic_fallback is True
    assert prop.rejection_reason.startswith("schema_violation:")


def test_all_11_pngs_processed_when_live(tmp_path: Path) -> None:
    from src.loaders.vlm_extractor import FAMILY_FIELDS

    manifest, errors = load_evidence_manifest(DATASET_DIR / "evidence_files.csv")
    assert not errors
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_vision_11")

    def handler(kwargs: dict[str, Any], _call_idx: int) -> str:
        user_content = kwargs["messages"][1]["content"]
        prompt_text = str(user_content[0]["text"]) if isinstance(user_content, list) else str(user_content)
        for _fam, fields in FAMILY_FIELDS.items():
            if all(f"- {name}:" in prompt_text for name in fields):
                return json.dumps(dict.fromkeys(fields))
        return json.dumps(dict.fromkeys(FAMILY_FIELDS["account_console"]))

    fake_client = _FakeOpenAIClient(handler)
    vision_agent = MultimodalVisionAgent(_live_config(), meter)
    verified = vision_agent.verify_png_evidence(
        DATASET_DIR,
        manifest,
        client=fake_client,
    )

    assert len(verified) == 11
    assert len(fake_client.chat.completions.calls) == 11
    assert all(item["schema_valid"] is True for item in verified)


def test_pdf_and_txt_document_analysis_invoked(tmp_path: Path) -> None:
    manifest, errors = load_evidence_manifest(DATASET_DIR / "evidence_files.csv")
    assert not errors
    meter = Meter(log_path=tmp_path / "usage.jsonl", run_id="test_docs")

    def handler(_kwargs: dict[str, Any], _call_idx: int) -> str:
        return json.dumps(
            {
                "files_analyzed": 5,
                "entities": [
                    {
                        "file_id": "doc_1",
                        "account_id": "acc_1",
                        "resources": ["res_1"],
                        "summary": "parsed",
                    }
                ],
            }
        )

    fake_client = _FakeOpenAIClient(handler)
    doc_agent = IntentDocumentAgent(_live_config(), meter)
    analysis = doc_agent.analyze_unstructured_documents(
        DATASET_DIR,
        manifest,
        client=fake_client,
    )

    assert analysis["files_analyzed"] == 5
    assert analysis["txt_files_analyzed"] == 1
    assert analysis["pdf_files_analyzed"] == 4
    assert len(analysis["file_ids"]) == 5
    assert len(fake_client.chat.completions.calls) == 1
    sent_prompt = str(fake_client.chat.completions.calls[0]["messages"][-1]["content"])
    assert "PDF family=" in sent_prompt
    assert "TXT " in sent_prompt


def test_intent_cache_persisted_and_reused_across_instances(tmp_path: Path) -> None:
    classifier_a = IntentClassifier(cache_dir=tmp_path)
    nuanced_text = "Unusual ambiguous phrasing with no regex match."
    assert classifier_a.classify_text_fast_path(nuanced_text) is None

    classifier_a.record_agent_verdict(
        nuanced_text,
        IntentVerdict(
            is_deletion=False,
            category="CUSTOM_NON_DELETION",
            confidence=0.96,
            reason="adjudicated by qwen3.7-max",
        ),
    )
    cache_file = tmp_path / "intent_classifications.json"
    assert cache_file.exists()

    classifier_b = IntentClassifier(cache_dir=tmp_path)
    verdict_b = classifier_b.classify(nuanced_text)
    assert verdict_b.is_deletion is False
    assert verdict_b.category == "CUSTOM_NON_DELETION"
    assert "adjudicated by qwen3.7-max" in verdict_b.reason
