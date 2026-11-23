"""No-network acceptance for host-pinned Agent Skills in the existing Agent loop."""
from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.test import TestModel
import pytest

from ai_foundation.agent_skills import SkillCatalog, BUNDLED_PINS, bundled_catalog
from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_request import CapabilityRequest


def _catalog(tmp_path: Path, name: str = "reference-skill", *,
             description: str = "Bounded reference for a fixed public fixture.",
             extra: str = "", body: str = "# Reference\nUse observed data only.\n"):
    folder = tmp_path / name
    folder.mkdir()
    raw = (
        f"---\nname: {name}\ndescription: {description}\n"
        f"{extra}---\n{body}"
    ).encode("utf-8")
    (folder / "SKILL.md").write_bytes(raw)
    return SkillCatalog(tmp_path, {name: hashlib.sha256(raw).hexdigest()}), folder / "SKILL.md"


def test_bundled_first_party_skills_match_trusted_sha256():
    catalog = bundled_catalog(Path(__file__).resolve().parents[1])
    assert catalog is not None
    assert {x.name for x in catalog.summaries()} == set(BUNDLED_PINS)
    for item in catalog.summaries():
        text = catalog.load(item.name)
        assert item.description not in text or item.name in text
        assert BUNDLED_PINS[item.name] in text
        assert "Host-pinned reference" in text
    with pytest.raises(PermissionError):
        catalog.load("unregistered")


def test_catalog_exposes_metadata_without_loading_instruction_body(tmp_path):
    catalog, _ = _catalog(tmp_path, body="# SECRET_MARKER_FOR_BODY\n")
    assert catalog.summaries()[0].name == "reference-skill"
    assert "SECRET_MARKER_FOR_BODY" not in repr(catalog.summaries())
    assert "SECRET_MARKER_FOR_BODY" in catalog.load("reference-skill")


def test_skill_rejects_content_change_after_catalog_creation(tmp_path):
    catalog, file = _catalog(tmp_path)
    file.write_text(file.read_text() + "\n# Unreviewed change\n")
    with pytest.raises(PermissionError, match="host pin"):
        catalog.load("reference-skill")


def test_unlisted_skill_cannot_be_minted_from_user_input(tmp_path):
    catalog, _ = _catalog(tmp_path)
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "SKILL.md").write_text(
        "---\nname: other\ndescription: Unapproved\n---\n# Unapproved"
    )
    assert [s.name for s in catalog.summaries()] == ["reference-skill"]
    with pytest.raises(PermissionError, match="host-pinned"):
        catalog.load("other")
    with pytest.raises(PermissionError):
        catalog.load("../outside")


def test_symlink_skill_directory_denied_even_if_hash_matches(tmp_path):
    catalog, file = _catalog(tmp_path)
    real = tmp_path / "real"
    file.parent.rename(real)
    (tmp_path / "reference-skill").symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        catalog.load("reference-skill")


def test_symlink_skill_file_denied_even_if_hash_matches(tmp_path):
    catalog, file = _catalog(tmp_path)
    real = tmp_path / "real.md"
    file.rename(real)
    file.symlink_to(real)
    with pytest.raises(OSError):
        catalog.load("reference-skill")


@pytest.mark.parametrize("replacement", [
    "---\nname: reference-skill\ndescription: ok\n---\n",
    "---\nname: different-skill\ndescription: ok\n---\n# Body",
    "---\nname: reference-skill\ndescription: ok\nname: reference-skill\n---\n# Body",
    "---\nname: reference-skill\ndescription: ok\nmetadata:\n  author: unknown\n---\n# Body",
    "---\nname: reference-skill\ndescription: &unexpected\n---\n# Body",
    "name: reference-skill\ndescription: no frontmatter\n# Body",
])
def test_unsupported_or_invalid_yaml_fails_closed(tmp_path, replacement):
    catalog, file = _catalog(tmp_path)
    raw = replacement.encode()
    file.write_bytes(raw)
    with pytest.raises((ValueError, PermissionError)):
        SkillCatalog(tmp_path, {"reference-skill": hashlib.sha256(raw).hexdigest()})



def test_host_pinned_skill_fifo_is_rejected_without_waiting_for_writer(tmp_path):
    """A hostile named pipe must not block the Agent's read-only skill loader."""
    import os
    import subprocess
    import sys

    if not hasattr(os, "mkfifo"):
        pytest.skip("POSIX FIFO required")
    folder = tmp_path / "reference-skill"
    folder.mkdir()
    os.mkfifo(folder / "SKILL.md")
    # Run in a child so a regression cannot hang the CI test process.
    script = (
        "from ai_foundation.agent_skills import SkillCatalog\\n"
        "from pathlib import Path\\n"
        "SkillCatalog(Path(__import__('sys').argv[1]), "
        "{'reference-skill': '0' * 64})\\n"
    ).replace("\\n", "\n")
    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        capture_output=True, text=True, timeout=3,
    )
    assert result.returncode != 0
    assert "invalid skill file type or size" in result.stderr


def test_skill_file_size_is_bounded(tmp_path):
    catalog, file = _catalog(tmp_path)
    raw = file.read_bytes() + b"x" * 33000
    file.write_bytes(raw)
    with pytest.raises(ValueError, match="size"):
        SkillCatalog(tmp_path, {"reference-skill": hashlib.sha256(raw).hexdigest()})


def test_invalid_pin_and_missing_root_rejected(tmp_path):
    with pytest.raises(ValueError):
        SkillCatalog(tmp_path, {"reference-skill": "0" * 63})
    with pytest.raises(OSError):
        SkillCatalog(tmp_path / "absent", {"reference-skill": "0" * 64})
    assert bundled_catalog(tmp_path / "absent") is None


def test_untrusted_allowed_tools_does_not_register_new_tools(tmp_path):
    catalog, _ = _catalog(tmp_path, extra="allowed-tools: Bash(*) Write(*):\n")
    class NoEffects:
        def execute(self, *args):
            raise AssertionError("Skill reference must never execute an effect")
    agent = AutoCapabilityAgent(
        TestModel(call_tools=[]), NoEffects(), CapabilityRequest("CHAT"), skill_catalog=catalog
    )
    names = set(agent.port.agent._function_toolset.tools)
    assert names == {"load_skill"}
    # The optional allowed-tools field is deliberately NOT passed to the model.
    assert "Bash(*)" not in agent.load_skill("reference-skill")
    with pytest.raises(PermissionError):
        agent.load_skill("other")


@pytest.mark.parametrize("skill, capability, tool, args,grant", [
    ("evidence-brief", "SEARCH", "search", {"query": "fixed public fixture"}, {}),
    ("verified-artifact", "DATA", "data", {"value": [3, 7, 11]}, {"data_operation": "json_summary"}),
    ("development-handoff", "CODE", "code", {"target": "README.md", "operation": "inspect"}, {"repo_root": "/trusted/repo"}),
])
def test_existing_agent_skill_then_authorized_tool_e2e(skill, capability, tool, args, grant, monkeypatch):
    # This is a deterministic local protocol E2E, not a claimed real M1 run.
    from pydantic_ai import models
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)

    class Executor:
        def __init__(self):
            self.calls = []
        def execute(self, request, payload, run_id):
            self.calls.append((request, payload, run_id))
            return "OBSERVED_" + request.capability

    def model(messages, info):
        names = {x.name for x in info.function_tools}
        assert "load_skill" in names
        # The skill cannot make the forbidden capabilities appear.
        assert names == {"load_skill", tool}
        returned = [
            p for m in messages if isinstance(m, ModelRequest)
            for p in m.parts if isinstance(p, ToolReturnPart)
        ]
        if not returned:
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": skill})])
        if len(returned) == 1:
            assert returned[-1].tool_name == "load_skill"
            assert "Host-pinned reference" in returned[-1].content
            return ModelResponse(parts=[ToolCallPart(tool, args)])
        assert len(returned) == 2
        assert returned[-1].tool_name == tool
        return ModelResponse(parts=[TextPart(returned[-1].content)])

    executor = Executor()
    agent = AutoCapabilityAgent(
        FunctionModel(model), executor, CapabilityRequest("CHAT", **grant),
        search_available=capability == "SEARCH",
        skill_catalog=bundled_catalog(Path(__file__).resolve().parents[1]),
    )
    assert agent.run("Process this approved fixture") == "OBSERVED_" + capability
    assert len(executor.calls) == 1
    assert executor.calls[0][0].capability == capability
    if capability == "CODE":
        assert executor.calls[0][0].repo_root == "/trusted/repo"
    if capability == "DATA":
        assert executor.calls[0][0].data_operation == "json_summary"


def test_agent_without_catalog_keeps_existing_tool_contract():
    class NoExec:
        def execute(self, *args):
            raise AssertionError("No execution")
    agent = AutoCapabilityAgent(TestModel(call_tools=[]), NoExec(), CapabilityRequest("CHAT"))
    assert "load_skill" not in agent.port.agent._function_toolset.tools


def test_skill_does_not_turn_read_only_chat_into_code_or_file_authority(tmp_path):
    catalog, _ = _catalog(tmp_path)
    class NoExec:
        def execute(self, *args):
            raise AssertionError("No execution")
    agent = AutoCapabilityAgent(TestModel(call_tools=[]), NoExec(), CapabilityRequest("CHAT"),
                                skill_catalog=catalog)
    assert set(agent.port.agent._function_toolset.tools) == {"load_skill"}
    with pytest.raises(ValueError):
        agent.code("README.md", "change", "oops")
    with pytest.raises(ValueError):
        agent.files("secrets.txt")


def test_skill_then_real_bounded_data_executor_and_no_effect_receipt(monkeypatch):
    """Use existing deterministic Foundation DATA code, not a fake result."""
    import ast
    from pydantic_ai import models
    from ai_foundation.capability_execution import CapabilityExecutor
    from ai_foundation.guard import GuardCore
    from ai_foundation.core import GuardState

    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    state = GuardState()

    def model(messages, info):
        returned = [
            p for m in messages if isinstance(m, ModelRequest)
            for p in m.parts if isinstance(p, ToolReturnPart)
        ]
        if not returned:
            assert {t.name for t in info.function_tools} == {"load_skill", "data"}
            return ModelResponse(parts=[ToolCallPart("load_skill", {"name": "verified-artifact"})])
        if len(returned) == 1:
            assert "verified-artifact" in returned[-1].content
            return ModelResponse(parts=[ToolCallPart("data", {"value": [3, 7, 11]})])
        return ModelResponse(parts=[TextPart(returned[-1].content)])

    agent = AutoCapabilityAgent(
        FunctionModel(model), CapabilityExecutor(None, GuardCore(state)),
        CapabilityRequest("CHAT", owner_id="owner", data_operation="json_summary"),
        skill_catalog=bundled_catalog(Path(__file__).resolve().parents[1]),
    )
    summary = ast.literal_eval(agent.run("Verify the fixed public dataset."))
    assert summary == {
        "type": "array", "count": 3, "numeric_count": 3,
        "min": 3.0, "max": 11.0, "mean": 7.0,
    }
    assert not state.effects



def test_two_pinned_skills_compose_in_one_existing_agent_loop(monkeypatch):
    """P4: no second coordinator or widened host scope."""
    import ast
    from pydantic_ai import models
    from ai_foundation.capability_execution import CapabilityExecutor
    from ai_foundation.guard import GuardCore
    from ai_foundation.core import GuardState

    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    state = GuardState()
    order = ["evidence-brief", "verified-artifact"]

    def model(messages, info):
        returned = [
            p for m in messages if isinstance(m, ModelRequest)
            for p in m.parts if isinstance(p, ToolReturnPart)
        ]
        assert {t.name for t in info.function_tools} == {"load_skill", "data"}
        if len(returned) < 2:
            return ModelResponse(parts=[ToolCallPart(
                "load_skill", {"name": order[len(returned)]})])
        if len(returned) == 2:
            assert all(p.tool_name == "load_skill" for p in returned)
            return ModelResponse(parts=[ToolCallPart("data", {"value": [3, 7, 11]})])
        return ModelResponse(parts=[TextPart(returned[-1].content)])

    agent = AutoCapabilityAgent(
        FunctionModel(model), CapabilityExecutor(None, GuardCore(state)),
        CapabilityRequest("CHAT", owner_id="owner", data_operation="json_summary"),
        skill_catalog=bundled_catalog(Path(__file__).resolve().parents[1]),
    )
    assert ast.literal_eval(agent.run("Summarize public values with evidence checks."))["mean"] == 7.0
    assert agent._loaded_skills == set(order)
    assert not state.effects


def test_composition_does_not_allow_three_skills_or_repeat_body(tmp_path):
    names = ["one", "two", "three"]
    pins = {}
    for n in names:
        p = tmp_path / n
        p.mkdir()
        raw = f"---\nname: {n}\ndescription: Public {n}.\n---\n# {n}\n".encode()
        (p / "SKILL.md").write_bytes(raw)
        pins[n] = hashlib.sha256(raw).hexdigest()
    catalog = SkillCatalog(tmp_path, pins)
    class NoEffect:
        def execute(self, *args):
            raise AssertionError("No capability grant")
    agent = AutoCapabilityAgent(TestModel(call_tools=[]), NoEffect(),
                                CapabilityRequest("CHAT"), skill_catalog=catalog)
    assert "Host-pinned reference" in agent.load_skill("one")
    assert agent.load_skill("one").startswith("SKILL_ALREADY_LOADED")
    assert "Host-pinned reference" in agent.load_skill("two")
    with pytest.raises(PermissionError, match="two procedural"):
        agent.load_skill("three")
    assert set(agent.port.agent._function_toolset.tools) == {"load_skill"}


def test_skill_selection_budget_resets_between_independent_agent_runs(tmp_path):
    catalog, _ = _catalog(tmp_path)
    from pydantic_ai.models.test import TestModel
    class NoEffect:
        def execute(self, *args):
            raise AssertionError("No host tools allowed")
    agent = AutoCapabilityAgent(TestModel(call_tools=[]), NoEffect(),
                                CapabilityRequest("CHAT"), skill_catalog=catalog)
    agent.load_skill("reference-skill")
    assert agent._loaded_skills
    assert agent.run("Answer without a tool.")
    assert agent._loaded_skills == set()
