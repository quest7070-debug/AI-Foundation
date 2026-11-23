"""Upgrade the EXISTING Foundation Secure MCP Tunnel to bounded owner tools.

No second tunnel ID, profile, ChatGPT plugin, listener or approval database.
The original foundation_status tool remains available. Work actions require
existing owner Guard grants or fixed local tickets; neither is supplied by MCP.
A successful doctor never proves a remote caller or Work execution.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess

if __package__:
    from .m1_foundation_tunnel import (
        PYTHON, TUNNEL_RE, _client_binary, _installed_source, _keychain_runtime_key,
        _trusted_bytes,
    )
else:
    from m1_foundation_tunnel import (
        PYTHON, TUNNEL_RE, _client_binary, _installed_source, _keychain_runtime_key,
        _trusted_bytes,
    )

PROFILE = "foundation-readonly"
SOURCES = ("scripts/m1_guarded_tunnel.py",
           "scripts/m1_guarded_tunnel_stdio.py",
           "scripts/m1_owner_delegated_mcp_stdio.py",
           "scripts/foundation_mcp_stdio.py",
           "scripts/m1_development_ticket_factory.py")


def readiness(*, checkout=None, owner_root=None, which=shutil.which):
    reviewed = (Path(__file__).resolve().parents[1]
                if checkout is None else Path(checkout))
    installed = (_installed_source(reviewed)
                 if owner_root is None else Path(owner_root))
    matched = True
    try:
        for path in SOURCES:
            if sha256(_trusted_bytes(reviewed / path)).digest() != sha256(
                    _trusted_bytes(installed / path)).digest():
                matched = False
    except (OSError, ValueError):
        matched = False
    owner = (platform.system() == "Darwin"
             and platform.machine() in ("arm64", "aarch64")
             and os.getuid() == 501 and os.geteuid() == os.getuid())
    client = _client_binary(which)
    installed_python = Path(PYTHON).is_file()
    if not owner:
        reason = "OWNER_M1_REQUIRED"
    elif not matched:
        reason = "OWNER_SOURCE_INSTALL_REQUIRED"
    elif client is None:
        reason = "TUNNEL_CLIENT_NOT_INSTALLED_OR_UNTRUSTED"
    elif not installed_python:
        reason = "PINNED_PYTHON_NOT_INSTALLED"
    else:
        reason = "NONE"
    return {
        "status": "READY_FOR_OWNER_SETUP" if reason == "NONE" else "BLOCKED",
        "reason": reason,
        "profile": PROFILE,
        "tool_scope": "STATUS_AND_OWNER_GUARD_PINNED_DEVELOPMENT",
        "existing_tunnel_reused": True,
        "remote_caller_e2e_verified": False,
        "owner_source_matches_main": matched,
        "model_calls": 0, "native_effects": 0,
    }


def _existing_tunnel_id(*, env=None):
    """Reuse the existing local owner profile, without returning its ID.

    Refuse a custom command, ambiguous YAML or untrusted file rather than
    re-pointing a different tunnel. Official init writes the ID as a single
    unquoted scalar inside control_plane. No new admin/API key is requested.
    """
    incoming = os.environ if env is None else env
    home = incoming.get("HOME")
    if type(home) is not str or not Path(home).is_absolute():
        return None
    directory = incoming.get("TUNNEL_CLIENT_PROFILE_DIR")
    if not directory:
        xdg = incoming.get("XDG_CONFIG_HOME")
        directory = str(Path(xdg) / "tunnel-client") if xdg else str(
            Path(home) / ".config" / "tunnel-client")
    if not Path(directory).is_absolute():
        return None
    try:
        raw = _trusted_bytes(Path(directory) / (PROFILE + ".yaml")).decode("utf-8")
    except (OSError, ValueError, UnicodeError):
        return None
    if not ("m1_foundation_tunnel_stdio.py" in raw
            or "m1_guarded_tunnel_stdio.py" in raw):
        return None
    inside = False
    ids = []
    for line in raw.splitlines():
        if line == "control_plane:":
            inside = True
            continue
        if inside and line and not line[0].isspace() and not line.startswith("#"):
            inside = False
        if inside:
            match = re.fullmatch(
                r"""\s+tunnel_id:\s*(?:"(?P<dbl>tunnel_(?:[a-z0-9]{4}_)?[a-z0-9]{32})"|'(?P<sgl>tunnel_(?:[a-z0-9]{4}_)?[a-z0-9]{32})'|(?P<bare>tunnel_(?:[a-z0-9]{4}_)?[a-z0-9]{32}))\s*(?:#.*)?""",
                line)
            if match:
                value = match.group("dbl") or match.group("sgl") or match.group("bare")
                if TUNNEL_RE.fullmatch(value):
                    ids.append(value)
    return ids[0] if len(ids) == 1 else None


def owner_action(mode, *, tunnel_id=None, env=None, run=subprocess.run,
                 which=shutil.which, checkout=None, owner_root=None):
    if mode not in ("configure", "doctor", "run"):
        raise ValueError("UNSUPPORTED_EXISTING_TUNNEL_MODE")
    state = readiness(checkout=checkout, owner_root=owner_root, which=which)
    if state["status"] != "READY_FOR_OWNER_SETUP":
        return state
    incoming = os.environ if env is None else env
    if mode == "configure":
        observed_id = _existing_tunnel_id(env=incoming)
        if observed_id is None or (
                tunnel_id is not None and tunnel_id != observed_id):
            return {**state, "status": "BLOCKED",
                    "reason": "EXISTING_TUNNEL_PROFILE_NOT_VERIFIED"}
        tunnel_id = observed_id
    key = _keychain_runtime_key(run=run)
    if key is None:
        return {**state, "status": "BLOCKED", "reason": "OWNER_KEYCHAIN_RUNTIME_KEY_REQUIRED"}
    reviewed = (Path(__file__).resolve().parents[1]
                if checkout is None else Path(checkout))
    installed = (_installed_source(reviewed)
                 if owner_root is None else Path(owner_root))
    argv = [_client_binary(which)]
    if mode == "configure":
        command = shlex.join([PYTHON, "-B",
            str(installed / "scripts" / "m1_guarded_tunnel_stdio.py")])
        argv += ["init", "--force", "--sample", "sample_mcp_stdio_local",
                 "--profile", PROFILE, "--tunnel-id", tunnel_id,
                 "--mcp-command", command,
                 "--health-listen-addr", "127.0.0.1:0"]
    else:
        argv += ["doctor" if mode == "doctor" else "run",
                 "--profile", PROFILE]
        if mode == "doctor":
            argv.append("--explain")
    child_env = {k: incoming[k] for k in
                 ("HOME", "USER", "PATH", "TMPDIR", "LANG", "LC_ALL")
                 if type(incoming.get(k)) is str and incoming[k]}
    child_env["CONTROL_PLANE_API_KEY"] = key
    if mode in ("run", "doctor"):
        child_env["HEALTH_LISTEN_ADDR"] = "127.0.0.1:0"
    try:
        if mode == "run":
            result = run(argv, env=child_env, check=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            result = run(argv, env=child_env, check=False, timeout=30,
                         capture_output=True, text=True)
        passed = type(result.returncode) is int and result.returncode == 0
    except (OSError, subprocess.TimeoutExpired, TypeError, AttributeError):
        passed = False
    return {**state, "status": (
        {"configure": "EXISTING_PROFILE_REPOINTED", "doctor": "DOCTOR_PASSED",
         "run": "CLIENT_EXITED_CLEANLY"}[mode] if passed else "BLOCKED"),
        "reason": "NONE" if passed else "TUNNEL_CLIENT_OPERATION_UNVERIFIED",
        "remote_caller_e2e_verified": False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="M1 single existing MCP tunnel upgrade")
    parser.add_argument("mode", choices=("status", "configure", "doctor", "run"))
    args = parser.parse_args()
    result = (readiness() if args.mode == "status" else owner_action(
        args.mode, tunnel_id=os.environ.get("FOUNDATION_TUNNEL_ID")))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {
        "READY_FOR_OWNER_SETUP", "EXISTING_PROFILE_REPOINTED",
        "DOCTOR_PASSED", "CLIENT_EXITED_CLEANLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
