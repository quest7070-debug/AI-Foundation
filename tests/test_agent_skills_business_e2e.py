"""P3/P4 source-to-artifact acceptance through the existing Foundation Guard.

No live model, outbound network, new authority, or effect on user files.
This is a real temporary disk write with independent readback; model tool
selection and P3 proposal use deterministic FunctionModel fixtures.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from pydantic_ai import Agent, models
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import FunctionModel

from ai_foundation.agent import PydanticAgentPort
from ai_foundation.agent_skills import bundled_catalog
from ai_foundation.artifact import TextArtifactResult
from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.skill_learning import run_evidence_bound_skill_learning


PUBLIC_DATA = [3, 7, 11]
ARTIFACT_BODY = "Public JSON summary\ncount: 3\nmin: 3.0\nmax: 11.0\nmean: 7.0\n"
REVISION = "a" * 40


class BoundedDiskPort:
    def __init__(self):
        self.writes = 0
        self.reads = 0

    def execute(self, plan):
        self.writes += 1
        Path(plan.target).write_bytes(plan.text.encode("utf-8"))

    def observe(self, plan):
        self.reads += 1
        return Path(plan.target).read_bytes().decode("utf-8")


def _responses(messages):
    return [
        part for message in messages if isinstance(message, ModelRequest)
        for part in message.parts if isinstance(part, ToolReturnPart)
    ]


def test_two_skills_existing_data_real_guard_disk_then_p3_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    root = tmp_path / "files"
    output = root / "output"
    output.mkdir(parents=True)
    disk = BoundedDiskPort()
    guard = GuardCore(GuardState())
    executor = CapabilityExecutor(None, guard, file_port=disk)
    request = CapabilityRequest(
        "CHAT", owner_id="public-fixture",
        data_operation="json_summary",
        file_read_root=str(root), file_write_root=str(output),
    )
    catalog = bundled_catalog(Path(__file__).resolve().parents[1])
    assert catalog is not None

    def tool_select(messages, info):
        names = {tool.name for tool in info.function_tools}
        assert names == {"load_skill", "data", "files", "list_files", "create_text_artifact"}
        observed = _responses(messages)
        if not observed:
            return ModelResponse(parts=[
                ToolCallPart("load_skill", {"name": "evidence-brief"})
            ])
        if len(observed) == 1:
            assert observed[0].tool_name == "load_skill"
            return ModelResponse(parts=[
                ToolCallPart("load_skill", {"name": "verified-artifact"})
            ])
        if len(observed) == 2:
            assert all(p.tool_name == "load_skill" for p in observed)
            return ModelResponse(parts=[
                ToolCallPart("data", {"value": PUBLIC_DATA})
            ])
        if len(observed) == 3:
            assert observed[-1].tool_name == "data"
            assert "'mean': 7.0" in observed[-1].content
            return ModelResponse(parts=[
                ToolCallPart("create_text_artifact", {
                    "target": "public-summary.md", "content": ARTIFACT_BODY
                })
            ])
        assert len(observed) == 4
        return ModelResponse(parts=[TextPart(observed[-1].content)])

    agent = AutoCapabilityAgent(
        FunctionModel(tool_select), executor, request,
        run_id="public-skills-e2e", skill_catalog=catalog,
    )
    result = json.loads(agent.run("Use only public fixture data, verify and save a summary."))
    assert result["status"] == "VERIFIED_COMPLETE"
    assert result["verified"] is True
    assert result["utf8_sha256"] == sha256(ARTIFACT_BODY.encode()).hexdigest()
    assert disk.writes == 1 and disk.reads >= 2
    assert (output / "public-summary.md").read_bytes() == ARTIFACT_BODY.encode()
    assert len(guard.state.effects) == 1
    assert all(effect.run_id.startswith("public-skills-e2e")
               for effect in guard.state.effects.values())

    # Existing, replacement-friendly AgentPort proposes text but cannot touch
    # the disk or grant permissions. Same public artifact source is re-read.
    def procedure(messages, info):
        assert not info.function_tools
        return ModelResponse(parts=[TextPart(
            "1. Use host-approved public data only.\n"
            "2. Call DATA when available and verify returned counts and mean.\n"
            "3. Persist output with an explicitly approved FILES tool.\n"
            "4. Require an independent exact text readback before claiming saved."
        )])
    proposer = PydanticAgentPort(Agent(FunctionModel(procedure)))
    tested = []
    published = []

    def acceptance(target, content, digest):
        assert target == "skills/public-array-brief/SKILL.md"
        assert digest == sha256(content.encode()).hexdigest()
        assert "source revision" in content
        assert "readback" in content
        tested.append(digest)
        return "VERIFIED"

    def draft_publisher(*, target, content, source_sha256, fingerprint):
        assert tested and source_sha256 == tested[-1]
        assert len(fingerprint) == 64
        assert target == "skills/public-array-brief/SKILL.md"
        published.append((source_sha256, fingerprint))
        # Stub only: real GitHub publication must be separately checked.
        return "FIXTURE_DRAFT_ADAPTER"

    receipt = TextArtifactResult(
        target="output/public-summary.md",
        status=result["status"],
        utf8_sha256=result["utf8_sha256"],
        utf8_bytes=result["utf8_bytes"],
    )
    delivery = run_evidence_bound_skill_learning(
        proposal_agent=proposer,
        public_objective="Turn verified public array statistics into a repeatable workflow.",
        name="public-array-brief",
        description="Create and verify a bounded public JSON array report.",
        artifact=receipt,
        readback=lambda name: (root / name).read_text(encoding="utf-8"),
        public_source_id="public-json-array-v1",
        source_revision=REVISION,
        independently_test=acceptance,
        publish_draft=draft_publisher,
    )
    assert delivery.status == "DRAFT_PR_PRESENTED"
    assert len(tested) == len(published) == 1
    assert (output / "public-summary.md").read_bytes() == ARTIFACT_BODY.encode()
    assert disk.writes == 1
