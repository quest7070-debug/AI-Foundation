#!/usr/bin/env python3
"""Install reviewed public CODE tickets into the existing M1 local MCP factory.

A one-time local checkout object import is NOT the development loop. The
owner's divergent main, existing tickets, Guard/Work, secrets and services are
left untouched. The installed ~/foundation CLI does inference/test/Guard on
M1 with Strata as optional remote-local CODE compute, no GitHub in edit loop.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from m1_development_ticket_factory import (
    _owner_file, _owner_manifest, _strict_json, _validate_ticket, _private_dir,
    MAX_OWNER_DEVELOPMENT_TICKETS,
)
from m1_direct_development import installed_config, write_private, git

BUNDLE = ROOT / "scripts/reviewed_strata_tickets.json"
OWNER_REPO = Path.home() / "Develop/AI-Foundation"
HEADER = "#!/bin/bash\n# Foundation owner direct development launcher v1\n"
# Only literal installer errors, not raw exceptions, may leave the owner M1.
_INSTALL_BLOCKERS = frozenset({
    "REVIEWED_TICKET_BUNDLE_INVALID", "REVIEWED_TICKET_COUNT_INVALID",
    "REVIEWED_TICKET_FIELDS_INVALID", "REVIEWED_TICKET_IDENTITY_INVALID",
    "REVIEWED_PUBLIC_FILE_UNAVAILABLE", "REVIEWED_PUBLIC_BLOB_MISMATCH",
    "OWNER_GIT_REPOSITORY_UNVERIFIED", "REVIEWED_WORKTREE_CHANGED",
    "REVIEWED_MAIN_CHECKOUT_REQUIRED", "REVIEWED_MAIN_COMMIT_UNAVAILABLE",
    "EXISTING_TICKET_MANIFEST_UNVERIFIED", "BASE_SOURCE_NOT_REVIEWED",
    "REVIEWED_TEST_ALREADY_TRACKED", "BASELINE_WORKTREE_NOT_CLEAN",
    "REVIEWED_BASELINE_CHANGED", "CONSUMED_OR_ALTERED_TICKET_REJECTED",
    "EXISTING_TICKET_CAPACITY", "OWNER_PYTHON_UNAVAILABLE",
    "EXISTING_LAUNCHER_REVIEW_REQUIRED",
    "DEVELOPMENT_TICKET_NOT_PINNED", "DEVELOPMENT_TICKET_SCHEMA_INVALID",
    "STRATA_PUBLIC_SOURCE_REVIEW_REQUIRED",
})

_SHA1 = re.compile(r"[0-9a-f]{40}\Z")
_TICKET = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")
_SOURCE = re.compile(r"src/ai_foundation/[A-Za-z0-9_]+\.py\Z")
_TEST = re.compile(r"tests/test_[A-Za-z0-9_]+\.py\Z")
_CASE = re.compile(r"experiments/strata_acceptance/[A-Za-z0-9_]+\.case\Z")

def _review_bundle():
    rows = _strict_json(BUNDLE.read_bytes())
    if type(rows) is not dict or set(rows) != {"version", "tickets"} or rows["version"] != 1:
        raise ValueError("REVIEWED_TICKET_BUNDLE_INVALID")
    tasks = rows["tickets"]
    if type(tasks) is not list or not 1 <= len(tasks) <= 8:
        raise ValueError("REVIEWED_TICKET_COUNT_INVALID")
    seen = set()
    for task in tasks:
        required = {"ticket_id", "target", "source_blob_sha1", "case_source",
                    "case_blob_sha1", "test", "instruction"}
        if (type(task) is not dict or not required <= set(task)
                or set(task) - required - {"allow_draft_delivery"}
                or ("allow_draft_delivery" in task
                    and type(task["allow_draft_delivery"]) is not bool)):
            raise ValueError("REVIEWED_TICKET_FIELDS_INVALID")
        name = task["ticket_id"]
        if (type(name) is not str or not _TICKET.fullmatch(name) or name in seen
                or type(task["target"]) is not str or not _SOURCE.fullmatch(task["target"])
                or type(task["test"]) is not str or not _TEST.fullmatch(task["test"])
                or type(task["case_source"]) is not str or not _CASE.fullmatch(task["case_source"])
                or any(type(task[key]) is not str or not _SHA1.fullmatch(task[key])
                       for key in ("source_blob_sha1", "case_blob_sha1"))
                or type(task["instruction"]) is not str
                or not 1 <= len(task["instruction"]) <= 4000):
            raise ValueError("REVIEWED_TICKET_IDENTITY_INVALID")
        seen.add(name)
    return tasks

def _reviewed_bytes(relative, blob_sha):
    path = ROOT / relative
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
        raise ValueError("REVIEWED_PUBLIC_FILE_UNAVAILABLE")
    if git(ROOT, "hash-object", "--", relative) != blob_sha:
        raise ValueError("REVIEWED_PUBLIC_BLOB_MISMATCH")
    return path.read_bytes()

def _owner_git():
    repo = OWNER_REPO
    info = repo.lstat()
    if (repo.is_symlink() or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o022
            or Path(git(repo, "rev-parse", "--show-toplevel")).resolve() != repo.resolve()):
        raise ValueError("OWNER_GIT_REPOSITORY_UNVERIFIED")
    return repo

def _worktree(repo, path, revision):
    if not path.exists():
        git(repo, "worktree", "add", "--detach", str(path), revision)
    if (path.is_symlink() or not path.is_dir()
            or git(path, "rev-parse", "HEAD") != revision
            or git(path, "status", "--porcelain")):
        raise ValueError("REVIEWED_WORKTREE_CHANGED")
    return path

def install():
    from m1_development_bridge import require_m1
    require_m1()
    if os.getuid() != 501 or os.geteuid() != 501:
        raise PermissionError("M1_OWNER_SESSION_REQUIRED")
    config_path, config, root = installed_config()
    repo = _owner_git()
    revision = git(ROOT, "rev-parse", "HEAD")
    if not _SHA1.fullmatch(revision) or git(ROOT, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("REVIEWED_MAIN_CHECKOUT_REQUIRED")
    # Exact checked-out tracked source/case bytes, not user-provided source
    # strings or a model-selected test command.
    reviewed = [
        (task, _reviewed_bytes(task["target"], task["source_blob_sha1"]),
         _reviewed_bytes(task["case_source"], task["case_blob_sha1"]))
        for task in _review_bundle()
    ]
    try:
        existing_commit = git(repo, "cat-file", "-t", revision) == "commit"
    except subprocess.CalledProcessError:
        existing_commit = False
    if not existing_commit:
        # Import only pinned objects from this reviewed checkout. Never
        # checkout, rebase, reset, move refs or alter the owner's divergent main.
        git(repo, "fetch", "--no-tags", "--no-write-fetch-head", str(ROOT), revision)
    if git(repo, "cat-file", "-t", revision) != "commit":
        raise ValueError("REVIEWED_MAIN_COMMIT_UNAVAILABLE")
    development = _private_dir(root / "development")
    import fcntl
    lock = development / "reviewed-strata-install.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime_root = _private_dir(development / "runtime")
        runtime = _worktree(repo, runtime_root / revision, revision)
        baselines = _private_dir(development / "baselines")
        manifest = development / "tickets.json"
        data = (_strict_json(_owner_manifest(manifest))
                if manifest.exists() else {"version": 1, "tickets": []})
        if (type(data) is not dict or set(data) != {"version", "tickets"}
                or data.get("version") != 1 or type(data["tickets"]) is not list):
            raise ValueError("EXISTING_TICKET_MANIFEST_UNVERIFIED")
        for record in data["tickets"]:
            _validate_ticket(record)
        new = []
        for task, source_bytes, case_bytes in reviewed:
            name = task["ticket_id"]
            baseline = baselines / name
            if not baseline.exists():
                baseline = _worktree(repo, baseline, revision)
                target = baseline / task["target"]
                if sha256(target.read_bytes()).digest() != sha256(source_bytes).digest():
                    raise ValueError("BASE_SOURCE_NOT_REVIEWED")
                test = baseline / task["test"]
                if test.exists() or test.is_symlink():
                    raise ValueError("REVIEWED_TEST_ALREADY_TRACKED")
                test.parent.mkdir(parents=True, exist_ok=True)
                test.write_bytes(case_bytes)
                git(baseline, "add", "--", task["test"])
                git(baseline, "-c", "user.name=Foundation Owner",
                    "-c", "user.email=owner@localhost", "commit", "-m",
                    "Local independent acceptance: " + name)
            if baseline.is_symlink() or git(baseline, "status", "--porcelain"):
                raise ValueError("BASELINE_WORKTREE_NOT_CLEAN")
            if ((baseline / task["test"]).read_bytes() != case_bytes
                    or (baseline / task["target"]).read_bytes() != source_bytes):
                raise ValueError("REVIEWED_BASELINE_CHANGED")
            record = {
                "ticket_id": name, "base_sha": git(baseline, "rev-parse", "HEAD"),
                "target": task["target"], "test": task["test"],
                "instruction": task["instruction"], "model": "strata",
                "source_sha256": sha256(source_bytes).hexdigest(),
                "public_source_sha256": sha256(source_bytes).hexdigest(),
                "test_sha256": sha256(case_bytes).hexdigest(),
                "public_instruction_sha256": sha256(task["instruction"].encode()).hexdigest(),
            }
            if "allow_draft_delivery" in task:
                record["allow_draft_delivery"] = task["allow_draft_delivery"]
            _validate_ticket(record)
            existing = [r for r in data["tickets"] if r["ticket_id"] == name]
            if existing and existing != [record]:
                raise ValueError("CONSUMED_OR_ALTERED_TICKET_REJECTED")
            if not existing:
                new.append(record)
        if len(data["tickets"]) + len(new) > MAX_OWNER_DEVELOPMENT_TICKETS:
            raise ValueError("EXISTING_TICKET_CAPACITY")
        if new:
            data["tickets"].extend(new)
            write_private(manifest, json.dumps(data, sort_keys=True, indent=2) + "\n")
        # Preserve the established one-command owner launcher, but update
        # its versioned local runtime only after every reviewed contract passes.
        py = repo / ".venv/bin/python"
        # A standard Python venv uses a symlink to its installed interpreter.
        # The already accepted r2 launcher uses this exact path. Require an
        # executable regular target, not a strict no-symlink policy that makes
        # a normal owner venv unusable.
        if not py.is_file() or not os.access(py, os.X_OK):
            raise ValueError("OWNER_PYTHON_UNAVAILABLE")
        launcher = Path.home() / "foundation"
        if launcher.exists() and (
                launcher.is_symlink() or launcher.stat().st_uid != os.getuid()
                or not launcher.read_text().startswith(HEADER)):
            raise ValueError("EXISTING_LAUNCHER_REVIEW_REQUIRED")
        line = (HEADER + "exec " + shlex.quote(str(py)) + " -B "
                + shlex.quote(str(runtime / "scripts/m1_direct_development.py"))
                + ' "$@"\n')
        if not launcher.exists() or launcher.read_text() != line:
            write_private(launcher, line)
            launcher.chmod(0o700)
        from m1_direct_development import strata_ready
        return {
            "strata_available": strata_ready(root),
            "status": "REVIEWED_TICKETS_INSTALLED",
            "revision": revision, "ticket_count": len(reviewed),
            "added": len(new), "github_in_run_loop": False, "model_calls": 0,
            "ticket_id": new[0]["ticket_id"] if len(new) == 1 else reviewed[0][0]["ticket_id"],
            # Only one newly admitted, never a historical manifest row, may
            # enter install-run. The local MCP Guard/Work status is checked
            # independently immediately before running.
            "fresh_ticket_id": new[0]["ticket_id"] if len(new) == 1 else None,
        }
    finally:
        os.close(fd)

def run_fresh_reviewed_ticket(report):
    """Fail closed before running: no selection by bundle position or replay."""
    ident = report.pop("fresh_ticket_id", None)
    if ident is None:
        return {**report, "status": "NO_SINGLE_FRESH_REVIEWED_TICKET", "model_calls": 0}
    if type(ident) is not str or not _TICKET.fullmatch(ident):
        raise ValueError("REVIEWED_TICKET_IDENTITY_INVALID")
    if report.get("strata_available") is not True:
        return {**report, "ticket_id": ident, "status": "WAITING_STRATA",
                "model_calls": 0}
    launcher = str(Path.home() / "foundation")
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "STRATA_API_KEY")}
    # The existing host owns status and scope. A manifest insertion or
    # discovery result is not authority to claim previously consumed Work.
    observed = subprocess.run([launcher, "status", ident],
                              capture_output=True, text=True, timeout=90, env=env)
    try:
        before = json.loads(observed.stdout) if observed.returncode == 0 else None
    except (ValueError, TypeError):
        before = None
    if (type(before) is not dict or before.get("status") != "OBSERVED"
            or type(before.get("ticket")) is not dict
            or before["ticket"].get("ticket_id") != ident
            or before["ticket"].get("state") != "READY"):
        return {**report, "ticket_id": ident,
                "status": "REVIEWED_TICKET_NOT_READY", "model_calls": 0}
    child = subprocess.run([launcher, "run", ident],
                           capture_output=True, text=True, timeout=650, env=env)
    try:
        result = json.loads(child.stdout)
    except (ValueError, TypeError):
        result = {"status": "LOCAL_MCP_RECEIPT_UNAVAILABLE"}
    allow = {"status", "durable_readback_matches", "replay_readonly",
             "github_in_run_loop", "cloud_chatgpt_muse_connection_verified"}
    # A real CODE run may have used a model; never propagate install-only 0.
    report.pop("model_calls", None)
    combined = {**report,
                **{k: result[k] for k in allow if k in result},
                "ticket": {k: result.get("ticket", {}).get(k)
                           for k in ("state", "source_sha256", "execution_binding")
                           if type(result.get("ticket")) is dict
                           and k in result["ticket"]}}
    if child.returncode != 0 and combined["status"] == "REVIEWED_TICKETS_INSTALLED":
        combined["status"] = "LOCAL_MCP_NOT_VERIFIED"
    return combined


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("install", "install-run"))
    args = parser.parse_args()
    phase = "INSTALL"
    try:
        report = install()
        if args.mode == "install-run":
            phase = "LOCAL_CLIENT"
            report = run_fresh_reviewed_ticket(report)
        else:
            report.pop("fresh_ticket_id", None)
    except Exception as exc:
        reason = str(exc) if type(exc) is ValueError else ""
        report = {"status": "REVIEWED_TICKET_INSTALL_BLOCKED"
                  if phase == "INSTALL" else "LOCAL_CLIENT_UNVERIFIED",
                  "phase": phase, "error_type": type(exc).__name__,
                  "reason_code": reason if reason in _INSTALL_BLOCKERS
                                 else "UNCLASSIFIED"}
        if phase == "INSTALL":
            report["model_calls"] = 0
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {
        "REVIEWED_TICKETS_INSTALLED", "MCP_CODE_VERIFIED"} else 2

if __name__ == "__main__":
    raise SystemExit(main())
