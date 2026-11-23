"""Single existing tunnel ID reused for owner-Guard tools, no new connector."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import m1_guarded_tunnel as guarded
from scripts import m1_guarded_tunnel_stdio as wrapper
from scripts.m1_owner_delegated_mcp_stdio import TrustedOwnerSessionRenewal


def _profile(tmp_path, *, text=None):
    profile_dir = tmp_path / ".config" / "tunnel-client"
    profile_dir.mkdir(parents=True, exist_ok=True)
    profile = profile_dir / "foundation-readonly.yaml"
    profile.write_text(text if text is not None else
        "config_version: 1\ncontrol_plane:\n"
        "  tunnel_id: \"tunnel_" + "a" * 32 + "\"\n"
        "mcp:\n  command: /opt/homebrew/bin/python3.12 -B "
        "/owner/scripts/m1_foundation_tunnel_stdio.py\n")
    return profile


def test_reuses_registered_profile_and_id_without_second_connection(monkeypatch, tmp_path):
    _profile(tmp_path)
    monkeypatch.setattr(guarded, "readiness",
                        lambda **kwargs: {"status": "READY_FOR_OWNER_SETUP"})
    monkeypatch.setattr(guarded, "_client_binary", lambda *_: "/trusted/client")
    monkeypatch.setattr(guarded, "_keychain_runtime_key",
                        lambda **kwargs: "control-plane-fixture")
    observed = {}
    def execute(argv, **kwargs):
        observed.update({"argv": argv, "env": kwargs["env"]})
        return SimpleNamespace(returncode=0)
    result = guarded.owner_action(
        "configure", owner_root=tmp_path, env={"HOME": str(tmp_path)},
        run=execute)
    assert result["status"] == "EXISTING_PROFILE_REPOINTED"
    argv = observed["argv"]
    assert argv[:3] == ["/trusted/client", "init", "--force"]
    assert argv[argv.index("--profile") + 1] == "foundation-readonly"
    assert argv[argv.index("--tunnel-id") + 1] == "tunnel_" + "a" * 32
    assert argv[argv.index("--health-listen-addr") + 1] == "127.0.0.1:0"
    command = argv[argv.index("--mcp-command") + 1]
    assert "m1_guarded_tunnel_stdio.py" in command
    assert "m1_foundation_tunnel_stdio.py" not in command
    assert observed["env"]["CONTROL_PLANE_API_KEY"] == "control-plane-fixture"


def test_missing_custom_or_changed_profile_fails_before_repoint(monkeypatch, tmp_path):
    monkeypatch.setattr(guarded, "readiness",
                        lambda **kwargs: {"status": "READY_FOR_OWNER_SETUP"})
    calls = []
    monkeypatch.setattr(guarded, "_keychain_runtime_key",
                        lambda **kwargs: calls.append("KEYCHAIN"))
    env = {"HOME": str(tmp_path)}
    assert guarded.owner_action("configure", env=env)["reason"] == (
        "EXISTING_TUNNEL_PROFILE_NOT_VERIFIED")
    _profile(tmp_path, text="control_plane:\n  tunnel_id: tunnel_" + "a"*32
             + "\nmcp:\n  command: /unknown/other-server.py\n")
    assert guarded.owner_action("configure", env=env)["reason"] == (
        "EXISTING_TUNNEL_PROFILE_NOT_VERIFIED")
    assert calls == []


def test_ambiguous_or_mismatching_existing_id_fails_closed(tmp_path, monkeypatch):
    _profile(tmp_path, text="control_plane:\n  tunnel_id: tunnel_" + "a"*32
             + "\n  tunnel_id: tunnel_" + "b"*32
             + "\nmcp:\n  command: m1_foundation_tunnel_stdio.py\n")
    assert guarded._existing_tunnel_id(env={"HOME": str(tmp_path)}) is None
    _profile(tmp_path)
    monkeypatch.setattr(guarded, "readiness",
                        lambda **kwargs: {"status": "READY_FOR_OWNER_SETUP"})
    result = guarded.owner_action(
        "configure", env={"HOME": str(tmp_path)},
        tunnel_id="tunnel_" + "b"*32)
    assert result["reason"] == "EXISTING_TUNNEL_PROFILE_NOT_VERIFIED"


def test_stdio_wrapper_drops_control_plane_and_other_secrets(monkeypatch, tmp_path):
    monkeypatch.setattr(wrapper.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(wrapper.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(wrapper.os, "getuid", lambda: 501)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 501)
    monkeypatch.setattr(wrapper.sys, "argv", ["m1_guarded_tunnel_stdio.py"])
    monkeypatch.setattr(wrapper, "_trusted_bytes", lambda *_args: b"verified")
    config = tmp_path / "owner.json"
    config.write_text("{}")
    monkeypatch.setenv("CONTROL_PLANE_API_KEY", "NO_EXPORT")
    monkeypatch.setenv("STRATA_API_KEY", "NO_EXPORT_EITHER")
    monkeypatch.setenv("GH_TOKEN", "NO_EXPORT_GITHUB")
    seen = {}
    def fake_exec(exe, argv, environment):
        seen.update({"exe": exe, "argv": argv, "environment": environment})
    wrapper.launch(execve=fake_exec,
                   resolve_config=lambda: (config, None, None),
                   executable=Path(__file__))
    assert "--enable-local-development" in seen["argv"]
    assert "--config" in seen["argv"]
    assert "CONTROL_PLANE_API_KEY" not in seen["environment"]
    assert "STRATA_API_KEY" not in seen["environment"]
    assert "GH_TOKEN" not in seen["environment"]


def test_owner_session_renews_only_with_same_tool_catalog():
    class Auth:
        alive = True
        def authenticate(self, _session, _token):
            return True if self.alive else None
    class Service:
        def __init__(self, n, scope):
            self.host = SimpleNamespace(authorizer=Auth())
            self.session_id = "session" + str(n)
            self.token = "token" + str(n)
            self.exposed_tools = frozenset(scope)
        def dispatch(self, msg):
            return (self.session_id, msg["method"])
    created = []
    def factory():
        item = Service(len(created), ("foundation_status", "development_status"))
        created.append(item)
        return item
    service = TrustedOwnerSessionRenewal(factory)
    assert service.dispatch({"method": "tools/list"}) == ("session0", "tools/list")
    created[0].host.authorizer.alive = False
    assert service.dispatch({"method": "tools/list"}) == ("session1", "tools/list")
    assert len(created) == 2


def test_owner_session_never_increases_scope_on_renewal():
    class Auth:
        def authenticate(self, *_args): return None
    class Service:
        def __init__(self, scopes):
            self.host = SimpleNamespace(authorizer=Auth())
            self.session_id = "session"
            self.token = "token"
            self.exposed_tools = frozenset(scopes)
        def dispatch(self, msg):
            raise AssertionError("new scope must never be dispatched")
    services = [Service(("foundation_status",)),
                Service(("foundation_status", "submit_decision"))]
    renewal = TrustedOwnerSessionRenewal(lambda: services.pop(0))
    with pytest.raises(PermissionError, match="OWNER_MCP_SCOPE_CHANGED"):
        renewal.dispatch({"method": "tools/list"})
