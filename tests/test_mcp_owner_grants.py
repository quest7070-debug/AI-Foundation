"""Owner-held exact MCP grants, using the SAME durable Guard and CSRF UI.

No provider, model, Native signal or production Guard activity.
"""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.mcp_host import AuthenticatedMcpHost
from ai_foundation.mcp_owner_grants import McpOwnerGrants
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication, serve
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore
from scripts.m1_owner_delegated_mcp_stdio import build_owner_mcp

M = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
     "io.modelcontextprotocol/clientCapabilities": {}}


def create(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    cfg = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / cfg.guard_db)
    guard = GuardCore(store.runtime_state(), store=store)
    grants = McpOwnerGrants(store, initialize=True)
    app = OperatorApplication(cfg, OperatorActions(guard),
                              csrf_token="fixture-csrf-token",
                              mcp_owner_delegations=grants)
    store.request_approval("owner-run", "production_deploy", "fixture-target",
                           "canon-fixture", "effect-fixture")
    return store, app, grants


def ref(app, run="owner-run"):
    rows = app.snapshot().as_dict()["attention"]
    return next(x["approval_ref"] for x in rows
                if x.get("kind") == "approval" and x.get("run_id") == run)


def call(service, name, arguments=None, *, seq=1):
    frame = {"jsonrpc":"2.0","id":seq, "method":"tools/call",
             "params":{"_meta":M,"name":name,"arguments":arguments or {}}}
    response = service.dispatch(frame)
    assert response["id"] == seq
    if "error" in response:
        return {"error": response["error"]["code"]}
    row = response["result"]
    return {"error": row["isError"],
            "value": json.loads(row["content"][0]["text"]) if not row["isError"] else None}


class Aggregate:
    def human_payload(self):
        return {"state": "READY", "notices": [], "services": []}


def test_no_grant_cannot_list_or_write_even_if_client_claims_owner(tmp_path):
    store, app, grants = create(tmp_path)
    server = build_owner_mcp(store, aggregate=Aggregate())
    denied = call(server, "approval_requests")
    assert denied["error"] is True
    attempt = call(server, "submit_decision", {
        "run_id": "owner-run", "request_ref": ref(app),
        "decision": "AUTHORIZE"})
    assert attempt["error"] is True
    assert not store.is_approved("owner-run")
    assert call(server,"foundation_status")["value"]["guard_pending"] == 0


def test_exact_one_time_owner_grant_authorize_and_replay_denied(tmp_path):
    store, app, grants = create(tmp_path)
    exact = ref(app)
    assert grants.issue("owner-run", exact, "AUTHORIZE")
    server = build_owner_mcp(store, aggregate=Aggregate())
    rows = call(server, "approval_requests")["value"]
    assert len(rows) == 1 and rows[0]["request_ref"] == exact
    assert call(server, "review_candidate",
                {"run_id":"owner-run","request_ref":exact})["value"]["current"]
    assert call(server, "submit_decision", {
        "run_id":"owner-run","request_ref":exact,"decision":"DENY"})["error"] is True
    approved = call(server, "submit_decision", {
        "run_id":"owner-run","request_ref":exact,"decision":"AUTHORIZE"})
    assert approved["value"] == {"ok": True, "status":"APPROVED"}
    assert store.is_approved_for("owner-run", "production_deploy",
                                 "fixture-target", "canon-fixture","effect-fixture")
    assert call(server, "submit_decision", {
        "run_id":"owner-run","request_ref":exact,"decision":"AUTHORIZE"})["error"] is True
    assert not store.is_cancelled("owner-run")


def test_pending_change_expiry_wrong_ref_and_wrong_owner_fail_closed(tmp_path):
    now = [1000.0]
    store, app, grants = create(tmp_path)
    timed = McpOwnerGrants(store, now=lambda:now[0])
    old = ref(app)
    assert timed.issue("owner-run",old,"DENY")
    assert timed.authorize(type("P",(),{"principal_id":"macos-owner-local"})(),
                           "submit_decision:DENY","owner-run")
    fake=type("P",(),{"principal_id":"different-owner"})()
    assert not timed.claim(fake,"owner-run",old,"DENY")
    assert not timed.claim(type("P",(),{"principal_id":"macos-owner-local"})(),
                           "owner-run","0"*64,"DENY")
    store.request_approval("owner-run","delete","changed-target",
                           "canon-fixture","effect-fixture")
    assert not timed.claim(type("P",(),{"principal_id":"macos-owner-local"})(),
                           "owner-run",old,"DENY")
    assert not store.is_cancelled("owner-run")
    new=ref(app)
    assert timed.issue("owner-run",new,"DENY")
    now[0]+=301
    assert not timed.claim(type("P",(),{"principal_id":"macos-owner-local"})(),
                           "owner-run",new,"DENY")


def test_operator_ui_csrf_origin_and_exact_current_ref_only(tmp_path):
    store,app,grants=create(tmp_path)
    # The owner notification screen is single-path: only the exact Guard
    # AUTHORIZE/DENY buttons render. Legacy scoped POST is tested below as
    # a separately CSRF+Origin protected internal transport, not a UI action.
    assert "DELEGATE AUTHORIZE VIA MCP" not in app.page()
    assert "DELEGATE DENY VIA MCP" not in app.page()
    assert "/action/approve/owner-run" in app.page()
    assert "/action/cancel/owner-run" in app.page()
    http=serve(app)
    thread=threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    try:
        base="http://127.0.0.1:"+str(http.server_port)
        def post(ref_string,csrf="fixture-csrf-token",origin=None,decision="DENY"):
            data=urllib.parse.urlencode({"csrf":csrf,"approval_ref":ref_string,
                                         "decision":decision}).encode()
            req=urllib.request.Request(base+"/action/delegate-mcp/owner-run",
                                       method="POST",data=data,
                                       headers={"Origin":origin} if origin else {})
            try:
                with urllib.request.urlopen(req,timeout=3) as res:
                    return res.status
            except urllib.error.HTTPError as e:
                return e.code
        exact=ref(app)
        assert post(exact,csrf="forged")==403
        assert post(exact,origin="https://outside.example")==403
        # No hidden MCP decision-issuer route can revive old UI buttons.
        assert post("a"*64)==404
        assert post(exact)==404
        assert not store.is_approved("owner-run")
        assert not store.is_cancelled("owner-run")
        server=build_owner_mcp(store,aggregate=Aggregate())
        result=call(server,"submit_decision",{
            "run_id":"owner-run","request_ref":exact,"decision":"DENY"})
        assert result["error"] is True
        assert not store.is_cancelled("owner-run")
        assert post(exact)==404
    finally:
        http.shutdown()
        http.server_close()
        thread.join(timeout=3)


def test_restart_revokes_unissued_claim_and_no_new_database(tmp_path):
    store,app,grants=create(tmp_path)
    new=McpOwnerGrants(store,initialize=False)
    fake=type("P",(),{"principal_id":"macos-owner-local"})()
    assert not new.authorize(fake,"submit_decision:AUTHORIZE","owner-run")
    assert not new.claim(fake,"owner-run",ref(app),"AUTHORIZE")
    assert not store.is_approved("owner-run")


def test_cannot_use_legacy_delegation_or_wrong_principal_for_other_request(tmp_path):
    store,app,grants=create(tmp_path)
    ref1=ref(app)
    assert grants.issue("owner-run",ref1,"AUTHORIZE")
    store.request_approval("not-delegated","send_email","fixture-other",
                           "canon-other","effect-other")
    server=build_owner_mcp(store,aggregate=Aggregate())
    listing=call(server,"approval_requests")["value"]
    assert [x["run_id"] for x in listing]==["owner-run"]
    attempted=call(server,"submit_decision",{
        "run_id":"not-delegated","request_ref":"b"*64,"decision":"AUTHORIZE"})
    assert attempted["error"] is True
    assert not store.is_approved("not-delegated")


def test_malformed_owner_delegation_never_creates_authority(tmp_path):
    store, app, grants = create(tmp_path)
    exact = ref(app)
    for run_id, request_ref, decision in (
        ("owner-run", "G" * 64, "AUTHORIZE"),
        ("owner-run", exact, "authorize"),
        ("owner-run", exact, "AUTHORIZE "),
        ("owner-run/other", exact, "AUTHORIZE"),
        ("owner-run", "0" * 64, "AUTHORIZE"),
    ):
        assert not grants.issue(run_id, request_ref, decision)
    server = build_owner_mcp(store, aggregate=Aggregate())
    assert call(server, "approval_requests")["error"] is True
    assert call(server, "submit_decision", {
        "run_id": "owner-run", "request_ref": exact,
        "decision": "AUTHORIZE"})["error"] is True
    assert not store.is_approved("owner-run")
    assert not store.is_cancelled("owner-run")
