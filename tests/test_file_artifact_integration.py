"""Combined FILES tool exposure and real in-process Guard output verification.

No provider inference, cloud calls, production mounts or Native side effects.
"""
import json
from pathlib import Path

from pydantic_ai import models
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore


def test_scoped_list_read_then_guarded_artifact_in_one_agent_run(tmp_path, monkeypatch):
    source = tmp_path / "source.txt"
    source.write_text("observed input", encoding="utf-8")
    output = tmp_path / "output"
    output.mkdir()
    counts = {"list": 0, "read": 0, "write": 0}

    class CombinedPort:
        def observe(self, plan):
            if plan.action == "list_directory":
                counts["list"] += 1
                return "\n".join(
                    ("[DIR] " if item.is_dir() else "[FILE] ") + item.name
                    for item in sorted(Path(plan.target).iterdir())
                )
            if plan.action in {"read", "write"}:
                # Guard verifies a completed write by observing the original write plan.
                counts["read"] += 1
                return Path(plan.target).read_text(encoding="utf-8")
            raise AssertionError("unreviewed observe action")

        def execute(self, plan):
            assert plan.action == "write"
            counts["write"] += 1
            Path(plan.target).write_text(plan.text, encoding="utf-8")

    state = GuardState()

    def scripted_model(messages, info):
        returned = [part for message in messages if isinstance(message, ModelRequest)
                    for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("list_files", {"target": "."})])
        if len(returned) == 1:
            assert "[FILE] source.txt" in returned[-1].content
            assert not state.effects, "listing must not create a Guard effect"
            return ModelResponse(parts=[ToolCallPart("files", {"target": "source.txt"})])
        if len(returned) == 2:
            assert returned[-1].content == "observed input"
            assert not state.effects, "read must not create a Guard effect"
            return ModelResponse(parts=[ToolCallPart(
                "create_text_artifact", {"target": "result.md", "content": "verified: observed input"})])
        assert len(returned) == 3
        result = json.loads(returned[-1].content)
        assert result["verified"] is True and result["target"] == "result.md"
        return ModelResponse(parts=[TextPart(returned[-1].content)])

    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    request = CapabilityRequest("CHAT", owner_id="owner",
                                file_read_root=str(tmp_path), file_write_root=str(output))
    executor = CapabilityExecutor(None, GuardCore(state), file_port=CombinedPort())
    agent = AutoCapabilityAgent(FunctionModel(scripted_model), executor, request, run_id="integrated-host-run")
    available = agent.port.agent._function_toolset.tools
    assert {"files", "list_files", "create_text_artifact"}.issubset(available)
    assert set(available["list_files"].function_schema.json_schema["properties"]) == {"target"}
    assert set(available["create_text_artifact"].function_schema.json_schema["properties"]) == {"target", "content"}

    result = json.loads(agent.run("Find the input and save its verified summary."))
    assert result["verified"] is True
    assert (output / "result.md").read_text(encoding="utf-8") == "verified: observed input"
    assert counts["list"] == 1 and counts["read"] >= 2 and counts["write"] == 1
    assert len(state.effects) == 1
    assert next(iter(state.effects.values())).run_id == "integrated-host-run"
