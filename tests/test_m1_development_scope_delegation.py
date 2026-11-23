"""One-time owner CODE delegation: source pins, UI authority and revocation.

Synthetic tracked repository and local Work DB only; no model, API or service.
"""
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import threading
import http.client
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from scripts.m1_development_scope_delegation import (
    delegated_record, enable_scope, revoke_scope, load_scope, scope_active,
)
from scripts.m1_development_ticket_factory import _OwnerScopeBoundPort
from scripts.m1_strata_owner_ticket_admission import reviewed_contract
from scripts.m1_development_owner_review import OwnerDevelopmentReview
from ai_foundation.operator_server import OperatorApplication, serve


def _git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, stderr=subprocess.DEVNULL).strip()


def _fixture(tmp_path, *, target="sample", content="VALUE = 1\n"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-q", "-b", "main", str(repo)])
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    source = repo / "src" / "ai_foundation" / (target + ".py")
    source.parent.mkdir(parents=True)
    source.write_text(content)
    fixed = repo / "tests" / ("test_" + target + ".py")
    fixed.parent.mkdir()
    fixed.write_text("def test_unchanged():\n    assert True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "synthetic pinned base")
    root = tmp_path / "owner"
    root.mkdir(mode=0o700)
    instruction = "Modify src/ai_foundation/" + target + ".py using tests/test_" + target + ".py."
    ticket = "bounded-source-work"
    principal = "macos-owner-local"
    job = "mcp-development-request:" + sha256(principal.encode()).hexdigest() + ":" + ticket
    with sqlite3.connect(root / "work.db") as db:
        db.execute("CREATE TABLE work_steps(job_id TEXT,position INTEGER,name TEXT,status TEXT,result TEXT)")
        db.execute("INSERT INTO work_steps VALUES(?,?,?,?,?)", (
            job, 0, "development-request", "WAITING_HUMAN",
            json.dumps({"ticket_id": ticket, "instruction": instruction})))
    return root, repo, ticket, instruction


def _enable(root, *, model="m1", draft=False):
    return enable_scope(root, model=model, allow_draft_delivery=draft, confirmed=True)


def test_no_grant_means_no_automatic_review_or_side_effect(tmp_path):
    root, repo, ticket, _ = _fixture(tmp_path)
    assert delegated_record(root, repo, ticket) is None
    assert load_scope(root) is None
    with pytest.raises(PermissionError):
        reviewed_contract(root, repo, ticket)
    assert not (root / "development").exists()


def test_scoped_local_code_uses_pinned_source_test_without_individual_review(tmp_path):
    root, repo, ticket, instruction = _fixture(tmp_path)
    if os.getuid() != 501:
        pytest.skip("Owner UI policy issuance is deliberately M1 UID 501 only")
    assert _enable(root, draft=True)["status"] == "DELEGATION_ENABLED"
    record = delegated_record(
        root, repo, ticket, expected_instruction_sha256=sha256(instruction.encode()).hexdigest())
    assert record["source_origin"] == "owner-scope-delegation-v1"
    assert record["model"] == "m1"
    assert record["allow_draft_delivery"] is True
    assert record["test"] == "tests/test_sample.py"
    assert "public_source_sha256" not in record
    assert reviewed_contract(root, repo, ticket) == record
    assert scope_active(root, record["scope_ref"])
    assert (root / "development/scope-delegation.json").stat().st_mode & 0o077 == 0
    assert not (root / "development/reviews").exists()
    with pytest.raises(PermissionError):
        _enable(root, model="auto")  # Cannot silently expand an active scope.


def test_scoped_public_auto_is_explicit_and_blocks_sensitive_source(tmp_path):
    root, repo, ticket, _ = _fixture(tmp_path)
    if os.getuid() != 501:
        pytest.skip("Owner UI policy issuance is deliberately M1 UID 501 only")
    _enable(root, model="auto")
    record = delegated_record(root, repo, ticket)
    assert record["model"] == "auto"
    assert record["public_source_sha256"] == record["source_sha256"]
    assert record["public_instruction_sha256"] == sha256(record["instruction"].encode()).hexdigest()
    src = repo / record["target"]
    src.write_text('API_KEY = "sk-proj-' + "A" * 48 + '"\n')
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "synthetic sensitive source")
    assert delegated_record(root, repo, ticket) is None


def test_guard_and_release_code_always_require_exact_owner_review(tmp_path):
    if os.getuid() != 501:
        pytest.skip("Owner UI policy issuance is deliberately M1 UID 501 only")
    for protected in (
            "guard", "release_gate", "mcp_host", "human_model_private",
            "development_requests", "routing", "capability_factory",
            "host_compute_lease", "storage_admission"):
        root, repo, ticket, _ = _fixture(tmp_path / protected, target=protected)
        _enable(root, model="m1", draft=True)
        assert delegated_record(root, repo, ticket) is None


class _Existing:
    def __init__(self):
        self.invocations = []
    def status(self, principal, ticket_id):
        return {"ticket_id": ticket_id, "state": "READY", "github_published": False}
    def run(self, principal, ticket_id):
        self.invocations.append(("run", ticket_id))
        return {"ticket_id": ticket_id, "state": "RUNNING"}
    def authorize_delivery(self, principal, ticket_id):
        return True
    def deliver(self, principal, ticket_id):
        self.invocations.append(("deliver", ticket_id))
        return "draft"
    def list_tickets(self, principal, *, authorize_status):
        return {"ticket_count": 1, "tickets": [self.status(principal, "bounded-source-work")]}


def test_revoke_cuts_off_fresh_work_and_draft_claims_without_replay(tmp_path):
    root, repo, ticket, _ = _fixture(tmp_path)
    if os.getuid() != 501:
        pytest.skip("Owner UI policy issuance is deliberately M1 UID 501 only")
    _enable(root, draft=True)
    ref = delegated_record(root, repo, ticket)["scope_ref"]
    existing = _Existing()
    gated = _OwnerScopeBoundPort(existing, root, {ticket: ref})
    assert gated.status(None, ticket)["state"] == "READY"
    assert gated.authorize_delivery(None, ticket) is True
    assert revoke_scope(root, confirmed=True)["status"] == "DELEGATION_DISABLED"
    assert gated.status(None, ticket)["state"] == "DELEGATION_REVOKED"
    assert gated.run(None, ticket)["state"] == "DELEGATION_REVOKED"
    assert gated.authorize_delivery(None, ticket) is False
    with pytest.raises(PermissionError, match="DELEGATION_REVOKED"):
        gated.deliver(None, ticket)
    assert existing.invocations == []
    assert scope_active(root, ref) is False
    assert delegated_record(root, repo, ticket) is None
    assert _enable(root, draft=True)["status"] == "DELEGATION_ENABLED"
    # A new owner authorization cannot resurrect tickets under the old grant.
    assert scope_active(root, ref) is False
    assert gated.run(None, ticket)["state"] == "DELEGATION_REVOKED"
    assert existing.invocations == []


def test_existing_autonomous_cycle_selects_only_authorized_scope_and_one_ticket(tmp_path):
    """Exercise real Work admission+cycle state, with no model or Guard effect."""
    from ai_foundation.development_requests import DevelopmentRequestPort
    from ai_foundation.durable_work import SQLiteWorkStore
    root, repo, ticket, instruction = _fixture(tmp_path)
    if os.getuid() != 501:
        pytest.skip("Owner scope issuance is deliberately M1 UID 501 only")
    principal = SimpleNamespace(principal_id="macos-owner-local")
    guard = object()
    class Pending:
        def __init__(self):
            self.guard = guard
        def authorize_list(self, principal):
            return True
        def list_tickets(self, principal, *, authorize_status):
            return {"ticket_count": 0, "tickets": []}
        def authorize(self, principal, ticket_id):
            return False

    class Admitted:
        def __init__(self):
            self.guard = guard
            self.calls = 0
        def authorize_list(self, principal):
            return True
        def list_tickets(self, principal, *, authorize_status):
            return {"ticket_count": 1,
                    "tickets": [self.status(principal, ticket)]}
        def authorize(self, principal, ticket_id):
            return ticket_id == ticket
        def status(self, principal, ticket_id):
            return {"ticket_id": ticket,
                    "state": "VERIFIED_LOCAL" if self.calls else "READY"}
        def run(self, principal, ticket_id):
            self.calls += 1
            return self.status(principal, ticket_id)

    admitted = Admitted()
    sink = SimpleNamespace(require=lambda _: None)
    expected_hash = sha256(instruction.encode()).hexdigest()
    port = DevelopmentRequestPort(
        Pending(), work=SQLiteWorkStore(root / "work.db"),
        principal_id=principal.principal_id, storage_admission=sink,
        admit_reviewed=lambda ident, digest: admitted if (
            ident == ticket and digest == expected_hash) else None,
        review_available=lambda ident: delegated_record(
            root, repo, ident, expected_instruction_sha256=expected_hash) is not None)
    author = lambda _: True
    before = port.cycle_one(principal, authorize_status=author, authorize_pending=author)
    assert before == {"state": "NO_ELIGIBLE_TICKET", "execution_started": False,
                      "authorized_examined": 1, "review_required": 1,
                      "blocked_state_counts": {
                          "review_required": 1, "failed_acceptance": 0,
                          "source_base_review": 0, "admission_refresh": 0,
                          "verified_local": 0, "other_terminal": 0},
                      "resume_only_after": "EXACT_REVIEW_OR_EXISTING_SCOPE_REQUIRED",
                      "retry_without_change": False,
                      "work_failed_count_inferred": False}
    assert admitted.calls == 0
    _enable(root, model="m1")
    result = port.cycle_one(principal, authorize_status=author, authorize_pending=author)
    assert result["state"] == "VERIFIED_LOCAL" and admitted.calls == 1
    after = port.cycle_one(principal, authorize_status=author, authorize_pending=author)
    assert after["state"] == "NO_ELIGIBLE_TICKET"
    assert admitted.calls == 1


def test_owner_ui_scope_requires_existing_csrf_origin_and_explicit_confirmation(tmp_path):
    root, repo, ticket, _ = _fixture(tmp_path)
    service = OwnerDevelopmentReview(root, repo_factory=lambda: repo)
    class Config:
        data_dir = str(root)
        work_db = "work.db"
    app = OperatorApplication(Config(), object(), csrf_token="scoped-token",
                              development_review=service)
    server = serve(app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    def request(path, form=None, **headers):
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
        client.request("GET" if form is None else "POST", path,
                       body=None if form is None else urlencode(form), headers=headers)
        response = client.getresponse()
        result = response.status, response.read().decode()
        client.close()
        return result
    try:
        status, page = request("/development/review")
        assert status == 503
        grant = {"csrf": "scoped-token", "model": "m1",
                 "allow_draft_delivery": "yes", "scope_confirmed": "yes"}
        assert request("/development/delegation/enable", grant, Origin="http://evil.invalid")[0] == 403
        assert request("/development/delegation/enable", {**grant, "csrf": "wrong"})[0] == 403
        assert request("/development/delegation/enable", {**grant, "scope_confirmed": "no"})[0] == 409
        assert load_scope(root) is None
        if os.getuid() == 501:
            assert request("/development/delegation/enable", grant)[0] == 200
            assert delegated_record(root, repo, ticket) is not None
            assert request("/development/delegation/revoke",
                           {"csrf": "scoped-token", "revoke_confirmed": "yes"})[0] == 200
            assert delegated_record(root, repo, ticket) is None
        else:
            assert request("/development/delegation/enable", grant)[0] == 409
    finally:
        server.shutdown()
        server.server_close()


def test_single_original_guard_scope_decision_and_no_reactivation(tmp_path, monkeypatch):
    from scripts.m1_development_scope_delegation import prepare_guard_scope, autonomous_scope
    from ai_foundation.store import SQLiteGuardStore, approval_request_ref
    root, repo, ticket, _ = _fixture(tmp_path)
    if os.getuid() != 501:
        pytest.skip("Owner scope issuance is deliberately M1 UID 501 only")
    store = SQLiteGuardStore(root / "guard.db")
    from ai_foundation.guard import GuardCore
    guard = GuardCore(store.runtime_state(), store=store)
    canon = {"status": "CANON_SOURCE_VERIFIED",
             "canon_revision": "canon-source/v1:" + "f"*64}
    def prepare():
        return prepare_guard_scope(root, repo, (ticket,), guard=guard,
            canon_observer=lambda: canon, storage=SimpleNamespace(require=lambda _: None))
    result = prepare()
    assert result["state"] == "SCOPE_APPROVAL_REQUIRED"
    assert load_scope(root) is None
    with store._connect() as db:
        row = db.execute("SELECT run_id,action,target,request_nonce,canon_revision,effect_id FROM approval_requests").fetchone()
    assert row[1] == "development_scope"
    assert prepare()["state"] == "SCOPE_APPROVAL_REQUIRED"
    assert not store.approve_pending(row[0], "0"*64)
    assert load_scope(root) is None
    assert store.approve_pending(row[0], approval_request_ref(*row))
    assert prepare()["state"] == "SCOPE_ACTIVATED"
    active = load_scope(root)
    assert active["model"] == "auto" and active["allow_draft_delivery"] is True
    assert autonomous_scope(root, guard=guard, canon=canon) is not None
    assert autonomous_scope(root, guard=guard, canon={**canon,
        "canon_revision":"canon-source/v1:"+"a"*64}) is None
    assert delegated_record(root, repo, ticket) is not None
    assert prepare() is None
    assert revoke_scope(root, confirmed=True)["status"] == "DELEGATION_DISABLED"
    assert prepare() is None
    assert not load_scope(root)["enabled"]
    assert autonomous_scope(root,guard=guard,canon=canon) is None
    # Filesystem loss after verified activation is not permission to replay.
    (root / "development" / "scope-delegation.json").unlink()
    assert prepare()["state"] == "SCOPE_EFFECT_NOT_VERIFIED"
    assert load_scope(root) is None


def test_autonomous_discovery_records_exact_work_once(tmp_path, monkeypatch):
    from ai_foundation.durable_work import SQLiteWorkStore
    from local9b_failure_candidates import discover_work_regression
    import local9b_failure_candidates as candidates
    from m1_development_review_candidate import snapshot
    root,repo,_,_=_fixture(tmp_path)
    # Exercise the actual macOS temporary-path alias failure mode on every
    # platform: realpath containment must compare two canonical paths.
    import tempfile
    actual=tmp_path/"temp-real"
    actual.mkdir()
    alias=tmp_path/"temp-alias"
    alias.symlink_to(actual,target_is_directory=True)
    create_temp=tempfile.TemporaryDirectory
    monkeypatch.setattr(tempfile,"TemporaryDirectory",
        lambda **kwargs:create_temp(dir=str(alias),**kwargs))
    base=_git(repo,"rev-parse","HEAD")
    work=SQLiteWorkStore(root/"work.db")
    storage=SimpleNamespace(require=lambda _:None)
    seen=[]
    class Fixed:
        def __init__(self,task,checkout,workspace):
            assert task["base_sha"]==base
        def run_tests(self,_):
            seen.append("fixed")
            raise RuntimeError("AssertionError\nFAILED tests/test_sample.py::test_unchanged\n1 failed")
    monkeypatch.setattr(candidates,"FixedPytest",Fixed)
    def submit(ticket,instruction):
        key=("mcp-development-request:"+sha256(b"macos-owner-local").hexdigest()+":"+ticket)
        work.request_development_review(key,json.dumps({"ticket_id":ticket,"instruction":instruction},
                                                 sort_keys=True,separators=(",",":")))
        return {"ticket_id":ticket,"instruction_sha256":sha256(instruction.encode()).hexdigest()}
    def discover(active):
        return discover_work_regression(repo,work,source_main=base,scope_current=lambda:active,
                                    storage=storage,submit=submit)
    assert discover(False) is None and not seen
    result=discover(True)
    assert result["state"]=="DISCOVERY_REQUEST_RECORDED",result
    ticket=result["ticket_id"]
    assert snapshot(root,repo,ticket)["base_sha"]==base
    assert discover(True) is None and seen==["fixed"]
    target=repo/"src/ai_foundation/sample.py"
    target.write_text("VALUE = 2\n")
    _git(repo,"add",".")
    _git(repo,"commit","-qm","changed source")
    with pytest.raises(ValueError,match="DISCOVERED_SOURCE_OR_TEST_MOVED"):
        snapshot(root,repo,ticket)


def test_scheduled_exact_owner_review_does_not_depend_on_broad_scope(tmp_path, monkeypatch):
    import sys
    from scripts import m1_owner_delegated_mcp_stdio as host
    import m1_development_ticket_factory as factory
    from types import SimpleNamespace
    root=tmp_path
    development=root/"development"
    development.mkdir()
    manifest=development/"tickets.json"
    manifest.write_text(json.dumps({"version":1, "tickets":[
        {"ticket_id":"exact", "source_origin":"owner-local-review-v1"},
        {"ticket_id":"delegated", "source_origin":"owner-scope-delegation-v1",
         "scope_ref":"a"*64}
    ]}))
    monkeypatch.setattr(factory, "_owner_manifest", lambda path:path.read_bytes())
    monkeypatch.setattr(factory, "_validate_ticket", lambda row:None)
    def check(ticket, ref, current):
        return host.scheduled_ticket_allowed(root, ticket, work_db="work.db",
                                              scope_ref=ref, scope_current=lambda:current)
    assert check("exact", None, False)
    assert not check("delegated", None, False)
    assert not check("delegated", "a"*64, False)
    assert check("delegated", "a"*64, True)
    assert not check("delegated", "b"*64, True)
    assert not check("unsigned", None, False)
