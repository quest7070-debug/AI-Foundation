"""Direct MCP development uses the existing local Guard/Work/acceptance; no GitHub calls."""
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import subprocess
import sys

import pytest

from ai_foundation.agent import AgentResult
from ai_foundation.core import GuardState
from ai_foundation.development_host import (
    HostBoundLocalDevelopmentPort, HostBoundLocalDevelopmentTask,
)
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.guard import GuardCore
from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
from scripts.foundation_mcp_stdio import MCPStdio, MODERN, VERSION_KEY, CAPABILITIES_KEY


class Lease:
    def hold(self):
        return nullcontext()


class Proposal:
    def __init__(self, text="VALUE = 2\n"):
        self.text = text
        self.calls = 0

    def run(self, _):
        self.calls += 1
        return AgentResult(self.text)


class FixedTests:
    def __init__(self, root):
        self.root = root
        self.calls = 0

    def run_tests(self, target):
        assert target == "accept.py"
        self.calls += 1
        result = subprocess.run([sys.executable, "-B", target], cwd=self.root,
                                capture_output=True, text=True, timeout=5)
        if result.returncode:
            raise RuntimeError("FIXED_TEST_FAILED")
        return "PASS"


def setup(tmp_path, proposal=None):
    (tmp_path / "value.py").write_text("VALUE = 0\n")
    (tmp_path / "accept.py").write_text(
        "from value import VALUE\nassert VALUE == 2\n")
    guard = GuardCore(GuardState())
    proposal = proposal or Proposal()
    fixed = FixedTests(tmp_path)
    work = SQLiteWorkStore(tmp_path / "existing-work.db")
    ticket = HostBoundLocalDevelopmentTask(
        ticket_id="ticket-1", principal_id="macos-owner-local",
        root=str(tmp_path), instruction="Fix the host-pinned test.",
        target="value.py", acceptance_target="accept.py",
        repository="quest7070-dev/AI-Foundation", branch="local/isolated-fixture",
        proposal_agent=proposal, tests=fixed, lease=Lease(), max_repairs=0)
    port = HostBoundLocalDevelopmentPort(
        guard=guard, work=work, tasks={ticket.ticket_id: ticket})
    principal = SimpleNamespace(principal_id="macos-owner-local")
    return guard, port, principal, proposal, fixed


def test_direct_local_guarded_edit_and_fixed_acceptance_never_calls_github(tmp_path, monkeypatch):
    import ai_foundation.development_host as module
    def forbidden_publisher(*a, **kw):
        raise AssertionError("GitHub publisher must not be constructed during local acceptance")
    monkeypatch.setattr(module, "GitDraftPublisher", forbidden_publisher)
    guard, port, principal, proposal, fixed = setup(tmp_path)
    assert port.status(principal, "ticket-1")["state"] == "READY"
    result = port.run(principal, "ticket-1")
    assert result["state"] == "VERIFIED_LOCAL"
    assert result["github_published"] is False
    assert len(result["source_sha256"]) == 64
    assert (tmp_path / "value.py").read_text() == "VALUE = 2\n"
    assert proposal.calls == fixed.calls == 1
    assert len(guard.state.effects) == 1
    # Host ticket is consumed; replaying an MCP request is read-only.
    assert port.run(principal, "ticket-1") == result
    assert proposal.calls == fixed.calls == 1
    with pytest.raises(PermissionError):
        port.run(SimpleNamespace(principal_id="other"), "ticket-1")
    # Work verification is historical; status must not hide a later source edit.
    (tmp_path / "value.py").write_text("VALUE = 999\n")
    assert port.status(principal, "ticket-1")["state"] == (
        "SOURCE_CHANGED_RECONCILE_REQUIRED")


def test_failed_development_ticket_is_not_retried_or_leaked(tmp_path):
    class Failure:
        calls = 0
        def run(self, request):
            self.calls += 1
            raise RuntimeError("SYNTHETIC_PRIVATE_HARNESS_OUTPUT")
    failure = Failure()
    _, port, principal, _, _ = setup(tmp_path, failure)
    result = port.run(principal, "ticket-1")
    assert result["state"] == "FAILED_REVIEW_REQUIRED"
    assert result["failure_code"] == "LOCAL_ACCEPTANCE_NOT_VERIFIED"
    assert "SYNTHETIC_PRIVATE" not in str(result)
    assert port.run(principal, "ticket-1") == result
    assert failure.calls == 1
    assert (tmp_path / "value.py").read_text() == "VALUE = 0\n"


def test_failed_work_status_does_not_expose_unknown_persisted_text(tmp_path):
    from ai_foundation.orchestration import WorkStatus
    _, port, principal, _, _ = setup(tmp_path)
    ticket_id = "ticket-1"
    job = port._job_id(ticket_id, principal.principal_id)
    port.work.ensure(job, port._step_names(port.tasks[ticket_id]))
    assert port.work.transition(job, 0, WorkStatus.PLANNED, WorkStatus.RUNNING)
    assert port.work.transition(job, 0, WorkStatus.RUNNING,
                                WorkStatus.FAILED, "untrusted-private-error-text")
    status = port.status(principal, ticket_id)
    assert status["state"] == "FAILED_REVIEW_REQUIRED"
    assert status["failure_code"] == "UNCLASSIFIED_FAILURE"
    assert "untrusted-private-error-text" not in str(status)


def test_mcp_owner_session_and_stdio_expose_only_prebound_ticket(tmp_path):
    guard, port, principal, proposal, fixed = setup(tmp_path)
    operator = SimpleNamespace(actions=SimpleNamespace(guard=guard))
    auth = McpHostAuthorizer(owner_authorize=lambda p, tool, ticket:
        p.principal_id == "macos-owner-local" and ticket == "ticket-1")
    host = AuthenticatedMcpHost(operator, auth, development_port=port)
    session, token = host.issue_principal(
        "macos-owner-local", {"development_run", "development_status",
                              "foundation_status"})
    auth.register(session, token)
    server = MCPStdio(host, session.session_id, token, exposed_tools=(
        "foundation_status", "development_run", "development_status"))

    def call(method, params):
        return server.dispatch({
            "jsonrpc": "2.0", "id": 1, "method": method,
            "params": {**params, "_meta": {
                VERSION_KEY: MODERN, CAPABILITIES_KEY: {}}}})

    names = [x["name"] for x in call("tools/list", {})["result"]["tools"]]
    assert set(names) == {"foundation_status", "development_run",
                          "development_status"}
    forged = call("tools/call", {"name": "development_run",
                                "arguments": {"ticket_id": "other"}})
    assert forged["result"]["isError"] is True
    assert proposal.calls == 0
    status = call("tools/call", {"name": "development_status",
                                "arguments": {"ticket_id": "ticket-1"}})
    assert '"READY"' in status["result"]["content"][0]["text"]
    run = call("tools/call", {"name": "development_run",
                             "arguments": {"ticket_id": "ticket-1"}})
    assert '"VERIFIED_LOCAL"' in run["result"]["content"][0]["text"]
    assert proposal.calls == fixed.calls == 1
    with pytest.raises(PermissionError):
        host.dispatch(session.session_id, "wrong", "development_run",
                      {"ticket_id": "ticket-1"})
    # A valid authenticated session without the exact tool scope also fails.
    auth2 = McpHostAuthorizer(owner_authorize=lambda *_: True)
    host2 = AuthenticatedMcpHost(operator, auth2, development_port=port)
    s2, t2 = host2.issue_principal("macos-owner-local", {"foundation_status"})
    auth2.register(s2, t2)
    with pytest.raises(PermissionError):
        host2.dispatch(s2.session_id, t2, "development_status",
                       {"ticket_id": "ticket-1"})


def test_explicit_owner_draft_delivery_runs_only_after_local_acceptance(tmp_path, monkeypatch):
    from dataclasses import replace
    import ai_foundation.development_host as dev
    guard, port, principal, proposal, fixed = setup(tmp_path)
    assert port.authorize_delivery(principal, "ticket-1") is False
    with pytest.raises(PermissionError):
        port.deliver(principal, "ticket-1")
    port.tasks["ticket-1"] = replace(
        port.tasks["ticket-1"], allow_draft_delivery=True)
    assert port.authorize_delivery(principal, "ticket-1") is True
    assert port.run(principal, "ticket-1")["state"] == "VERIFIED_LOCAL"
    calls = []
    class Publisher:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def __call__(self, **kwargs):
            calls.append(kwargs)
            return "https://github.com/quest7070-dev/AI-Foundation/pull/123"
    monkeypatch.setattr(dev, "GitDraftPublisher", Publisher)
    first = port.deliver(principal, "ticket-1")
    assert first["state"] == "VERIFIED_LOCAL"
    assert first["github_published"] is True
    assert first["draft_pr_url"].endswith("/pull/123")
    assert port.deliver(principal, "ticket-1") == first
    assert proposal.calls == fixed.calls == 1
    assert len(calls) == 2


def test_lost_draft_delivery_receipt_is_never_replayed(tmp_path, monkeypatch):
    from dataclasses import replace
    import ai_foundation.development_host as dev
    _, port, principal, _, _ = setup(tmp_path)
    port.tasks["ticket-1"] = replace(
        port.tasks["ticket-1"], allow_draft_delivery=True)
    assert port.run(principal, "ticket-1")["state"] == "VERIFIED_LOCAL"
    sends = []
    class Unknown:
        def __init__(self, **kwargs):
            pass
        def __call__(self, **kwargs):
            sends.append(1)
            raise RuntimeError("SYNTHETIC_PRIVATE_GIT_ERROR")
    monkeypatch.setattr(dev, "GitDraftPublisher", Unknown)
    result = port.deliver(principal, "ticket-1")
    assert result["github_published"] is False
    assert result["delivery_state"] == "RECONCILE_REQUIRED"
    assert port.deliver(principal, "ticket-1") == result
    assert len(sends) == 1
    assert "SYNTHETIC_PRIVATE" not in str(result)



def test_inventory_is_readonly_and_filters_each_ticket(tmp_path, monkeypatch):
    from dataclasses import replace
    guard, port, principal, proposal, fixed = setup(tmp_path)
    port.tasks["hidden"] = replace(port.tasks["ticket-1"], ticket_id="hidden",
                                   principal_id="other")
    def forbidden(*args, **kwargs):
        raise AssertionError("Inventory must not create or claim Work")
    monkeypatch.setattr(port.work, "ensure", forbidden)
    monkeypatch.setattr(port.work, "transition", forbidden)
    assert port.list_tickets(principal, authorize_status=lambda ticket: True) == {
        "ticket_count": 1, "tickets": [{"ticket_id": "ticket-1",
        "state": "READY", "github_published": False}]}
    assert port.list_tickets(principal, authorize_status=lambda ticket: False) == {
        "ticket_count": 0, "tickets": []}
    with pytest.raises(PermissionError):
        port.list_tickets(SimpleNamespace(principal_id="unknown"),
                          authorize_status=lambda ticket: True)
    assert proposal.calls == fixed.calls == 0


def test_inventory_retains_terminal_state_without_replaying(tmp_path):
    _, port, principal, proposal, fixed = setup(tmp_path)
    result = port.run(principal, "ticket-1")
    assert port.list_tickets(principal, authorize_status=lambda ticket: True)["tickets"] == [result]
    assert proposal.calls == fixed.calls == 1


def test_inventory_requires_own_scope_and_exact_status_authorization(tmp_path):
    import json
    guard, port, _, proposal, fixed = setup(tmp_path)
    operator = SimpleNamespace(actions=SimpleNamespace(guard=guard))
    allowed = {"development_list"}
    auth = McpHostAuthorizer(owner_authorize=lambda principal, tool, ticket:
                             tool in allowed)
    host = AuthenticatedMcpHost(operator, auth, development_port=port)
    principal, token = host.issue_principal("macos-owner-local",
        {"foundation_status", "development_list", "development_status"})
    auth.register(principal, token)
    server = MCPStdio(host, principal.session_id, token, exposed_tools=(
        "foundation_status", "development_list"))
    def call(name, arguments):
        return server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments,
            "_meta": {VERSION_KEY: MODERN, CAPABILITIES_KEY: {}}}}).get("result", {"isError": True})
    assert json.loads(call("development_list", {})["content"][0]["text"])["tickets"] == []
    allowed.add("development_status")
    assert json.loads(call("development_list", {})["content"][0]["text"])["ticket_count"] == 1
    assert call("development_list", {"ticket_id": "ticket-1"})["isError"] is True
    allowed.clear()
    assert call("development_list", {})["isError"] is True
    assert proposal.calls == fixed.calls == 0


@pytest.mark.parametrize("binding", ["local:ollama-shared9b:general",
                                    "local:llama-swap:local-code-agent",
                                    "local:mainpc-strata:code-agent"])
def test_backend_receipt_retains_actual_or_historical_local_binding(tmp_path, binding):
    _, port, principal, proposal, fixed = setup(tmp_path)
    proposal.last_binding = binding
    written = port.run(principal, "ticket-1")
    assert written["state"] == "VERIFIED_LOCAL"
    assert written["execution_binding"] == binding
    assert port.status(principal, "ticket-1") == written
    assert proposal.calls == fixed.calls == 1


def test_owner_reviewed_baseline_pass_is_held_without_model_or_work_replay(tmp_path):
    from dataclasses import replace
    from ai_foundation.development_loop import TestAcceptanceReceipt

    guard, port, principal, proposal, _ = setup(tmp_path)
    class Baseline:
        calls = 0
        def run_acceptance(self, target):
            assert target == "accept.py"
            self.calls += 1
            return TestAcceptanceReceipt(True, "22 passed")

    tests = Baseline()
    port.tasks["ticket-1"] = replace(
        port.tasks["ticket-1"], tests=tests, baseline_preflight=True)
    first = port.run(principal, "ticket-1")
    assert first["state"] == "BASELINE_ALREADY_PASSES_REVIEW_REQUIRED"
    assert first["github_published"] is False
    assert proposal.calls == 0
    assert len(guard.state.effects) == 0
    assert (tmp_path / "value.py").read_text() == "VALUE = 0\n"
    assert port.run(principal, "ticket-1") == first
    assert tests.calls == 1
    assert proposal.calls == 0


def test_owner_reviewed_failing_baseline_still_runs_single_model_proposal(tmp_path):
    from dataclasses import replace
    from ai_foundation.development_loop import TestAcceptanceReceipt

    _, port, principal, proposal, fixed = setup(tmp_path)
    class Baseline:
        calls = 0
        def run_acceptance(self, target):
            self.calls += 1
            try:
                return TestAcceptanceReceipt(True, fixed.run_tests(target))
            except RuntimeError:
                return TestAcceptanceReceipt(False, "fixture failure")
    tests = Baseline()
    port.tasks["ticket-1"] = replace(
        port.tasks["ticket-1"], tests=tests, baseline_preflight=True)
    first = port.run(principal, "ticket-1")
    assert first["state"] == "VERIFIED_LOCAL"
    assert proposal.calls == 1
    assert tests.calls == 2
    assert fixed.calls == 2
    assert (tmp_path / "value.py").read_text() == "VALUE = 2\n"


def test_untrusted_baseline_evidence_holds_instead_of_writing(tmp_path):
    from dataclasses import replace

    _, port, principal, proposal, _ = setup(tmp_path)
    class Unavailable:
        calls = 0
        def run_acceptance(self, _target):
            self.calls += 1
            raise RuntimeError("SYNTHETIC_PRIVATE_TEST_FAILURE")
    tests = Unavailable()
    port.tasks["ticket-1"] = replace(
        port.tasks["ticket-1"], tests=tests, baseline_preflight=True)
    first = port.run(principal, "ticket-1")
    assert first["state"] == "BASELINE_PREFLIGHT_UNVERIFIED"
    assert "PRIVATE" not in str(first)
    assert proposal.calls == 0
    assert port.run(principal, "ticket-1") == first
    assert tests.calls == 1


def _run_with_raised(tmp_path, monkeypatch, exc):
    import ai_foundation.development_host as module

    def boom(**kwargs):
        raise exc

    monkeypatch.setattr(module, "run_local_development_task", boom)
    _, port, principal, _, _ = setup(tmp_path)
    return port.run(principal, "ticket-1")


def test_failure_code_keeps_recipe_token_but_not_tail(tmp_path, monkeypatch):
    result = _run_with_raised(
        tmp_path, monkeypatch,
        ValueError("FIXED_TEST_INFRASTRUCTURE_FAILED: 5 errors in "
                   "/private/owner/path with secret text"))
    assert result["state"] == "FAILED_REVIEW_REQUIRED"
    assert result["failure_code"] == "ValueError:FIXED_TEST_INFRASTRUCTURE_FAILED"
    assert "/private/owner/path" not in str(result)
    assert "secret text" not in str(result)


def test_failure_code_drops_free_text_value_error(tmp_path, monkeypatch):
    result = _run_with_raised(
        tmp_path, monkeypatch,
        ValueError("a free-form explanation from somewhere"))
    assert result["state"] == "FAILED_REVIEW_REQUIRED"
    assert result["failure_code"] == "ValueError"
    assert "free-form" not in str(result)


def test_failure_code_drops_code_shaped_runtime_error(tmp_path, monkeypatch):
    result = _run_with_raised(
        tmp_path, monkeypatch,
        RuntimeError("SYNTHETIC_PRIVATE_HARNESS_OUTPUT"))
    assert result["state"] == "FAILED_REVIEW_REQUIRED"
    assert result["failure_code"] == "RuntimeError"
    assert "SYNTHETIC_PRIVATE" not in str(result)
