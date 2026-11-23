"""Independent synthetic MCP external-client protocol/auth contract."""
import io
import json

from scripts import foundation_mcp_stdio as mcp


class CurrentOperator:
    def human_payload(self):
        return {
            "state": "FAILED",
            "notices": [{"level": 4, "status": "WAITING_HUMAN",
                         "approval_ref": "a" * 64, "private": "SECRET"}],
            "services": [{"ok": True, "secret": "PRIVATE"}],
        }


def modern(method, params=None, id_=1):
    p = dict(params or {})
    p["_meta"] = {mcp.VERSION_KEY: mcp.MODERN,
                  mcp.CAPABILITIES_KEY: {},
                  "io.modelcontextprotocol/clientInfo":
                      {"name": "untrusted-client", "version": "1.0"}}
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": p}


def service():
    host, session, token = mcp._new_readonly_host(CurrentOperator())
    return mcp.MCPStdio(host, session, token)


def test_modern_external_discover_list_and_live_operator_status():
    server = service()
    discovery = server.dispatch(modern("server/discover", id_=1))
    assert discovery["result"]["supportedVersions"] == [mcp.MODERN]
    assert "protocolVersions" not in discovery["result"]
    assert discovery["result"]["resultType"] == "complete"
    assert discovery["result"]["_meta"]["io.modelcontextprotocol/serverInfo"] == mcp.SERVER_INFO
    assert discovery["result"]["cacheScope"] == "private"
    catalog = server.dispatch(modern("tools/list", id_=2))["result"]["tools"]
    assert [row["name"] for row in catalog] == ["foundation_status"]
    call = server.dispatch(modern("tools/call", {
        "name": "foundation_status", "arguments": {}}, 3))
    result = json.loads(call["result"]["content"][0]["text"])
    assert call["result"]["isError"] is False
    assert result["state"] == "FAILED"
    assert result["services_ok"] == 1
    assert result["guard_pending"] == 1
    assert "SECRET" not in json.dumps(call)
    assert "PRIVATE" not in json.dumps(call)


def test_spoofed_owner_and_write_tool_never_granted():
    server = service()
    claimed = modern("tools/call", {
        "name": "submit_decision", "arguments": {
            "run_id": "someone-else", "request_ref": "f"*64,
            "decision": "AUTHORIZE",
        }})
    claimed["params"]["_meta"]["io.modelcontextprotocol/clientInfo"] = {
        "name": "root-owned-agent", "version": "trusted"}
    denied = server.dispatch(claimed)
    assert denied["error"]["code"] == -32602
    assert "owner" not in json.dumps(denied).lower()
    extra = server.dispatch(modern("tools/call", {
        "name": "foundation_status", "arguments": {"private": True}}))
    assert extra["error"]["code"] == -32602


def test_legacy_mcp_requires_real_handshake_before_calls():
    server = service()
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    assert server.dispatch(call)["error"]["code"] == -32602
    init = server.dispatch({"jsonrpc": "2.0", "id": 1,
                            "method": "initialize",
                            "params": {"protocolVersion": mcp.LEGACY,
                                       "capabilities": {},
                                       "clientInfo": {"name": "legacy", "version": "1"}}})
    assert init["result"]["protocolVersion"] == mcp.LEGACY
    assert server.dispatch({"jsonrpc": "2.0",
                            "method": "notifications/initialized", "params": {}}) is None
    assert server.dispatch(call)["result"]["tools"][0]["name"] == "foundation_status"


def test_owner_status_http_proxy_does_not_pass_through_private_notices(monkeypatch):
    raw = json.dumps({"state": "PRIVATE_SECRET", "notices": [
        {"level": 4, "status": "WAITING_HUMAN",
         "approval_ref": "b" * 64, "private_name": "DO_NOT_EXPORT"}],
        "services": [{"ok": True, "config": "PRIVATE_CONFIG"}]})
    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, size): return raw.encode()
    class FakeOpener:
        def open(self, req, timeout):
            assert req.full_url == "http://127.0.0.1:8766/api/human"
            assert timeout == 4
            return FakeResponse()
    monkeypatch.setattr(mcp.request, "build_opener", lambda *args: FakeOpener())
    p = mcp.OperatorAggregateProxy().human_payload()
    assert p["state"] == "UNKNOWN"
    assert p["notices"][0]["approval_ref"] == "PRESENT"
    assert "PRIVATE" not in json.dumps(p)
    assert "DO_NOT_EXPORT" not in json.dumps(p)


def test_stdio_ignores_notifications_and_rejects_unbounded_or_invalid_json():
    server = service()
    input_data = (json.dumps(modern("tools/list", id_=1)) + "\n"
                  + "{bad json}\n"
                  + json.dumps(modern("tools/call",
                         {"name":"submit_decision","arguments":{}},id_=3)) + "\n")
    sink = io.StringIO()
    mcp.serve_stdio(server, source=io.BytesIO(input_data.encode()), sink=sink)
    lines = [json.loads(s) for s in sink.getvalue().splitlines()]
    assert len(lines) == 3
    assert lines[0]["result"]["tools"][0]["name"] == "foundation_status"
    assert lines[1]["error"]["code"] == -32700
    assert lines[2]["error"]["code"] == -32602


def bound_service(*, decision_scopes=("submit_decision:AUTHORIZE",)):
    """Synthetic producer: identity, scope and exact-run grant are host-owned."""
    from types import SimpleNamespace
    from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer

    class DurableStore:
        def approve_pending(self, *args): pass
        def cancel_pending(self, *args): pass

    class BoundOperator(CurrentOperator):
        def __init__(self):
            self.pending = True
            self.calls = []
            self.actions = SimpleNamespace(guard=SimpleNamespace(store=DurableStore()))

        def snapshot(self):
            rows = [
                {"kind": "approval", "run_id": "run-1", "approval_ref": "a" * 64,
                 "action": "production_deploy", "private": "DONOTLEAK"}
            ] if self.pending else []
            rows.append({"kind": "approval", "run_id": "run-other",
                         "approval_ref": "b" * 64, "action": "delete"})
            return SimpleNamespace(as_dict=lambda: {"attention": rows})

        def act(self, action, run_id, approval_ref):
            assert run_id == "run-1" and approval_ref == "a" * 64
            self.calls.append(action)
            self.pending = False
            return SimpleNamespace(ok=True, status="APPROVED" if action == "approve" else "DENIED")

    def owner_grant(principal, tool, run_id):
        return ((tool == "approval_requests" and run_id == "")
                or (run_id == "run-1" and tool in {
                    "approval_requests", "review_candidate", *decision_scopes}))

    operator = BoundOperator()
    auth = McpHostAuthorizer(owner_authorize=owner_grant)
    scopes = {"foundation_status", "approval_requests", "review_candidate", *decision_scopes}
    principal, token = AuthenticatedMcpHost.issue_principal("verified-owner", scopes)
    auth.register(principal, token)
    host = AuthenticatedMcpHost(operator, auth)
    server = mcp.MCPStdio(host, principal.session_id, token, exposed_tools=(
        "foundation_status", "approval_requests", "review_candidate", "submit_decision"))
    return server, operator


def _tool(server, name, arguments=None):
    reply = server.dispatch(modern("tools/call", {
        "name": name, "arguments": {} if arguments is None else arguments,
    }))
    assert "result" in reply
    return reply["result"]


def test_opt_in_stdio_lists_scoped_tools_but_default_remains_readonly():
    server, operator = bound_service()
    names = [row["name"] for row in server.dispatch(
        modern("tools/list"))["result"]["tools"]]
    assert names == ["foundation_status", "approval_requests",
                     "review_candidate", "submit_decision"]
    readonly = mcp.MCPStdio(server.host, server.session_id, server.token)
    assert [row["name"] for row in readonly.dispatch(
        modern("tools/list"))["result"]["tools"]] == ["foundation_status"]
    assert readonly.dispatch(modern("tools/call", {
        "name": "submit_decision",
        "arguments": {"run_id": "run-1", "request_ref": "a" * 64,
                      "decision": "AUTHORIZE"}}))["error"]["code"] == -32602
    assert operator.calls == []


def test_scoped_stdio_review_and_exact_authorize_replay_fails_closed():
    server, operator = bound_service()
    rows = json.loads(_tool(server, "approval_requests")["content"][0]["text"])
    assert [row["run_id"] for row in rows] == ["run-1"]
    assert "DONOTLEAK" not in json.dumps(rows)
    current = json.loads(_tool(server, "review_candidate", {
        "run_id": "run-1", "request_ref": "a" * 64})["content"][0]["text"])
    assert current["current"] is True and current["authorized"] is False
    approved = json.loads(_tool(server, "submit_decision", {
        "run_id": "run-1", "request_ref": "a" * 64,
        "decision": "AUTHORIZE"})["content"][0]["text"])
    assert approved == {"ok": True, "status": "APPROVED"}
    assert operator.calls == ["approve"]
    replay = json.loads(_tool(server, "submit_decision", {
        "run_id": "run-1", "request_ref": "a" * 64,
        "decision": "AUTHORIZE"})["content"][0]["text"])
    assert replay == {"ok": False, "status": "STALE_OR_UNBOUND_APPROVAL"}
    assert operator.calls == ["approve"]


def test_scoped_stdio_rejects_ungranted_decision_foreign_run_and_bad_arguments():
    server, operator = bound_service()
    denied = _tool(server, "submit_decision", {
        "run_id": "run-1", "request_ref": "a" * 64,
        "decision": "DENY"})
    assert denied["isError"] is True
    foreign = _tool(server, "submit_decision", {
        "run_id": "run-other", "request_ref": "b" * 64,
        "decision": "AUTHORIZE"})
    assert foreign["isError"] is True
    invalid = server.dispatch(modern("tools/call", {
        "name": "submit_decision", "arguments": {
            "run_id": "run-1", "request_ref": "a" * 64,
            "decision": "AUTHORIZE", "client_owner": "verified-owner"}}))
    assert invalid["error"]["code"] == -32602
    wrong_type = server.dispatch(modern("tools/call", {
        "name": ["submit_decision"], "arguments": {}}))
    assert wrong_type["error"]["code"] == -32602
    assert operator.calls == []


def test_scoped_stdio_deny_requires_own_host_scope_and_current_guard_ref():
    server, operator = bound_service(decision_scopes=("submit_decision:DENY",))
    result = json.loads(_tool(server, "submit_decision", {
        "run_id": "run-1", "request_ref": "a" * 64,
        "decision": "DENY"})["content"][0]["text"])
    assert result == {"ok": True, "status": "DENIED"}
    assert operator.calls == ["cancel"]
    rejected = _tool(server, "submit_decision", {
        "run_id": "run-1", "request_ref": "a" * 64,
        "decision": "AUTHORIZE"})
    assert rejected["isError"] is True
    assert operator.calls == ["cancel"]



def _durable_owner_stdio(tmp_path, *, decision="AUTHORIZE"):
    """Real temporary SQLite Guard, no production mutation or network."""
    from ai_foundation.core import GuardState
    from ai_foundation.guard import GuardCore
    from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
    from ai_foundation.operator_actions import OperatorActions
    from ai_foundation.operator_server import OperatorApplication
    from ai_foundation.productization import FoundationConfig
    from ai_foundation.store import SQLiteGuardStore

    root = tmp_path / "owner-test"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(store.load(), store=store)
    operator = OperatorApplication(config, OperatorActions(guard))
    def existing_owner_delegation(principal, tool, run_id):
        # Fixture of an independently verified host owner/run delegation:
        # never grant all runs, arbitrary source instructions or both decisions.
        return (principal.principal_id == "owner-local"
                and (tool == "approval_requests" and run_id in ("", "run-owner-1")
                     or run_id == "run-owner-1" and tool in (
                         "review_candidate", "submit_decision:" + decision)))
    auth = McpHostAuthorizer(owner_authorize=existing_owner_delegation)
    scopes = {"foundation_status", "approval_requests",
              "review_candidate", "submit_decision:" + decision}
    principal, token = AuthenticatedMcpHost.issue_principal("owner-local", scopes)
    auth.register(principal, token)
    host = AuthenticatedMcpHost(operator, auth)
    server = mcp.MCPStdio(host, principal.session_id, token, exposed_tools=(
        "foundation_status", "approval_requests",
        "review_candidate", "submit_decision"))
    return store, server


def test_real_sqlite_owner_authorize_rejects_replay_foreign_and_stale(tmp_path):
    store, server = _durable_owner_stdio(tmp_path)
    store.request_approval("run-owner-1", "production_deploy",
                           "fixed-public-fixture", "canon-1", "effect-1")
    store.request_approval("run-other", "delete",
                           "other-fixture", "canon-1", "effect-2")
    pending = json.loads(_tool(server, "approval_requests")["content"][0]["text"])
    assert len(pending) == 1 and pending[0]["run_id"] == "run-owner-1"
    ref = pending[0]["request_ref"]
    assert len(ref) == 64 and not store.is_approved("run-owner-1")
    before = json.loads(_tool(server, "review_candidate", {
        "run_id": "run-owner-1", "request_ref": ref})["content"][0]["text"])
    assert before["current"] is True
    approved = json.loads(_tool(server, "submit_decision", {
        "run_id": "run-owner-1", "request_ref": ref,
        "decision": "AUTHORIZE"})["content"][0]["text"])
    assert approved == {"ok": True, "status": "APPROVED"}
    assert store.is_approved("run-owner-1") and not store.is_approved("run-other")
    replay = json.loads(_tool(server, "submit_decision", {
        "run_id": "run-owner-1", "request_ref": ref,
        "decision": "AUTHORIZE"})["content"][0]["text"])
    assert replay == {"ok": False, "status": "STALE_OR_UNBOUND_APPROVAL"}
    wrong = _tool(server, "submit_decision", {
        "run_id": "run-other", "request_ref": "b" * 64,
        "decision": "AUTHORIZE"})
    assert wrong["isError"] is True


def test_real_sqlite_owner_deny_cannot_cancel_replaced_guard_request(tmp_path):
    store, server = _durable_owner_stdio(tmp_path, decision="DENY")
    store.request_approval("run-owner-1", "send_email",
                           "old-public-fixture", "canon-1", "effect-1")
    original = json.loads(_tool(server, "approval_requests")["content"][0]["text"])
    old_ref = original[0]["request_ref"]
    store.request_approval("run-owner-1", "send_email",
                           "new-public-fixture", "canon-1", "effect-1")
    stale = json.loads(_tool(server, "submit_decision", {
        "run_id": "run-owner-1", "request_ref": old_ref,
        "decision": "DENY"})["content"][0]["text"])
    assert stale == {"ok": False, "status": "STALE_OR_UNBOUND_APPROVAL"}
    assert not store.is_cancelled("run-owner-1")
    current = json.loads(_tool(server, "approval_requests")["content"][0]["text"])
    new_ref = current[0]["request_ref"]
    assert new_ref != old_ref
    denied = json.loads(_tool(server, "submit_decision", {
        "run_id": "run-owner-1", "request_ref": new_ref,
        "decision": "DENY"})["content"][0]["text"])
    assert denied == {"ok": True, "status": "CANCELLED"}
    assert store.is_cancelled("run-owner-1")
    assert _tool(server, "submit_decision", {
        "run_id": "run-owner-1", "request_ref": new_ref,
        "decision": "AUTHORIZE"})["isError"] is True
    assert not store.is_approved("run-owner-1")



def test_stdio_default_proxy_only_passes_allowlisted_observed_runtime(monkeypatch):
    payload = {
        "state": "READY", "notices": [], "services": [],
        "development": {
            "source": "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME",
            "local9b_worker": "SCHEDULED_IDLE",
            "local9b_queue_state": "NO_QUEUED_TASK",
            "klm_status": "CURRENT",
            "approved_humanmodel_view": "SECRET_PRIVATE_VIEW",
            "raw_owner_evidence": "SECRET_PRIVATE_CONTENT",
        },
    }
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, size): return json.dumps(payload).encode()
    class Opener:
        def open(self, req, timeout): return Reply()
    monkeypatch.setattr(mcp.request, "build_opener", lambda *args: Opener())
    proxy = mcp.OperatorAggregateProxy()
    public = proxy.human_payload()
    assert public["development"] == {
        "source": "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME",
        "local9b_worker": "SCHEDULED_IDLE",
        "local9b_queue_state": "NO_QUEUED_TASK",
        "klm_status": "CURRENT",
    }
    host, session, token = mcp._new_readonly_host(proxy)
    result = host.dispatch(session, token, "foundation_status")
    assert result["worker_runtime"] == "SCHEDULED_IDLE"
    assert result["worker_queue"] == "NO_QUEUED_TASK"
    assert result["klm_runtime"] == "CURRENT"
    assert result["approved_humanmodel_view"] == "UNVERIFIED"
    assert "SECRET" not in json.dumps(result)


def test_long_lived_tunnel_renews_expired_status_only_principal():
    """After five minutes the stdio child must not silently lose MCP access."""
    original, session, token = mcp._new_readonly_host(CurrentOperator())
    principal = original.authorizer._sessions[session][0]
    assert principal.expires_at - principal.issued_at == 300
    # Advance the trusted owner's authentication clock; never sleep or call a
    # model, GitHub, tunnel API, or current real Operator.
    original.authorizer._now = lambda: principal.expires_at + 1
    renewals = []
    def fixed_owner_renew():
        renewals.append("fixed-owner-status-only")
        return mcp._new_readonly_host(CurrentOperator())
    server = mcp.MCPStdio(original, session, token,
                          readonly_host_refresh=fixed_owner_renew)
    call = modern("tools/call", {"name": "foundation_status", "arguments": {}},
                  id_=31)
    result = server.dispatch(call)
    assert result["result"]["isError"] is False
    assert json.loads(result["result"]["content"][0]["text"])["state"] == "FAILED"
    assert renewals == ["fixed-owner-status-only"]
    assert original.authorizer.authenticate(session, token) is None
    assert server.host is not original
    assert [x["name"] for x in server.dispatch(modern("tools/list"))["result"]["tools"]] == [
        "foundation_status"]
    assert server.dispatch(call)["result"]["isError"] is False
    assert renewals == ["fixed-owner-status-only"]


def test_readonly_renewal_never_activates_other_mcp_tools_or_grants():
    import pytest
    host, session, token = mcp._new_readonly_host(CurrentOperator())
    with pytest.raises(ValueError, match="readonly renewal"):
        mcp.MCPStdio(
            host, session, token,
            exposed_tools=("foundation_status", "approval_requests"),
            readonly_host_refresh=lambda: mcp._new_readonly_host(CurrentOperator()))
    with pytest.raises(ValueError, match="readonly renewal"):
        mcp.MCPStdio(host, session, token, readonly_host_refresh="untrusted")
    calls = []
    server = mcp.MCPStdio(
        host, session, token,
        readonly_host_refresh=lambda: calls.append("SHOULD_NOT_RUN"))
    forged = modern("tools/call", {"name": "submit_decision", "arguments": {
        "run_id": "private-run", "request_ref": "0" * 64, "decision": "AUTHORIZE"}})
    assert server.dispatch(forged)["error"]["code"] == -32602
    assert server.dispatch(modern("tools/call", {
        "name": "foundation_status", "arguments": {"read_private": True}
    }))["error"]["code"] == -32602
    assert calls == []


def test_malformed_trusted_renewal_fails_closed_and_never_leaks_source():
    host, session, token = mcp._new_readonly_host(CurrentOperator())
    host.authorizer._now = lambda: float("inf")
    server = mcp.MCPStdio(
        host, session, token,
        readonly_host_refresh=lambda: ("PRIVATE_TOKEN_CANARY", None))
    reply = server.dispatch(modern("tools/call", {
        "name": "foundation_status", "arguments": {}}))
    assert reply["result"]["isError"] is True
    assert "PRIVATE_TOKEN_CANARY" not in json.dumps(reply)
    assert reply["result"]["content"][0]["text"] == (
        "Local Operator or MCP authority unavailable")


def _proxied_aggregate_status(payload):
    """Exercise fixed HTTP sanitizer -> authenticated host -> public MCP."""
    from unittest.mock import patch
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return None
        def read(self, size): return json.dumps(payload).encode()
    class Opener:
        def open(self, req, timeout):
            assert req.full_url == "http://127.0.0.1:8766/api/human"
            assert timeout == 4
            return Reply()
    with patch.object(mcp.request, "build_opener", return_value=Opener()):
        proxy = mcp.OperatorAggregateProxy()
        public = proxy.human_payload()
        host, session, token = mcp._new_readonly_host(proxy)
        return public, host.dispatch(session, token, "foundation_status")


def test_http_proxy_preserves_current_counts_receipts_and_unknown_services():
    payload = {
        "state": "FAILED", "runtime_health": "READY", "notices": [],
        "state_diagnostics": {"failed_effect_window": 1},
        "services": [{"ok": True}, {"ok": False}, {"ok": None},
                     {"ok": 1}, {"ok": "false"}],
        "development": {
            "source": "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME",
            "guard_actionable": 0, "work_running": 0,
            "work_waiting_human": 0, "work_failed": 0, "work_uncertain": 0,
            "local9b_worker": "SCHEDULED_IDLE",
            "local9b_queue_state": "NO_QUEUED_TASK", "klm_status": "CURRENT",
            "direct_mcp_status": "WORK_RECEIPTS_ONLY",
            "direct_mcp_verified_receipts": 2,
            "private_owner_record": "PRIVATE_CANARY",
        },
    }
    public, result = _proxied_aggregate_status(payload)
    assert public["development"]["work_running"] == 0
    assert result["work_failed"] == result["work_uncertain"] == 0
    assert result["state"] == "FAILED"  # retained history is not erased
    assert result["runtime_health"] == "READY"
    assert result["failed_effect_history"] == 1
    assert result["guard_pending"] == 0
    assert result["direct_mcp_work"] == "WORK_RECEIPTS_ONLY"
    assert result["direct_mcp_verified_receipts"] == 2
    assert (result["services_ok"], result["services_down"],
            result["services_unverified"], result["services_unavailable"]) == (1, 1, 3, 4)
    assert "PRIVATE_CANARY" not in json.dumps((public, result))
    for state in ("WAITING_HUMAN", "UNCERTAIN", "RECOVERING"):
        payload["state"] = state
        assert _proxied_aggregate_status(payload)[1]["state"] == state


def test_http_proxy_rejects_unbound_or_malformed_aggregate_evidence():
    payload = {"state": "READY", "notices": [], "services": [],
               "development": {
                   "source": "CURRENT_GUARD_WORK_SNAPSHOT",
                   "guard_actionable": 2, "work_failed": 3,
                   "work_uncertain": 1,
                   "local9b_worker": "RUNNING", "klm_status": "CURRENT",
                   "direct_mcp_status": "NO_WORK_RECEIPTS",
                   "direct_mcp_verified_receipts": 0}}
    _, result = _proxied_aggregate_status(payload)
    assert (result["guard_pending"], result["work_failed"], result["work_uncertain"]) == (2, 3, 1)
    assert result["worker_runtime"] == result["klm_runtime"] == "UNVERIFIED"
    for source in ("UNTRUSTED", None, [], {}):
        payload["development"]["source"] = source
        _, result = _proxied_aggregate_status(payload)
        assert result["work_failed"] is result["work_uncertain"] is None
        assert result["direct_mcp_work"] == "UNVERIFIED"
        assert result["direct_mcp_verified_receipts"] is None
    payload["development"]["source"] = "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME"
    for bad in (True, -1, 1000001, "0", None, [], {}):
        payload["development"].update(
            guard_actionable=bad, work_failed=bad, work_uncertain=bad,
            direct_mcp_verified_receipts=bad)
        _, result = _proxied_aggregate_status(payload)
        assert result["work_failed"] is result["work_uncertain"] is None
        assert result["direct_mcp_verified_receipts"] is None
        assert result["guard_pending"] == 0


def test_operator_http_outage_retains_scoped_mcp_with_unverified_counts(monkeypatch):
    from urllib.error import URLError

    class UnreachableOpener:
        def open(self, req, timeout):
            assert req.full_url == "http://127.0.0.1:8766/api/human"
            assert timeout == 4
            raise URLError("PRIVATE_HOSTNAME_DO_NOT_EXPOSE")

    monkeypatch.setattr(mcp.request, "build_opener",
                        lambda *args: UnreachableOpener())
    host, session, token = mcp._new_readonly_host(mcp.OperatorAggregateProxy())
    server = mcp.MCPStdio(host, session, token)
    result = server.dispatch(modern("tools/call", {
        "name": "foundation_status", "arguments": {}}))["result"]
    assert result["isError"] is False
    row = json.loads(result["content"][0]["text"])
    assert row["state"] == "UNKNOWN"
    assert row["runtime_health"] == "UNVERIFIED"
    assert row["operator_observation"] == "OPERATOR_HTTP_UNAVAILABLE"
    assert all(row[x] is None for x in (
        "services_ok", "services_unavailable", "services_down",
        "services_unverified", "guard_pending", "work_failed",
        "work_uncertain", "failed_effect_history",
        "dismissed_failed_notices", "direct_mcp_verified_receipts"))
    assert set(row["notice_levels"].values()) == {None}
    assert row["worker_queue"] == row["klm_runtime"] == "UNVERIFIED"
    assert "PRIVATE_HOSTNAME" not in json.dumps(result)
    assert [x["name"] for x in server.dispatch(modern(
        "tools/list"))["result"]["tools"]] == ["foundation_status"]
    rejected = server.dispatch(modern("tools/call", {
        "name": "approval_requests", "arguments": {}}))
    assert rejected["error"]["code"] == -32602


def test_status_invalid_operator_projection_never_fakes_a_zero_or_ready():
    import pytest

    class InvalidOperator:
        def human_payload(self):
            raise ValueError("PRIVATE_OPERATOR_RECORD")

    host, session, token = mcp._new_readonly_host(InvalidOperator())
    result = host.dispatch(session, token, "foundation_status")
    assert result["operator_observation"] == "OPERATOR_PROJECTION_UNVERIFIED"
    assert result["state"] == "UNKNOWN"
    assert result["services_ok"] is None
    assert result["guard_pending"] is None
    assert "PRIVATE_OPERATOR_RECORD" not in json.dumps(result)

    class MisleadingOperator:
        def human_payload(self):
            return {"state": "READY", "services": [{"ok": True}],
                    "notices": "NOT_A_LIST"}

    host, session, token = mcp._new_readonly_host(MisleadingOperator())
    result = host.dispatch(session, token, "foundation_status")
    assert result["operator_observation"] == "OPERATOR_PROJECTION_UNVERIFIED"
    assert result["services_ok"] is result["guard_pending"] is None


def test_status_authority_denial_remains_error_not_unverified_success():
    class DeniedOperator:
        def human_payload(self):
            raise PermissionError("PRIVATE_GUARD_DENIAL")

    host, session, token = mcp._new_readonly_host(DeniedOperator())
    server = mcp.MCPStdio(host, session, token)
    result = server.dispatch(modern("tools/call", {
        "name": "foundation_status", "arguments": {}}))["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == (
        "Local Operator or MCP authority unavailable")
    assert "PRIVATE_GUARD_DENIAL" not in json.dumps(result)
    # A client-forged principal cannot obtain status through the same method.
    server.token = "not-the-trusted-token"
    result = server.dispatch(modern("tools/call", {
        "name": "foundation_status", "arguments": {}}))["result"]
    assert result["isError"] is True


def test_source_backed_operator_status_marks_observation_and_preserves_values():
    _, row = _proxied_aggregate_status({
        "state": "WAITING_HUMAN", "runtime_health": "READY",
        "notices": [], "services": [{"ok": True}],
        "development": {
            "source": "CURRENT_GUARD_WORK_SNAPSHOT",
            "guard_actionable": 2,
            "work_failed": 5, "work_uncertain": 0,
        },
    })
    assert row["operator_observation"] == "CURRENT_OPERATOR_API"
    assert row["runtime_health"] == "READY"
    assert row["services_ok"] == 1
    assert row["guard_pending"] == 2
    assert row["work_failed"] == 5
    assert row["work_uncertain"] == 0
