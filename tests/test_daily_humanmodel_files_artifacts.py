"""Daily Agent FILES/artifact composition must survive the live HumanModel addon.

This is a source-level synthetic compatibility gate, NOT a deployed-service
acceptance. It uses no personal data, model inference, ToolHive, or Native tasks.
"""
import json
from pathlib import Path

import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from ai_foundation import auto_agent
from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
import ai_foundation.human_model_runtime as runtime


class SyntheticProjectContext:
    owner_id = "owner"
    local_required = False
    scopes = ("project",)
    search_available = False

    def read(self, owner, scope, offset=0):
        assert (owner, scope, offset) == ("owner", "project", 0)
        return json.dumps({
            "status": "AVAILABLE", "scope": "project",
            "records": [{"id": "evidence-1", "content": "Synthetic project reference"}],
        })


class SyntheticFilePort:
    def __init__(self):
        self.calls = []
    def observe(self, plan):
        self.calls.append(("observe", plan.action))
        if plan.action == "list_directory":
            return "\n".join(
                ("[DIR] " if p.is_dir() else "[FILE] ") + p.name
                for p in sorted(Path(plan.target).iterdir())
            )
        if plan.action in ("read", "write"):
            return Path(plan.target).read_text(encoding="utf-8")
        raise AssertionError("unexpected observation")
    def execute(self, plan):
        assert plan.action == "write"
        self.calls.append(("execute", "write"))
        Path(plan.target).write_text(plan.text, encoding="utf-8")


def install_synthetic_daily_factory(monkeypatch, tmp_path, context):
    # This is the same *factory-installation path* used by the additive
    # human_model_operator_launcher, but with private/production I/O replaced.
    monkeypatch.setattr(auto_agent, "AutoCapabilityAgent", auto_agent.AutoCapabilityAgent)
    monkeypatch.setattr(runtime, "build_human_model_context",
                        lambda *args, **kwargs: context)
    return runtime.install_legacy_agent_factory(
        binding_path=tmp_path / "unused-binding.json",
        repository_root=tmp_path, audit_path=tmp_path / "context-audit.jsonl",
    )


def test_real_additive_factory_retains_files_read_and_guarded_artifact(tmp_path, monkeypatch):
    (tmp_path / "input.txt").write_text("approved synthetic input", encoding="utf-8")
    output = tmp_path / "artifacts"
    output.mkdir()
    state = GuardState()
    port = SyntheticFilePort()
    executor = CapabilityExecutor(None, GuardCore(state), file_port=port)
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)

    def select(messages, info):
        returned = [p for msg in messages if isinstance(msg, ModelRequest)
                    for p in msg.parts if isinstance(p, ToolReturnPart)]
        if len(returned) == 0:
            return ModelResponse(parts=[ToolCallPart("human_model_context", {"scope": "project"})])
        if len(returned) == 1:
            assert "evidence-1" in returned[-1].content
            assert not state.effects
            return ModelResponse(parts=[ToolCallPart("list_files", {"target": "."})])
        if len(returned) == 2:
            assert "[FILE] input.txt" in returned[-1].content
            assert not state.effects
            return ModelResponse(parts=[ToolCallPart("files", {"target": "input.txt"})])
        if len(returned) == 3:
            assert returned[-1].content == "approved synthetic input"
            assert not state.effects
            return ModelResponse(parts=[ToolCallPart(
                "create_text_artifact", {"target": "summary.md", "content": "verified synthetic input"},
            )])
        assert len(returned) == 4
        receipt = json.loads(returned[-1].content)
        assert receipt["verified"] is True and receipt["target"] == "summary.md"
        return ModelResponse(parts=[TextPart(returned[-1].content)])

    factory = install_synthetic_daily_factory(monkeypatch, tmp_path, SyntheticProjectContext())
    req = CapabilityRequest("CHAT", owner_id="owner",
                            file_read_root=str(tmp_path), file_write_root=str(output))
    agent = factory(FunctionModel(select), executor, req, run_id="humanmodel-files-composed")
    assert agent.human_model_runtime_wrapper
    available = agent.port.agent._function_toolset.tools
    assert {"human_model_context", "list_files", "files", "create_text_artifact"}.issubset(available)
    assert set(available["create_text_artifact"].function_schema.json_schema["properties"]) == {"target", "content"}
    result = json.loads(agent.run("Read the approved source and save a grounded text artifact."))
    assert result["verified"] is True
    assert (output / "summary.md").read_text(encoding="utf-8") == "verified synthetic input"
    assert len(state.effects) == 1
    assert next(iter(state.effects.values())).run_id == "humanmodel-files-composed"
    assert [name for action, name in port.calls if action == "execute"] == ["write"]

    audit = (tmp_path / "context-audit.jsonl").read_text(encoding="utf-8")
    assert '"evidence-1"' in audit
    assert "Synthetic project reference" not in audit
    progress = (tmp_path / "agent-progress.jsonl").read_text(encoding="utf-8")
    assert "approved synthetic input" not in progress
    assert "verified synthetic input" not in progress


def test_additive_context_never_mints_missing_file_grants(tmp_path, monkeypatch):
    factory = install_synthetic_daily_factory(monkeypatch, tmp_path, SyntheticProjectContext())
    executor = CapabilityExecutor(None, GuardCore(GuardState()))
    agent = factory(FunctionModel(lambda *_: ModelResponse(parts=[TextPart("ok")])),
                    executor, CapabilityRequest("CHAT", owner_id="owner"), run_id="no-files")
    tools = agent.port.agent._function_toolset.tools
    assert "human_model_context" in tools
    assert "list_files" not in tools and "files" not in tools and "create_text_artifact" not in tools


def test_additive_owner_mismatch_fails_without_guard_effect(tmp_path, monkeypatch):
    factory = install_synthetic_daily_factory(monkeypatch, tmp_path, SyntheticProjectContext())
    state = GuardState()
    executor = CapabilityExecutor(None, GuardCore(state))
    with pytest.raises(PermissionError, match="HumanModel owner mismatch"):
        factory(FunctionModel(lambda *_: ModelResponse(parts=[TextPart("not used")])),
                executor, CapabilityRequest("CHAT", owner_id="another"), run_id="denied")
    assert not state.effects
