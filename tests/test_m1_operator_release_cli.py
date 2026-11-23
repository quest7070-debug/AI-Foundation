"""No live Guard, macOS service, or owner identity in these CLI regressions."""
from types import SimpleNamespace

import pytest

from scripts import m1_operator_release_cli as cli


SCOPE = SimpleNamespace(
    path="m1-operator",
    scope_ref="a" * 64,
    candidate_authority="github-commit:" + "b" * 40,
)


CANON_REVISION = "canon-source/v1:" + "e" * 64

def args(operation, **kw):
    return SimpleNamespace(
        operation=operation, expected_head="b" * 40,
        canon_revision=kw.get("canon_revision"),
        run_id=kw.get("run_id"),
        request_ref=kw.get("request_ref"),
    )


@pytest.fixture
def no_real_host(monkeypatch):
    monkeypatch.setattr(cli, "_owner_session", lambda: None)
    monkeypatch.setattr(cli, "_release_scope", lambda *a: SCOPE)
    monkeypatch.setattr(cli, "_release_canon", lambda repo: {
        "status": "CANON_SOURCE_VERIFIED",
        "canon_revision": CANON_REVISION,
        "source_main": "f" * 40,
        "source_count": 6,
        "service_mutations": 0,
        "guard_writes": 0,
    })


def test_inspect_never_loads_or_creates_guard(no_real_host, monkeypatch):
    monkeypatch.setattr(
        cli, "_guard_gate", lambda *a: pytest.fail("inspect opened Guard"))
    monkeypatch.setattr(
        cli, "FixedOperatorHost", lambda *a, **k: pytest.fail("host constructed"))
    result = cli.run(args("inspect"))
    assert result["status"] == "OBSERVED_NO_EFFECT"
    assert result["service_mutations"] == 0
    assert result["guard_writes"] == 0


def test_request_fails_closed_if_live_canon_source_cannot_be_verified(
        no_real_host, monkeypatch):
    monkeypatch.setattr(cli, "_guard_gate",
                        lambda *a: pytest.fail("Guard must not open"))
    def cannot_observe(_):
        raise cli.OwnerReleaseDenied("CANON_SOURCE_REMOTE_UNAVAILABLE")
    monkeypatch.setattr(cli, "_release_canon", cannot_observe)
    with pytest.raises(cli.OwnerReleaseDenied, match="CANON_SOURCE_REMOTE_UNAVAILABLE"):
        cli.run(args("request"), confirmer=lambda *a: pytest.fail(
            "cannot confirm unverified policy"))


def test_request_rejects_caller_supplied_synthetic_canon(
        no_real_host, monkeypatch):
    monkeypatch.setattr(cli, "_guard_gate",
                        lambda *a: pytest.fail("Guard must not open"))
    with pytest.raises(cli.OwnerReleaseDenied, match="CANON_SOURCE_REVISION_MISMATCH"):
        cli.run(args("request", canon_revision="release-gate/v1"),
                confirmer=lambda *a: pytest.fail("cannot use synthetic Canon"))


def test_request_needs_interactive_owner_confirmation(no_real_host, monkeypatch):
    reads = []
    def read_only_before_confirmation(*_args, **kwargs):
        if kwargs != {"readonly": True, "scope": SCOPE}:
            pytest.fail("writable Guard opened before owner confirmation")
        reads.append(True)
        return SimpleNamespace(registry=SimpleNamespace(get=lambda _path: None))
    monkeypatch.setattr(cli, "_guard_gate", read_only_before_confirmation)
    with pytest.raises(cli.OwnerReleaseDenied, match="CONFIRMATION"):
        cli.run(args("request"),
                confirmer=lambda *a: False)
    assert reads == [True]


def test_request_only_creates_pending_no_switch(no_real_host, monkeypatch):
    seen = []
    class Gate:
        def prepare(self, scope, *, canon_revision):
            seen.append((scope, canon_revision))
            return {"ok": True, "status": "WAITING_HUMAN",
                    "scope_ref": "a" * 64, "run_id": "release-123",
                    "request_ref": "c" * 64}
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: Gate())
    monkeypatch.setattr(
        cli, "FixedOperatorHost", lambda *a, **k: pytest.fail("host constructed"))
    output = cli.run(
        args("request"),
        confirmer=lambda prompt, phrase: phrase == "REQUEST " + "a" * 16,
    )
    assert seen == [(SCOPE, CANON_REVISION)]
    assert output == {
        "status": "WAITING_HUMAN", "scope_ref": "a" * 64,
        "run_id": "release-123", "request_ref": "c" * 64,
        "approved": False, "service_mutations": 0,
    }


@pytest.mark.parametrize("approval", [
    {"ok": False, "status": "OWNER_APPROVAL_REQUIRED"},
    {"ok": True, "status": "PENDING", "approved": False},
    {"ok": True, "status": "APPROVED", "approved": True, "scope_ref": "f" * 64},
])
def test_apply_denies_unapproved_and_changed_scope(
        no_real_host, monkeypatch, approval):
    class Gate:
        registry = SimpleNamespace(get=lambda path: SimpleNamespace(
            status="PREPARED", release_run_id="release-123",
            release_request_ref="c" * 64,
            release_canon_revision=CANON_REVISION))
        def verify(self, *a):
            return approval
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: Gate())
    monkeypatch.setattr(
        cli, "FixedOperatorHost", lambda *a, **k: pytest.fail("host constructed"))
    with pytest.raises(cli.OwnerReleaseDenied, match="GUARD"):
        cli.run(args("apply", run_id="release-123", request_ref="c" * 64),
                confirmer=lambda *a: pytest.fail("must not prompt"))
    

@pytest.mark.parametrize("run_id,ref", [
    (None, "c" * 64), ("release-123", None),
    ("!bad", "c" * 64), ("release-123", "c" * 63),
])
def test_apply_requires_exact_ref_before_opening_guard(
        no_real_host, monkeypatch, run_id, ref):
    monkeypatch.setattr(cli, "_guard_gate",
                        lambda *a: pytest.fail("Guard must not open"))
    with pytest.raises(cli.OwnerReleaseDenied, match="REQUEST"):
        cli.run(args("apply", run_id=run_id, request_ref=ref))


def test_exact_owner_gate_is_not_same_as_guard_approval(no_real_host):
    called = []
    owner = cli.InteractiveOwnerGate(
        SCOPE, "release-123", "c" * 64,
        confirmer=lambda prompt, phrase: called.append(phrase) or True)
    assert called == ["APPLY " + "a" * 16]
    assert owner.verify_exact_release(SCOPE, "release-123", "c" * 64)
    assert not owner.verify_exact_release(SCOPE, "release-other", "c" * 64)
    assert not owner.verify_exact_release(SCOPE, "release-123", "d" * 64)
    assert not owner.verify_exact_release(SimpleNamespace(scope_ref="b"*64),
                                          "release-123", "c"*64)


def test_owner_confirmation_refusal_is_no_effect(no_real_host, monkeypatch):
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: SimpleNamespace(
        registry=SimpleNamespace(get=lambda path: SimpleNamespace(
            status="PREPARED", release_run_id="release-123",
            release_request_ref="c" * 64,
            release_canon_revision=CANON_REVISION)),
        verify=lambda *a: {"status": "APPROVED", "approved": True,
                           "scope_ref": "a" * 64}))
    monkeypatch.setattr(
        cli, "FixedOperatorHost", lambda *a, **k: pytest.fail("host constructed"))
    with pytest.raises(cli.OwnerReleaseDenied, match="CONFIRMATION"):
        cli.run(args("apply", run_id="release-123", request_ref="c" * 64),
                confirmer=lambda *a: False)


def test_apply_delegates_only_to_existing_transaction(
        no_real_host, monkeypatch):
    called = []
    guard = SimpleNamespace(
        verify=lambda *a: {
            "status": "APPROVED", "approved": True, "scope_ref": "a" * 64},
        registry=SimpleNamespace(get=lambda path: SimpleNamespace(
            status="PREPARED",
            release_run_id="release-123",
            release_request_ref="c" * 64,
            release_canon_revision=CANON_REVISION)))
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: guard)
    host = object()
    monkeypatch.setattr(cli, "FixedOperatorHost", lambda *a, **k: host)

    class Transaction:
        def __init__(self, gate, received_host, owner_gate):
            assert gate is guard and received_host is host
            assert owner_gate.verify_exact_release(
                SCOPE, "release-123", "c" * 64)
        def execute(self, scope, run, request_ref):
            called.append((scope, run, request_ref))
            return SimpleNamespace(status="VERIFIED", scope_ref="a" * 64,
                                   operator_only=True, guard_approved=True)
    monkeypatch.setattr(cli, "OperatorOnlyCutover", Transaction)
    output = cli.run(
        args("apply", run_id="release-123", request_ref="c" * 64),
        confirmer=lambda prompt, phrase: phrase == "APPLY " + "a" * 16)
    assert called == [(SCOPE, "release-123", "c" * 64)]
    assert output == {"status": "VERIFIED", "scope_ref": "a" * 64,
                      "operator_only": True, "guard_approved": True}


def test_readonly_guard_never_initializes_or_writes_existing_db(tmp_path):
    import sqlite3
    path = tmp_path / "guard.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE approvals (run_id TEXT)")
        db.execute("INSERT INTO approvals VALUES ('known')")
    before = path.read_bytes()
    store = cli.ReadOnlyGuardStore(path)
    with store._connect() as db:
        assert db.execute("SELECT run_id FROM approvals").fetchone() == ("known",)
        with pytest.raises(sqlite3.OperationalError):
            db.execute("INSERT INTO approvals VALUES ('forbidden')")
    assert path.read_bytes() == before
    with pytest.raises(sqlite3.OperationalError):
        cli.ReadOnlyGuardStore(tmp_path / "nonexistent.sqlite")._connect()


def test_inconsistent_guard_prepare_receipt_never_produces_approval(
        no_real_host, monkeypatch):
    class BadGate:
        def prepare(self, *a, **k):
            return {"status": "WAITING_HUMAN", "scope_ref": "a"*64,
                    "run_id": "release-123", "request_ref": "c"*64,
                    "ok": False}
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: BadGate())
    with pytest.raises(cli.OwnerReleaseDenied, match="PREPARE_NOT_ACCEPTED"):
        cli.run(args("request"),
                confirmer=lambda *a: True)


def test_preflight_is_read_only_and_reports_rollback_state(
        no_real_host, monkeypatch, tmp_path):
    import json

    calls = []
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "paths": {"m1-operator": {"status": "ROLLED_BACK"}}
    }))
    monkeypatch.setattr(
        cli, "_guard_path",
        lambda home: (tmp_path / "unused-guard.sqlite", registry))
    monkeypatch.setattr(
        cli, "_owner_file",
        lambda path, limit=500000: path.read_bytes())
    class ReadOnlyHost:
        def __init__(self, repo, *, home):
            calls.append("host")
        def _registered(self):
            calls.append("launchctl_print")
            return True
        def _pid_owned(self):
            calls.append("pid_readback")
            return True
        def _human(self):
            calls.append("http_get")
            return {"activity": []}
    monkeypatch.setattr(cli, "FixedOperatorHost", ReadOnlyHost)
    monkeypatch.setattr(
        cli, "_guard_gate", lambda *a, **k: pytest.fail("no Guard access"))
    monkeypatch.setattr(
        cli, "OperatorOnlyCutover", lambda *a, **k: pytest.fail("no cutover"))
    result = cli.run(args("preflight"))
    assert result == {
        "status": "OBSERVED_NO_EFFECT", "operator_only": True,
        "scope_ref": "a" * 64, "release_state": "ROLLED_BACK",
        "verified_incumbent_loaded": False,
        "launchd_registered": True, "pid_bound": True,
        "operator_api_readable": True, "operator_idle": True,
        "preflight_ok": True, "guard_writes": 0, "service_mutations": 0,
    }
    assert calls == ["host", "launchctl_print", "pid_readback", "http_get"]


@pytest.mark.parametrize("denial,expected", [
    ("OPERATOR_BOOTOUT_REJECTED", "OPERATOR_BOOTOUT_REJECTED"),
    ("OPERATOR_BOOTSTRAP_REJECTED", "OPERATOR_BOOTSTRAP_REJECTED"),
    ("OPERATOR_BOOTSTRAP_REJECTED_LABEL_PRESENT", "OPERATOR_BOOTSTRAP_REJECTED_LABEL_PRESENT"),
    ("OPERATOR_BOOTSTRAP_REJECTED_RETRY_EXHAUSTED", "OPERATOR_BOOTSTRAP_REJECTED_RETRY_EXHAUSTED"),
    ("OPERATOR_BOOTSTRAP_REJECTED_PERMISSION", "OPERATOR_BOOTSTRAP_REJECTED_PERMISSION"),
    ("ROLLBACK_BOOTSTRAP_REJECTED_LABEL_PRESENT", "ROLLBACK_BOOTSTRAP_REJECTED_LABEL_PRESENT"),

    ("OPERATOR_BOOTOUT_SETTLE_TIMEOUT", "OPERATOR_BOOTOUT_SETTLE_TIMEOUT"),
    ("ROLLBACK_BOOTOUT_SETTLE_TIMEOUT", "ROLLBACK_BOOTOUT_SETTLE_TIMEOUT"),
    ("OPERATOR_BUSY_OR_NOT_PID_BOUND", "OPERATOR_BUSY_OR_NOT_PID_BOUND"),
    ("PINNED_CANDIDATE_REQUIRED", "PINNED_CANDIDATE_REQUIRED"),
    ("private path: /Users/someone", "OperatorHostDenied"),
])
def test_cli_reports_only_allowlisted_host_denial(
        monkeypatch, capsys, denial, expected):
    def denied(_args):
        raise cli.OperatorHostDenied(denial)
    monkeypatch.setattr(cli, "run", denied)
    assert cli.main(["preflight", "--expected-head", "b" * 40]) == 2
    import json
    obj = json.loads(capsys.readouterr().out)
    assert obj == {"status": "BLOCKED", "reason": expected}


def test_untrusted_runtime_exception_never_exposes_raw_error(
        monkeypatch, capsys):
    def denied(_args):
        raise RuntimeError("SECRET_IGNORED")
    monkeypatch.setattr(cli, "run", denied)
    assert cli.main(["preflight", "--expected-head", "b" * 40]) == 2
    import json
    assert json.loads(capsys.readouterr().out) == {
        "status": "BLOCKED", "reason": "RuntimeError",
    }


def test_preflight_requires_pinned_scope_before_accessing_host(
        no_real_host, monkeypatch):
    def fail_scope(*a):
        raise cli.OwnerReleaseDenied("SOURCE_OR_INSTALLED_SCOPE_MISMATCH")
    monkeypatch.setattr(cli, "_release_scope", fail_scope)
    monkeypatch.setattr(
        cli, "_guard_path", lambda home: pytest.fail("no Guard"))
    monkeypatch.setattr(
        cli, "FixedOperatorHost", lambda *a, **k: pytest.fail("no host"))
    with pytest.raises(cli.OwnerReleaseDenied, match="SCOPE"):
        cli.run(args("preflight"))


@pytest.mark.parametrize("status", [
    "ROLLED_BACK", "CUTOVER", "VERIFIED", "MISSING",
])
def test_apply_rejects_replay_of_consumed_release_before_host_or_prompt(
        no_real_host, monkeypatch, status):
    def get(_path):
        if status == "MISSING":
            return None
        return SimpleNamespace(
            status=status, release_run_id="release-123",
            release_request_ref="c" * 64)
    verified = []
    gate = SimpleNamespace(
        registry=SimpleNamespace(get=get),
        verify=lambda *a: verified.append(True))
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: gate)
    monkeypatch.setattr(
        cli, "FixedOperatorHost",
        lambda *a, **k: pytest.fail("stale release constructed host"))
    with pytest.raises(cli.OwnerReleaseDenied, match="RELEASE_STATE_NOT_PREPARED"):
        cli.run(
            args("apply", run_id="release-123", request_ref="c" * 64),
            confirmer=lambda *a: pytest.fail("stale release prompted owner"))
    assert verified == []


@pytest.mark.parametrize("mismatch", ["run", "ref"])
def test_apply_rejects_registry_mismatch_before_guard_or_host(
        no_real_host, monkeypatch, mismatch):
    row = SimpleNamespace(
        status="PREPARED",
        release_run_id="other" if mismatch == "run" else "release-123",
        release_request_ref="d" * 64 if mismatch == "ref" else "c" * 64)
    gate = SimpleNamespace(
        registry=SimpleNamespace(get=lambda _path: row),
        verify=lambda *a: pytest.fail("stale binding Guard verification"))
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: gate)
    with pytest.raises(cli.OwnerReleaseDenied, match="RELEASE_STATE_NOT_PREPARED"):
        cli.run(
            args("apply", run_id="release-123", request_ref="c" * 64),
            confirmer=lambda *a: pytest.fail("stale binding prompted owner"))


def test_canon_check_is_read_only_and_does_not_enter_guard_or_host(
        no_real_host, monkeypatch):
    monkeypatch.setattr(cli, "_guard_gate",
                        lambda *a, **k: pytest.fail("no Guard access"))
    monkeypatch.setattr(cli, "FixedOperatorHost",
                        lambda *a, **k: pytest.fail("no host"))
    got = cli.run(args("canon-check"))
    assert got["canon_revision"] == CANON_REVISION
    assert got["status"] == "CANON_SOURCE_VERIFIED"
    assert got["guard_writes"] == got["service_mutations"] == 0


def test_apply_rejects_changed_canon_source_before_owner_prompt_and_guard_verify(
        no_real_host, monkeypatch):
    gate = SimpleNamespace(
        registry=SimpleNamespace(get=lambda path: SimpleNamespace(
            status="PREPARED", release_run_id="release-123",
            release_request_ref="c" * 64,
            release_canon_revision="canon-source/v1:" + "a" * 64)),
        verify=lambda *a: pytest.fail("must not verify stale authorization"))
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: gate)
    monkeypatch.setattr(
        cli, "FixedOperatorHost", lambda *a, **k: pytest.fail("must not build host"))
    with pytest.raises(cli.OwnerReleaseDenied, match="CANON_SOURCE_REVISION_CHANGED"):
        cli.run(args("apply", run_id="release-123", request_ref="c" * 64),
                confirmer=lambda *a: pytest.fail("must not prompt owner"))


def test_apply_rejects_legacy_or_unbound_canon_revision_before_authority(
        no_real_host, monkeypatch):
    gate = SimpleNamespace(
        registry=SimpleNamespace(get=lambda path: SimpleNamespace(
            status="PREPARED", release_run_id="release-123",
            release_request_ref="c" * 64,
            release_canon_revision="github-main:" + "f" * 40)),
        verify=lambda *a: pytest.fail("must not verify unbound authority"))
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: gate)
    with pytest.raises(cli.OwnerReleaseDenied, match="CANON_SOURCE_REVISION_UNBOUND"):
        cli.run(args("apply", run_id="release-123", request_ref="c" * 64),
                confirmer=lambda *a: pytest.fail("must not prompt owner"))


def test_source_resolver_failure_only_exposes_fixed_code(monkeypatch):
    def denied(_):
        raise cli.CanonSourceDenied("CANON_SOURCE_REMOTE_UNAVAILABLE")
    monkeypatch.setattr(cli, "observe_release_canon", denied)
    with pytest.raises(cli.OwnerReleaseDenied, match="CANON_SOURCE_REMOTE_UNAVAILABLE"):
        cli._release_canon(None)


def test_owner_request_successor_only_after_incumbent_loaded_proof(
        no_real_host, monkeypatch):
    prior = SimpleNamespace(status="VERIFIED", release_scope_ref="d"*64,
                            candidate_authority="github-commit:"+"c"*40)
    calls = []
    class Gate:
        registry = SimpleNamespace(get=lambda path: prior)
        def prepare(self, scope, *, canon_revision, verified_predecessor_ref):
            calls.append(("prepare", verified_predecessor_ref))
            assert canon_revision == CANON_REVISION
            return {"ok": True, "status": "WAITING_HUMAN",
                    "scope_ref": scope.scope_ref, "run_id": "release-next",
                    "request_ref": "e"*64}
    monkeypatch.setattr(cli, "_guard_gate", lambda *a, **k: Gate())
    verified = {"value": False}
    monkeypatch.setattr(cli, "FixedOperatorHost",
        lambda *a, **k: SimpleNamespace(
            verified_current_release=lambda record: (
                calls.append(("loaded", record.release_scope_ref))
                or verified["value"])))
    confirmation = lambda prompt, phrase: (
        calls.append(("owner", phrase)) or True)
    with pytest.raises(cli.OwnerReleaseDenied,
                       match="VERIFIED_PREDECESSOR_NOT_RUNNING"):
        cli.run(args("request"), confirmer=confirmation)
    assert calls == [("loaded", "d"*64)]
    verified["value"] = True
    outcome = cli.run(args("request"), confirmer=confirmation)
    assert outcome["status"] == "WAITING_HUMAN"
    assert outcome["approved"] is False
    assert calls == [("loaded", "d"*64), ("loaded", "d"*64),
                     ("owner", "REQUEST " + "a"*16),
                     ("prepare", "d"*64)]


def test_verified_preflight_needs_live_prior_release_not_registry_word(
        no_real_host, monkeypatch, tmp_path):
    reg = tmp_path/"release-registry.json"
    reg.write_text('{"schema":2,"paths":{"m1-operator":{'
                   '"status":"VERIFIED",'
                   '"release_scope_ref":"' + "d"*64 + '",'
                   '"candidate_authority":"github-commit:' + "c"*40 + '"}}}')
    monkeypatch.setattr(cli, "_guard_path", lambda home: (None, reg))
    approved = {"value": False}
    class Host:
        def __init__(self, *args, **kwargs):
            pass
        def verified_current_release(self, prior):
            assert prior.release_scope_ref == "d"*64
            return approved["value"]
        def _registered(self): return True
        def _pid_owned(self): return True
        def _human(self): return {"activity": []}
    monkeypatch.setattr(cli, "FixedOperatorHost", Host)
    denied = cli._live_preflight(tmp_path, tmp_path, SCOPE)
    assert denied["release_state"] == "VERIFIED"
    assert denied["verified_incumbent_loaded"] is False
    assert denied["preflight_ok"] is False
    approved["value"] = True
    allowed = cli._live_preflight(tmp_path, tmp_path, SCOPE)
    assert allowed["preflight_ok"] is True
    assert allowed["verified_incumbent_loaded"] is True
    assert allowed["guard_writes"] == allowed["service_mutations"] == 0


def test_apply_reads_only_the_exact_candidate_release_registry(no_real_host, monkeypatch):
    seen = []
    def guarded(home, *, readonly=False, scope=None):
        seen.append((readonly, scope))
        if readonly is not True or scope is not SCOPE:
            pytest.fail("an unscoped or writable Guard ledger was opened")
        return SimpleNamespace(registry=SimpleNamespace(get=lambda _: None))
    monkeypatch.setattr(cli, "_guard_gate", guarded)
    monkeypatch.setattr(cli, "FixedOperatorHost", lambda *_a, **_k:
                        pytest.fail("blocked apply must not reach a service"))
    with pytest.raises(cli.OwnerReleaseDenied, match="RELEASE_STATE_NOT_PREPARED"):
        cli.run(args("apply", run_id="release-123", request_ref="c" * 64),
                confirmer=lambda *_: pytest.fail("blocked apply must not prompt"))
    assert seen == [(True, SCOPE)]


def test_owner_guard_selector_uses_scoped_existing_ledger(monkeypatch, tmp_path):
    primary = tmp_path / "release-registry.json"
    older = tmp_path / ("operator-owner-main-release-" + "a"*20 + ".json")
    newer = tmp_path / ("operator-owner-main-release-" + "b"*20 + ".json")
    older.write_text("{}")
    newer.write_text("{}")
    selected = []
    monkeypatch.setattr(cli, "_guard_path", lambda _: (tmp_path / "guard.db", primary))
    class Host:
        def __init__(self, *a, **kw): pass
        def select_release_registry(self, path, *, scope=None):
            selected.append(scope)
            return newer if scope is SCOPE else older
    monkeypatch.setattr(cli, "FixedOperatorHost", Host)
    monkeypatch.setattr(cli, "_owner_file", lambda *a, **kw: b"{}")
    monkeypatch.setattr(cli, "ReadOnlyGuardStore", lambda _: object())
    monkeypatch.setattr(cli, "GuardReleaseGate", lambda store, path:
                        SimpleNamespace(registry_path=path))
    observed = cli._guard_gate(tmp_path, readonly=True, scope=SCOPE)
    assert observed.registry_path == newer
    assert selected == [SCOPE]
    assert older.read_text() == newer.read_text() == "{}"


@pytest.mark.parametrize("case,expected", [
    ("pending", True), ("approved", True), ("missing", False),
    ("cancelled", False), ("wrong_scope", False), ("busy", False),
])
def test_prepared_mobile_release_can_continue_only_exact_live_guard(
        monkeypatch, tmp_path, case, expected):
    import json
    from ai_foundation.release_gate import ImmutableReleaseScope
    scope = ImmutableReleaseScope(
        "m1-operator", "d"*64, "prior", "endpoint",
        "github-commit:"+"b"*40, "endpoint", "rollback",
        "switch", "readback", "rollback-readback")
    reg = tmp_path/"registry.json"
    record = {
        "status": "PREPARED", "generation": 1,
        "release_scope_ref": scope.scope_ref if case != "wrong_scope" else "e"*64,
        "release_scope": scope.as_dict(),
        "candidate_authority": scope.candidate_authority,
        "release_run_id": "release-123", "release_request_ref": "c"*64,
    }
    reg.write_text(json.dumps({"paths": {scope.path: record}}))
    monkeypatch.setattr(cli, "_guard_path", lambda home: (None, reg))
    class Host:
        def __init__(self, *a, **kw): pass
        def _registered(self): return True
        def _pid_owned(self): return True
        def _human(self): return {"activity": [{}] if case == "busy" else []}
    monkeypatch.setattr(cli, "FixedOperatorHost", Host)
    def read_gate(home, *, readonly, scope):
        assert readonly is True
        return SimpleNamespace(
            store=SimpleNamespace(is_cancelled=lambda run: case == "cancelled"),
            verify=lambda scope, run, ref, **kw: {
                "ok": True, "scope_ref": scope.scope_ref,
                "status": "APPROVED" if case == "approved" else "PENDING",
                "approved": case == "approved"},
            _request_row=lambda run: None if case == "missing" else ("saved",),
            _request_ref=lambda run, row: "c"*64)
    monkeypatch.setattr(cli, "_guard_gate", read_gate)
    result = cli._live_preflight(tmp_path, tmp_path, scope)
    assert result["release_state"] == "PREPARED"
    assert result["preflight_ok"] is expected
    assert result["guard_writes"] == result["service_mutations"] == 0
