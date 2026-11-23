"""One-shot owner-controlled switch of ONE existing Foundation MCP tunnel.

Only the authenticated owner PR #1321 workflow may invoke. Stage an immutable
source worktree, verify the local guarded stdio protocol before any mutation,
preflight the existing profile and Keychain, then switch the one tunnel client.
Never touch Operator/Guard/KLM/9B processes or invent new tunnel credentials.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time

if __package__:
    from . import m1_guarded_tunnel as tunnel
    from .m1_foundation_tunnel_stage import stage_source
    from .m1_p4_mcp_stdio_e2e import _request
else:
    import m1_guarded_tunnel as tunnel
    from m1_foundation_tunnel_stage import stage_source
    from m1_p4_mcp_stdio_e2e import _request

ROOT = Path(__file__).resolve().parents[1]
LABEL = "dev.quest7070.ai-foundation.tunnel-guarded"
PR = 1321
OWNER = "quest7070-debug"


class CutoverDenied(RuntimeError):
    pass


def require(check, reason):
    if not check:
        raise CutoverDenied(reason)


def owner_event():
    require(platform.system() == "Darwin"
            and platform.machine() in ("arm64", "aarch64")
            and os.getuid() == os.geteuid() == 501,
            "OWNER_M1_ONLY")
    require(os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
            and os.environ.get("GITHUB_REPOSITORY") == "quest7070-dev/AI-Foundation",
            "EXACT_OWNER_PR_REQUIRED")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    require(event.get("action") in ("opened", "synchronize"),
            "EXACT_OWNER_PR_REQUIRED")
    pr = event.get("pull_request", {})
    require(type(pr) is dict and pr.get("number") == PR
            and pr.get("user", {}).get("login") == OWNER
            and pr.get("head", {}).get("repo", {}).get("full_name")
                == "quest7070-dev/AI-Foundation"
            and pr.get("head", {}).get("ref")
                == "feat/guarded-owner-mcp-separate-tunnel-20261115",
            "EXACT_OWNER_PR_REQUIRED")
    actual = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
                            capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    require(re.fullmatch(r"[0-9a-f]{40}", actual) is not None
            and actual == pr.get("head", {}).get("sha"),
            "EXACT_PR_HEAD_REQUIRED")


def child_smoke(stage):
    """Before any cutover, verify the actual owner-bound MCP child and tools."""
    reqs = [_request(1, "server/discover"),
            _request(2, "tools/list"),
            _request(3, "tools/call", name="foundation_status", arguments={})]
    env = {k: os.environ[k] for k in ("HOME", "USER", "PATH", "TMPDIR", "LANG")
           if type(os.environ.get(k)) is str and os.environ[k]}
    try:
        out = subprocess.run(
            [tunnel.PYTHON, "-B",
             str(stage / "scripts" / "m1_guarded_tunnel_stdio.py")],
            input="\n".join(json.dumps(q) for q in reqs)+"\n",
            capture_output=True, text=True, timeout=25, check=False, env=env)
        rows = [json.loads(x) for x in out.stdout.splitlines()]
        require(out.returncode == 0 and len(rows) == len(reqs)
                and [row.get("id") for row in rows] == [1, 2, 3],
                "GUARDED_STDIO_UNAVAILABLE")
        discovery = rows[0].get("result", {})
        toolset = rows[1].get("result", {}).get("tools", [])
        names = {x.get("name") for x in toolset if type(x) is dict}
        require("2026-07-28" in discovery.get("supportedVersions", [])
                and {"foundation_status", "development_status", "development_run"}
                    <= names, "GUARDED_TOOLS_NOT_READY")
        answer = rows[2].get("result", {})
        require(answer.get("isError") is False
                and len(answer.get("content", [])) > 0,
                "GUARDED_STATUS_UNVERIFIED")
    except (OSError, ValueError, TypeError, subprocess.TimeoutExpired) as error:
        raise CutoverDenied("GUARDED_STDIO_UNAVAILABLE") from None


def active_client_pids():
    # Narrow to the exact already-registered profile. Never stop 9B, Operator,
    # MainPC, or any other tunnel client. ps is owner-local; no issue text in argv.
    raw = subprocess.run(["/bin/ps", "-axo", "pid=,uid=,command="],
                         capture_output=True, text=True, check=True, timeout=5).stdout
    found = []
    for line in raw.splitlines():
        m = re.match(r"\s*(\d+)\s+(\d+)\s+(.+)", line)
        if not m or int(m.group(2)) != os.getuid():
            continue
        command = m.group(3)
        if re.search(r"(?:^|/)tunnel-client\s+run\s+--profile(?:=|\s+)foundation-readonly(?:\s|$)",
                     command):
            found.append(int(m.group(1)))
    return found


def replace_file(path, raw):
    # Preserve existing profile without ever displaying ID or any other data.
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            tmp = Path(out.name)
            os.fchmod(out.fileno(), 0o600)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)


def plist_path():
    return Path.home() / "Library" / "LaunchAgents" / (LABEL + ".plist")


def prior_rollback_agent():
    """Accept only our exact previous owner rollback LaunchAgent, never a foreign one."""
    path = plist_path()
    if not path.exists() and not path.is_symlink():
        return False
    try:
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                and info.st_mode & 0o077 == 0 and not path.is_symlink(),
                "FOREIGN_TUNNEL_AGENT_REVIEW_REQUIRED")
        args = plistlib.loads(path.read_bytes()).get("ProgramArguments")
        require(type(args) is list and len(args) == 4
                and args[0] == tunnel.PYTHON and args[1] == "-B"
                and args[3] == "run", "FOREIGN_TUNNEL_AGENT_REVIEW_REQUIRED")
        source = Path(args[2])
        base = Path.home() / ".ai-foundation-tunnel-sources"
        require(source.name == "m1_foundation_tunnel.py"
                and source.parent.name == "scripts"
                and source.parent.parent.parent == base
                and re.fullmatch(r"[0-9a-f]{40}", source.parent.parent.name)
                and source.is_file() and not source.is_symlink(),
                "FOREIGN_TUNNEL_AGENT_REVIEW_REQUIRED")
        return True
    except (OSError, ValueError, plistlib.InvalidFileException):
        raise CutoverDenied("FOREIGN_TUNNEL_AGENT_REVIEW_REQUIRED") from None


def launchctl(*args):
    return subprocess.run(["/bin/launchctl", *args], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, check=False, timeout=12)


def owner_managed(label=LABEL):
    row = subprocess.run(["/bin/launchctl", "print",
                          "gui/" + str(os.getuid()) + "/" + label],
                         capture_output=True, text=True, check=False, timeout=5)
    return row.returncode == 0 and "state = running" in row.stdout


def installed_agent(stage, *, guarded):
    path = plist_path()
    require(path.parent.is_dir() and not path.is_symlink(),
            "OWNER_LAUNCHAGENTS_UNVERIFIED")
    mode = "m1_guarded_tunnel.py" if guarded else "m1_foundation_tunnel.py"
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [tunnel.PYTHON, "-B", str(stage / "scripts" / mode), "run"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 20,
        "ProcessType": "Background",
        "EnvironmentVariables": {
            "HOME": str(Path.home()),
            "USER": os.environ.get("USER", ""),
            "PATH": "/opt/homebrew/bin:/usr/bin:/bin",
        },
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    })


def launch_agent(stage, *, guarded):
    path = plist_path()
    require(not path.is_symlink() and not path.exists(),
            "TUNNEL_AGENT_ALREADY_EXISTS")
    replace_file(path, installed_agent(stage, guarded=guarded))
    result = launchctl("bootstrap", "gui/" + str(os.getuid()), str(path))
    if result.returncode:
        path.unlink(missing_ok=True)
        raise CutoverDenied("OWNER_LAUNCHD_BOOTSTRAP_DENIED")
    for _ in range(10):
        if owner_managed():
            return True
        time.sleep(1)
    raise CutoverDenied("OWNER_LAUNCHD_NOT_RUNNING")


def rollback(stage, original):
    path = plist_path()
    launchctl("bootout", "gui/" + str(os.getuid()) + "/" + LABEL)
    if path.exists() and not path.is_symlink():
        path.unlink()
    profile = Path.home() / ".config" / "tunnel-client" / (tunnel.PROFILE + ".yaml")
    replace_file(profile, original)
    # If the owner's previous foreground process automatically recovered,
    # do not spawn a second instance with its tunnel ID.
    for _ in range(6):
        if not active_client_pids():
            break
        time.sleep(1)
    if active_client_pids():
        return "PREVIOUS_PROCESS_STILL_RUNNING"
    try:
        launch_agent(stage, guarded=False)
    except (OSError, CutoverDenied, subprocess.TimeoutExpired):
        return "ORIGINAL_PROFILE_RESTORED_PROCESS_UNVERIFIED"
    return "ORIGINAL_READONLY_AGENT_RESTORED"


def switch():
    owner_event()
    require("TUNNEL_CLIENT_PROFILE_DIR" not in os.environ
            and "XDG_CONFIG_HOME" not in os.environ,
            "CUSTOM_TUNNEL_PROFILE_DIR_REVIEW_REQUIRED")
    current = tunnel._existing_tunnel_id()
    require(current is not None, "EXISTING_TUNNEL_ID_UNVERIFIED")
    p = Path.home() / ".config" / "tunnel-client" / (tunnel.PROFILE + ".yaml")
    original = tunnel._trusted_bytes(p)
    require(not p.is_symlink() and p.stat().st_uid == os.getuid(),
            "EXISTING_TUNNEL_PROFILE_UNTRUSTED")
    rollback_agent = prior_rollback_agent()
    require(rollback_agent or not owner_managed(),
            "FOREIGN_TUNNEL_AGENT_REVIEW_REQUIRED")
    old_pids = active_client_pids()
    require(len(old_pids) == 1, "EXISTING_CLIENT_PROCESS_NOT_UNIQUE")
    # Stage under the owner private worktree without moving main/working branch.
    staged = stage_source()
    require(staged.get("status") == "SOURCE_STAGED_VERIFIED",
            "PINNED_SOURCE_NOT_STAGED")
    stage = Path.home() / ".ai-foundation-tunnel-sources" / staged["revision"]
    require(tunnel.readiness()["status"] == "READY_FOR_OWNER_SETUP",
            "GUARDED_SOURCE_NOT_READY")
    child_smoke(stage)
    config = tunnel.owner_action("configure")
    if config["status"] != "EXISTING_PROFILE_REPOINTED":
        replace_file(p, original)
        raise CutoverDenied("OWNER_PROFILE_REPOINT_DENIED")
    doctor = tunnel.owner_action("doctor")
    if doctor["status"] != "DOCTOR_PASSED":
        replace_file(p, original)
        raise CutoverDenied("GUARDED_TUNNEL_DOCTOR_FAILED")
    # No destructive M1 service changes: signal the exact one old tunnel client.
    try:
        if rollback_agent:
            result = launchctl("bootout", "gui/" + str(os.getuid()) + "/" + LABEL)
            require(result.returncode == 0, "ORIGINAL_AGENT_BOOTOUT_DENIED")
            plist_path().unlink()
        if old_pids[0] in active_client_pids():
            os.kill(old_pids[0], signal.SIGTERM)
        for _ in range(12):
            if not active_client_pids():
                break
            time.sleep(1)
        require(not active_client_pids(), "OLD_CLIENT_DID_NOT_EXIT")
        launch_agent(stage, guarded=True)
        for _ in range(12):
            if len(active_client_pids()) == 1:
                break
            time.sleep(1)
        require(len(active_client_pids()) == 1,
                "GUARDED_CLIENT_PROCESS_NOT_UNIQUE")
        return {"status": "EXISTING_CONNECTION_SWITCHED_M1",
                "same_registered_tunnel": True, "status_tool_preserved": True,
                "new_connections": 0, "new_tunnel_ids": 0,
                "owner_local_guarded_tools_verified": True,
                "remote_chatgpt_tools_verified": False,
                "model_calls": 0, "main_branch_changed": False}
    except (CutoverDenied, OSError, subprocess.TimeoutExpired) as exc:
        reason = exc.args[0] if isinstance(exc, CutoverDenied) else (
            "CUTOVER_OS_OPERATION_DENIED" if isinstance(exc, OSError)
            else "CUTOVER_OPERATION_TIMEOUT")
        state = rollback(stage, original)
        return {"status": "ROLLED_BACK_OR_UNVERIFIED",
                "reason": reason,
                "rollback": state,
                "existing_tunnel_process_count": len(active_client_pids()),
                "same_registered_tunnel": True, "model_calls": 0,
                "remote_chatgpt_tools_verified": False}


if __name__ == "__main__":
    try:
        result = switch()
        print(json.dumps(result, sort_keys=True))
        if result["status"] != "EXISTING_CONNECTION_SWITCHED_M1":
            raise SystemExit(1)
    except (CutoverDenied, OSError, ValueError, TypeError, subprocess.TimeoutExpired) as exc:
        # Fixed, secret-free error code. Never print client/config/env output.
        label = exc.args[0] if isinstance(exc, CutoverDenied) else "CUTOVER_UNVERIFIED"
        print(json.dumps({"status": "BLOCKED", "reason": label,
                          "remote_chatgpt_tools_verified": False}))
        raise SystemExit(1)
