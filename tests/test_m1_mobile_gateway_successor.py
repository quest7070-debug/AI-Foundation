"""Single-source Gateway successor release acceptance, without real M1 effects."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_foundation.release_gate import ImmutableReleaseScope
from scripts import m1_mobile_gateway_successor as g

HEAD = "a" * 40
RUN = "release-existing-123"
REF = "c" * 64
CANON = "canon-source/v1:" + "d" * 64


def args(action, *, run=RUN, ref=REF):
    return SimpleNamespace(operation=action, expected_head=HEAD,
                           run_id=run if action == "apply" else None,
                           request_ref=ref if action == "apply" else None)


def scope():
    return ImmutableReleaseScope(
        path="m1-remote-gateway", source_sha=HEAD,
        previous_authority="launchd:remote:sha256:" + "e" * 64,
        previous_endpoint="https://127.0.0.1:8793",
        candidate_authority="github-commit:" + HEAD,
        candidate_endpoint="https://127.0.0.1:8793/mobile-owner",
        rollback_procedure="RESTORE_EXACT_PREVIOUS_GATEWAY_LAUNCHAGENT_AND_PID_READBACK",
        switch_target="dev.quest7070.ai-foundation.remote-gateway",
        readback_target="PID_BOUND_127.0.0.1_8793",
        rollback_readback_target="PRIOR_PLIST_AND_8793_HEALTH")


def context():
    return g.ReleaseContext(scope(), "f" * 64, Path("/tmp/inert.plist"),
                            b"old-plist", b"new-plist", 0o600,
                            Path("/tmp/inert-stage"))


def denied(*a, **kw):
    pytest.fail("unauthorized Guard or service effect")


def fake_guard(monkeypatch, *, approved=False):
    ctx = context()
    record = SimpleNamespace(
        status="PREPARED", release_scope_ref=ctx.scope.scope_ref,
        release_run_id=RUN, release_request_ref=REF,
        release_canon_revision=CANON)
    transitions = []
    gate = SimpleNamespace(
        registry=SimpleNamespace(
            get=lambda path: record,
            transition=lambda path, before, after:
                transitions.append((path, before, after))),
        verify=lambda *a: {"status": "APPROVED" if approved
                           else "OWNER_APPROVAL_REQUIRED",
                           "approved": approved, "scope_ref": ctx.scope.scope_ref})
    monkeypatch.setattr(g, "_gateway_gate", lambda *a, **kw: gate)
    monkeypatch.setattr(g.owner, "_release_canon", lambda path: {
        "status": "CANON_SOURCE_VERIFIED", "canon_revision": CANON})
    return transitions


def fake_context(monkeypatch):
    ctx = context()
    monkeypatch.setattr(g, "_context", lambda head, **kw: ctx)
    return ctx


def no_effects(monkeypatch):
    monkeypatch.setattr(g.gateway, "_backup", denied)
    monkeypatch.setattr(g.gateway, "_stop_and_start", denied)


def test_inspect_has_no_guard_or_service_effect(monkeypatch):
    fake_context(monkeypatch)
    no_effects(monkeypatch)
    monkeypatch.setattr(g, "_gateway_gate", denied)
    monkeypatch.setattr(g.owner, "_tty_confirm", denied)
    row = g.run(args("inspect"))
    assert row["status"] == "GATEWAY_SOURCE_OBSERVED_NO_EFFECT"
    assert row["release_permitted"] is False
    assert row["guard_writes"] == row["service_mutations"] == 0


def test_request_needs_real_owner_terminal_before_any_guard_write(monkeypatch):
    fake_context(monkeypatch)
    no_effects(monkeypatch)
    fake_guard(monkeypatch)
    monkeypatch.setattr(g.owner, "_tty_confirm", lambda *a: False)
    with pytest.raises(g.GatewaySuccessorDenied,
                       match="OWNER_TERMINAL_CONFIRMATION_REQUIRED"):
        g.run(args("request"))


def test_apply_unapproved_cannot_request_owner_or_switch(monkeypatch):
    fake_context(monkeypatch)
    no_effects(monkeypatch)
    fake_guard(monkeypatch, approved=False)
    monkeypatch.setattr(g.owner, "_tty_confirm", denied)
    with pytest.raises(g.GatewaySuccessorDenied,
                       match="EXACT_OWNER_GUARD_APPROVAL_REQUIRED"):
        g.run(args("apply"))


@pytest.mark.parametrize("run,ref", [
    ("stale", REF), (RUN, "9" * 64), ("", REF), (RUN, "")])
def test_apply_rejects_stale_run_and_request_refs(monkeypatch, run, ref):
    fake_context(monkeypatch)
    no_effects(monkeypatch)
    fake_guard(monkeypatch, approved=True)
    monkeypatch.setattr(g.owner, "_tty_confirm", denied)
    with pytest.raises(g.GatewaySuccessorDenied, match="EXACT_"):
        g.run(args("apply", run=run, ref=ref))


def test_approved_apply_still_requires_owner_tty(monkeypatch):
    fake_context(monkeypatch)
    no_effects(monkeypatch)
    fake_guard(monkeypatch, approved=True)
    monkeypatch.setattr(g.owner, "_tty_confirm", lambda *a: False)
    with pytest.raises(g.GatewaySuccessorDenied,
                       match="OWNER_TERMINAL_CONFIRMATION_REQUIRED"):
        g.run(args("apply"))


def test_gateway_request_apply_exact_prepared_scope_roundtrip(monkeypatch, tmp_path):
    """A real request creates PREPARED; only the SAME immutable scope can apply."""
    from types import SimpleNamespace
    from dataclasses import replace

    root = tmp_path / ".ai-foundation-tunnel-sources"
    source, previous = root / HEAD, root / ("b" * 40)
    source.mkdir(parents=True)
    previous.mkdir(parents=True)
    monkeypatch.setattr(g.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(g.owner, "_owner_session", lambda: None)
    monkeypatch.setattr(g.gateway, "_commit", lambda p: HEAD)
    monkeypatch.setattr(g.gateway, "_owned_plist", lambda: (
        tmp_path / "gateway.plist", b"old-plist",
        {"WorkingDirectory": str(previous)}, 0o600))
    monkeypatch.setattr(g.gateway, "_running", lambda: 51)
    monkeypatch.setattr(g.gateway, "_port_owned",
                        lambda pid, *, strict_local: pid == 51 and strict_local)
    monkeypatch.setattr(g.gateway, "_candidate_plist", lambda *_: b"new-plist")
    monkeypatch.setattr(g, "_gateway_transport_state",
                        lambda: "OPERATOR_UNAVAILABLE")
    # Construct the scope without accessing Guard state. This is the exact
    # scope that a preceding successful request would have persisted.
    approved_candidate = g._context(HEAD, observe_only=True)
    scope = approved_candidate.scope
    record = SimpleNamespace(
        status="PREPARED", release_scope=scope.as_dict(),
        release_scope_ref=scope.scope_ref)
    monkeypatch.setattr(g, "_gateway_gate", lambda *a, **kw:
                        SimpleNamespace(registry=SimpleNamespace(get=lambda p: record)))
    assert g._context(HEAD).scope.scope_ref == scope.scope_ref
    # An old/foreign PREPARED record is never accepted by partial SHA matching.
    record.release_scope = replace(
        scope, previous_authority="wrong-original").as_dict()
    record.release_scope_ref = g.ImmutableReleaseScope(
        **record.release_scope).scope_ref
    with pytest.raises(g.GatewaySuccessorDenied,
                       match="PENDING_GATEWAY_SCOPE_CHANGED"):
        g._context(HEAD)
    # No scope from a different source may be rebound under current request.
    record.release_scope = replace(
        scope, candidate_authority="github-commit:" + "f"*40).as_dict()
    record.release_scope_ref = g.ImmutableReleaseScope(
        **record.release_scope).scope_ref
    with pytest.raises(g.GatewaySuccessorDenied,
                       match="PENDING_GATEWAY_SCOPE_CHANGED"):
        g._context(HEAD)


def test_only_exact_gateway_tls_health_is_accepted(monkeypatch):
    class Response:
        def __init__(self, status, body):
            self.status, self.body = status, body
        def read(self, n):
            assert n == 129
            return self.body[:n]
    class TLS:
        response = None
        def __init__(self, host, port, *, timeout, context):
            assert (host, port, timeout) == ("127.0.0.1", g.gateway.PORT, 4)
        def request(self, method, path, *, headers):
            assert (method, path, headers) == (
                "GET", "/health", {"Host": "127.0.0.1"})
        def getresponse(self):
            return self.response
        def close(self):
            pass
    monkeypatch.setattr(g.ssl, "_create_unverified_context", lambda: object())
    monkeypatch.setattr(g.http.client, "HTTPSConnection", TLS)
    cases = [
        (503, b'{"ok":false,"upstream":false}', "OPERATOR_UNAVAILABLE"),
        (503, b'{"ok":false,"upstream":false}\n', "OPERATOR_UNAVAILABLE"),
        (503, b'{"ok":false,"upstream":false}\\n', "OPERATOR_UNAVAILABLE"),
        (200, b'{"ok":true,"upstream":true}', "OPERATOR_READY"),
        (200, b'{"ok":false,"upstream":false}', None),
        (503, b'{"ok":true,"upstream":false}', None),
        (401, b'{"ok":false,"upstream":false}', None),
        (503, b'x'*200, None)]
    for status, body, want in cases:
        TLS.response = Response(status, body)
        assert g._gateway_transport_state() == want


def test_readback_rejects_wrong_plist_before_touching_tls(monkeypatch, tmp_path):
    path = tmp_path / "gateway.plist"
    path.write_bytes(b"old")
    monkeypatch.setattr(g.gateway, "_running", lambda: 44)
    monkeypatch.setattr(g.gateway, "_port_owned",
                        lambda pid, *, strict_local: pid == 44 and strict_local)
    visits = []
    monkeypatch.setattr(g, "_gateway_transport_state",
                        lambda: visits.append("tls") or "OPERATOR_UNAVAILABLE")
    assert g._gateway_transport_readback(
        path, b"new", strict_local=True) is None
    assert visits == []
    assert g._gateway_transport_readback(
        path, b"old", strict_local=True) == "OPERATOR_UNAVAILABLE"


def _journal(monkeypatch, tmp_path, *, duplicate=False, corrupt=False, absent=False):
    primary = tmp_path / "operator-only-release-registry.json"
    primary.write_text(json.dumps({
        "schema": 2, "paths": {"m1-operator": {"status": "PREPARED"}}}))
    for n in range(4):
        (tmp_path / ("operator-owner-main-release-" + format(n+1, "020x")
                     + ".json")).write_text(json.dumps({
                         "schema": 2, "paths": {
                             "m1-operator": {"status": "PREPARED"}}}))
    obj = scope()
    row = {**obj.as_dict(), "status": "VERIFIED", "generation": 1,
           "release_scope": obj.as_dict(), "release_scope_ref": obj.scope_ref,
           "release_run_id": RUN, "release_request_ref": REF,
           "release_canon_revision": CANON}
    row["history"] = [dict(row)]
    if corrupt:
        row["history"][-1]["release_scope_ref"] = "9" * 64
    path = tmp_path / ("operator-owner-main-release-" + "a" * 20 + ".json")
    if not absent:
        path.write_text(json.dumps({
            "schema": 2, "paths": {"m1-remote-gateway": row}}))
    if duplicate:
        (tmp_path / ("operator-owner-main-release-" + "b"*20 + ".json")
         ).write_text(json.dumps({
             "schema": 2, "paths": {"m1-remote-gateway": row}}))
    guard = tmp_path / "real-guard.sqlite"
    monkeypatch.setattr(g.owner, "_guard_path", lambda home: (guard, primary))
    monkeypatch.setattr(g.owner, "_owner_file",
                        lambda p, *, limit: p.read_bytes())
    monkeypatch.setattr(g.owner, "ReadOnlyGuardStore",
                        lambda p: ("read", p))
    monkeypatch.setattr(g.owner, "SQLiteGuardStore",
                        lambda p: ("write", p))
    monkeypatch.setattr(g.owner, "GuardReleaseGate",
                        lambda store, p: SimpleNamespace(store=store, journal=p))
    return path, guard


def test_unique_gateway_journal_ignores_four_operator_prepared(monkeypatch, tmp_path):
    path, db = _journal(monkeypatch, tmp_path)
    ro = g._gateway_gate(tmp_path, readonly=True)
    rw = g._gateway_gate(tmp_path, readonly=False)
    assert ro.journal == rw.journal == path
    assert ro.store == ("read", db)
    assert rw.store == ("write", db)


@pytest.mark.parametrize("duplicate,corrupt,absent,error", [
    (True, False, False, "GATEWAY_LEDGER_NOT_UNIQUELY_BOUND"),
    (False, True, False, "GATEWAY_LEDGER_UNTRUSTED"),
    (False, False, True, "EXISTING_GATEWAY_LEDGER_NOT_FOUND")])
def test_corrupt_missing_and_duplicate_gateway_journals_fail_closed(
        monkeypatch, tmp_path, duplicate, corrupt, absent, error):
    _journal(monkeypatch, tmp_path, duplicate=duplicate,
             corrupt=corrupt, absent=absent)
    with pytest.raises(g.GatewaySuccessorDenied, match=error):
        g._gateway_gate(tmp_path, readonly=True)


def _apply_fixture(monkeypatch, tmp_path, *, readbacks):
    ctx = fake_context(monkeypatch)
    monkeypatch.setattr(g.Path, "home", lambda: tmp_path)
    transitions = fake_guard(monkeypatch, approved=True)
    monkeypatch.setattr(g.owner, "_tty_confirm", lambda *a: True)
    monkeypatch.setattr(g.gateway, "_owned_plist", lambda: (
        ctx.plist, ctx.previous_bytes, {}, ctx.previous_mode))
    monkeypatch.setattr(g.gateway, "_commit", lambda src: HEAD)
    monkeypatch.setattr(g, "_gateway_transport_state",
                        lambda: "OPERATOR_UNAVAILABLE")
    events = []
    monkeypatch.setattr(g.gateway, "_backup",
                        lambda *a: events.append("BACKUP"))
    monkeypatch.setattr(g.gateway, "_stop_and_start",
                        lambda path, content, mode:
                            events.append("NEW" if content == ctx.candidate_bytes
                                          else "OLD"))
    checks = iter(readbacks)
    monkeypatch.setattr(g, "_gateway_transport_readback",
                        lambda *a, **kw: next(checks))
    return events, transitions


def test_whole_authorized_gateway_cutover_does_not_require_operator_200(
        monkeypatch, tmp_path):
    events, transitions = _apply_fixture(
        monkeypatch, tmp_path, readbacks=["OPERATOR_UNAVAILABLE"])
    row = g.run(args("apply"))
    assert row["status"] == "VERIFIED"
    assert row["operator_upstream"] == "OPERATOR_UNAVAILABLE"
    assert row["mobile_owner_post"] == "NOT_VERIFIED"
    assert events == ["BACKUP", "NEW"]
    assert transitions == [
        ("m1-remote-gateway", "PREPARED", "CUTOVER"),
        ("m1-remote-gateway", "CUTOVER", "VERIFIED")]


def test_failed_new_gateway_rolls_back_complete_previous_plist(
        monkeypatch, tmp_path):
    events, transitions = _apply_fixture(
        monkeypatch, tmp_path, readbacks=[None, "OPERATOR_UNAVAILABLE"])
    with pytest.raises(g.GatewaySuccessorDenied,
                       match="NEW_GATEWAY_TRANSPORT_READBACK_FAILED"):
        g.run(args("apply"))
    assert events == ["BACKUP", "NEW", "OLD"]
    assert transitions == [
        ("m1-remote-gateway", "PREPARED", "CUTOVER"),
        ("m1-remote-gateway", "CUTOVER", "ROLLED_BACK")]


def test_unexpected_private_error_is_redacted(monkeypatch, capsys):
    def fail(*a, **kw):
        raise RuntimeError("owner/private/guard.sqlite")
    monkeypatch.setattr(g, "_context", fail)
    assert g.main(["inspect", "--expected-head", HEAD]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result == {"status": "BLOCKED",
                      "reason": "OWNER_GATEWAY_PREREQUISITE_UNVERIFIED"}
