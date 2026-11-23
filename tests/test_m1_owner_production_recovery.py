"""Cohesive Operator+Gateway recovery acceptance; NO real owner effect."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_foundation.release_gate import ImmutableReleaseScope
from scripts import m1_owner_production_recovery as r


HEAD = "a" * 40
RUN = "release-test-123"
REF = "b" * 64
CANON = "canon-source/v1:" + "c" * 64


def args(service="both", *, operator_run=RUN, operator_ref=REF,
         gateway_run=RUN, gateway_ref=REF):
    return argparse.Namespace(
        operation="apply", service=service, expected_head=HEAD,
        operator_run_id=operator_run, operator_request_ref=operator_ref,
        gateway_run_id=gateway_run, gateway_request_ref=gateway_ref)


def scope():
    return ImmutableReleaseScope(
        path="m1-operator", source_sha="d"*64,
        previous_authority="launchd:operator:sha256:" + "d"*64,
        previous_endpoint="http://127.0.0.1:8766",
        candidate_authority="github-commit:" + HEAD,
        candidate_endpoint="http://127.0.0.1:8766",
        rollback_procedure="RESTORE_EXACT_OPERATOR",
        switch_target="dev.quest7070.ai-foundation.operator",
        readback_target="PID_BOUND_8766",
        rollback_readback_target="PRIOR_OPERATOR")


def deny(*a, **k):
    pytest.fail("unapproved mutation or owner prompt")


def test_inspect_does_not_read_guard_or_operate_services(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda sha: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator", deny)
    monkeypatch.setattr(r, "_gateway_authorized", deny)
    monkeypatch.setattr(r, "_gateway_cutover", deny)
    monkeypatch.setattr(r, "_operator_cutover", deny)
    row = r.run(argparse.Namespace(
        operation="inspect", expected_head=HEAD, service="both"))
    assert row["status"] == "STAGED_SOURCE_OBSERVED_NO_EFFECT"
    assert row["release_permitted"] is False
    assert row["guard_writes"] == row["service_mutations"] == 0


def test_both_requires_two_independent_approvals_before_any_effect(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_authorized",
                        lambda *a: (_ for _ in ()).throw(
                            r.RecoveryDenied("EXACT_GATEWAY_RUN_REF_REQUIRED")))
    monkeypatch.setattr(r, "_gateway_cutover", deny)
    monkeypatch.setattr(r, "_operator_cutover", deny)
    with pytest.raises(r.RecoveryDenied, match="EXACT_GATEWAY_RUN_REF_REQUIRED"):
        r.run(args())


def test_operator_guard_failure_does_not_touch_gateway(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator",
                        lambda *a: (_ for _ in ()).throw(
                            r.RecoveryDenied("EXACT_OPERATOR_GUARD_APPROVAL_REQUIRED")))
    monkeypatch.setattr(r, "_gateway_authorized", deny)
    monkeypatch.setattr(r, "_gateway_cutover", deny)
    with pytest.raises(r.RecoveryDenied, match="EXACT_OPERATOR_GUARD"):
        r.run(args())


def test_dual_recovery_order_is_gateway_then_operator(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_authorized", lambda *a: object())
    effect = []

    def gateway(*a):
        effect.append("gateway")
        return {"gateway": "VERIFIED", "gateway_scope_ref": "g"*64,
                "gateway_upstream": "OPERATOR_UNAVAILABLE",
                "mobile_owner_post": "NOT_VERIFIED"}

    def operator(*a):
        effect.append("operator")
        return {"operator": "VERIFIED", "operator_scope_ref": "o"*64}

    def final_readback():
        effect.append("gateway-to-operator-readback")
        return "OPERATOR_READY"

    monkeypatch.setattr(r, "_gateway_cutover", gateway)
    monkeypatch.setattr(r, "_operator_cutover", operator)
    monkeypatch.setattr(r.mobile, "_gateway_transport_state", final_readback)
    result = r.run(args())

    assert effect == ["gateway", "operator", "gateway-to-operator-readback"]
    assert result["status"] == "GATEWAY_AND_OPERATOR_VERIFIED"
    assert result["gateway_upstream_at_cutover"] == "OPERATOR_UNAVAILABLE"
    assert result["gateway_upstream"] == "OPERATOR_READY"
    assert result["mobile_owner_post"] == "NOT_VERIFIED"


@pytest.mark.parametrize("final,expected", [
    ("OPERATOR_UNAVAILABLE", "OPERATOR_UNAVAILABLE"),
    (None, "UNVERIFIED"),
    ("unknown", "UNVERIFIED"),
])
def test_dual_recovery_refuses_to_green_unverified_final_upstream(
        monkeypatch, final, expected):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_authorized", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_cutover", lambda *a: {
        "gateway": "VERIFIED", "gateway_scope_ref": "g"*64,
        "gateway_upstream": "OPERATOR_UNAVAILABLE"})
    monkeypatch.setattr(r, "_operator_cutover", lambda *a: {
        "operator": "VERIFIED", "operator_scope_ref": "o"*64})
    monkeypatch.setattr(r.mobile, "_gateway_transport_state", lambda: final)

    result = r.run(args())
    assert result["gateway"] == result["operator"] == "VERIFIED"
    assert result["status"] == "GATEWAY_AND_OPERATOR_VERIFIED_UPSTREAM_UNVERIFIED"
    assert result["gateway_upstream_at_cutover"] == "OPERATOR_UNAVAILABLE"
    assert result["gateway_upstream"] == expected
    assert result["mobile_owner_post"] == "NOT_VERIFIED"


def test_dual_recovery_post_operator_transport_exception_fails_closed(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_authorized", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_cutover", lambda *a: {
        "gateway": "VERIFIED", "gateway_scope_ref": "g"*64,
        "gateway_upstream": "OPERATOR_UNAVAILABLE"})
    monkeypatch.setattr(r, "_operator_cutover", lambda *a: {
        "operator": "VERIFIED", "operator_scope_ref": "o"*64})

    def unavailable():
        raise OSError("upstream not ready")

    monkeypatch.setattr(r.mobile, "_gateway_transport_state", unavailable)
    result = r.run(args())
    assert result["status"] == "GATEWAY_AND_OPERATOR_VERIFIED_UPSTREAM_UNVERIFIED"
    assert result["gateway_upstream"] == "UNVERIFIED"


def test_gateway_only_keeps_its_independent_transport_receipt(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_gateway_authorized", lambda *a: object())
    monkeypatch.setattr(r, "_approved_operator", deny)
    monkeypatch.setattr(r, "_operator_cutover", deny)
    monkeypatch.setattr(r.mobile, "_gateway_transport_state", deny)
    monkeypatch.setattr(r, "_gateway_cutover", lambda *a: {
        "gateway": "VERIFIED", "gateway_scope_ref": "g"*64,
        "gateway_upstream": "OPERATOR_UNAVAILABLE"})
    result = r.run(args("gateway"))
    assert result["status"] == "GATEWAY_VERIFIED"
    assert result["gateway_upstream"] == "OPERATOR_UNAVAILABLE"
    assert "gateway_upstream_at_cutover" not in result


def test_verified_gateway_preserved_if_operator_release_fails(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_authorized", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_cutover", lambda *a: {
        "gateway": "VERIFIED", "gateway_scope_ref": "g"*64,
        "gateway_upstream": "OPERATOR_UNAVAILABLE"})
    monkeypatch.setattr(r.mobile, "_gateway_transport_state", deny)

    def failed(*a):
        raise r.OperatorHostDenied("OPERATOR_BOOTOUT_REJECTED")

    monkeypatch.setattr(r, "_operator_cutover", failed)
    result = r.run(args())
    assert result["status"] == "GATEWAY_VERIFIED_OPERATOR_UNVERIFIED"
    assert result["gateway"] == "VERIFIED"
    assert result["operator"] == "UNVERIFIED"


def test_operator_scope_keeps_distinct_commit_and_manifest_identities(monkeypatch):
    """Operator manifest digest is 64 hex; Git commit authority is 40 hex."""
    actual = scope()
    assert actual.source_sha != HEAD and len(actual.source_sha) == 64
    assert actual.candidate_authority == "github-commit:" + HEAD
    monkeypatch.setattr(r.cli, "_release_scope",
                        lambda source, head, home: actual)
    assert r._operator_scope(Path("/tmp/source"), HEAD,
                             Path("/tmp/owner")) == actual

    from dataclasses import replace
    forged_commit = replace(actual, candidate_authority="github-commit:"+"f"*40)
    monkeypatch.setattr(r.cli, "_release_scope",
                        lambda source, head, home: forged_commit)
    with pytest.raises(r.RecoveryDenied,
                       match="OPERATOR_SCOPE_NOT_SOURCE_BOUND"):
        r._operator_scope(Path("/tmp/source"), HEAD, Path("/tmp/owner"))

    missing_manifest = replace(actual, source_sha=HEAD)
    monkeypatch.setattr(r.cli, "_release_scope",
                        lambda source, head, home: missing_manifest)
    with pytest.raises(r.RecoveryDenied,
                       match="OPERATOR_SCOPE_NOT_SOURCE_BOUND"):
        r._operator_scope(Path("/tmp/source"), HEAD, Path("/tmp/owner"))


def test_no_effect_when_exact_run_refs_absent(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_gateway_authorized", deny)
    monkeypatch.setattr(r, "_operator_cutover", deny)
    with pytest.raises(r.RecoveryDenied, match="EXACT_OPERATOR_RUN_REF_REQUIRED"):
        r._approved_operator(HEAD, None, REF)


def _ledger(monkeypatch, tmp_path, *, duplicate=False, absent=False, broken=False):
    main = tmp_path / "operator-only-release-registry.json"
    main.write_text(json.dumps({"schema": 2, "paths": {}}))
    current_scope = scope()
    for n in range(4):
        row = {"path": "m1-operator", "status": "PREPARED",
               "candidate_authority": "github-commit:" + HEAD,
               "release_scope": current_scope.as_dict(),
               "release_scope_ref": current_scope.scope_ref,
               "release_run_id": "other-run-"+str(n),
               "release_request_ref": format(n+1, "064x"),
               "release_canon_revision": CANON}
        (tmp_path / ("operator-owner-main-release-" +
                     format(n+1, "020x") + ".json")
         ).write_text(json.dumps({"schema": 2, "paths": {"m1-operator": row}}))
    exact = {"path": "m1-operator", "status": "PREPARED",
             "candidate_authority": "github-commit:" + HEAD,
             "release_scope": current_scope.as_dict(),
             "release_scope_ref": current_scope.scope_ref,
             "release_run_id": RUN, "release_request_ref": REF,
             "release_canon_revision": CANON, "generation": 1}
    if broken:
        exact["release_scope"]["source_sha"] = "e"*40
    exact["history"] = [dict(exact)]
    target = tmp_path / ("operator-owner-main-release-"+"a"*20+".json")
    if not absent:
        target.write_text(json.dumps({"schema": 2, "paths": {
            "m1-operator": exact}}))
    if duplicate:
        (tmp_path / ("operator-owner-main-release-"+"b"*20+".json")
         ).write_text(json.dumps({"schema": 2, "paths": {
             "m1-operator": exact}}))
    db = tmp_path / "real-guard.sqlite"
    monkeypatch.setattr(r.cli, "_guard_path", lambda home: (db, main))
    monkeypatch.setattr(r.cli, "_owner_file", lambda path, *, limit:
                        path.read_bytes())
    monkeypatch.setattr(r.cli, "ReadOnlyGuardStore",
                        lambda path: ("ro", path))
    monkeypatch.setattr(r.cli, "SQLiteGuardStore",
                        lambda path: ("rw", path))
    monkeypatch.setattr(r.cli, "GuardReleaseGate",
                        lambda store, path: SimpleNamespace(
                            store=store, ledger=path))
    return current_scope, target, db


def test_exact_operator_journal_selected_amid_four_historical_prepared(
        monkeypatch, tmp_path):
    sc, target, db = _ledger(monkeypatch, tmp_path)
    ro = r._existing_operator_gate(tmp_path, sc, RUN, REF, readonly=True)
    rw = r._existing_operator_gate(tmp_path, sc, RUN, REF, readonly=False)
    assert ro.ledger == rw.ledger == target
    assert ro.store == ("ro", db)
    assert rw.store == ("rw", db)


@pytest.mark.parametrize("duplicate,absent,broken", [
    (True, False, False), (False, True, False), (False, False, True)])
def test_operator_journal_must_be_unique_existing_and_exact(
        monkeypatch, tmp_path, duplicate, absent, broken):
    sc, target, db = _ledger(
        monkeypatch, tmp_path, duplicate=duplicate, absent=absent,
        broken=broken)
    if broken:
        # A scope-corrupt matching row is rejected at the canonical gate.
        with pytest.raises(r.RecoveryDenied, match="OPERATOR_LEDGER_UNTRUSTED"):
            r._existing_operator_gate(tmp_path, sc, RUN, REF, readonly=True)
    else:
        with pytest.raises(r.RecoveryDenied, match="EXACT_OPERATOR_JOURNAL_NOT_UNIQUE"):
            r._existing_operator_gate(tmp_path, sc, RUN, REF, readonly=True)


def test_unresponsive_operator_switch_requires_trusted_old_source_and_pid(
        monkeypatch):
    host = object.__new__(r.UnresponsiveOperatorHost)
    sc = scope()
    host.candidate_definition = b"new"
    host.target = "gui/501/test"
    host.verify_candidate = lambda s: True
    host.current_scope_ref = lambda: sc.scope_ref
    host._human = lambda: None
    host._prior_physical_binding = lambda s: False
    host._launch = deny
    with pytest.raises(r.OperatorHostDenied, match="UNRESPONSIVE_PREDECESSOR_UNATTESTED"):
        host.switch_operator(sc)


def test_unresponsive_operator_switch_requires_owner_bound_physical_incumbent(
        monkeypatch):
    host = object.__new__(r.UnresponsiveOperatorHost)
    sc = scope()
    host.candidate_definition = b"new"
    host.target = "gui/501/test"
    host.verify_candidate = lambda s: True
    host.current_scope_ref = lambda: sc.scope_ref
    host._prior_physical_binding = lambda s: True
    host._human = lambda: None
    calls = []
    host._launch = lambda *a: calls.append(a) or SimpleNamespace(returncode=0)
    host._await_unregistered = lambda: True
    host._atomic_plist = lambda b: calls.append(("atomic",b))
    host._bootstrap_settled = lambda: calls.append(("bootstrap",))
    host.switch_operator(sc)
    assert calls == [
        ("bootout", "gui/501/test"), ("atomic", b"new"), ("bootstrap",)]


def test_healthy_busy_operator_still_refuses_replacement():
    host = object.__new__(r.UnresponsiveOperatorHost)
    sc = scope()
    host.verify_candidate = lambda s: True
    host.current_scope_ref = lambda: sc.scope_ref
    host._prior_physical_binding = lambda s: True
    host._human = lambda: {"activity":[{"task":"active"}]}
    host._launch = deny
    with pytest.raises(r.OperatorHostDenied, match="OPERATOR_BUSY"):
        host.switch_operator(sc)


def test_unexpected_guard_error_is_redacted(monkeypatch, capsys):
    monkeypatch.setattr(r, "_source",
                        lambda head: (_ for _ in ()).throw(
                            RuntimeError("/private/owner/secret.sqlite")))
    assert r.main(["inspect", "--expected-head", HEAD]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "BLOCKED",
                      "reason": "OWNER_PRODUCTION_RECOVERY_NOT_VERIFIED"}



def test_partial_gateway_recovery_is_nonzero_exit_code(monkeypatch, capsys):
    """Machine consumers cannot mistake a partial durable recovery for done."""
    monkeypatch.setattr(r, "run", lambda a: {
        "status": "GATEWAY_VERIFIED_OPERATOR_UNVERIFIED",
        "gateway": "VERIFIED", "operator": "UNVERIFIED",
        "mobile_owner_post": "NOT_VERIFIED"})
    exit_code = r.main(["apply", "--service", "both", "--expected-head", HEAD,
                        "--operator-run-id", RUN,
                        "--operator-request-ref", REF,
                        "--gateway-run-id", RUN,
                        "--gateway-request-ref", REF])
    assert exit_code == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "GATEWAY_VERIFIED_OPERATOR_UNVERIFIED"



def _operator_request_fixture(monkeypatch, tmp_path, *, owner_accepts):
    sc = scope()
    monkeypatch.setattr(r, "_source", lambda head: tmp_path)
    monkeypatch.setattr(r.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(r.cli, "_release_scope",
                        lambda source, head, home: sc)
    monkeypatch.setattr(r.cli, "_release_canon", lambda source: {
        "status": "CANON_SOURCE_VERIFIED", "canon_revision": CANON})
    monkeypatch.setattr(r, "_operator_predecessor",
                        lambda home, scope, source: (
                            tmp_path / "existing-guard.sqlite",
                            tmp_path / "original-operator-ledger.json",
                            "e" * 64))
    monkeypatch.setattr(r.cli, "_tty_confirm", lambda *a: owner_accepts)
    return sc


def test_operator_request_never_opens_guard_without_owner_confirmation(
        monkeypatch, tmp_path):
    _operator_request_fixture(monkeypatch, tmp_path, owner_accepts=False)
    monkeypatch.setattr(r.cli, "SQLiteGuardStore", deny)
    monkeypatch.setattr(r.cli, "GuardReleaseGate", deny)
    with pytest.raises(r.RecoveryDenied,
                       match="OWNER_TERMINAL_CONFIRMATION_REQUIRED"):
        r._operator_request(HEAD)


def test_operator_request_uses_original_verified_incumbent_and_guard(
        monkeypatch, tmp_path):
    sc = _operator_request_fixture(monkeypatch, tmp_path, owner_accepts=True)
    calls = []
    monkeypatch.setattr(r.cli, "SQLiteGuardStore",
                        lambda db: calls.append(("db", db)) or "original-db")
    class ExistingGate:
        def __init__(self, store, ledger):
            assert store == "original-db"
            assert ledger == tmp_path / "original-operator-ledger.json"
        def prepare(self, scope, *, canon_revision, verified_predecessor_ref):
            calls.append(("prepare", scope.scope_ref,
                          canon_revision, verified_predecessor_ref))
            return {"ok": True, "status": "WAITING_HUMAN",
                    "scope_ref": scope.scope_ref,
                    "run_id": RUN, "request_ref": REF}
    monkeypatch.setattr(r.cli, "GuardReleaseGate", ExistingGate)
    result = r._operator_request(HEAD)
    assert result["operator"] == "WAITING_HUMAN"
    assert result["operator_approved"] is False
    assert result["operator_run_id"] == RUN
    assert calls == [
        ("db", tmp_path / "existing-guard.sqlite"),
        ("prepare", sc.scope_ref, CANON, "e" * 64)]


def test_predecessor_accepts_only_one_loaded_verified_old_source(monkeypatch,
                                                                  tmp_path):
    sc = scope()
    old = {"path": "m1-operator", "status": "VERIFIED",
           "candidate_authority": "github-commit:" + "e" * 40,
           "candidate_endpoint": sc.previous_endpoint,
           "release_scope_ref": "f" * 64}
    more = {**old, "release_scope_ref": "1" * 64}
    gate = tmp_path / "original-guard.sqlite"
    monkeypatch.setattr(r, "_operator_rows",
                        lambda home: (gate, [
                            (tmp_path / "one.json",old,2),
                            (tmp_path / "other.json",
                             {"status": "PREPARED"},2)]))
    class Host:
        def __init__(self, source, *, home):
            pass
        def diagnose_current_release(self, prior):
            return ("RUNNING_OPERATOR_API_UNAVAILABLE"
                    if prior.release_scope_ref == old["release_scope_ref"]
                    else "RUNNING_PID_NOT_BOUND")
    monkeypatch.setattr(r, "UnresponsiveOperatorHost", Host)
    assert r._operator_predecessor(tmp_path, sc, tmp_path) == (
        gate, tmp_path / "one.json", "f" * 64)
    monkeypatch.setattr(r, "_operator_rows",
                        lambda home: (gate, [
                            (tmp_path / "one.json",old,2),
                            (tmp_path / "two.json",more,2)]))
    monkeypatch.setattr(Host, "diagnose_current_release",
                        lambda self, prior: "RUNNING_OPERATOR_API_UNAVAILABLE")
    with pytest.raises(r.RecoveryDenied,
                       match="VERIFIED_OPERATOR_PREDECESSOR_NOT_UNIQUE"):
        r._operator_predecessor(tmp_path, sc, tmp_path)


def test_request_for_two_services_retains_real_operator_pending_on_gateway_error(
        monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_operator_request", lambda head: {
        "operator": "WAITING_HUMAN", "operator_run_id": RUN,
        "operator_request_ref": REF})
    monkeypatch.setattr(r, "_gateway_request",
                        lambda head: (_ for _ in ()).throw(
                            r.RecoveryDenied("GATEWAY_GUARD_REQUEST_NOT_ACCEPTED")))
    row = r.run(argparse.Namespace(
        operation="request", service="both", expected_head=HEAD,
        operator_run_id=None, operator_request_ref=None,
        gateway_run_id=None, gateway_request_ref=None))
    assert row["status"] == "OPERATOR_REQUESTED_GATEWAY_UNVERIFIED"
    assert row["operator"] == "WAITING_HUMAN"
    assert row["gateway"] == "UNVERIFIED"


def test_request_cannot_reuse_old_guard_grants(monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_operator_request", deny)
    with pytest.raises(r.RecoveryDenied,
                       match="REQUEST_CANNOT_REUSE_GUARD_APPROVAL"):
        r.run(argparse.Namespace(
            operation="request", service="operator", expected_head=HEAD,
            operator_run_id=RUN, operator_request_ref=REF,
            gateway_run_id=None, gateway_request_ref=None))



def _owner_decision_fixture(monkeypatch, tmp_path, *, approved_tty=True):
    """All authority is mocked; no test performs any real Guard or service write."""
    monkeypatch.setattr(r, "_source", lambda head: tmp_path / "source")
    monkeypatch.setattr(r.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(r.cli, "_guard_path",
                        lambda home: (tmp_path / "original-guard.sqlite",
                                      tmp_path / "original-ledger.json"))
    scopes = {
        "operator": SimpleNamespace(scope_ref="1"*64),
        "gateway": SimpleNamespace(scope_ref="2"*64),
    }
    calls = []
    def pending(head, service, run, ref, source, home):
        calls.append(("preflight",service))
        s = scopes[service]
        gate = SimpleNamespace(verify=lambda scope, run_id, request_ref: {
            "status": "APPROVED", "approved": True, "ok": True,
            "scope_ref": s.scope_ref})
        return (service, s, run, ref, gate)
    monkeypatch.setattr(r, "_exact_pending_for_owner", pending)
    prompts = []
    def consent(text, phrase):
        prompts.append(phrase)
        return approved_tty if isinstance(approved_tty, bool) else (
            len(prompts) == 1)
    monkeypatch.setattr(r.cli, "_tty_confirm", consent)
    return calls, prompts, scopes


def test_owner_guard_approve_two_explicit_tty_decisions_then_existing_action(
        monkeypatch, tmp_path):
    calls, prompts, scopes = _owner_decision_fixture(monkeypatch, tmp_path)
    class Store:
        def runtime_state(self):
            return {}
    monkeypatch.setattr(r.cli, "SQLiteGuardStore", lambda path: Store())
    monkeypatch.setattr(r, "GuardCore", lambda *a, **kw: object())
    class Actions:
        def __init__(self, guard):
            assert guard is not None
        def approve_pending(self, run_id, request_ref):
            calls.append(("guard_approve", run_id, request_ref))
            return SimpleNamespace(ok=True, status="APPROVED")
    monkeypatch.setattr(r, "OperatorActions", Actions)
    result = r._owner_guard_decisions(HEAD, "both", args())
    assert result["status"] == "GUARD_APPROVED"
    assert result["operator"] == result["gateway"] == "APPROVED"
    assert result["service_mutations"] == 0
    assert calls == [
        ("preflight","operator"), ("preflight","gateway"),
        ("guard_approve", RUN, REF), ("guard_approve", RUN, REF)]
    assert prompts == [
        "AUTHORIZE " + scopes["operator"].scope_ref[:16],
        "AUTHORIZE " + scopes["gateway"].scope_ref[:16]]


def test_owner_guard_approve_tty_refusal_has_zero_writes(monkeypatch, tmp_path):
    calls, prompts, scopes = _owner_decision_fixture(
        monkeypatch, tmp_path, approved_tty="first-only")
    monkeypatch.setattr(r.cli, "SQLiteGuardStore", deny)
    monkeypatch.setattr(r, "OperatorActions", deny)
    with pytest.raises(r.RecoveryDenied,
                       match="OWNER_TERMINAL_CONFIRMATION_REQUIRED"):
        r._owner_guard_decisions(HEAD, "both", args())
    assert calls == [("preflight","operator"), ("preflight","gateway")]
    assert len(prompts) == 2


def test_owner_guard_approve_rejects_pending_mismatch_before_any_tty(
        monkeypatch, tmp_path):
    calls, prompts, scopes = _owner_decision_fixture(monkeypatch, tmp_path)
    def refuse(head, service, run, ref, source, home):
        raise r.RecoveryDenied("EXACT_PENDING_OWNER_RELEASE_REQUIRED")
    monkeypatch.setattr(r, "_exact_pending_for_owner", refuse)
    monkeypatch.setattr(r.cli, "SQLiteGuardStore", deny)
    with pytest.raises(r.RecoveryDenied,
                       match="EXACT_PENDING_OWNER_RELEASE_REQUIRED"):
        r._owner_guard_decisions(HEAD, "both", args())
    assert prompts == []



def recovery_args():
    """New owner command has no recycled Guard refs."""
    return args(operator_run=None, operator_ref=None,
                gateway_run=None, gateway_ref=None)


def _recover_receipt():
    return {
        "status": "WAITING_HUMAN", "source_sha": HEAD,
        "operator": "WAITING_HUMAN", "operator_approved": False,
        "operator_run_id": RUN, "operator_request_ref": REF,
        "operator_scope_ref": "c"*64,
        "gateway": "WAITING_HUMAN", "gateway_approved": False,
        "gateway_run_id": "release-other-456",
        "gateway_request_ref": "d"*64,
        "gateway_scope_ref": "e"*64,
        "service_mutations": 0,
    }


def test_one_owner_command_compares_both_original_guard_receipts_before_apply(
        monkeypatch):
    calls = []

    def exact(state):
        calls.append(state)
        if state.operation == "request":
            assert state.operator_run_id is None
            assert state.gateway_run_id is None
            return _recover_receipt()
        assert state.operator_run_id == RUN
        assert state.operator_request_ref == REF
        assert state.gateway_run_id == "release-other-456"
        assert state.gateway_request_ref == "d"*64
        if state.operation == "approve":
            return {"status": "GUARD_APPROVED", "source_sha": HEAD,
                    "operator": "APPROVED", "gateway": "APPROVED",
                    "service_mutations": 0}
        if state.operation == "apply":
            return {"status": "GATEWAY_AND_OPERATOR_VERIFIED",
                    "source_sha": HEAD, "operator": "VERIFIED",
                    "gateway": "VERIFIED", "gateway_upstream": "OPERATOR_READY",
                    "mobile_owner_post": "NOT_VERIFIED"}
        pytest.fail("unrecognized recovery stage")

    monkeypatch.setattr(r, "run", exact)
    result = r.recover_once(recovery_args())
    assert result["status"] == "GATEWAY_AND_OPERATOR_VERIFIED"
    assert result["gateway_upstream"] == "OPERATOR_READY"
    assert result["mobile_owner_post"] == "NOT_VERIFIED"
    assert [stage.operation for stage in calls] == [
        "request", "approve", "apply"]


@pytest.mark.parametrize("post_upstream", [
    None, "UNVERIFIED", "OPERATOR_UNAVAILABLE"])
def test_one_owner_command_rejects_missing_final_upstream(
        monkeypatch, post_upstream):
    calls = []

    def exact(state):
        calls.append(state.operation)
        if state.operation == "request":
            return _recover_receipt()
        if state.operation == "approve":
            return {"status": "GUARD_APPROVED", "source_sha": HEAD,
                    "operator": "APPROVED", "gateway": "APPROVED",
                    "service_mutations": 0}
        if state.operation == "apply":
            return {"status": "GATEWAY_AND_OPERATOR_VERIFIED",
                    "source_sha": HEAD, "operator": "VERIFIED",
                    "gateway": "VERIFIED", "gateway_upstream": post_upstream,
                    "mobile_owner_post": "NOT_VERIFIED"}
        pytest.fail("unrecognized recovery stage")

    monkeypatch.setattr(r, "run", exact)
    result = r.recover_once(recovery_args())
    assert result["status"] == "RECOVERY_NOT_FULLY_VERIFIED"
    assert calls == ["request", "approve", "apply"]


def test_one_owner_command_partial_request_is_never_approved_or_applied(
        monkeypatch):
    calls = []
    def partial(state):
        calls.append(state.operation)
        if len(calls) != 1:
            pytest.fail("partial request must stop before Guard approval")
        return {**_recover_receipt(),
                "status": "OPERATOR_REQUESTED_GATEWAY_UNVERIFIED",
                "gateway": "UNVERIFIED"}
    monkeypatch.setattr(r, "run", partial)
    result = r.recover_once(recovery_args())
    assert result["status"] == "RECOVERY_REQUEST_INCOMPLETE"
    assert calls == ["request"]


@pytest.mark.parametrize("corrupt", [
    ("operator_run_id", "bad;command"),
    ("gateway_request_ref", "f"*40),
    ("gateway_scope_ref", "bad-scope"),
    ("gateway_scope_ref", "c"*64),
    ("source_sha", "f"*40),
])
def test_one_owner_command_rejects_foreign_or_incomplete_scope_receipt_before_guard(
        monkeypatch, corrupt):
    calls = []
    def source(state):
        calls.append(state.operation)
        if len(calls) != 1:
            pytest.fail("invalid exact original receipt reached Guard")
        return {**_recover_receipt(), corrupt[0]: corrupt[1]}
    monkeypatch.setattr(r, "run", source)
    result = r.recover_once(recovery_args())
    assert result["status"] in {
        "RECOVERY_REQUEST_INCOMPLETE", "RECOVERY_REQUEST_REF_UNVERIFIED",
        "RECOVERY_SCOPE_COLLISION"}
    assert calls == ["request"]


def test_one_owner_command_partial_guard_approval_never_reaches_cutover(
        monkeypatch):
    calls = []
    def staged(state):
        calls.append(state.operation)
        if state.operation == "request":
            return _recover_receipt()
        if state.operation == "approve":
            return {"status": "GUARD_PARTIAL_APPROVAL",
                    "operator": "APPROVED", "gateway": "UNVERIFIED",
                    "source_sha": HEAD, "service_mutations": 0}
        pytest.fail("partial Guard approval cannot reach apply")
    monkeypatch.setattr(r, "run", staged)
    result = r.recover_once(recovery_args())
    assert result["status"] == "RECOVERY_APPROVAL_INCOMPLETE"
    assert calls == ["request", "approve"]


def test_one_owner_command_rejects_reused_guard_refs_before_any_execution(
        monkeypatch):
    monkeypatch.setattr(r, "run", deny)
    with pytest.raises(r.RecoveryDenied, match="RECOVERY_CANNOT_REUSE_OLD_REQUESTS"):
        r.recover_once(args(operator_ref=REF))
    with pytest.raises(r.RecoveryDenied, match="RECOVERY_CANNOT_REUSE_OLD_REQUESTS"):
        r.recover_once(args(service="operator", operator_ref=REF))


def _operator_only_request():
    return {
        "status": "WAITING_HUMAN", "source_sha": HEAD,
        "operator": "WAITING_HUMAN", "operator_approved": False,
        "operator_run_id": RUN, "operator_request_ref": REF,
        "operator_scope_ref": "c"*64, "gateway": "NOT_REQUESTED",
        "service_mutations": 0,
    }


def _operator_recovery_args():
    return args(service="operator", operator_run=None, operator_ref=None,
                gateway_run=None, gateway_ref=None)


def test_operator_one_shot_keeps_gateway_unchanged_and_requires_exact_guard(
        monkeypatch, capsys):
    calls = []
    def stage(state):
        calls.append(state.operation)
        assert state.service == "operator"
        assert state.gateway_run_id is None
        assert state.gateway_request_ref is None
        if state.operation == "request":
            assert state.operator_run_id is None
            assert state.operator_request_ref is None
            return _operator_only_request()
        assert state.operator_run_id == RUN
        assert state.operator_request_ref == REF
        if state.operation == "approve":
            return {"status": "GUARD_APPROVED", "source_sha": HEAD,
                    "operator": "APPROVED", "gateway": "NOT_REQUESTED",
                    "service_mutations": 0}
        assert state.operation == "apply"
        return {"status": "OPERATOR_VERIFIED", "source_sha": HEAD,
                "operator": "VERIFIED", "gateway": "NOT_REQUESTED",
                "gateway_upstream": "OPERATOR_READY",
                "mobile_owner_post": "NOT_VERIFIED"}
    monkeypatch.setattr(r, "run", stage)
    code = r.main(["recover", "--service", "operator",
                   "--expected-head", HEAD])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "OPERATOR_VERIFIED"
    assert result["gateway"] == "NOT_REQUESTED"
    assert result["mobile_owner_post"] == "NOT_VERIFIED"
    assert calls == ["request", "approve", "apply"]


@pytest.mark.parametrize("field,bad", [
    ("source_sha", "f"*40),
    ("operator", "NOT_REQUESTED"),
    ("operator_approved", True),
    ("operator_run_id", "untrusted;command"),
    ("operator_request_ref", "b"*40),
    ("operator_scope_ref", "not-a-scope"),
    ("gateway", "WAITING_HUMAN"),
])
def test_operator_one_shot_rejects_bad_request_before_guard_writes(
        monkeypatch, field, bad):
    calls = []
    def stage(state):
        calls.append(state.operation)
        if len(calls) > 1:
            pytest.fail("No approval after a malformed fresh request")
        return {**_operator_only_request(), field: bad}
    monkeypatch.setattr(r, "run", stage)
    result = r.recover_once(_operator_recovery_args())
    assert result["status"] in {
        "RECOVERY_REQUEST_INCOMPLETE", "RECOVERY_REQUEST_REF_UNVERIFIED"}
    assert calls == ["request"]


def test_operator_one_shot_stops_on_partial_guard_authorization(monkeypatch):
    calls = []
    def stage(state):
        calls.append(state.operation)
        if state.operation == "request":
            return _operator_only_request()
        if state.operation == "approve":
            return {"status": "GUARD_PARTIAL_APPROVAL", "source_sha": HEAD,
                    "operator": "UNVERIFIED", "gateway": "NOT_REQUESTED",
                    "service_mutations": 0}
        pytest.fail("No Operator effect until exact approval")
    monkeypatch.setattr(r, "run", stage)
    result = r.recover_once(_operator_recovery_args())
    assert result["status"] == "RECOVERY_APPROVAL_INCOMPLETE"
    assert calls == ["request", "approve"]


@pytest.mark.parametrize("field,bad", [
    ("status", "OPERATOR_VERIFIED_GATEWAY_UPSTREAM_UNVERIFIED"),
    ("source_sha", "f"*40),
    ("operator", "UNVERIFIED"),
    ("gateway", "VERIFIED"),
    ("gateway_upstream", "OPERATOR_UNAVAILABLE"),
    ("gateway_upstream", None),
    ("mobile_owner_post", "OWNER_POST_TRANSPORT_VERIFIED"),
])
def test_operator_one_shot_cannot_green_partial_final_readback(
        monkeypatch, capsys, field, bad):
    calls = []
    def stage(state):
        calls.append(state.operation)
        if state.operation == "request":
            return _operator_only_request()
        if state.operation == "approve":
            return {"status": "GUARD_APPROVED", "source_sha": HEAD,
                    "operator": "APPROVED", "gateway": "NOT_REQUESTED",
                    "service_mutations": 0}
        return {**{
            "status": "OPERATOR_VERIFIED", "source_sha": HEAD,
            "operator": "VERIFIED", "gateway": "NOT_REQUESTED",
            "gateway_upstream": "OPERATOR_READY",
            "mobile_owner_post": "NOT_VERIFIED"}, field: bad}
    monkeypatch.setattr(r, "run", stage)
    code = r.main(["recover", "--service", "operator",
                   "--expected-head", HEAD])
    assert code == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "RECOVERY_NOT_FULLY_VERIFIED"
    assert calls == ["request", "approve", "apply"]


def test_operator_only_existing_guard_and_fresh_gateway_readback_no_gateway_restart(
        monkeypatch):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_authorized", deny)
    monkeypatch.setattr(r, "_gateway_cutover", deny)
    events = []
    monkeypatch.setattr(r, "_operator_cutover", lambda *a: (
        events.append("operator"),
        {"operator": "VERIFIED", "operator_scope_ref": "a"*64})[1])
    monkeypatch.setattr(r.mobile, "_gateway_transport_state", lambda: (
        events.append("gateway-readonly"), "OPERATOR_READY")[1])
    result = r.run(args(service="operator", gateway_run=None,
                        gateway_ref=None))
    assert result["status"] == "OPERATOR_VERIFIED"
    assert result["gateway"] == "NOT_REQUESTED"
    assert result["gateway_upstream"] == "OPERATOR_READY"
    assert events == ["operator", "gateway-readonly"]


@pytest.mark.parametrize("status", [None, "UNVERIFIED", "OPERATOR_UNAVAILABLE"])
def test_operator_only_post_cutover_upstream_must_be_ready(
        monkeypatch, status):
    monkeypatch.setattr(r, "_source", lambda head: Path("/tmp/staged"))
    monkeypatch.setattr(r, "_approved_operator", lambda *a: object())
    monkeypatch.setattr(r, "_gateway_authorized", deny)
    monkeypatch.setattr(r, "_gateway_cutover", deny)
    monkeypatch.setattr(r, "_operator_cutover",
                        lambda *a: {"operator": "VERIFIED"})
    monkeypatch.setattr(r.mobile, "_gateway_transport_state", lambda: status)
    receipt = r.run(args(service="operator", gateway_run=None,
                         gateway_ref=None))
    assert receipt["status"] == "OPERATOR_VERIFIED_GATEWAY_UPSTREAM_UNVERIFIED"
    assert receipt["gateway"] == "NOT_REQUESTED"
    assert receipt["mobile_owner_post"] == "NOT_VERIFIED"



def _gateway_only_request():
    return {
        "status": "WAITING_HUMAN", "source_sha": HEAD,
        "operator": "NOT_REQUESTED", "gateway": "WAITING_HUMAN",
        "gateway_approved": False, "gateway_run_id": RUN,
        "gateway_request_ref": REF, "gateway_scope_ref": "e"*64,
        "service_mutations": 0,
    }


def _gateway_recovery_args():
    return args(service="gateway", operator_run=None, operator_ref=None,
                gateway_run=None, gateway_ref=None)


def test_gateway_one_owner_command_is_exact_three_gate_release_and_operator_untouched(
        monkeypatch, capsys):
    calls = []

    def exact(state):
        calls.append((state.operation, state.operator_run_id,
                      state.gateway_run_id))
        assert state.service == "gateway"
        assert state.expected_head == HEAD
        assert state.operator_run_id is None
        assert state.operator_request_ref is None
        if state.operation == "request":
            assert state.gateway_run_id is None
            assert state.gateway_request_ref is None
            return _gateway_only_request()
        assert state.gateway_run_id == RUN
        assert state.gateway_request_ref == REF
        if state.operation == "approve":
            return {"status": "GUARD_APPROVED", "source_sha": HEAD,
                    "operator": "NOT_REQUESTED", "gateway": "APPROVED",
                    "service_mutations": 0}
        assert state.operation == "apply"
        return {"status": "GATEWAY_VERIFIED", "source_sha": HEAD,
                "operator": "NOT_REQUESTED", "gateway": "VERIFIED",
                "gateway_upstream": "OPERATOR_READY",
                "mobile_owner_post": "NOT_VERIFIED"}

    monkeypatch.setattr(r, "run", exact)
    code = r.main(["recover", "--service", "gateway",
                   "--expected-head", HEAD])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "GATEWAY_VERIFIED"
    assert result["operator"] == "NOT_REQUESTED"
    assert result["mobile_owner_post"] == "NOT_VERIFIED"
    assert [item[0] for item in calls] == ["request", "approve", "apply"]


@pytest.mark.parametrize("corrupt", [
    ("status", "OPERATOR_REQUESTED_GATEWAY_UNVERIFIED"),
    ("source_sha", "f"*40),
    ("operator", "WAITING_HUMAN"),
    ("gateway_approved", True),
    ("gateway_scope_ref", "bad"),
    ("gateway_run_id", "old;command"),
    ("gateway_request_ref", "a"*40),
])
def test_gateway_one_owner_command_fails_before_approval_on_bad_fresh_receipt(
        monkeypatch, corrupt):
    calls = []
    def exact(state):
        calls.append(state.operation)
        if len(calls) > 1:
            pytest.fail("bad request must never reach Guard decision or apply")
        return {**_gateway_only_request(), corrupt[0]: corrupt[1]}
    monkeypatch.setattr(r, "run", exact)
    result = r.recover_once(_gateway_recovery_args())
    assert result["status"] in {
        "RECOVERY_REQUEST_INCOMPLETE", "RECOVERY_REQUEST_REF_UNVERIFIED"}
    assert calls == ["request"]


def test_gateway_one_owner_command_partial_approval_stops_before_apply(
        monkeypatch):
    calls = []
    def exact(state):
        calls.append(state.operation)
        if state.operation == "request":
            return _gateway_only_request()
        if state.operation == "approve":
            return {"status": "GUARD_PARTIAL_APPROVAL", "source_sha": HEAD,
                    "operator": "NOT_REQUESTED", "gateway": "UNVERIFIED",
                    "service_mutations": 0}
        pytest.fail("approval not current; service must stay unchanged")
    monkeypatch.setattr(r, "run", exact)
    result = r.recover_once(_gateway_recovery_args())
    assert result["status"] == "RECOVERY_APPROVAL_INCOMPLETE"
    assert calls == ["request", "approve"]


@pytest.mark.parametrize("condition", [
    ("status", "GATEWAY_CUTOVER_UNVERIFIED"),
    ("gateway", "UNVERIFIED"),
    ("operator", "VERIFIED"),
    ("gateway_upstream", "OPERATOR_UNAVAILABLE"),
    ("gateway_upstream", None),
    ("source_sha", "0"*40),
    ("mobile_owner_post", "OWNER_POST_TRANSPORT_VERIFIED"),
])
def test_gateway_one_owner_command_partial_readback_never_exits_green(
        monkeypatch, capsys, condition):
    calls = []
    def exact(state):
        calls.append(state.operation)
        if state.operation == "request":
            return _gateway_only_request()
        if state.operation == "approve":
            return {"status": "GUARD_APPROVED", "source_sha": HEAD,
                    "operator": "NOT_REQUESTED", "gateway": "APPROVED",
                    "service_mutations": 0}
        if state.operation == "apply":
            return {**{"status": "GATEWAY_VERIFIED", "source_sha": HEAD,
                       "operator": "NOT_REQUESTED", "gateway": "VERIFIED",
                       "gateway_upstream": "OPERATOR_READY",
                       "mobile_owner_post": "NOT_VERIFIED"},
                    condition[0]: condition[1]}
        pytest.fail("unknown recovery step")
    monkeypatch.setattr(r, "run", exact)
    code = r.main(["recover", "--service", "gateway",
                   "--expected-head", HEAD])
    assert code == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "RECOVERY_NOT_FULLY_VERIFIED"
    assert calls == ["request", "approve", "apply"]


def test_one_owner_command_partial_apply_must_be_nonzero_and_never_claims_post(
        monkeypatch, capsys):
    def staged(state):
        if state.operation == "request":
            return _recover_receipt()
        if state.operation == "approve":
            return {"status": "GUARD_APPROVED", "source_sha": HEAD,
                    "operator": "APPROVED", "gateway": "APPROVED",
                    "service_mutations": 0}
        return {"status": "GATEWAY_VERIFIED_OPERATOR_UNVERIFIED",
                "source_sha": HEAD, "operator": "UNVERIFIED",
                "gateway": "VERIFIED", "mobile_owner_post": "NOT_VERIFIED"}

    monkeypatch.setattr(r, "run", staged)
    code = r.main(["recover", "--service", "both", "--expected-head", HEAD])
    assert code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "RECOVERY_NOT_FULLY_VERIFIED"
    assert output["mobile_owner_post"] == "NOT_VERIFIED"


@pytest.mark.parametrize("upstream", [
    "OPERATOR_UNAVAILABLE", "UNVERIFIED", None])
def test_cli_dual_cutover_never_exits_zero_without_post_operator_readback(
        monkeypatch, capsys, upstream):
    monkeypatch.setattr(r, "run", lambda state: {
        "status": "GATEWAY_AND_OPERATOR_VERIFIED",
        "source_sha": HEAD, "gateway": "VERIFIED",
        "operator": "VERIFIED", "gateway_upstream": upstream,
        "mobile_owner_post": "NOT_VERIFIED"})
    code = r.main(["apply", "--service", "both", "--expected-head", HEAD])
    assert code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["gateway_upstream"] == upstream


def test_cli_dual_cutover_returns_zero_only_with_final_upstream(
        monkeypatch, capsys):
    monkeypatch.setattr(r, "run", lambda state: {
        "status": "GATEWAY_AND_OPERATOR_VERIFIED",
        "source_sha": HEAD, "gateway": "VERIFIED",
        "operator": "VERIFIED", "gateway_upstream": "OPERATOR_READY",
        "mobile_owner_post": "NOT_VERIFIED"})
    code = r.main(["apply", "--service", "both", "--expected-head", HEAD])
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["gateway_upstream"] == "OPERATOR_READY"
    assert output["mobile_owner_post"] == "NOT_VERIFIED"


def test_cli_combined_upstream_failure_status_is_nonzero(
        monkeypatch, capsys):
    monkeypatch.setattr(r, "run", lambda state: {
        "status": "GATEWAY_AND_OPERATOR_VERIFIED_UPSTREAM_UNVERIFIED",
        "source_sha": HEAD, "gateway": "VERIFIED",
        "operator": "VERIFIED", "gateway_upstream": "OPERATOR_UNAVAILABLE",
        "mobile_owner_post": "NOT_VERIFIED"})
    code = r.main(["apply", "--service", "both", "--expected-head", HEAD])
    assert code == 3
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "GATEWAY_AND_OPERATOR_VERIFIED_UPSTREAM_UNVERIFIED"
