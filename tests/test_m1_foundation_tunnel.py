"""Focused synthetic contracts for private, no-key-leak MCP tunnel integration."""
from __future__ import annotations

import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
from unittest import mock

import pytest

from scripts import m1_foundation_tunnel as tunnel
from scripts import m1_foundation_tunnel_stdio as wrapper


def test_owner_source_and_tunnel_client_are_observed_without_creds(tmp_path, monkeypatch):
    source, installed = tmp_path / "reviewed", tmp_path / "owner"
    for root in (source, installed):
        for name in tunnel.SOURCE_NAMES:
            p = root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("readonly-fixture")
    binary = tmp_path / "tunnel-client"
    binary.write_bytes(b"not-run")
    binary.chmod(0o700)
    monkeypatch.setattr(tunnel.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(tunnel.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(tunnel.os, "getuid", lambda: 501)
    monkeypatch.setattr(tunnel.os, "geteuid", lambda: 501)
    monkeypatch.setattr(tunnel, "_trusted_bytes", lambda path: Path(path).read_bytes())
    monkeypatch.setattr(tunnel, "PYTHON", sys.executable)
    got = tunnel.readiness(checkout=source, owner_root=installed,
                           which=lambda _: str(binary))
    assert got["status"] == "READY_FOR_OWNER_SETUP"
    assert got["remote_chatgpt_connection_verified"] is False
    assert got["tool_scope"] == "foundation_status_ONLY"
    assert got["service_mutations"] == got["model_calls"] == 0

    (installed / tunnel.SOURCE_NAMES[0]).write_text("tampered")
    got = tunnel.readiness(checkout=source, owner_root=installed,
                           which=lambda _: str(binary))
    assert got["status"] == "BLOCKED"
    assert got["reason"] == "OWNER_SOURCE_INSTALL_REQUIRED"
    assert "tampered" not in json.dumps(got)


def test_only_fixed_tunnel_profile_and_keychain_credential_no_argv_leak(monkeypatch, tmp_path):
    calls = []
    def command(argv, **kw):
        if argv[0] == "/usr/bin/security":
            return SimpleNamespace(returncode=0, stdout="sk-private-runtime-canary\n")
        calls.append((argv, kw))
        return SimpleNamespace(returncode=0, stdout="PRIVATE_TUNNEL_DIAGNOSTIC", stderr="")
    good = {"status": "READY_FOR_OWNER_SETUP",
            "remote_chatgpt_connection_verified": False, "reason": "NONE"}
    monkeypatch.setattr(tunnel, "readiness", lambda **kw: good)
    monkeypatch.setattr(tunnel, "_client_binary", lambda which: "/trusted/tunnel-client")
    tid = "tunnel_" + "a" * 32
    configured = tunnel.owner_action(
        "configure", tunnel_id=tid, run=command,
        owner_root=tmp_path / "owner", env={"HOME": "/tmp", "GITHUB_TOKEN": "HIDDEN"})
    assert configured["status"] == "PROFILE_CONFIGURED"
    args, kwargs = calls[0]
    assert args[:6] == ["/trusted/tunnel-client", "init", "--sample",
                        "sample_mcp_stdio_local", "--profile", tunnel.PROFILE]
    assert "--mcp-command" in args
    server = args[args.index("--mcp-command") + 1]
    assert "m1_foundation_tunnel_stdio.py" in server
    assert "m1_owner_delegated_mcp_stdio.py" not in server
    assert "sk-private-runtime-canary" not in str(args)
    assert kwargs["env"]["CONTROL_PLANE_API_KEY"] == "sk-private-runtime-canary"
    assert "GITHUB_TOKEN" not in kwargs["env"]
    assert "PRIVATE_TUNNEL_DIAGNOSTIC" not in json.dumps(configured)
    assert configured["remote_chatgpt_connection_verified"] is False


def test_missing_id_or_key_never_initializes_profile(monkeypatch):
    monkeypatch.setattr(tunnel, "readiness", lambda **kw: {
        "status": "READY_FOR_OWNER_SETUP", "reason": "NONE"})
    calls = []
    def no_key(argv, **kw):
        calls.append(argv)
        return SimpleNamespace(returncode=1, stdout="")
    bad = tunnel.owner_action("configure", tunnel_id="owner-claimed",
                              run=no_key)
    assert bad["reason"] == "EXACT_TUNNEL_ID_REQUIRED"
    assert calls == []
    bad = tunnel.owner_action("configure", tunnel_id="tunnel_" + "f"*32,
                              run=no_key)
    assert bad["reason"] == "OWNER_KEYCHAIN_RUNTIME_KEY_REQUIRED"
    assert calls == [["/usr/bin/security", "find-generic-password",
                      "-s", tunnel.KEYCHAIN_SERVICE, "-w"]]


def test_wrapper_drops_all_parent_tokens_and_has_fixed_readonly_server(monkeypatch, tmp_path):
    captured = []
    def fake_exec(exe, argv, env):
        captured.append((exe, argv, env))
    stat_row = SimpleNamespace(st_mode=stat.S_IFREG | 0o600,
                               st_uid=501, st_size=100)
    monkeypatch.setattr(wrapper.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(wrapper.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(wrapper.os, "getuid", lambda: 501)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 501)
    monkeypatch.setattr(wrapper.sys, "argv", ["fixed-launcher"])
    with mock.patch.object(Path, "lstat", return_value=stat_row), \
         mock.patch.object(Path, "is_file", return_value=True):
        wrapper.launch(
            root=tmp_path, executable="/trusted/python3",
            environ={"HOME": "/Users/owner", "LANG": "ja_JP.UTF-8",
                     "CONTROL_PLANE_API_KEY": "PRIVATE_TUNNEL_KEY",
                     "GITHUB_TOKEN": "PRIVATE_GITHUB",
                     "OPENAI_API_KEY": "PRIVATE_OPENAI",
                     "FOUNDATION_TUNNEL_ID": "PRIVATE_ID",
                     "PYTHONPATH": "/private/injection"},
            execve=fake_exec)
    assert len(captured) == 1
    exe, argv, env = captured[0]
    assert exe == "/trusted/python3"
    assert argv == [exe, "-B", str(tmp_path / "scripts" / "foundation_mcp_stdio.py")]
    assert set(env) == {"HOME", "LANG", "PYTHONDONTWRITEBYTECODE"}
    assert "PRIVATE_" not in json.dumps(env)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"


def test_wrapper_never_allows_arguments_or_non_owner(monkeypatch):
    monkeypatch.setattr(wrapper.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(wrapper.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(wrapper.os, "getuid", lambda: 501)
    monkeypatch.setattr(wrapper.os, "geteuid", lambda: 501)
    monkeypatch.setattr(wrapper.sys, "argv", ["wrapper", "--enable-local-development"])
    with pytest.raises(PermissionError, match="OWNER_M1_FIXED"):
        wrapper.launch(execve=lambda *a: pytest.fail("must not exec"))


def test_tunnel_readiness_is_fixed_owner_issue_read_only():
    from pathlib import Path
    from scripts import m1_development_bridge as bridge
    body = '<!-- foundation-m1-bridge: {"version":1,"operation":"tunnel-readiness"} -->'
    assert bridge.parse_request("Foundation M1 Bridge: tunnel-readiness", body) == "tunnel-readiness"
    with pytest.raises(bridge.BridgeDenied):
        bridge.parse_request("Foundation M1 Bridge: tunnel-readiness",
                             body.replace('"} -->', '","key":"private"} -->'))
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/m1-development-bridge.yml").read_text()
    assert workflow.count("github.event.issue.title == 'Foundation M1 Bridge: tunnel-readiness'") == 1
    assert "github.event.issue.user.login == 'quest7070-debug'" in workflow
    assert "runs-on: [self-hosted, macOS, ARM64]" in workflow


def test_platform_tunnel_ids_keep_official_opaque_namespaces_without_shell_chars():
    # Tunnel IDs are opaque: 32 lowercase alphanumeric characters, optionally
    # preceded by a four-character lowercase/digit namespace. Not just hex.
    valid = [
        "tunnel_" + "a" * 32,
        "tunnel_" + "z" * 32,
        "tunnel_ab12_" + "g" * 32,
    ]
    for value in valid:
        assert tunnel.TUNNEL_RE.fullmatch(value)
    invalid = [
        "tunnel_ABC_" + "a" * 32,
        "tunnel_" + "A" * 32,
        "tunnel_" + "a" * 31,
        "tunnel_abc_" + "a" * 32,
        "tunnel_abcde_" + "a" * 32,
        "tunnel_" + "a" * 32 + ";echo secret",
        "../tunnel_" + "a" * 32,
    ]
    for value in invalid:
        assert tunnel.TUNNEL_RE.fullmatch(value) is None


def test_tunnel_doctor_and_run_use_private_ephemeral_health_port(monkeypatch, tmp_path):
    from types import SimpleNamespace
    seen = []
    monkeypatch.setattr(tunnel, "readiness", lambda **_: {
        "status": "READY_FOR_OWNER_SETUP", "reason": "NONE",
        "remote_chatgpt_connection_verified": False})
    monkeypatch.setattr(tunnel, "_client_binary", lambda _: "/trusted/tunnel-client")

    def fake_run(argv, **kwargs):
        if argv[0] == "/usr/bin/security":
            return SimpleNamespace(returncode=0, stdout="sk-private-runtime-canary")
        seen.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    for mode in ("doctor", "run"):
        result = tunnel.owner_action(mode, run=fake_run, owner_root=tmp_path,
                                     env={"HOME": "/tmp", "HEALTH_LISTEN_ADDR": ":8080"})
        assert result["status"] in ("DOCTOR_PASSED", "CLIENT_EXITED_CLEANLY")
    assert len(seen) == 2
    for argv, kwargs in seen:
        assert argv[0] == "/trusted/tunnel-client"
        assert kwargs["env"]["HEALTH_LISTEN_ADDR"] == "127.0.0.1:0"
        assert kwargs["env"]["CONTROL_PLANE_API_KEY"] == "sk-private-runtime-canary"
        assert "GITHUB_TOKEN" not in kwargs["env"]
