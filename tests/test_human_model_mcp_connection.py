"""No-network integration of the EXISTING authenticated MCP host and owner ledger.

The synthetic trusted host adapter supplies a server-authenticated actor,
independent current-source read and a source-specific Guard consent grant.
No model text, raw owner content or alternate approval/identity database.
"""
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

from ai_foundation.core import CanonContract, GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.human_model_collection_guard import (
    GuardCollectionConsent, collection_intent,
)
from ai_foundation.human_model_context import HumanModelBinding
from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_server import OperatorApplication
from ai_foundation.productization import FoundationConfig
from ai_foundation.store import SQLiteGuardStore, approval_request_ref

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "human_model"))
from human_model_ledger import Ledger
from human_model_owner_publication import prepare_admission_schema
from human_model_source_admission import HostCollectionGrant, TrustedSourceSnapshot
from human_model_host_mcp import HumanModelOwnerMcpPort, TrustedOwnerSourcePort

SOURCE = "SYNTHETIC-PRIVATE-OWNER-OBSERVATION"
SCOPES = frozenset({
    "human_model_status", "human_model_collect",
    "human_model_revoke", "human_model_refresh",
})


def setup(tmp_path, *, with_source=True, with_host_port=True, principal_id="owner@m1"):
    root = tmp_path / "runtime"
    root.mkdir()
    config = FoundationConfig(str(root.resolve()))
    store = SQLiteGuardStore(root / config.guard_db)
    guard = GuardCore(store.runtime_state(), store=store)
    operator = OperatorApplication(config, OperatorActions(guard))
    source_root = tmp_path / "Volumes" / "SYNTHETIC-USB" / "HumanModel"
    path = source_root / "ledger" / "human_model.sqlite3"
    path.parent.mkdir(parents=True)
    ledger = Ledger(path)
    try:
        prepare_admission_schema(ledger)
        ledger.define_view(view_id="work", purpose="synthetic",
                           audience="foundation", allowed_scopes=["work"],
                           max_privacy="private")
    finally:
        ledger.close()
    binding = HumanModelBinding(
        "owner@m1", str(source_root), "work", ("work",), "private")
    canon = CanonContract("test-host-collection", "canon-v1")
    verifier = GuardCollectionConsent(
        authenticated_owner="owner@m1", binding=binding,
        guard=guard, canon=canon)
    grant = HostCollectionGrant(
        owner_id="owner@m1", source_system="chat",
        source_record_id="message-123", source_revision="rev-1",
        source_uri="synthetic:chat:thread-1/message-123",
        scope="work", privacy="private", purpose="exact owner observation",
        consent_id="human-collection-1", consent_revision="1",
        expected_sha256=hashlib.sha256(SOURCE.encode()).hexdigest(),
    )
    snapshot = TrustedSourceSnapshot(
        source_system="chat", source_record_id=grant.source_record_id,
        source_revision=grant.source_revision, source_uri=grant.source_uri,
        actor_principal_id="owner@m1", actor_kind="owner",
        actor_verified=True, complete=True, content=SOURCE,
        observed_at="2026-11-10T13:20:00+09:00",
    )
    def exact_grant(owner, system, record, scope, run_id):
        assert (owner,system,record,scope,run_id) == (
            "owner@m1","chat","message-123","work","human-collection-1")
        return grant
    def exact_reader(system, record):
        assert (system,record) == ("chat","message-123")
        return snapshot
    source = TrustedOwnerSourcePort(
        grant_for=exact_grant, read_current=exact_reader) if with_source else None
    port = HumanModelOwnerMcpPort(
        binding=binding, consent=verifier,
        open_owner_ledger=lambda: Ledger(path),
        open_readonly_connection=lambda: sqlite3.connect(path.as_uri()+"?mode=ro", uri=True),
        source=source) if with_host_port else None
    authorizer = McpHostAuthorizer(
        owner_authorize=lambda principal, tool, run_id:
            principal.principal_id == "owner@m1"
            and (not run_id or run_id == "human-collection-1"))
    host = AuthenticatedMcpHost(operator, authorizer, human_model_port=port)
    principal, token = host.issue_principal(principal_id, SCOPES)
    authorizer.register(principal, token)
    args = {"source_system":"chat", "record_id":"message-123",
            "scope":"work", "run_id":"human-collection-1"}
    return store, guard, host, principal, token, grant, binding, canon, path, args


def approve_exact(store, guard, grant, binding, canon):
    intent = collection_intent(grant, binding=binding, canon=canon)
    assert store.request_approval(intent.run_id, intent.action,
                                  intent.target, intent.canon_revision, intent.effect_id)
    with sqlite3.connect(store.path) as db:
        approval = db.execute(
            "SELECT action,target,request_nonce,canon_revision,effect_id "
            "FROM approval_requests WHERE run_id=?", (intent.run_id,)).fetchone()
    result = OperatorActions(guard).approve_pending(
        intent.run_id, approval_request_ref(intent.run_id, *approval))
    assert result.ok


def dispatch(host, principal, token, tool, args=None):
    return host.dispatch(principal.session_id, token, tool, args)


def test_exact_guard_approved_owner_source_via_existing_mcp_and_revocation(tmp_path):
    store, guard, host, principal, token, grant, binding, canon, db_path, args = setup(tmp_path)
    assert set(host.tool_catalog()) == {"foundation_status", "approval_requests",
        "review_candidate", "submit_decision", "human_model_status",
        "human_model_collect", "human_model_revoke", "human_model_refresh"}
    with pytest.raises(PermissionError, match="CURRENT_COLLECTION_GUARD_REQUIRED"):
        dispatch(host,principal,token,"human_model_collect",args)
    approve_exact(store,guard,grant,binding,canon)
    first = dispatch(host,principal,token,"human_model_collect",args)
    assert first["status"] == "SOURCE_PUBLISHED"
    assert first["execution_authority"] is False
    assert SOURCE not in json.dumps(first)
    assert grant.source_uri not in json.dumps(first)
    second = dispatch(host,principal,token,"human_model_collect",args)
    assert second["status"] == "SOURCE_ALREADY_CURRENT"
    status = dispatch(host,principal,token,"human_model_status")
    assert status["records"] == 1 and status["admitted_sources"] == 1
    assert SOURCE not in json.dumps(status)
    receipt = dispatch(host,principal,token,"human_model_refresh")
    assert receipt["status"] == "OWNER_LIFECYCLE_VERIFIED"
    assert receipt["source_current"] == 1
    assert receipt["execution_authority"] is False
    with pytest.raises(PermissionError, match="GUARD_CANCEL_NOT_PROVEN"):
        dispatch(host,principal,token,"human_model_revoke",{"run_id":grant.consent_id})
    guard.cancel(grant.consent_id)
    revoked = dispatch(host,principal,token,"human_model_revoke",{"run_id":grant.consent_id})
    assert revoked["withdrawn_sources"] == 1
    ledger = Ledger(db_path)
    try:
        ledger.rebuild_view(view_id="work")
        assert ledger.query(view_id="work", scope="work", audience="foundation") == []
        assert ledger.db.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == 1
    finally:
        ledger.close()



def test_existing_operator_cancel_auto_invalidates_owned_source(tmp_path):
    store, guard, host, principal, token, grant, binding, canon, path, args = setup(tmp_path)
    approve_exact(store, guard, grant, binding, canon)
    assert dispatch(host,principal,token,"human_model_collect",args)["status"] == "SOURCE_PUBLISHED"
    ledger = Ledger(path)
    try:
        ledger.rebuild_view(view_id="work")
    finally:
        ledger.close()
    outcome = host.tools._operator.act("cancel", grant.consent_id)
    assert outcome.ok is True and outcome.status == "CANCELLED"
    assert store.is_cancelled(grant.consent_id)
    ledger = Ledger(path)
    try:
        assert ledger.db.execute(
            "SELECT state FROM human_source_admissions").fetchone() == ("WITHDRAWN",)
        assert ledger.db.execute(
            "SELECT stale FROM model_views WHERE id='work'").fetchone() == (1,)
        ledger.rebuild_view(view_id="work")
        assert ledger.query(view_id="work",scope="work",audience="foundation") == []
    finally:
        ledger.close()
    assert dispatch(host,principal,token,"human_model_status")["withdrawn_sources"] == 1


def test_cancel_callback_unavailable_reports_pending_not_false_success(tmp_path):
    store, guard, host, principal, token, grant, binding, canon, path, args = setup(tmp_path)
    approve_exact(store,guard,grant,binding,canon)
    assert dispatch(host,principal,token,"human_model_collect",args)["status"] == "SOURCE_PUBLISHED"
    def cannot_sync(_):
        raise RuntimeError("SYNTHETIC-USB-UNAVAILABLE")
    host.tools._operator.actions._cancel_observer = cannot_sync
    result = host.tools._operator.act("cancel",grant.consent_id)
    assert result.ok and result.status == "CANCELLED_HUMANMODEL_SYNC_PENDING"
    assert store.is_cancelled(grant.consent_id)
    assert host.human_model_port.consent.active_digest(
        hashlib.sha256(grant.consent_id.encode()).hexdigest()) is False



def test_unrelated_operator_cancel_never_opens_private_human_model_volume(tmp_path):
    store, guard, host, principal, token, grant, binding, canon, path, args = setup(tmp_path)
    def private_volume_must_not_open():
        raise RuntimeError("UNRELATED_PRIVATE_VOLUME_ACCESS")
    host.human_model_port.open_owner_ledger = private_volume_must_not_open
    result = host.tools._operator.act("cancel", "ordinary-job-42")
    assert result.ok and result.status == "CANCELLED"
    assert store.is_cancelled("ordinary-job-42")
    assert host.human_model_port.on_guard_cancelled("ordinary-job-42") == {
        "status": "NO_HUMANMODEL_GRANT", "execution_authority": False}


def test_no_host_source_port_cannot_collect_or_refresh(tmp_path):
    store, guard, host, principal, token, grant, binding, canon, db_path, args = setup(
        tmp_path, with_source=False)
    approve_exact(store,guard,grant,binding,canon)
    with pytest.raises(PermissionError, match="TRUSTED_OWNER_SOURCE_NOT_CONNECTED"):
        dispatch(host,principal,token,"human_model_collect",args)
    with pytest.raises(PermissionError, match="TRUSTED_OWNER_SOURCE_NOT_CONNECTED"):
        dispatch(host,principal,token,"human_model_refresh")
    assert dispatch(host,principal,token,"human_model_status")["records"] == 0


def test_unregistered_host_port_rejects_human_model_tools(tmp_path):
    _, _, host, principal, token, _, _, _, _, args = setup(tmp_path, with_host_port=False)
    assert not any(name.startswith("human_model_") for name in host.tool_catalog())
    with pytest.raises(PermissionError):
        dispatch(host,principal,token,"human_model_status")
    with pytest.raises(PermissionError):
        dispatch(host,principal,token,"human_model_collect",args)


def test_token_scope_owner_and_expiry_are_required(tmp_path):
    store, guard, host, principal, token, grant, binding, canon, db_path, args = setup(tmp_path)
    approve_exact(store,guard,grant,binding,canon)
    with pytest.raises(PermissionError):
        host.dispatch(principal.session_id,"invalid","human_model_collect",args)
    with pytest.raises(ValueError):
        host.dispatch(principal.session_id,token,"human_model_collect",dict(args,actor="user"))
    with pytest.raises(ValueError):
        host.dispatch(principal.session_id,token,"human_model_collect",
                      dict(args,content=SOURCE))
    fake, fake_token = host.issue_principal("foreign-owner", SCOPES)
    host.authorizer.register(fake, fake_token)
    with pytest.raises(PermissionError):
        dispatch(host,fake,fake_token,"human_model_status")
    assert dispatch(host,principal,token,"human_model_status")["records"] == 0



def test_mcp_status_unavailable_never_creates_missing_private_database(tmp_path):
    store,guard,host,principal,token,grant,binding,canon,path,args = setup(tmp_path)
    path.unlink()
    result = dispatch(host,principal,token,"human_model_status")
    assert result == {"status":"OWNER_LEDGER_UNAVAILABLE","execution_authority":False}
    assert not path.exists()


def test_mcp_source_adapter_cannot_label_assistant_as_owner(tmp_path):
    store,guard,host,principal,token,grant,binding,canon,path,args = setup(tmp_path)
    approve_exact(store,guard,grant,binding,canon)
    from dataclasses import replace
    def forged(_system,_record):
        return TrustedSourceSnapshot(
            source_system=grant.source_system,
            source_record_id=grant.source_record_id,
            source_revision=grant.source_revision,
            source_uri=grant.source_uri,
            actor_principal_id="owner@m1",
            actor_kind="assistant",
            actor_verified=True,complete=True,content=SOURCE)
    source=host.human_model_port.source
    host.human_model_port.source=TrustedOwnerSourcePort(
        grant_for=source.grant_for,read_current=forged)
    with pytest.raises(PermissionError,match="UNVERIFIED_OWNER_SOURCE"):
        dispatch(host,principal,token,"human_model_collect",args)
    assert dispatch(host,principal,token,"human_model_status")["records"]==0



def test_external_factory_requires_explicit_owner_schema_migration(tmp_path, monkeypatch):
    import storage_location
    store,guard,host,principal,token,grant,binding,canon,path,args = setup(tmp_path)
    monkeypatch.setattr(storage_location,"validated_ledger_path",lambda _root: path)
    strict = HumanModelOwnerMcpPort.from_existing_external(
        binding=binding, consent=host.human_model_port.consent,
        source=host.human_model_port.source)
    # Simulate a valid, pre-existing original SQLite without the optional
    # HumanModel admission schema. Reads still work; writes cannot migrate.
    ledger = Ledger(path)
    try:
        ledger.db.execute("DROP TABLE human_source_admissions")
        ledger.db.commit()
    finally:
        ledger.close()
    with pytest.raises(RuntimeError,match="OWNER_ADMISSION_SCHEMA_NOT_PREPARED"):
        strict.open_owner_ledger()
    assert strict.status(principal)["records"] == 0
    db = sqlite3.connect(path)
    try:
        assert db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='human_source_admissions'").fetchone()[0]==0
    finally:
        db.close()
    # Exact reviewed migration is a separate owner action.
    ledger=Ledger(path)
    try:
        prepare_admission_schema(ledger)
    finally:
        ledger.close()
    writer=strict.open_owner_ledger()
    writer.close()


def test_no_synthetic_approval_is_authentication(tmp_path):
    store, guard, host, principal, token, grant, binding, canon, path, args = setup(tmp_path)
    approve_exact(store,guard,grant,binding,canon)
    forged_session, forged_token = host.issue_principal("owner@m1", set())
    host.authorizer.register(forged_session,forged_token)
    with pytest.raises(PermissionError):
        dispatch(host,forged_session,forged_token,"human_model_collect",args)
    assert dispatch(host,principal,token,"human_model_status")["records"] == 0


def test_owner_answer_is_available_through_scoped_existing_mcp_stdio(tmp_path):
    """Real owner ledger -> Guard read -> existing local model -> scoped MCP result."""
    from functools import partial
    from types import SimpleNamespace
    from ai_foundation.auto_agent import AutoCapabilityAgent
    from ai_foundation.capability_request import CapabilityRequest
    from ai_foundation.human_model_context import HumanModelContext
    from ai_foundation.routed_agent_model import foundation_agent_model
    from foundation_readonly import read_view_snapshot
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from foundation_mcp_stdio import MCPStdio

    store, guard, host, principal, token, _, binding, _, path, _ = setup(tmp_path)
    ledger = Ledger(path)
    try:
        evidence_id = ledger.add(
            source_uri="synthetic:private-choice", source_revision="1",
            kind="decision", scope="work",
            content="I prefer reliable weekdays over an honorary job title.",
            privacy="private", observed_at="2026-11-12T00:00:00Z")
        ledger.rebuild_view(view_id="work")
    finally:
        ledger.close()

    root = path.parent.parent
    volumes = tmp_path / "Volumes"
    approved_reader = partial(
        read_view_snapshot, volumes_dir=volumes,
        mount_check=lambda mount: mount == str(volumes / "SYNTHETIC-USB"))
    context = HumanModelContext(
        binding, approved_reader, guard=guard, run_id="synthetic-owner-answer")
    class Router:
        def choose(self, _function, *, exclude=(), local_required=False):
            assert local_required
            return SimpleNamespace(binding="local", kind="LOCAL",
                                   execution_slot=None, model="synthetic")
    class Endpoint:
        def __init__(self): self.payloads = []
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            prompt = json.dumps(payload, ensure_ascii=False)
            assert "reliable weekdays" in prompt
            assert "Would I take an honorary title?" in prompt
            assert evidence_id in prompt
            assert not payload.get("tools")
            return {"model": "synthetic", "choices": [{"message": {
                "content": "Simulation: I would not trade reliable weekdays for a title."
                           " [HumanModel:" + evidence_id + "]"}}]}
    endpoint = Endpoint()
    model = foundation_agent_model(
        Router(), lambda _: pytest.fail("private owner data cannot use cloud"),
        endpoint, local_required=True)
    agent = AutoCapabilityAgent(
        model, object(), CapabilityRequest(owner_id=binding.owner_id),
        human_model_context=context)
    host.human_model_port.answer_agent_factory = lambda owner: agent
    assert host.tool_catalog()["human_model_answer"]["writes"] is False

    authorized, key = host.issue_principal(
        binding.owner_id, {"foundation_status", "human_model_answer"})
    host.authorizer.register(authorized, key)
    server = MCPStdio(
        host, authorized.session_id, key,
        exposed_tools=("foundation_status", "human_model_answer"))
    server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                     "params": {}})
    server.dispatch({"jsonrpc": "2.0", "method": "notifications/initialized"})
    tools = server.dispatch({"jsonrpc": "2.0", "id": 2, "method": "tools/list",
                             "params": {}})["result"]["tools"]
    assert [t["name"] for t in tools] == ["foundation_status", "human_model_answer"]
    call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "human_model_answer", "arguments": {
                "question": "Would I take an honorary title?", "scope": "work"}}}
    outcome = server.dispatch(call)["result"]
    assert outcome["isError"] is False
    response = json.loads(outcome["content"][0]["text"])
    assert response["status"] == "SIMULATED_PROVISIONAL"
    assert response["candidate_evidence_ids"] == [evidence_id]
    assert response["owner_statement_verified"] is False
    assert response["execution_authority"] is False
    assert len(endpoint.payloads) == 1
    assert "I prefer reliable weekdays" not in outcome["content"][0]["text"]

    # The public/default stdio still exposes only aggregate status.
    plain = MCPStdio(host, authorized.session_id, key)
    assert plain.dispatch(call)["error"]["code"] == -32602
    with pytest.raises(PermissionError):
        host.dispatch(principal.session_id, token, "human_model_answer",
                      {"question": "Would I take an honorary title?", "scope": "work"})
    with pytest.raises(ValueError):
        host.dispatch(authorized.session_id, key, "human_model_answer",
                      {"question": "test", "scope": "work", "owner": "forged"})
    bad_scope = server.dispatch({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                 "params": {"name": "human_model_answer", "arguments": {
                                     "question": "test", "scope": "other"}}})
    assert bad_scope["result"]["isError"] is True
