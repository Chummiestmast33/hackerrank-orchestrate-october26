"""Unit tests for the vision extractor (P4.4/P4.5); fake client, no real calls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from src.evaluation.metering import Meter
from src.loaders import vlm_extractor
from src.loaders.transcription_store import load_store

CAPTURED = "2026-09-26T11:00:00Z"


class FakeCompletions:
    def __init__(self, contents: list[str]) -> None:
        self.contents = list(contents)
        self.calls: list[dict] = []

    def create(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        content = self.contents.pop(0)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )


class FakeClient:
    def __init__(self, contents: list[str]) -> None:
        self.completions = FakeCompletions(contents)
        self.chat = SimpleNamespace(completions=self.completions)


def config(model_pass_b: str = "qwen-vl-max") -> vlm_extractor.VisionConfig:
    return vlm_extractor.VisionConfig(
        provider="qwen",
        model="qwen-vl-plus",
        model_pass_b=model_pass_b,
        base_url="http://example.test/v1",
        api_key="test-key",
    )


def meter(tmp_path: Path) -> Meter:
    return Meter(log_path=tmp_path / "usage.jsonl", run_id="run-vlm")


def image(tmp_path: Path) -> Path:
    path = tmp_path / "image.png"
    path.write_bytes(b"fake-png-bytes")
    return path


def usage_entries(tmp_path: Path) -> list[dict]:
    log = tmp_path / "usage.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line]


def test_prompt_version_and_prompt_files() -> None:
    assert vlm_extractor.PROMPT_VERSION == "p4-v2"
    for family, fields in vlm_extractor.FAMILY_FIELDS.items():
        prompt_path = vlm_extractor.PROMPTS_DIR / f"vlm_{family}.md"
        assert prompt_path.exists(), family
        text = prompt_path.read_text(encoding="utf-8")
        for field_name in fields:
            assert field_name in text, (family, field_name)
    prompt_a = vlm_extractor.build_prompt("account_console", pass_b=False)
    prompt_b = vlm_extractor.build_prompt("account_console", pass_b=True)
    assert "name, badge, user_id" in prompt_a
    assert "address, support_ref, orders" in prompt_b


def test_transcribe_image_parses_json_and_meters(tmp_path: Path) -> None:
    client = FakeClient(['{"name": "Haruka Sato"}'])
    result = vlm_extractor.transcribe_image(
        config(),
        image(tmp_path),
        "account_console",
        pass_b=False,
        meter=meter(tmp_path),
        client=client,
    )
    assert result == {"name": "Haruka Sato"}
    call = client.completions.calls[0]
    assert call["temperature"] == 0
    assert call["model"] == "qwen-vl-plus"
    assert "data:image/png;base64," in call["messages"][1]["content"][1]["image_url"]["url"]
    entries = usage_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["purpose"] == "vlm:account_console:pass_a"
    assert entries[0]["input_tokens"] == 100


def test_fenced_json_is_tolerated(tmp_path: Path) -> None:
    client = FakeClient(['```json\n{"name": "A"}\n```'])
    result = vlm_extractor.transcribe_image(
        config(),
        image(tmp_path),
        "account_console",
        pass_b=False,
        meter=meter(tmp_path),
        client=client,
    )
    assert result["name"] == "A"


def test_malformed_json_raises(tmp_path: Path) -> None:
    client = FakeClient(["not json at all"])
    with pytest.raises(vlm_extractor.TranscriptionParseError):
        vlm_extractor.transcribe_image(
            config(),
            image(tmp_path),
            "account_console",
            pass_b=False,
            meter=meter(tmp_path),
            client=client,
        )


def test_unavailable_without_api_key(tmp_path: Path) -> None:
    unavailable = vlm_extractor.VisionConfig(
        provider="qwen", model="m", model_pass_b="", base_url="", api_key=""
    )
    with pytest.raises(vlm_extractor.TranscriptionUnavailable):
        vlm_extractor.transcribe_image(
            unavailable, image(tmp_path), "account_console", pass_b=False, meter=meter(tmp_path)
        )


def test_unsupported_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_MODEL_PROVIDER", "gemini")
    with pytest.raises(vlm_extractor.UnsupportedVisionProvider):
        vlm_extractor.VisionConfig.from_env()


def test_env_config_reads_pass_b_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_MODEL_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_VISION_MODEL", "model-a")
    monkeypatch.setenv("QWEN_VISION_MODEL_PASS_B", "model-b")
    monkeypatch.setenv("QWEN_BASE_URL", "http://base")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "k")
    cfg = vlm_extractor.VisionConfig.from_env()
    assert cfg.model == "model-a" and cfg.resolve_pass_b() == "model-b"
    monkeypatch.delenv("QWEN_VISION_MODEL_PASS_B")
    monkeypatch.delenv("VISION_MODEL_PASS_B", raising=False)
    assert vlm_extractor.VisionConfig.from_env().resolve_pass_b() == "model-a"


def test_merge_agreement_normalizes_email_case_and_row_order() -> None:
    pass_a = {
        "name": "Haruka Sato",
        "email": "Haruka.S1838@Zoho.com",
        "orders": [{"order_id": "ORD-2"}, {"order_id": "ORD-1"}],
    }
    pass_b = {
        "name": "Haruka Sato ",
        "email": "haruka.s1838@zoho.com ",
        "orders": [{"order_id": "ORD-1"}, {"order_id": "ORD-2"}],
    }
    merge = vlm_extractor.merge_passes("account_console", pass_a, pass_b)
    assert merge.disagreements == ()
    assert merge.merged["email"] == "Haruka.S1838@Zoho.com"
    assert merge.merged["orders"] == pass_a["orders"]


def test_merge_disagreement_clears_field() -> None:
    merge = vlm_extractor.merge_passes(
        "account_console",
        {"account_id": "account_1"},
        {"account_id": "account_2"},
    )
    assert merge.merged["account_id"] is None
    assert "vlm_disagreement:account_id" in merge.disagreements


def test_two_pass_uses_second_model_and_caches(tmp_path: Path) -> None:
    store_path = tmp_path / "store.json"
    client = FakeClient(['{"name": "A"}', '{"name": "A"}'])
    entry = vlm_extractor.transcribe_two_pass(
        config(),
        image(tmp_path),
        file_id="evidence_04",
        family="account_console",
        meter=meter(tmp_path),
        store_path=store_path,
        client=client,
    )
    assert entry.model_a == "qwen-vl-plus"
    assert entry.model_b == "qwen-vl-max"
    assert entry.merged["name"] == "A"
    assert entry.disagreements == ()
    purposes = [item["purpose"] for item in usage_entries(tmp_path)]
    assert purposes == ["vlm:account_console:pass_a", "vlm:account_console:pass_b"]
    assert [item["model"] for item in usage_entries(tmp_path)] == ["qwen-vl-plus", "qwen-vl-max"]
    stored, warnings = load_store(store_path)
    assert warnings == [] and len(stored) == 1
    empty_client = FakeClient([])
    cached = vlm_extractor.transcribe_two_pass(
        config(),
        image(tmp_path),
        file_id="evidence_04",
        family="account_console",
        meter=meter(tmp_path),
        store_path=store_path,
        client=empty_client,
    )
    assert cached == entry
    assert empty_client.completions.calls == []
    assert len(usage_entries(tmp_path)) == 2


def test_two_pass_disagreement_is_recorded(tmp_path: Path) -> None:
    client = FakeClient(['{"email": "a@example.test"}', '{"email": "b@example.test"}'])
    entry = vlm_extractor.transcribe_two_pass(
        config(),
        image(tmp_path),
        file_id="evidence_x",
        family="account_console",
        meter=meter(tmp_path),
        client=client,
    )
    assert entry.merged["email"] is None
    assert "vlm_disagreement:email" in entry.disagreements
