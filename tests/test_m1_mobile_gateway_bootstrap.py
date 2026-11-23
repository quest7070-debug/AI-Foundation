"""Bounded static contract for the one-time M1 owner mobile gateway bootstrap.

No launchctl, live approval, mutable host or paid/provider effect is tested here.
"""
from pathlib import Path
import plistlib
from types import SimpleNamespace
import pytest

from scripts import m1_mobile_gateway_bootstrap as b


def _old_plist():
    return {
        "Label": b.LABEL,
        "ProgramArguments": [
            "/opt/homebrew/bin/python3.12", "-B",
            "/Users/owner/Develop/AI-Foundation/scripts/run_remote_gateway.py",
            "--port", "8793", "--upstream-port", "8766",
            "--cert", "/Users/owner/Library/cert.pem",
            "--key", "/Users/owner/Library/key.pem",
        ],
        "EnvironmentVariables": {
            "FOUNDATION_REMOTE_ALLOWED_HOSTS":
                "owner-m1.example.ts.net",
            "PRIVATE_UNRELATED_SETTING": "do-not-change",
        },
        "WorkingDirectory": "/Users/owner/Develop/AI-Foundation",
        "KeepAlive": True,
        "RunAtLoad": True,
    }


def test_gateway_candidate_is_only_one_label_and_one_loopback_service():
    old = _old_plist()
    original = plistlib.dumps(old)
    staged = Path("/Users/owner/.ai-foundation-tunnel-sources/" + "e" * 40)
    new = plistlib.loads(b._candidate_plist(old, staged))
    assert new["Label"] == b.LABEL
    assert old == plistlib.loads(original)
    assert b._opt(new["ProgramArguments"], "--listen") == "127.0.0.1"
    assert b._opt(new["ProgramArguments"], "--port") == "8793"
    assert b._opt(new["ProgramArguments"], "--upstream-port") == "8766"
    assert new["ProgramArguments"][2] == str(staged / "scripts/run_remote_gateway.py")
    assert new["WorkingDirectory"] == str(staged)
    assert new["EnvironmentVariables"]["FOUNDATION_REMOTE_SERVE_OWNER_ENABLED"] == "1"
    assert new["EnvironmentVariables"]["FOUNDATION_REMOTE_MOBILE_RELEASE_ENABLED"] == "1"
    assert new["EnvironmentVariables"]["PRIVATE_UNRELATED_SETTING"] == "do-not-change"
    assert new["KeepAlive"] is old["KeepAlive"]
    assert new["RunAtLoad"] is old["RunAtLoad"]


@pytest.mark.parametrize("bad", [
    ["--port", "8794"], ["--upstream-port", "8443"],
    ["--listen", "0.0.0.0", "--listen", "0.0.0.0"],
    ["--cert"], ["--key"],
])
def test_gateway_refuses_changed_ports_missing_tls_or_ambiguous_listen(bad):
    p = _old_plist()
    argv = list(p["ProgramArguments"])
    if bad[0] == "--listen":
        argv += bad
    else:
        pos = argv.index(bad[0])
        if len(bad) == 1:
            argv = argv[:pos] + argv[pos + 2:]
        else:
            argv[pos + 1] = bad[1]
    p["ProgramArguments"] = argv
    with pytest.raises(b.BootstrapDenied):
        b._candidate_plist(p, Path("/private/stage"))


def test_gateway_not_accepting_unscoped_or_duplicate_runner():
    p = _old_plist()
    p["ProgramArguments"].append("/extra/scripts/run_remote_gateway.py")
    with pytest.raises(b.BootstrapDenied):
        b._candidate_plist(p, Path("/private/stage"))
    p = _old_plist()
    p["EnvironmentVariables"].pop("FOUNDATION_REMOTE_ALLOWED_HOSTS")
    with pytest.raises(b.BootstrapDenied):
        b._candidate_plist(p, Path("/private/stage"))


def test_no_guard_approval_no_gateway_effect(monkeypatch):
    scope = SimpleNamespace(scope_ref="1" * 64)
    checks = []
    class Gate:
        def verify(self, passed_scope, run, ref):
            checks.append((passed_scope, run, ref))
            return {"status": "OWNER_APPROVAL_REQUIRED", "approved": False}
    monkeypatch.setattr(b.cli, "_guard_gate", lambda *a, **k: Gate())
    tick = [0.0]
    monkeypatch.setattr(b.time, "monotonic", lambda: tick[0])
    def advance(n):
        tick[0] += n
    monkeypatch.setattr(b.time, "sleep", advance)
    monkeypatch.setattr(b, "WAIT_SECONDS", 6)
    with pytest.raises(b.BootstrapDenied, match="OWNER_APPROVAL_STILL_PENDING"):
        b._wait_approval(scope, "run", "a" * 64)
    assert len(checks) >= 2


def test_guard_approval_requires_exact_verified_scope(monkeypatch):
    scope = SimpleNamespace(scope_ref="a" * 64)
    gate = SimpleNamespace(verify=lambda *args: {
        "status": "APPROVED", "approved": True, "scope_ref": "b" * 64})
    monkeypatch.setattr(b.cli, "_guard_gate", lambda *a, **k: gate)
    monkeypatch.setattr(b, "WAIT_SECONDS", 0.01)
    monkeypatch.setattr(b.time, "sleep", lambda n: None)
    with pytest.raises(b.BootstrapDenied, match="EXACT_GUARD_STATE_CHANGED"):
        b._wait_approval(scope, "run", "c" * 64)



def test_loopback_pid_readback_uses_lsof_name_not_node(monkeypatch):
    good = ("COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            "Python 123 501 3u IPv4 0x1 0t0 TCP 127.0.0.1:8793 (LISTEN)\n")
    def run(*_args, **_kwargs):
        return SimpleNamespace(returncode=0, stdout=good, stderr="")
    monkeypatch.setattr(b, "_cmd", run)
    assert b._port_owned(123, strict_local=True)
    assert not b._port_owned(456, strict_local=True)

    bad = good.replace("127.0.0.1:8793", "*:8793")
    monkeypatch.setattr(b, "_cmd", lambda *_args, **_kwargs:
                        SimpleNamespace(returncode=0, stdout=bad, stderr=""))
    assert not b._port_owned(123, strict_local=True)
    assert b._port_owned(123, strict_local=False)



def test_gateway_preserves_existing_pinned_python_alias_and_rejects_shell():
    old = _old_plist()
    old["ProgramArguments"][0] = "/opt/homebrew/Cellar/python@3.12/3.12.14/bin/python3.12"
    staged = Path("/Users/owner/.ai-foundation-tunnel-sources/" + "e" * 40)
    transformed = plistlib.loads(b._candidate_plist(old, staged))
    assert transformed["ProgramArguments"][0] == old["ProgramArguments"][0]
    old["ProgramArguments"][0] = "/bin/sh"
    with pytest.raises(b.BootstrapDenied, match="GATEWAY_PYTHON_LAUNCHER_MISMATCH"):
        b._candidate_plist(old, staged)


@pytest.mark.parametrize("launcher", [
    "/Users/owner/Develop/AI-Foundation/.venv/bin/python",
    "/opt/homebrew/Cellar/python@3.12/3.12.14/bin/python3.12",
    "/opt/homebrew/bin/python3.14",
    "/opt/homebrew/Cellar/python@3.12/3.12.14/Frameworks/Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python",
])
def test_bootstrap_preserves_verified_absolute_python_alias(launcher):
    old = _old_plist()
    old["ProgramArguments"][0] = launcher
    assert b._launcher_kind(old["ProgramArguments"]) == "PYTHON"
    updated = plistlib.loads(b._candidate_plist(old, Path("/private/immutable-stage")))
    assert updated["ProgramArguments"][0] == launcher


@pytest.mark.parametrize("launcher,kind", [
    ("/bin/sh", "SHELL_OR_WRAPPER"),
    ("/usr/bin/env", "SHELL_OR_WRAPPER"),
    ("python", "RELATIVE"),
    ("/usr/local/bin/uv", "OTHER"),
])
def test_bootstrap_denies_wrappers_and_untrusted_interpreters(launcher, kind):
    old = _old_plist()
    old["ProgramArguments"][0] = launcher
    assert b._launcher_kind(old["ProgramArguments"]) == kind
    with pytest.raises(b.BootstrapDenied, match="GATEWAY_PYTHON_LAUNCHER_MISMATCH"):
        b._candidate_plist(old, Path("/private/immutable-stage"))

@pytest.mark.parametrize("approved,expected", [
    (True, "EXACT_GUARD_APPROVED_OWNER_APPLY_REQUIRED"),
    (False, "EXACT_GUARD_NOT_APPROVED"),
])
def test_exact_operator_guard_observe_never_requests_or_applies(
        monkeypatch, approved, expected):
    scope = SimpleNamespace(scope_ref=b.OPERATOR_SCOPE, path="m1-operator")
    record = SimpleNamespace(
        status="PREPARED", release_scope_ref=b.OPERATOR_SCOPE,
        release_run_id=b.OPERATOR_RUN, release_request_ref=b.OPERATOR_REF)
    examined = []
    monkeypatch.setattr(b.cli, "_release_scope", lambda *args: scope)
    def gate(home, *, readonly=False, scope=None):
        assert readonly
        examined.append(scope.scope_ref if scope is not None else "CURRENT")
        if scope is not None:
            assert scope.scope_ref == b.OPERATOR_SCOPE
        return SimpleNamespace(
            registry=SimpleNamespace(get=lambda path:
                (None if scope is None else record) if path == "m1-operator" else None),
            verify=lambda _scope, run, ref: {
                "status": "APPROVED" if approved else "OWNER_APPROVAL_REQUIRED",
                "approved": approved, "scope_ref": b.OPERATOR_SCOPE})
    monkeypatch.setattr(b.cli, "_guard_gate", gate)
    monkeypatch.setattr(b.cli, "run", lambda *_a, **_k:
                        pytest.fail("observation must not execute an Operator release"))
    monkeypatch.setattr(b, "_owner_confirm", lambda *_a:
                        pytest.fail("observation must not ask for approval"))
    assert b.observe_existing_operator_guard() == expected
    assert examined == ["CURRENT", b.OPERATOR_SCOPE]


def test_exact_operator_guard_observe_refuses_other_ledger_and_loaded_mismatch(
        monkeypatch):
    scope = SimpleNamespace(scope_ref=b.OPERATOR_SCOPE, path="m1-operator")
    record = SimpleNamespace(
        status="PREPARED", release_scope_ref=b.OPERATOR_SCOPE,
        release_run_id="old-release-run", release_request_ref=b.OPERATOR_REF)
    monkeypatch.setattr(b.cli, "_release_scope", lambda *args: scope)
    monkeypatch.setattr(b.cli, "_guard_gate", lambda *args, **kwargs:
                        SimpleNamespace(
                            registry=SimpleNamespace(get=lambda path: record),
                            verify=lambda *args: pytest.fail("wrong request must not be verified")))
    assert b.observe_existing_operator_guard() == "EXACT_OPERATOR_RELEASE_BINDING_CHANGED"
    scope.scope_ref = "f" * 64
    assert b.observe_existing_operator_guard() == "OPERATOR_SOURCE_SCOPE_CHANGED"


def test_owner_observer_detects_existing_real_verified_release_before_recomputing_scope(
        monkeypatch):
    # The original fixed release was applied earlier. Its prior-incumbent
    # scope is not reproducible once a new Operator is physically running.
    saved = SimpleNamespace(
        status="VERIFIED", release_scope_ref=b.OPERATOR_SCOPE,
        release_run_id=b.OPERATOR_RUN, release_request_ref=b.OPERATOR_REF)
    seen = []
    def gate(_home, *, readonly=False, scope=None):
        assert readonly is True and scope is None
        seen.append("read-current-ledger")
        return SimpleNamespace(registry=SimpleNamespace(get=lambda path: saved))
    monkeypatch.setattr(b.cli, "_guard_gate", gate)
    monkeypatch.setattr(b.cli, "_release_scope", lambda *_a, **_k:
                        pytest.fail("must not recalculate an old release against a new incumbent"))
    class Host:
        def __init__(self, *_a, **_kw): pass
        def verified_current_release(self, prior):
            assert prior is saved
            seen.append("physical-pid-source-api")
            return True
    monkeypatch.setattr(b.cli, "FixedOperatorHost", Host)
    assert b.observe_existing_operator_guard() == "EXACT_OPERATOR_ALREADY_LOADED"
    assert seen == ["read-current-ledger", "physical-pid-source-api"]


def test_owner_observer_does_not_trust_verified_ledger_without_live_pid(
        monkeypatch):
    saved = SimpleNamespace(
        status="VERIFIED", release_scope_ref=b.OPERATOR_SCOPE,
        release_run_id=b.OPERATOR_RUN, release_request_ref=b.OPERATOR_REF)
    monkeypatch.setattr(b.cli, "_guard_gate", lambda *_a, **_kw:
                        SimpleNamespace(registry=SimpleNamespace(get=lambda _: saved)))
    monkeypatch.setattr(b.cli, "FixedOperatorHost", lambda *_a, **_kw:
                        SimpleNamespace(verified_current_release=lambda *_: False))
    monkeypatch.setattr(b.cli, "_release_scope", lambda *_a, **_kw:
                        pytest.fail("no scope recomputation on VERIFIED receipt"))
    assert b.observe_existing_operator_guard() == "OPERATOR_LEDGER_ONLY_NOT_LOADED"
