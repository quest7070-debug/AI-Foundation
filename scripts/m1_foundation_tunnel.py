"""Owner-local, zero-model-call Secure MCP Tunnel setup for Foundation.

Use the EXISTING foundation_status-only stdio MCP server through a dedicated
OpenAI tunnel-client profile. No public port, no Kandev lifecycle dependency,
no Guard/9B/KLM/Native write, no automatic credential creation or paid API.
The remote ChatGPT plugin registration is a distinct owner UI operation.

Only an interactive M1 owner may configure/doctor/run a tunnel. GitHub Issue
diagnostics may invoke readiness() only: never Keychain, client init or run.
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
import stat
import subprocess
import sys

PROFILE = "foundation-readonly"
KEYCHAIN_SERVICE = "ai-foundation-tunnel-control-plane-runtime"
TUNNEL_RE = re.compile(r"tunnel_(?:[a-z0-9]{4}_)?[a-z0-9]{32}\Z")
SOURCE_NAMES = ("scripts/foundation_mcp_stdio.py",
                "scripts/m1_foundation_tunnel_stdio.py")
PYTHON = "/opt/homebrew/bin/python3.12"


def _trusted_bytes(path):
    info = Path(path).lstat()
    if (not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o022
            or not 0 < info.st_size <= 131072):
        raise ValueError("UNTRUSTED_OWNER_SOURCE")
    return Path(path).read_bytes()


def _client_binary(which=shutil.which):
    found = which("tunnel-client")
    if not found:
        for candidate in ("/opt/homebrew/bin/tunnel-client",
                          "/usr/local/bin/tunnel-client"):
            if Path(candidate).exists():
                found = candidate
                break
    if type(found) is not str or not os.path.isabs(found):
        return None
    try:
        actual = Path(found).resolve(strict=True)
        info = actual.stat()
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid not in (0, os.getuid())
                or info.st_mode & 0o022
                or not os.access(actual, os.X_OK)):
            return None
    except (OSError, ValueError):
        return None
    return str(actual)


def _installed_source(reviewed):
    """Prefer the unchanged, exact-commit owner private tunnel worktree."""
    fallback = Path.home() / "Develop" / "AI-Foundation"
    try:
        p = subprocess.run(
            ["/usr/bin/git", "-C", str(reviewed), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=False, timeout=3)
        sha = p.stdout.strip()
        if p.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha):
            staged = Path.home() / ".ai-foundation-tunnel-sources" / sha
            if staged.exists() and not staged.is_symlink():
                info = staged.lstat()
                if stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid():
                    check = subprocess.run(
                        ["/usr/bin/git", "-C", str(staged), "rev-parse", "HEAD"],
                        capture_output=True, text=True, timeout=3, check=False)
                    if check.returncode == 0 and check.stdout.strip() == sha:
                        return staged
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return fallback


def readiness(*, checkout=None, owner_root=None, which=shutil.which):
    """Non-secret evidence only, safe for the existing read-only M1 bridge."""
    reviewed = (Path(__file__).resolve().parents[1]
                if checkout is None else Path(checkout))
    installed = (_installed_source(reviewed)
                 if owner_root is None else Path(owner_root))
    matched = True
    try:
        for name in SOURCE_NAMES:
            if sha256(_trusted_bytes(reviewed / name)).digest() != sha256(
                    _trusted_bytes(installed / name)).digest():
                matched = False
    except (OSError, ValueError):
        matched = False
    executable = _client_binary(which)
    owner = (platform.system() == "Darwin"
             and platform.machine() in ("arm64", "aarch64")
             and os.getuid() == 501 and os.geteuid() == os.getuid())
    ready = owner and matched and executable is not None and Path(PYTHON).is_file()
    if not owner:
        reason = "OWNER_M1_REQUIRED"
    elif not matched:
        reason = "OWNER_SOURCE_INSTALL_REQUIRED"
    elif executable is None:
        reason = "TUNNEL_CLIENT_NOT_INSTALLED_OR_UNTRUSTED"
    elif not Path(PYTHON).is_file():
        reason = "PINNED_PYTHON_NOT_INSTALLED"
    else:
        reason = "NONE"
    return {
        "status": "READY_FOR_OWNER_SETUP" if ready else "BLOCKED",
        "reason": reason,
        "owner_source_matches_main": matched,
        "tunnel_client_present": executable is not None,
        "dedicated_profile": PROFILE,
        "transport": "private-outbound-stdio",
        "tool_scope": "foundation_status_ONLY",
        "remote_chatgpt_connection_verified": False,
        "control_plane_credential_verified": False,
        "model_calls": 0, "native_effects": 0, "service_mutations": 0,
    }


def _keychain_runtime_key(*, run=subprocess.run):
    try:
        outcome = run(
            ["/usr/bin/security", "find-generic-password",
             "-s", KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, check=False, timeout=8)
        if (outcome.returncode == 0 and type(outcome.stdout) is str
                and 12 <= len(outcome.stdout.strip()) <= 1024):
            return outcome.stdout.strip()
    except (OSError, subprocess.TimeoutExpired, TypeError, AttributeError):
        pass
    return None


def owner_action(mode, *, tunnel_id=None, env=None, run=subprocess.run,
                 which=shutil.which, checkout=None, owner_root=None):
    """Explicit local-only action; return fixed codes, never client or key output."""
    if mode not in ("configure", "doctor", "run"):
        raise ValueError("UNSUPPORTED_TUNNEL_MODE")
    state = readiness(checkout=checkout, owner_root=owner_root, which=which)
    if state["status"] != "READY_FOR_OWNER_SETUP":
        return state
    if mode == "configure" and (type(tunnel_id) is not str or
                                TUNNEL_RE.fullmatch(tunnel_id) is None):
        return {**state, "status": "BLOCKED", "reason": "EXACT_TUNNEL_ID_REQUIRED"}
    key = _keychain_runtime_key(run=run)
    if key is None:
        return {**state, "status": "BLOCKED", "reason": "OWNER_KEYCHAIN_RUNTIME_KEY_REQUIRED"}
    owner_root = (_installed_source(Path(__file__).resolve().parents[1]
                                     if checkout is None else Path(checkout))
                  if owner_root is None else Path(owner_root))
    argv = [_client_binary(which)]
    if mode == "configure":
        cmd = shlex.join([PYTHON, "-B",
                          str(owner_root / "scripts" / "m1_foundation_tunnel_stdio.py")])
        argv += ["init", "--sample", "sample_mcp_stdio_local",
                 "--profile", PROFILE, "--tunnel-id", tunnel_id,
                 "--mcp-command", cmd]
    else:
        argv += ["doctor" if mode == "doctor" else "run",
                 "--profile", PROFILE]
        if mode == "doctor":
            argv += ["--explain"]
    incoming = os.environ if env is None else env
    child_env = {k: incoming[k] for k in
                 ("HOME", "USER", "PATH", "TMPDIR", "LANG", "LC_ALL")
                 if type(incoming.get(k)) is str and incoming[k]}
    child_env["CONTROL_PLANE_API_KEY"] = key
    if mode in ("doctor", "run"):
        # This host already has another owner service on 127.0.0.1:8080.
        # Scope only the tunnel health UI to a free loopback port, never expose it.
        child_env["HEALTH_LISTEN_ADDR"] = "127.0.0.1:0"
    try:
        # The tunnel binary may print credentials or request metadata; never
        # expose stdout/stderr in GitHub, logs, or the owner's CLI summary.
        if mode == "run":
            result = run(argv, env=child_env, check=False,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            result = run(argv, env=child_env, check=False, timeout=30,
                         capture_output=True, text=True)
        success = type(result.returncode) is int and result.returncode == 0
    except (OSError, subprocess.TimeoutExpired, TypeError, AttributeError):
        success = False
    return {**state, "status": (
        {"configure": "PROFILE_CONFIGURED", "doctor": "DOCTOR_PASSED",
         "run": "CLIENT_EXITED_CLEANLY"}[mode] if success else "BLOCKED"),
        "reason": "NONE" if success else "TUNNEL_CLIENT_OPERATION_UNVERIFIED",
        # Even a successful tunnel doctor never proves a ChatGPT plugin call.
        "remote_chatgpt_connection_verified": False,
        "control_plane_credential_verified": False}


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Foundation owner-only readonly tunnel")
    parser.add_argument("mode", choices=("status", "configure", "doctor", "run"))
    args = parser.parse_args()
    if args.mode == "status":
        result = readiness()
    else:
        result = owner_action(
            args.mode, tunnel_id=os.environ.get("FOUNDATION_TUNNEL_ID"))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {
        "READY_FOR_OWNER_SETUP", "PROFILE_CONFIGURED", "DOCTOR_PASSED",
        "CLIENT_EXITED_CLEANLY"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
