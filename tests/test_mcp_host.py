"""Authenticated MCP host integration. Real SQLite Guard, no network listener."""
import time

import pytest

from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer, McpHostPrincipal
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore

DECISION_SCOPES = {
    "foundation_status", "approval_requests", "review_candidate",
    "submit_decision:AUTHORIZE", "submit_decision:DENY",
}


def setup(tmp_path, scopes=None):
    root = tmp_path / "data"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(store.load(), store=store)
    app = OperatorApplication(config, OperatorActions(guard))
    # Test fixture supplies an independently trusted owner delegation.
    # Production MUST bind this callback to the host's real owner/run identity.
    auth = McpHostAuthorizer(owner_authorize=lambda p, tool, run:
                            p.principal_id == "owner@m1"
                            and (not run or run.startswith("run-")))
    host = AuthenticatedMcpHost(app, auth)
    principal, token = host.issue_principal("owner@m1", scopes or DECISION_SCOPES)
    auth.register(principal, token)
    return store, host, principal, token


def test_missing_or_bad_auth_fails_closed(tmp_path):
    store, host, principal, token = setup(tmp_path)
    store.request_approval("run-1", "production_deploy", "secret-target",
                           "revision-1", "effect-1")
    with pytest.raises(PermissionError):
        host.dispatch(principal.session_id, "wrong-token", "foundation_status")
    with pytest.raises(PermissionError):
        host.dispatch("unknown-session", token, "foundation_status")
    ref = host.dispatch(principal.session_id, token, "approval_requests")[0]["request_ref"]
    with pytest.raises(PermissionError):
        host.dispatch(principal.session_id, "wrong", "submit_decision",
                      {"run_id": "run-1", "request_ref": ref, "decision": "AUTHORIZE"})
    assert not store.is_approved("run-1")


def test_read_status_and_exact_decision_use_same_guard(tmp_path):
    store, host, principal, token = setup(tmp_path)
    store.request_approval("run-2", "send_email", "private-recipient",
                           "revision-2", "effect-2")
    status = host.dispatch(principal.session_id, token, "foundation_status")
    assert status["guard_pending"] == 1
    assert "private-recipient" not in str(status)
    requests = host.dispatch(principal.session_id, token, "approval_requests")
    ref = requests[0]["request_ref"]
    assert len(ref) == 64
    assert host.dispatch(principal.session_id, token, "review_candidate",
                         {"run_id": "run-2", "request_ref": ref})["current"] is True
    result = host.dispatch(principal.session_id, token, "submit_decision",
                           {"run_id": "run-2", "request_ref": ref, "decision": "AUTHORIZE"})
    assert result == {"ok": True, "status": "APPROVED"}
    assert store.is_approved("run-2")


def test_expired_session_and_scope_cannot_write(tmp_path):
    store, host, principal, token = setup(tmp_path)
    store.request_approval("run-3", "delete", "test", "rev", "eff")
    requests = host.dispatch(principal.session_id, token, "approval_requests")
    ref = requests[0]["request_ref"]
    read_only = McpHostAuthorizer()
    ro_host = AuthenticatedMcpHost(host.tools._operator, read_only)
    ro_p, ro_t = ro_host.issue_principal("ro@m1", {"foundation_status", "approval_requests", "review_candidate"})
    read_only.register(ro_p, ro_t)
    with pytest.raises(PermissionError):
        ro_host.dispatch(ro_p.session_id, ro_t, "submit_decision",
                         {"run_id": "run-3", "request_ref": ref, "decision": "DENY"})
    now = [time.time()]
    expired_auth = McpHostAuthorizer(now=lambda: now[0])
    exp_host = AuthenticatedMcpHost(host.tools._operator, expired_auth)
    exp_p, exp_t = exp_host.issue_principal("exp@m1", DECISION_SCOPES, ttl_seconds=60,
                                            now=lambda: now[0])
    expired_auth.register(exp_p, exp_t)
    now[0] += 120
    with pytest.raises(PermissionError):
        exp_host.dispatch(exp_p.session_id, exp_t, "approval_requests")
    assert not store.is_cancelled("run-3")


def test_unknown_tool_and_bad_arguments_fail_closed(tmp_path):
    _, host, principal, token = setup(tmp_path)
    with pytest.raises(ValueError):
        host.dispatch(principal.session_id, token, "run_shell", {"cmd": "echo hi"})
    with pytest.raises(ValueError):
        host.dispatch(principal.session_id, token, "foundation_status", "bad")


def test_missing_owner_delegation_does_not_expose_requests_or_approve(tmp_path):
    store, host, owner, token = setup(tmp_path)
    store.request_approval("run-6", "production_deploy", "target", "rev", "eff")
    unbound_auth = McpHostAuthorizer()
    unbound_host = AuthenticatedMcpHost(host.tools._operator, unbound_auth)
    p, t = unbound_host.issue_principal("arbitrary@m1", DECISION_SCOPES)
    unbound_auth.register(p, t)
    assert unbound_host.dispatch(p.session_id, t, "foundation_status")["guard_pending"] == 1
    with pytest.raises(PermissionError):
        unbound_host.dispatch(p.session_id, t, "approval_requests")
    # No independent owner proof; approval requests and decisions fail closed.
    with pytest.raises(PermissionError):
        unbound_host.dispatch(p.session_id, t, "submit_decision",
                              {"run_id": "run-6", "request_ref": "0" * 64,
                               "decision": "AUTHORIZE"})
    assert not store.is_approved("run-6")


def test_forged_principal_cannot_bypass_dispatch_token(tmp_path):
    store, host, real, token = setup(tmp_path)
    store.request_approval("run-7", "production_deploy", "target", "rev", "eff")
    forged = McpHostPrincipal("owner@m1", real.session_id,
                              real.scopes, real.issued_at, real.expires_at)
    # Calling the underlying source adapter directly must still check that the
    # exact host-registered principal instance is delegated and authenticated.
    with pytest.raises(PermissionError):
        host.tools.approval_requests(forged)
    with pytest.raises(PermissionError):
        host.tools.submit_decision(forged, "run-7", "0" * 64, "AUTHORIZE")
    assert not store.is_approved("run-7")


def test_unknown_fields_and_session_overwrite_are_rejected(tmp_path):
    _, host, principal, token = setup(tmp_path)
    with pytest.raises(ValueError):
        host.dispatch(principal.session_id, token, "foundation_status", {"run_id": "extra"})
    with pytest.raises(ValueError):
        host.dispatch(principal.session_id, token, "review_candidate", {})
    with pytest.raises(ValueError):
        host.authorizer.register(principal, token)


def test_approval_list_filters_each_run_by_trusted_owner_delegation(tmp_path):
    store, host, _, _ = setup(tmp_path)
    store.request_approval("run-visible", "production_deploy", "target-a", "rev", "eff-a")
    store.request_approval("run-other-owner", "delete", "target-b", "rev", "eff-b")
    auth = McpHostAuthorizer(owner_authorize=lambda principal, tool, run:
                             principal.principal_id == "owner@m1"
                             and tool == "approval_requests"
                             and (not run or run == "run-visible"))
    bound = AuthenticatedMcpHost(host.tools._operator, auth)
    principal, token = bound.issue_principal("owner@m1", {"approval_requests"})
    auth.register(principal, token)
    rows = bound.dispatch(principal.session_id, token, "approval_requests")
    assert [r["run_id"] for r in rows] == ["run-visible"]
    assert not store.is_approved("run-visible")
    assert not store.is_approved("run-other-owner")
