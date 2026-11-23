#!/usr/bin/env python3
"""Fast owner-only real HumanModel E2E, using ONLY the installed Operator Python.

No environment installation, model selection, data output or process eviction.
A missing exact runtime returns fixed preflight status without reading the View.
All private inference still happens in the existing real View E2E script.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import m1_development_bridge as bridge
import m1_human_model_activation_readiness as readiness
from m1_humanmodel_pinned_env import runtime_ready

# This entry must remain stdlib-only even when the host Python has no
# Pydantic. The child revalidates the exact same owner event independently.
REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 HumanModel synthetic 9B E2E"
TITLE = "Foundation HumanModel 9B E2E: current approved view"
BODY = "<!-- foundation-humanmodel-real-view-9b:v1 -->"
MARKER = "<!-- foundation-humanmodel-real-view-9b-receipt:v1:"


def exact_owner_event(event, live):
    issue = event.get("issue") if type(event) is dict else None
    return (
        type(issue) is dict and event.get("action") == "opened"
        and event.get("repository", {}).get("full_name") == REPO
        and event.get("sender", {}).get("login") == OWNER
        and type(issue.get("number")) is int and issue["number"] > 0
        and issue.get("state") == "open"
        and issue.get("user", {}).get("login") == OWNER
        and issue.get("title") == TITLE and issue.get("body") == BODY
        and type(live) is dict
        and all(live.get(k) == issue.get(k)
                for k in ("number", "state", "title", "body"))
        and live.get("user", {}).get("login") == OWNER
    )

def installed_python():
    # Prefer the host-owned one-time frozen isolated runtime. Never mutate the
    # installed Operator's Python or install during an owner answer request.
    prepared = runtime_ready()
    if prepared is not None:
        return prepared
    if readiness.installed_paths() is None:
        return None
    path = Path.home() / "Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist"
    row = plistlib.loads(path.read_bytes())
    args = row.get("ProgramArguments")
    if type(args) is not list or not args:
        return None
    # The already-reviewed Operator launch contract is the sole interpreter
    # source: never select from $PATH or model/Issue text.
    candidate = Path(args[0])
    if args[0] == "/usr/bin/env" and len(args) > 1:
        candidate = Path(args[1])
    if (not candidate.is_absolute() or candidate.name not in (
            "python", "python3", "python3.12", "Python")):
        return None
    original = candidate.resolve(strict=True)
    info = original.stat()
    if (not stat.S_ISREG(info.st_mode)
            or info.st_uid not in (0, os.getuid())
            or info.st_mode & 0o022
            or not info.st_mode & stat.S_IXUSR):
        return None
    return original


def main():
    if (platform.system() != "Darwin"
            or platform.machine() not in ("arm64", "aarch64")
            or os.getuid() != os.geteuid() or os.getuid() != 501
            or os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_WORKFLOW") != WORKFLOW
            or os.environ.get("GITHUB_EVENT_NAME") != "issues"
            or os.environ.get("GITHUB_ACTOR") != OWNER):
        raise PermissionError("OWNER_M1_REQUIRED")
    token, event_path = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_EVENT_PATH")
    if not token or not event_path:
        raise PermissionError("EXACT_OWNER_EVENT_REQUIRED")
    event = json.loads(Path(event_path).read_text())
    issue = event.get("issue", {})
    number = issue.get("number")
    if type(number) is not int or number < 1:
        raise PermissionError("OWNER_ISSUE_MISSING")
    prefix = "/repos/" + REPO + "/issues/" + str(number)
    live = bridge._github_api("GET", prefix, token)
    if not exact_owner_event(event, live):
        raise PermissionError("OWNER_ISSUE_CHANGED")
    comments = bridge._github_api("GET", prefix + "/comments?per_page=100", token)
    if (type(comments) is not list or len(comments) >= 100
            or any(type(c) is dict and MARKER + str(number) + " -->" in c.get("body", "")
                   for c in comments)):
        raise PermissionError("REPLAY_OR_UNBOUNDED_RECEIPT")

    reason = "INSTALLED_OPERATOR_PYTHON_UNAVAILABLE"
    try:
        python = installed_python()
    except (OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException):
        python = None
    if python is not None:
        # The production interpreter must already satisfy this exact frozen
        # source contract. Never use pip/uv or a different local LLM.
        try:
            check = subprocess.run(
                [str(python), "-I", "-c",
                 "import sys; from importlib.metadata import version; "
                 "assert sys.version_info >= (3,12); "
                 "assert version('pydantic-ai-slim')=='2.47.0'"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
            runtime_ready = check.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            runtime_ready = False
        if runtime_ready:
            command = [
                str(python), "-B", str(ROOT / "scripts/host_compute_lease.py"),
                "run", "--max-wait-seconds", "35", "--",
                str(python), "-B", str(ROOT / "scripts/m1_owner_humanmodel_real_e2e.py"),
            ]
            try:
                # Suppress output from the private source/model path; the
                # child itself writes only allowlisted metadata to GitHub.
                child = subprocess.run(command, stdout=subprocess.DEVNULL,
                                       stderr=subprocess.DEVNULL, timeout=385)
                reason = "EXISTING_RUNTIME_PROBE_FAILED"
                if child.returncode == 0:
                    return 0
            except (OSError, subprocess.TimeoutExpired):
                reason = "EXISTING_RUNTIME_PROBE_UNAVAILABLE"
        else:
            reason = "PINNED_OPERATOR_DEPENDENCY_UNAVAILABLE"

    # If the child already emitted the authoritative receipt, preserve it;
    # never post conflicting status or issue an automatic second inference.
    updated = bridge._github_api("GET", prefix + "/comments?per_page=100", token)
    if any(type(c) is dict and MARKER + str(number) + " -->" in c.get("body", "")
           for c in updated):
        return 1
    bridge._github_api("POST", prefix + "/comments", token, {
        "body": MARKER + str(number) + " -->\n\n~~~json\n"
                + json.dumps({
                    "schema": 1, "status": "BLOCKED", "reason": reason,
                    "model_calls": "UNVERIFIED",
                    "no_private_content_export": True,
                    "owner_fidelity_accepted": False,
                }, sort_keys=True) + "\n~~~",
    })
    print(json.dumps({"status": "BLOCKED", "reason": reason}, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
