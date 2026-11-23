from concurrent.futures import ThreadPoolExecutor
import sqlite3
from hashlib import sha256
from types import SimpleNamespace

import pytest

from ai_foundation.development_requests import DevelopmentRequestPort
from ai_foundation.durable_work import SQLiteWorkStore


OWNER = SimpleNamespace(principal_id="owner")


class ExistingPort:
    guard = object()

    def authorize(self, principal, ticket):
        return principal.principal_id == "owner" and ticket == "verified"

    def status(self, principal, ticket):
        return {"ticket_id": ticket, "state": "VERIFIED_LOCAL"}

    def list_tickets(self, principal, *, authorize_status):
        return {"tickets": [self.status(principal, "verified")], "ticket_count": 1}

    def run(self, *args):
        raise AssertionError("request must never execute an admitted ticket")


def port(path):
    return DevelopmentRequestPort(ExistingPort(), work=SQLiteWorkStore(path),
                                  principal_id="owner",
                                  storage_admission=SimpleNamespace(require=lambda _: None))


def test_request_survives_restart_is_not_chat_intake_and_cannot_run(tmp_path):
    db = tmp_path / "work.db"
    p = port(db)
    first = p.request(OWNER, "new", "Implement a bounded improvement")
    assert first["state"] == "REVIEW_REQUIRED" and not first["execution_started"]
    p = port(db)
    assert p.request(OWNER, "new", "Implement a bounded improvement")["replay_readonly"]
    assert p.run(OWNER, "new")["state"] == "REVIEW_REQUIRED"
    assert p.status(OWNER, "verified")["state"] == "VERIFIED_LOCAL"
    assert p.list_tickets(OWNER, authorize_status=lambda _: True)["ticket_count"] == 2
    with sqlite3.connect(db) as c:
        assert c.execute("SELECT status,name FROM work_steps").fetchall() == [("WAITING_HUMAN", "development-request")]
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='task_intake'").fetchone()


def test_exact_request_replay_survives_storage_pressure_without_reopening_work(tmp_path):
    p = port(tmp_path / "work.db")
    initial = p.request(OWNER, "new", "public reviewed task")
    assert initial["replay_readonly"] is False
    before = p.work.load(p.prefix + "new")[0]
    def storage_denied(_):
        raise PermissionError("no new storage available")
    p.storage_admission = SimpleNamespace(require=storage_denied)
    replay = p.request(OWNER, "new", "public reviewed task")
    assert replay["replay_readonly"] is True
    assert replay["instruction_sha256"] == initial["instruction_sha256"]
    assert replay["state"] == "REVIEW_REQUIRED" and replay["execution_started"] is False
    assert p.work.load(p.prefix + "new")[0] == before
    with pytest.raises(ValueError, match="DEVELOPMENT_REQUEST_CONFLICT"):
        p.request(OWNER, "new", "different instruction")
    with pytest.raises(PermissionError, match="no new storage available"):
        p.request(OWNER, "another", "new task must be gated")
    assert not p.authorize(OWNER, "another")


def test_changed_replay_and_admitted_ids_are_rejected(tmp_path):
    p = port(tmp_path / "work.db")
    p.request(OWNER, "new", "original")
    with pytest.raises(ValueError, match="CONFLICT"):
        p.request(OWNER, "new", "changed")
    with pytest.raises(ValueError, match="ALREADY_ADMITTED"):
        p.request(OWNER, "verified", "new instruction")


@pytest.mark.parametrize("ticket", ["Upper", "with_dot.x", "with:colon", "a" * 49])
def test_request_rejects_ids_the_existing_ticket_factory_cannot_admit(tmp_path, ticket):
    p = port(tmp_path / "work.db")
    with pytest.raises(ValueError, match="INVALID_DEVELOPMENT_REQUEST_ID"):
        p.request(OWNER, ticket, "original")
    assert p.work.development_review_requests(p.prefix) == []


def test_other_owner_cannot_submit_read_or_run_request(tmp_path):
    p = port(tmp_path / "work.db")
    p.request(OWNER, "new", "original")
    other = SimpleNamespace(principal_id="other")
    for operation in (lambda: p.request(other, "new", "original"),
                      lambda: p.status(other, "new"), lambda: p.run(other, "new")):
        with pytest.raises(PermissionError):
            operation()
    assert not p.authorize(other, "new")


def test_concurrent_duplicates_create_one_request(tmp_path):
    p = port(tmp_path / "work.db")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: p.request(OWNER, "same", "original"), range(8)))
    assert sum(not row["replay_readonly"] for row in rows) == 1


def test_storage_denial_leaves_no_request(tmp_path):
    p = port(tmp_path / "work.db")
    def deny(_):
        raise PermissionError("storage full")
    p.storage_admission = SimpleNamespace(require=deny)
    with pytest.raises(PermissionError, match="storage full"):
        p.request(OWNER, "new", "original")
    assert not p.authorize(OWNER, "new")


def test_authenticated_stdio_request_scope_and_fixed_arguments(tmp_path):
    from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
    from scripts.foundation_mcp_stdio import MCPStdio

    p = port(tmp_path / "work.db")
    auth = McpHostAuthorizer(owner_authorize=lambda principal, tool, run:
                             p.authorize_request(principal))
    operator = SimpleNamespace(actions=SimpleNamespace(guard=p.guard))
    host = AuthenticatedMcpHost(operator, auth, development_port=p)
    principal, token = host.issue_principal("owner", {"foundation_status", "development_request"})
    auth.register(principal, token)
    service = MCPStdio(host, principal.session_id, token,
                       exposed_tools=("foundation_status", "development_request"))
    result = host.dispatch(principal.session_id, token, "development_request",
                           {"ticket_id": "mcp-new", "instruction": "public improvement"})
    assert result["state"] == "REVIEW_REQUIRED"
    assert "development_request" in service.exposed_tools
    from scripts import foundation_mcp_stdio as protocol
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "development_request",
        "arguments": {"ticket_id": "protocol-new", "instruction": "public improvement"},
        "_meta": {protocol.VERSION_KEY: protocol.MODERN, protocol.CAPABILITIES_KEY: {}}}}
    response = service.dispatch(message)
    assert response["result"]["isError"] is False
    assert "public improvement" not in str(response)
    assert p.status(principal, "protocol-new")["state"] == "REVIEW_REQUIRED"
    with pytest.raises(ValueError):
        host.dispatch(principal.session_id, token, "development_request",
                      {"ticket_id": "bad", "instruction": "change", "command": "shell"})
    other, other_token = host.issue_principal("owner", {"foundation_status"})
    auth.register(other, other_token)
    with pytest.raises(PermissionError):
        host.dispatch(other.session_id, other_token, "development_request",
                      {"ticket_id": "forbidden", "instruction": "change"})


def test_reviewed_admission_reloads_same_guard_without_execution(tmp_path):
    p = port(tmp_path / "work.db")
    p.request(OWNER, "new", "original instruction")
    calls = []
    class Admitted(ExistingPort):
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket in {"new", "verified"}
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": "READY"}
    def review(ticket, digest):
        calls.append((ticket, digest))
        assert digest == sha256(b"original instruction").hexdigest()
        return Admitted()
    p.admit_reviewed = review
    p.can_admit = True
    result = p.admit(OWNER, "new")
    assert result["state"] == "READY" and result["admission_completed"]
    assert p.admit(OWNER, "new")["replay_readonly"]
    assert len(calls) == 1
    assert p.work.load(p.prefix + "new")[0].status.value == "VERIFIED"


def test_missing_review_and_cancelled_request_cannot_be_admitted(tmp_path):
    from ai_foundation.orchestration import WorkStatus
    p = port(tmp_path / "work.db")
    p.request(OWNER, "new", "original")
    def no_review(*_):
        raise PermissionError("OWNER_REVIEW_REQUIRED")
    p.admit_reviewed = no_review
    p.can_admit = True
    with pytest.raises(PermissionError, match="OWNER_REVIEW_REQUIRED"):
        p.admit(OWNER, "new")
    assert p.run(OWNER, "new")["state"] == "REVIEW_REQUIRED"
    saved = p.work.load(p.prefix + "new")[0]
    p.work.transition(saved.job_id, 0, WorkStatus.WAITING_HUMAN, WorkStatus.CANCELLED, saved.result)
    assert p.admit(OWNER, "new")["state"] == "CANCELLED"
    assert p.run(OWNER, "new")["state"] == "CANCELLED"
    with pytest.raises(PermissionError):
        p.admit(SimpleNamespace(principal_id="other"), "new")


def test_admission_rejects_replacement_guard(tmp_path):
    p = port(tmp_path / "work.db")
    p.request(OWNER, "new", "original")
    class WrongGuard(ExistingPort):
        guard = object()
    p.admit_reviewed = lambda *_: WrongGuard()
    p.can_admit = True
    with pytest.raises(PermissionError, match="SAME_GUARD"):
        p.admit(OWNER, "new")
    assert p.run(OWNER, "new")["state"] == "REVIEW_REQUIRED"


def test_cancellation_during_manifest_admission_blocks_execution_after_restart(tmp_path):
    from ai_foundation.orchestration import WorkStatus
    db = tmp_path / "work.db"
    p = port(db)
    p.request(OWNER, "new", "original")
    class PersistedAdmission(ExistingPort):
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket == "new"
        def authorize_delivery(self, *_):
            raise AssertionError("cancelled request cannot reach publisher")
    def cancelled_while_admitting(*_):
        saved = p.work.load(p.prefix + "new")[0]
        assert p.work.transition(saved.job_id, 0, WorkStatus.WAITING_HUMAN,
                                 WorkStatus.CANCELLED, saved.result)
        return PersistedAdmission()
    p.admit_reviewed = cancelled_while_admitting
    p.can_admit = True
    assert p.admit(OWNER, "new")["state"] == "CANCELLED"
    # Reconstructed host can load the manifest, but the durable cancellation wins.
    restarted = DevelopmentRequestPort(PersistedAdmission(), work=SQLiteWorkStore(db),
                                       principal_id="owner", storage_admission=p.storage_admission)
    for current in (p, restarted):
        assert current.status(OWNER, "new")["state"] == "CANCELLED"
        assert current.run(OWNER, "new")["state"] == "CANCELLED"
        assert current.authorize_delivery(OWNER, "new") is False


def test_mcp_admission_needs_its_own_scope_and_no_contract_arguments(tmp_path):
    from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
    p = port(tmp_path / "work.db")
    p.request(OWNER, "new", "original")
    p.can_admit = True
    calls = []
    def missing_review(*args):
        calls.append(args)
        raise PermissionError("OWNER_REVIEW_REQUIRED")
    p.admit_reviewed = missing_review
    auth = McpHostAuthorizer(owner_authorize=lambda principal, tool, ticket:
                             p.authorize_admit(principal, ticket))
    host = AuthenticatedMcpHost(SimpleNamespace(actions=SimpleNamespace(guard=p.guard)),
                                auth, development_port=p)
    reader, reader_token = host.issue_principal("owner", {"development_status"})
    auth.register(reader, reader_token)
    with pytest.raises(PermissionError):
        host.dispatch(reader.session_id, reader_token, "development_admit", {"ticket_id": "new"})
    assert not calls
    owner, token = host.issue_principal("owner", {"development_admit"})
    auth.register(owner, token)
    with pytest.raises(ValueError):
        host.dispatch(owner.session_id, token, "development_admit",
                      {"ticket_id": "new", "review": "approved"})
    assert not calls
    with pytest.raises(PermissionError, match="OWNER_REVIEW_REQUIRED"):
        host.dispatch(owner.session_id, token, "development_admit", {"ticket_id": "new"})
    assert calls == [("new", sha256(b"original").hexdigest())]


def test_one_call_continuation_requires_owner_review_then_admits_runs_once(tmp_path):
    p = port(tmp_path / "work.db")
    p.request(OWNER, "next", "fixed public instruction")
    calls = []
    class Reviewed(ExistingPort):
        state = "READY"
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket == "next"
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": self.state}
        def run(self, principal, ticket):
            assert self.state == "READY"
            calls.append("run")
            self.state = "VERIFIED_LOCAL"
            return self.status(principal, ticket)
        def authorize_delivery(self, *_):
            return False
    def owner_review(ticket, digest):
        calls.append("review")
        assert ticket == "next"
        assert digest == sha256(b"fixed public instruction").hexdigest()
        return Reviewed()
    p.can_admit = True
    p.admit_reviewed = lambda *_: (_ for _ in ()).throw(
        PermissionError("OWNER_REVIEW_REQUIRED"))
    with pytest.raises(PermissionError, match="OWNER_REVIEW_REQUIRED"):
        p.continue_reviewed(OWNER, "next")
    assert p.status(OWNER, "next")["state"] == "REVIEW_REQUIRED"
    assert p.work.load(p.prefix + "next")[0].status.value == "WAITING_HUMAN"
    p.admit_reviewed = owner_review
    assert p.continue_reviewed(OWNER, "next")["state"] == "VERIFIED_LOCAL"
    assert p.continue_reviewed(OWNER, "next")["state"] == "VERIFIED_LOCAL"
    assert calls == ["review", "run"]
    assert p.work.load(p.prefix + "next")[0].status.value == "VERIFIED"


def test_continuation_never_overrides_cancellation_or_foreign_owner(tmp_path):
    from ai_foundation.orchestration import WorkStatus
    p = port(tmp_path / "work.db")
    p.request(OWNER, "next", "original")
    p.can_admit = True
    p.admit_reviewed = lambda *_: (_ for _ in ()).throw(
        AssertionError("cancelled task must not be reviewed"))
    saved = p.work.load(p.prefix + "next")[0]
    assert p.work.transition(saved.job_id, 0, WorkStatus.WAITING_HUMAN,
                             WorkStatus.CANCELLED, saved.result)
    assert p.continue_reviewed(OWNER, "next")["state"] == "CANCELLED"
    with pytest.raises(PermissionError, match="CONTINUATION_NOT_AUTHORIZED"):
        p.continue_reviewed(SimpleNamespace(principal_id="other"), "next")


def test_continuation_requires_three_host_scopes_and_separate_draft_optin(tmp_path):
    from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
    from scripts.foundation_mcp_stdio import MCPStdio
    p = port(tmp_path / "work.db")
    p.request(OWNER, "next", "approved public")
    calls = []
    class Reviewed(ExistingPort):
        state = "READY"
        optin = True
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket == "next"
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": self.state}
        def run(self, principal, ticket):
            calls.append("run")
            self.state = "VERIFIED_LOCAL"
            return self.status(principal, ticket)
        def authorize_delivery(self, principal, ticket):
            return self.optin and self.authorize(principal, ticket)
        def deliver(self, principal, ticket):
            calls.append("draft")
            return {"ticket_id": ticket, "state": "VERIFIED_LOCAL",
                    "github_published": True}
    reviewed = Reviewed()
    p.admit_reviewed = lambda *_: reviewed
    p.can_admit = True
    operator = SimpleNamespace(actions=SimpleNamespace(guard=p.guard))
    auth = McpHostAuthorizer(owner_authorize=lambda principal, tool, ticket:
                             principal.principal_id == "owner" and ticket == "next"
                             and (tool != "development_deliver"
                                  or p.authorize_delivery(principal, ticket)))
    host = AuthenticatedMcpHost(operator, auth, development_port=p)
    # Neither the newly exposed tool nor a single old write scope is enough.
    for scopes in (
        {"development_continue"},
        {"development_continue", "development_run"},
        {"development_continue", "development_admit"}):
        user, token = host.issue_principal("owner", scopes)
        auth.register(user, token)
        with pytest.raises(PermissionError, match="continuation not authorized"):
            host.dispatch(user.session_id, token, "development_continue",
                          {"ticket_id": "next"})
    assert calls == []
    owner, token = host.issue_principal("owner", {
        "foundation_status", "development_continue",
        "development_admit", "development_run"})
    auth.register(owner, token)
    server = MCPStdio(host, owner.session_id, token,
                      exposed_tools=("foundation_status", "development_continue"))
    assert server.exposed_tools == frozenset({"foundation_status", "development_continue"})
    with pytest.raises(ValueError):
        host.dispatch(owner.session_id, token, "development_continue",
                      {"ticket_id": "next", "model": "paid"})
    result = host.dispatch(owner.session_id, token, "development_continue",
                           {"ticket_id": "next"})
    assert result["state"] == "VERIFIED_LOCAL" and not result.get("github_published")
    assert calls == ["run"]
    # A separate delivery-capable session can now produce the Draft.
    delivery_owner, delivery_token = host.issue_principal("owner", {
        "development_continue", "development_admit", "development_run",
        "development_deliver"})
    auth.register(delivery_owner, delivery_token)
    again = host.dispatch(delivery_owner.session_id, delivery_token,
                          "development_continue", {"ticket_id": "next"})
    assert again["github_published"] is True
    assert calls == ["run", "draft"]


def test_development_cycle_runs_only_one_ready_and_never_unsigned(tmp_path):
    class Admitted(ExistingPort):
        def __init__(self):
            self.state = "READY"
            self.calls = 0
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket == "ready"
        def authorize_list(self, principal):
            return principal.principal_id == "owner"
        def list_tickets(self, principal, *, authorize_status):
            return {"tickets": [self.status(principal, "ready")],
                    "ticket_count": 1}
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": self.state}
        def run(self, principal, ticket):
            assert self.state == "READY"
            self.calls += 1
            self.state = "VERIFIED_LOCAL"
            return self.status(principal, ticket)
    active = Admitted()
    p = DevelopmentRequestPort(
        active, work=SQLiteWorkStore(tmp_path / "work.db"),
        principal_id="owner",
        storage_admission=SimpleNamespace(require=lambda _: None),
        admit_reviewed=lambda *_: (_ for _ in ()).throw(
            AssertionError("unsigned review must not be admitted")),
        review_available=lambda _: False,
    )
    p.request(OWNER, "unsigned", "review is not yet signed")
    allow = lambda _: True
    first = p.cycle_one(OWNER, authorize_status=allow, authorize_pending=allow)
    assert first == {"ticket_id": "ready", "state": "VERIFIED_LOCAL"}
    assert active.calls == 1
    second = p.cycle_one(OWNER, authorize_status=allow, authorize_pending=allow)
    assert second == {"state": "NO_ELIGIBLE_TICKET",
                      "execution_started": False,
                      "authorized_examined": 2, "review_required": 1,
                      "blocked_state_counts": {
                          "review_required": 1, "failed_acceptance": 0,
                          "source_base_review": 0, "admission_refresh": 0,
                          "verified_local": 1, "other_terminal": 0},
                      "resume_only_after": "EXACT_REVIEW_OR_EXISTING_SCOPE_REQUIRED",
                      "retry_without_change": False,
                      "work_failed_count_inferred": False}
    assert active.calls == 1
    with pytest.raises(PermissionError):
        p.cycle_one(SimpleNamespace(principal_id="foreign"),
                    authorize_status=allow, authorize_pending=allow)


def test_development_cycle_uses_exact_existing_owner_review_for_pending(tmp_path):
    calls = []
    class Unadmitted(ExistingPort):
        def authorize_list(self, principal):
            return principal.principal_id == "owner"
        def authorize(self, principal, ticket):
            return False
        def list_tickets(self, principal, *, authorize_status):
            return {"tickets": [], "ticket_count": 0}
    class Reviewed(Unadmitted):
        def __init__(self):
            self.state = "READY"
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket == "signed"
        def list_tickets(self, principal, *, authorize_status):
            return {"tickets": [self.status(principal, "signed")], "ticket_count": 1}
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": self.state}
        def run(self, principal, ticket):
            calls.append("run")
            assert self.state == "READY"
            self.state = "VERIFIED_LOCAL"
            return self.status(principal, ticket)
    def admit(ticket, digest):
        calls.append("owner-review-readback")
        assert ticket == "signed"
        assert digest == sha256(b"exact signed source and test").hexdigest()
        return Reviewed()
    signed = {"present": False}
    p = DevelopmentRequestPort(
        Unadmitted(), work=SQLiteWorkStore(tmp_path / "work.db"),
        principal_id="owner", storage_admission=SimpleNamespace(require=lambda _: None),
        admit_reviewed=admit, review_available=lambda _: signed["present"],
    )
    p.request(OWNER, "signed", "exact signed source and test")
    allow = lambda _: True
    before = p.cycle_one(OWNER, authorize_status=allow, authorize_pending=allow)
    assert before["state"] == "NO_ELIGIBLE_TICKET"
    assert before["resume_only_after"] == "EXACT_REVIEW_OR_EXISTING_SCOPE_REQUIRED"
    assert before["retry_without_change"] is False
    assert calls == []
    signed["present"] = True
    assert p.cycle_one(OWNER, authorize_status=allow,
                       authorize_pending=lambda _: False)["state"] == "NO_ELIGIBLE_TICKET"
    assert calls == []
    result = p.cycle_one(OWNER, authorize_status=allow, authorize_pending=allow)
    assert result["state"] == "VERIFIED_LOCAL"
    assert calls == ["owner-review-readback", "run"]
    final = p.cycle_one(OWNER, authorize_status=allow, authorize_pending=allow)
    assert final["state"] == "NO_ELIGIBLE_TICKET"
    assert final["resume_only_after"] == "NEW_ELIGIBLE_WORK_REQUIRED"
    assert final["retry_without_change"] is False
    assert calls == ["owner-review-readback", "run"]


def test_mcp_development_cycle_needs_own_and_per_ticket_scopes(tmp_path):
    from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
    from scripts.foundation_mcp_stdio import MCPStdio
    class Admitted(ExistingPort):
        state = "READY"
        calls = 0
        def authorize_list(self, principal):
            return principal.principal_id == "owner"
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket == "ready"
        def list_tickets(self, principal, *, authorize_status):
            return {"tickets": [self.status(principal, "ready")], "ticket_count": 1}
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": self.state}
        def run(self, principal, ticket):
            self.calls += 1
            self.state = "VERIFIED_LOCAL"
            return self.status(principal, ticket)
    active = Admitted()
    p = DevelopmentRequestPort(
        active, work=SQLiteWorkStore(tmp_path / "work.db"),
        principal_id="owner", storage_admission=SimpleNamespace(require=lambda _: None),
        admit_reviewed=lambda *_: None, review_available=lambda _: False,
    )
    def owner_auth(principal, tool, ticket):
        return principal.principal_id == "owner" and (
            tool in {"development_cycle", "development_list"}
            or ticket == "ready")
    auth = McpHostAuthorizer(owner_authorize=owner_auth)
    host = AuthenticatedMcpHost(
        SimpleNamespace(actions=SimpleNamespace(guard=p.guard)),
        auth, development_port=p,
    )
    for scopes in (
        {"development_list", "development_status", "development_run"},
        {"development_cycle", "development_status", "development_run"},
    ):
        principal, token = host.issue_principal("owner", scopes)
        auth.register(principal, token)
        with pytest.raises(PermissionError, match="cycle not authorized"):
            host.dispatch(principal.session_id, token, "development_cycle", {})
    assert active.calls == 0
    scopes = {"foundation_status", "development_cycle", "development_list",
              "development_status", "development_run"}
    principal, token = host.issue_principal("owner", scopes)
    auth.register(principal, token)
    service = MCPStdio(host, principal.session_id, token,
                       exposed_tools=("foundation_status", "development_cycle"))
    assert "development_cycle" in service.exposed_tools
    with pytest.raises(ValueError):
        host.dispatch(principal.session_id, token, "development_cycle",
                      {"ticket_id": "ready"})
    result = host.dispatch(principal.session_id, token, "development_cycle", {})
    assert result["state"] == "VERIFIED_LOCAL"
    assert active.calls == 1
    assert host.dispatch(principal.session_id, token, "development_cycle",
                         {})["state"] == "NO_ELIGIBLE_TICKET"
    assert active.calls == 1



def test_selfdev_cycle_triages_failed_acceptance_and_unreviewed_base_no_retry(
        tmp_path):
    states = {
        "failed-a": "FAILED_REVIEW_REQUIRED",
        "failed-b": "FAILED_REVIEW_REQUIRED",
        "source-base": "SOURCE_BASE_REVIEW_REQUIRED",
        "waiting": "REVIEW_REQUIRED",
        "ready-done": "VERIFIED_LOCAL",
    }
    class ExistingReviews(ExistingPort):
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket in states
        def authorize_list(self, principal):
            return principal.principal_id == "owner"
        def list_tickets(self, principal, *, authorize_status):
            rows = [self.status(principal, ticket) for ticket in states]
            return {"tickets": rows, "ticket_count": len(rows)}
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": states[ticket]}
        def run(self, *_):
            raise AssertionError("failed/review-required work must not rerun")
    p = DevelopmentRequestPort(
        ExistingReviews(), work=SQLiteWorkStore(tmp_path / "work.db"),
        principal_id="owner",
        storage_admission=SimpleNamespace(require=lambda _: None),
        admit_reviewed=lambda *_: (_ for _ in ()).throw(
            AssertionError("missing owner approval")),
        review_available=lambda _: False,
        discover=lambda *_: (_ for _ in ()).throw(
            AssertionError("unfinished committed work takes priority over discovery")))
    scope = lambda _: True
    row = p.cycle_one(OWNER, authorize_status=scope, authorize_pending=scope)
    assert row["state"] == "NO_ELIGIBLE_TICKET"
    assert row["resume_only_after"] == "OWNER_REVIEW_FAILED_LOCAL_ACCEPTANCE"
    assert row["blocked_state_counts"] == {
        "review_required": 1, "failed_acceptance": 2,
        "source_base_review": 1, "admission_refresh": 0,
        "verified_local": 1, "other_terminal": 0}
    assert row["work_failed_count_inferred"] is False
    assert row["retry_without_change"] is False
    assert row["execution_started"] is False


def test_selfdev_cycle_denies_duplicate_state_rows_without_any_execution(
        tmp_path):
    class Duplicate(ExistingPort):
        def authorize_list(self, principal):
            return True
        def list_tickets(self, principal, *, authorize_status):
            row = {"ticket_id": "dup", "state": "FAILED_REVIEW_REQUIRED"}
            return {"tickets": [row, row], "ticket_count": 2}
        def authorize(self, principal, ticket):
            return True
        def run(self, *_):
            raise AssertionError("duplicate must not run")
    p = DevelopmentRequestPort(
        Duplicate(), work=SQLiteWorkStore(tmp_path / "work.db"),
        principal_id="owner",
        storage_admission=SimpleNamespace(require=lambda _: None))
    with pytest.raises(ValueError, match="DUPLICATE_TICKET"):
        p.cycle_one(OWNER, authorize_status=lambda _: True,
                    authorize_pending=lambda _: True)


def test_autonomous_cycle_finishes_previously_tested_owner_authorized_draft_once(tmp_path):
    """A prior VERIFIED_LOCAL receipt needs no new CODE, test or separate UI."""
    from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer

    class AlreadyTested(ExistingPort):
        guard = object()
        published = False
        draft_calls = 0
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket == "tested"
        def authorize_list(self, principal):
            return principal.principal_id == "owner"
        def list_tickets(self, principal, *, authorize_status):
            return {"tickets": [self.status(principal, "tested")], "ticket_count": 1}
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": "VERIFIED_LOCAL",
                    "github_published": self.published}
        def authorize_delivery(self, principal, ticket):
            return self.authorize(principal, ticket)
        def run(self, *_):
            raise AssertionError("never repeat already tested CODE or model work")
        def deliver(self, principal, ticket):
            assert self.authorize_delivery(principal, ticket)
            self.draft_calls += 1
            self.published = True
            return self.status(principal, ticket)

    already = AlreadyTested()
    port = DevelopmentRequestPort(
        already, work=SQLiteWorkStore(tmp_path / "work.db"),
        principal_id="owner", storage_admission=SimpleNamespace(
            require=lambda _: None))
    auth = McpHostAuthorizer(owner_authorize=lambda principal, tool, ticket:
                              principal.principal_id == "owner" and
                              (tool in {"development_cycle", "development_list"}
                               or ticket == "tested"))
    host = AuthenticatedMcpHost(
        SimpleNamespace(actions=SimpleNamespace(guard=already.guard)),
        auth, development_port=port)
    # No delivery grant: a verified receipt must not trigger publication.
    readonly, token = host.issue_principal("owner", {
        "development_cycle", "development_list",
        "development_status", "development_run"})
    auth.register(readonly, token)
    result = host.dispatch(readonly.session_id, token, "development_cycle", {})
    assert result["state"] == "NO_ELIGIBLE_TICKET"
    assert already.draft_calls == 0

    # The same original host, now with the separately authorized Draft scope:
    owner, token = host.issue_principal("owner", {
        "development_cycle", "development_list", "development_status",
        "development_run", "development_deliver"})
    auth.register(owner, token)
    delivered = host.dispatch(owner.session_id, token, "development_cycle", {})
    assert delivered["state"] == "VERIFIED_LOCAL" and delivered["github_published"]
    assert already.draft_calls == 1
    again = host.dispatch(owner.session_id, token, "development_cycle", {})
    assert again["state"] == "NO_ELIGIBLE_TICKET"
    assert already.draft_calls == 1

def test_cycle_recovers_verified_admission_without_new_review_or_replay(tmp_path):
    calls = []

    class Empty(ExistingPort):
        def authorize_list(self, principal):
            return principal.principal_id == "owner"
        def authorize(self, principal, ticket):
            return False
        def list_tickets(self, principal, *, authorize_status):
            return {"tickets": [], "ticket_count": 0}

    class Reviewed(Empty):
        state = "READY"
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket == "resume"
        def status(self, principal, ticket):
            return {"ticket_id": ticket, "state": self.state}
        def list_tickets(self, principal, *, authorize_status):
            return {"tickets": [self.status(principal, "resume")], "ticket_count": 1}
        def run(self, principal, ticket):
            assert self.state == "READY"
            calls.append("run")
            self.state = "VERIFIED_LOCAL"
            return self.status(principal, ticket)

    db = tmp_path / "work.db"
    reviewed = Reviewed()
    available = {"manifest": True}

    def read_review(ticket, digest):
        assert ticket == "resume"
        assert digest == sha256(b"exact original review").hexdigest()
        calls.append("review")
        return reviewed

    def refresh(ticket, digest):
        assert ticket == "resume"
        assert digest == sha256(b"exact original review").hexdigest()
        calls.append("refresh")
        return reviewed if available["manifest"] else None

    def restart():
        return DevelopmentRequestPort(
            Empty(), work=SQLiteWorkStore(db), principal_id="owner",
            storage_admission=SimpleNamespace(require=lambda _: None),
            admit_reviewed=read_review, review_available=lambda _: False,
            refresh_admitted=refresh)

    first = restart()
    first.request(OWNER, "resume", "exact original review")
    assert first.admit(OWNER, "resume")["state"] == "READY"
    p = restart()
    assert p.status(OWNER, "resume")["state"] == "ADMISSION_REFRESH_REQUIRED"
    allow = lambda _: True
    available["manifest"] = False
    assert p.cycle_one(OWNER, authorize_status=allow,
                       authorize_pending=allow)["state"] == "NO_ELIGIBLE_TICKET"
    available["manifest"] = True
    assert p.cycle_one(OWNER, authorize_status=allow,
                       authorize_pending=lambda _: False)["state"] == "NO_ELIGIBLE_TICKET"
    assert calls == ["review", "refresh"]
    assert p.cycle_one(OWNER, authorize_status=allow,
                       authorize_pending=allow)["state"] == "VERIFIED_LOCAL"
    assert calls == ["review", "refresh", "refresh", "run"]
    assert p.cycle_one(OWNER, authorize_status=allow,
                       authorize_pending=allow)["state"] == "NO_ELIGIBLE_TICKET"
    assert calls == ["review", "refresh", "refresh", "run"]


@pytest.mark.parametrize("terminal", ["FAILED_REVIEW_REQUIRED", "RECONCILE_REQUIRED"])
def test_cycle_skips_terminal_draft_and_selects_eligible_delivery(tmp_path, terminal):
    class Tested(ExistingPort):
        def authorize_list(self, principal):
            return principal.principal_id == "owner"
        def authorize(self, principal, ticket):
            return principal.principal_id == "owner" and ticket in {"blocked", "eligible"}
        def status(self, principal, ticket):
            row = {"ticket_id": ticket, "state": "VERIFIED_LOCAL",
                   "github_published": False}
            if ticket == "blocked":
                row["delivery_state"] = terminal
            return row
        def list_tickets(self, principal, *, authorize_status):
            return {"tickets": [self.status(principal, key)
                                for key in ("blocked", "eligible")], "ticket_count": 2}
        def authorize_delivery(self, principal, ticket):
            return self.authorize(principal, ticket)

    p = DevelopmentRequestPort(
        Tested(), work=SQLiteWorkStore(tmp_path / "work.db"),
        principal_id="owner", storage_admission=SimpleNamespace(require=lambda _: None))
    allow = lambda _: True
    assert p.cycle_one(OWNER, authorize_status=allow, authorize_pending=allow,
                       authorize_delivery=allow)["ticket_id"] == "eligible"
    assert p.cycle_one(OWNER, authorize_status=allow, authorize_pending=allow,
                       authorize_delivery=lambda key: key == "blocked")["state"] == "NO_ELIGIBLE_TICKET"
