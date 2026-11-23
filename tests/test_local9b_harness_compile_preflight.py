"""Host rejects Python compile-time errors before guarded source write.

This is syntax-only checking: compile() does not execute the source, install
packages, call a model or acquire a compute lease.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_foundation.agent import AgentRequest
from ai_foundation.development_host import HarnessProposalAgent


def agent_for(source, monkeypatch):
    def fake_run(argv, *, cwd, env, stdin, stdout, stderr, check, timeout):
        assert argv[-1] == "synthetic request"
        assert timeout == 5
        stdout.write(json.dumps(source).encode())
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("ai_foundation.development_host.subprocess.run", fake_run)
    return HarnessProposalAgent(("synthetic-native-harness",), "/tmp", {}, 5)


@pytest.mark.parametrize("source", [
    "return 42\n",
    "break\n",
    "continue\n",
    "yield 42\n",
])
def test_invalid_top_level_control_flow_is_rejected_before_guard_write(source,monkeypatch):
    candidate = agent_for(source,monkeypatch)
    with pytest.raises(SyntaxError):
        candidate.run(AgentRequest("synthetic request"))


def test_valid_function_return_is_allowed(monkeypatch):
    source="def check():\n    return 42\n"
    proposal=agent_for(source,monkeypatch).run(AgentRequest("synthetic request"))
    assert proposal.output==source


def test_compile_check_does_not_execute_python(monkeypatch,tmp_path):
    output=tmp_path/"must-not-exist"
    source="from pathlib import Path\nPath("+repr(str(output))+").write_text('bad')\n"
    proposal=agent_for(source,monkeypatch).run(AgentRequest("synthetic request"))
    assert proposal.output==source
    assert not output.exists()


def test_uncompiled_literal_only_remains_rejected(monkeypatch):
    with pytest.raises(ValueError,match="HARNESS_SOURCE_IS_ONLY_A_LITERAL"):
        agent_for('"quoted"',monkeypatch).run(AgentRequest("synthetic request"))


def test_invalid_return_after_a_valid_function_matches_real_failure_shape(monkeypatch):
    # A model can emit good function definitions followed by an accidentally
    # outdented return. ast.parse accepts it but module compilation must not.
    output="def project_push(payload):\n    return ()\nreturn payload\n"
    with pytest.raises(SyntaxError, match="outside function"):
        agent_for(output,monkeypatch).run(AgentRequest("synthetic request"))


def test_failed_harness_stderr_is_not_returned_to_development_loop(monkeypatch):
    def failed_run(argv, *, cwd, env, stdin, stdout, stderr, check, timeout):
        stderr.write(b"SYNTHETIC_API_KEY_AND_OWNER_PROMPT_DO_NOT_EXPOSE")
        return SimpleNamespace(returncode=23)
    monkeypatch.setattr("ai_foundation.development_host.subprocess.run", failed_run)
    harness = HarnessProposalAgent(("synthetic-native-harness",), "/tmp", {}, 5)
    with pytest.raises(RuntimeError, match="^HARNESS_EXIT_NONZERO$") as caught:
        harness.run(AgentRequest("synthetic request"))
    assert "SYNTHETIC_API_KEY" not in repr(caught.value)
