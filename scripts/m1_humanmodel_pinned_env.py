#!/usr/bin/env python3
"""One owner-requested, model-free provisioning for a pinned HumanModel runtime.

Only exact main source, owner Issue, frozen uv.lock, private local environment.
No Operator interpreter modification, no model call, no HumanModel records.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import m1_development_bridge as bridge

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 HumanModel synthetic 9B E2E"
TITLE = "Foundation M1 HumanModel: prepare frozen local runtime"
BODY = "<!-- foundation-humanmodel-pinned-runtime:v1 -->"
MARKER = "<!-- foundation-humanmodel-pinned-runtime-receipt:v1:"
PACKAGE = "pydantic-ai-slim"
VERSION = "2.47.0"
PARENT_NAME = "Library/Application Support/AI-Foundation/humanmodel-pinned"
MANIFEST_NAME = "runtime-manifest-v1.json"


def parent_path():
    return Path.home() / PARENT_NAME


def event_authorized(event, live):
    issue = event.get("issue") if type(event) is dict else None
    return (
        type(issue) is dict and event.get("action") == "opened"
        and event.get("repository", {}).get("full_name") == REPO
        and event.get("sender", {}).get("login") == OWNER
        and type(issue.get("number")) is int and issue["number"] > 0
        and issue.get("user", {}).get("login") == OWNER
        and issue.get("state") == "open"
        and issue.get("title") == TITLE and issue.get("body") == BODY
        and type(live) is dict
        and all(live.get(k) == issue.get(k)
                for k in ("number", "state", "title", "body"))
        and live.get("user", {}).get("login") == OWNER
    )


def owner_context():
    if (platform.system() != "Darwin"
            or platform.machine() not in ("arm64", "aarch64")
            or os.getuid() != os.geteuid() or os.getuid() != 501
            or os.environ.get("GITHUB_REPOSITORY") != REPO
            or os.environ.get("GITHUB_WORKFLOW") != WORKFLOW
            or os.environ.get("GITHUB_EVENT_NAME") != "issues"
            or os.environ.get("GITHUB_ACTOR") != OWNER):
        raise PermissionError("OWNER_M1_WORKFLOW_REQUIRED")
    token, event_path = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_EVENT_PATH")
    if not token or not event_path:
        raise PermissionError("OWNER_EVENT_REQUIRED")
    event = json.loads(Path(event_path).read_text())
    number = event.get("issue", {}).get("number")
    if type(number) is not int or number < 1:
        raise PermissionError("OWNER_ISSUE_REQUIRED")
    prefix = "/repos/" + REPO + "/issues/" + str(number)
    if not event_authorized(event, bridge._github_api("GET", prefix, token)):
        raise PermissionError("OWNER_ISSUE_CHANGED")
    head = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=8, check=False)
    if (head.returncode != 0
            or head.stdout.strip() != os.environ.get("GITHUB_SHA")):
        raise PermissionError("PINNED_MAIN_CHECKOUT_REQUIRED")
    return token, prefix, number


def secure_parent(*, create=False):
    parent = parent_path()
    # Reject symlink escape anywhere along Foundation's private subtree.
    home = Path.home()
    for part in ("Library", "Application Support", "AI-Foundation", "humanmodel-pinned"):
        home = home / part
        if home.is_symlink():
            raise PermissionError("RUNTIME_PARENT_SYMLINK")
    if create:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        parent.chmod(0o700)
    info = parent.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise PermissionError("RUNTIME_PARENT_UNTRUSTED")
    env = parent / "venv"
    if env.is_symlink():
        raise PermissionError("RUNTIME_VENV_SYMLINK")
    if env.exists():
        meta = env.lstat()
        if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid()
                or meta.st_mode & 0o022):
            raise PermissionError("RUNTIME_VENV_UNTRUSTED")
    return parent


def source_signature():
    return {
        "uv_lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "project_sha256": hashlib.sha256((ROOT / "pyproject.toml").read_bytes()).hexdigest(),
    }


def runtime_ready():
    """Read-only exact source/runtime integrity check. Never auto-install."""
    try:
        parent = secure_parent()
        env = parent / "venv"
        marker = parent / MANIFEST_NAME
        if marker.is_symlink() or not marker.is_file():
            return None
        meta = marker.stat()
        if (meta.st_uid != os.getuid() or meta.st_mode & 0o077
                or meta.st_size > 2048):
            return None
        data = json.loads(marker.read_text())
        if (type(data) is not dict or data.get("schema") != 1
                or data.get("package") != PACKAGE
                or data.get("version") != VERSION
                or any(data.get(k) != v for k, v in source_signature().items())):
            return None
        py = env / "bin/python"
        resolved = py.resolve(strict=True)
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022:
            return None
        check = subprocess.run(
            [str(py), "-I", "-c",
             "import sys; from importlib.metadata import version; "
             "assert sys.version_info >= (3,12); "
             "assert version('pydantic-ai-slim')=='2.47.0'"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
        return py if check.returncode == 0 else None
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired):
        return None


def finalize(*, sync_outcome=None):
    token, prefix, number = owner_context()
    history = bridge._github_api("GET", prefix + "/comments?per_page=100", token)
    if (type(history) is not list or len(history) >= 100
            or any(type(c) is dict and MARKER + str(number) + " -->" in c.get("body", "")
                   for c in history)):
        raise PermissionError("DUPLICATE_OR_UNBOUNDED_RECEIPT")
    result = {"schema": 1, "status": "BLOCKED",
              "reason": "PINNED_RUNTIME_NOT_READY", "model_calls": 0,
              "owner_records_read": 0, "paid_calls": 0}
    try:
        # This package may still exist in an older environment after a failed
        # download/lease/sync. Only this run's successful frozen sync can bind
        # its environment to the current lock; preserve any old manifest.
        if sync_outcome != "success":
            result["reason"] = "DEPENDENCY_SYNC_NOT_SUCCESSFUL"
            raise ValueError("DEPENDENCY_SYNC_NOT_SUCCESSFUL")
        parent = secure_parent()
        py = parent / "venv/bin/python"
        # Verify installed interpreter before writing the private manifest.
        check = subprocess.run(
            [str(py), "-I", "-c",
             "import sys; from importlib.metadata import version; "
             "assert sys.version_info >= (3,12); "
             "assert version('pydantic-ai-slim')=='2.47.0'"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=12)
        if check.returncode != 0:
            raise ValueError("PINNED_RUNTIME_IMPORT_FAILED")
        bundle = {
            "schema": 1, "package": PACKAGE, "version": VERSION,
            **source_signature()
        }
        fd, tmp = tempfile.mkstemp(prefix=".hm-venv-", dir=parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(bundle, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, parent / MANIFEST_NAME)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        if runtime_ready() is None:
            raise ValueError("PINNED_RUNTIME_POSTREAD_UNVERIFIED")
        result.update({"status": "PINNED_RUNTIME_READY", "reason": "VERIFIED"})
    except (OSError, ValueError, RuntimeError, PermissionError,
            subprocess.TimeoutExpired):
        pass
    bridge._github_api("POST", prefix + "/comments", token, {
        "body": MARKER + str(number) + " -->\n\n~~~json\n"
                + json.dumps(result, sort_keys=True) + "\n~~~",
    })
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "PINNED_RUNTIME_READY" else 1


def main():
    if sys.argv[1:] == ["preflight"]:
        owner_context()
        secure_parent(create=True)
        print("PINNED_RUNTIME_PREFLIGHT_READY")
        return 0
    if sys.argv[1:] == ["finalize"]:
        return finalize(sync_outcome=os.environ.get("FOUNDATION_HM_SYNC_OUTCOME"))
    raise ValueError("INVALID_OPERATION")


if __name__ == "__main__":
    raise SystemExit(main())
