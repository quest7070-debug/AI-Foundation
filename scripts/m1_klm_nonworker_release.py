#!/usr/bin/env python3
"""Pinned KLM-only non-executable Harness parent admission fix; no model request in Action."""
from __future__ import annotations
import hashlib
import json
import os
import pathlib
import plistlib
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time

if __package__:
    from . import m1_development_bridge as bridge
else:
    import m1_development_bridge as bridge

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
OLD = "82b79daee075f371794fe9f1e29ce74280da8cab"
NEW = "398592a317afc18dad7b1e55c3458324bb15889c"
LABEL = "dev.quest7070.ai-foundation.klm-drive"
ENTRY = "scripts/klm_drive_host_tick.py"
HANDLER = "src/ai_foundation/klm_9b_handler.py"
OLD_ENTRY_BLOB = "cb642dc679c8de3f719e5797aca7167a4dcbe131"
NEW_ENTRY_BLOB = "cb642dc679c8de3f719e5797aca7167a4dcbe131"
OLD_HANDLER = "6f92ea5ebd9d5b67fdcc85484e43d3ae85b63676"
NEW_HANDLER = "6f92ea5ebd9d5b67fdcc85484e43d3ae85b63676"
TITLE = "Foundation KLM non-worker parent gate release: 398592a3"
BODY = "<!-- foundation-klm-nonworker-release: {\"version\":1,\"release\":\"398592a317afc18dad7b1e55c3458324bb15889c\",\"previous_release\":\"82b79daee075f371794fe9f1e29ce74280da8cab\",\"scope\":\"klm-only\",\"intent\":\"2026-11-10-user-fast-implementation\"} -->"
WORKFLOW = "Foundation M1 KLM nonworker parent admission release"
MARKER = "<!-- foundation-klm-nonworker-release-receipt:v1:"

class Denied(ValueError):
    pass

def insist(ok, code):
    if not ok:
        raise Denied(code)

def blob(raw):
    return hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()

def check_release(release, sha, handler_blob):
    insist(release.is_dir() and not release.is_symlink(), "RELEASE_DIRECTORY_UNTRUSTED")
    insist(sha in {OLD, NEW}, "PINNED_RELEASE_IDENTITY_REQUIRED")
    expected_entry = OLD_ENTRY_BLOB if sha == OLD else NEW_ENTRY_BLOB
    for name, expected in ((ENTRY, expected_entry), (HANDLER, handler_blob)):
        p = release / name
        insist(p.is_file() and not p.is_symlink() and blob(p.read_bytes()) == expected,
               "RELEASE_FILE_FINGERPRINT_MISMATCH")
    if sha == NEW:
        # Pin all new lifecycle modules, not only the inference handler.
        for name, expected in (
            ("src/ai_foundation/knowledge_lifecycle.py", "4a64f2473e4c8ca695b56efae25b6862dcf4e5ec"),
            ("src/ai_foundation/klm_drive_cycle.py", "90f04549e13293d7ae1f87e9625dfc344eec4532"),
            ("src/ai_foundation/klm_drive_work.py", "4d53c54f620393af5357757c93420de722ed5d45"),
            ("src/ai_foundation/klm_projection.py", "0fa6ae0dc151455a6144beb1421d0d2ce70ae721"),
            ("src/ai_foundation/klm_drive_input.py", "3461b366d60c1fdf1db29bee8447ead2b02928f0"),
            ("src/ai_foundation/klm_drive_auth.py", "226b0dd292d2bef2fde3ad61d5d1b848acc3fa00"),
            ("src/ai_foundation/klm_compute_admission.py", "183bc3a31471d2ec73fd2de5efc1249469f07efb"),
            ("scripts/m1_klm_status_probe.py", "40bda65c29e050970312365ea220dd422243ff4d"),
            ("src/ai_foundation/klm_drive_runtime.py", "42775f69fb023c5913acbf6a9ac561db189373b9"),
            ("src/ai_foundation/klm_llmperks_source.py", "c6fbcfcef2241ae0718e6c5b1655c2b8ecf5c73a"),
        ):
            p = release / name
            insist(p.is_file() and not p.is_symlink() and blob(p.read_bytes()) == expected,
                   "LIFECYCLE_SOURCE_FINGERPRINT_MISMATCH")
    g = subprocess.run(["/usr/bin/git", "-C", str(release), "rev-parse", "HEAD"],
                       capture_output=True, text=True, timeout=8)
    insist(g.returncode == 0 and g.stdout.strip() == sha, "RELEASE_HEAD_MISMATCH")

def owner_paths():
    bridge.require_m1()
    insist(os.getuid() == 501, "M1_OWNER_SESSION_MISMATCH")
    h = pathlib.Path.home()
    base = h / "Library/Application Support/AI-Foundation/klm-drive"
    insist(base.is_dir() and not base.is_symlink(), "KLM_OWNER_DIRECTORY_MISSING")
    conf = base / "host.json"
    info = conf.lstat()
    insist(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
           and info.st_mode & 0o077 == 0 and info.st_size <= 65536,
           "KLM_OWNER_PRIVATE_CONFIG_UNTRUSTED")
    data = json.loads(conf.read_text())
    insist(set(data) == {"foundation_root", "roots", "owner_scope"},
           "KLM_OWNER_CONFIG_SCHEMA_CHANGED")
    return (pathlib.Path(data["foundation_root"]),
            h / "Library/LaunchAgents" / (LABEL + ".plist"), base / "releases")

def old_plist_and_new(plist, releases):
    insist(plist.is_file() and not plist.is_symlink(), "KLM_PLIST_UNTRUSTED")
    old = plist.read_bytes()
    values = plistlib.loads(old)
    env = values.get("EnvironmentVariables", {})
    args = values.get("ProgramArguments", [])
    insist(values.get("Label") == LABEL and values.get("StartInterval") == 900,
           "KLM_SERVICE_CONTRACT_CHANGED")
    insist(isinstance(env, dict) and isinstance(args, list),
           "KLM_PLIST_SCHEMA_INVALID")
    oldscript = str(releases / OLD / ENTRY)
    insist(sum(x == oldscript for x in args if isinstance(x, str)) == 1
           and sum(OLD in x for x in args if isinstance(x, str)) == 1,
           "KLM_EXPECTED_OLD_SCRIPT_MISMATCH")
    path = env.get("PYTHONPATH")
    insist(isinstance(path, str) and path.count(OLD) == 1 and NEW not in path,
           "KLM_EXPECTED_OLD_PYTHONPATH_MISMATCH")
    modified = dict(values)
    modified["ProgramArguments"] = [v.replace(OLD, NEW) if isinstance(v, str) else v for v in args]
    modified["EnvironmentVariables"] = {**env, "PYTHONPATH": path.replace(OLD, NEW)}
    return old, plistlib.dumps(modified)

def is_new_plist(plist, releases):
    if not plist.is_file() or plist.is_symlink():
        return False
    values = plistlib.loads(plist.read_bytes())
    args = values.get("ProgramArguments", [])
    env = values.get("EnvironmentVariables", {})
    path = env.get("PYTHONPATH", "")
    return (values.get("Label") == LABEL and values.get("StartInterval") == 900
            and isinstance(args, list) and
            sum(x == str(releases / NEW / ENTRY) for x in args) == 1
            and isinstance(path, str) and path.count(NEW) == 1 and OLD not in path)

def stage(releases):
    """Fetch only an immutable reviewed commit, never mutable branch HEAD."""
    insist(re.fullmatch(r"[0-9a-f]{40}", NEW) is not None and NEW != OLD,
           "RELEASE_TARGET_SHA_NOT_PINNED")
    dest = releases / NEW
    if dest.exists():
        check_release(dest, NEW, NEW_HANDLER)
        return dest
    insist(releases.is_dir() and not releases.is_symlink(), "RELEASES_ROOT_UNTRUSTED")
    temp = pathlib.Path(tempfile.mkdtemp(prefix=".klm-research-stage-", dir=releases))
    checkout = temp / "repo"
    checkout.mkdir(mode=0o700)
    try:
        for args, timeout in (
            (["/usr/bin/git", "-C", str(checkout), "init", "-q"], 10),
            (["/usr/bin/git", "-C", str(checkout), "remote", "add", "origin",
              "https://github.com/quest7070-dev/AI-Foundation.git"], 10),
            (["/usr/bin/git", "-C", str(checkout),
              "-c", "credential.interactive=never", "fetch", "--quiet",
              "--depth", "1", "origin", NEW], 90),
            (["/usr/bin/git", "-C", str(checkout), "checkout",
              "--detach", "--quiet", NEW], 20),
        ):
            result = subprocess.run(args, capture_output=True, timeout=timeout)
            insist(result.returncode == 0, "PINNED_GITHUB_FETCH_UNAVAILABLE")
        check_release(checkout, NEW, NEW_HANDLER)
        checkout.rename(dest)
    finally:
        shutil.rmtree(temp)
    return dest


def launch(*args):
    return subprocess.run(["/bin/launchctl", *args], capture_output=True,
                          text=True, timeout=16)

def label_idle():
    result = launch("print", "gui/501/" + LABEL)
    return (result.returncode == 0 and
            re.search(r"^\s*state = not running\s*$", result.stdout, re.M) is not None)

def atomic_plist(path, data):
    fd, temp = tempfile.mkstemp(prefix=".klm-pinned-rollback-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, 0o644)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def running_klm_steps(db):
    """Read-only bounded detection of *running* KLM Work, never queued Work."""
    with sqlite3.connect("file:" + str(db) + "?mode=ro",
                         uri=True, timeout=3) as con:
        count = con.execute(
            "SELECT COUNT(*) FROM work_steps WHERE job_id LIKE 'klm-%' "
            "AND status='RUNNING'").fetchone()[0]
    insist(type(count) is int and 0 <= count <= 100000,
           "KLM_ACTIVE_WORK_COUNT_UNTRUSTED")
    return count


def compute_admission(foundation, releases):
    # The cutover only swaps one idle KLM LaunchAgent source. It does not
    # perform 9B inference and does not take development time. Do NOT gate a
    # code-only release on the existence of queued developer tasks: the NEW
    # IdleKlmWorker still checks development priority twice before any model
    # call, under the same shared HostComputeLease. Here, deny a running KLM
    # step and require the shared lease to be immediately free.
    # This lease module was added after OLD. Import from the immutable NEW
    # release that has already passed full blob / commit verification in stage().
    import importlib
    new_src = str(releases / NEW / "src")
    sys.path.insert(0, new_src)
    for name in tuple(sys.modules):
        if name == "ai_foundation.host_compute_lease":
            del sys.modules[name]
    from ai_foundation.host_compute_lease import HostComputeLease
    cfg = json.loads((foundation / "config.json").read_text())
    d = pathlib.Path(cfg.get("data_dir", foundation))
    if not d.is_absolute():
        d = foundation / d
    db = pathlib.Path(cfg["work_db"])
    if not db.is_absolute():
        db = d / db
    insist(db.is_file() and not db.is_symlink(), "KLM_WORK_DB_UNAVAILABLE")
    # PLANNED is durable queued work, not an active effect. Preserve it
    # across code-only cutover; still deny any RUNNING KLM Work, including
    # retries, legacy reviews, scans and audits (not just Intake rows).
    insist(running_klm_steps(db) == 0, "KLM_WORK_ACTIVE")
    # This Action only swaps the KLM GUI service's pinned source/plist.
    # A CI worker, resident Ollama model or sleeping llama process cannot
    # imply unsafe cutover; the old KLM service must be quiescent and the
    # shared lease plus fresh development priority remain mandatory.
    # No 9B inference is initiated by this release entry.
    return HostComputeLease()

def switch(plist, old, new, dest):
    backup = dest / "previous-klm-launchagent.plist"
    insist(not backup.exists() and not backup.is_symlink(),
           "KLM_BACKUP_ALREADY_PRESENT")
    insist(label_idle(), "KLM_SCHEDULED_TICK_RUNNING")
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(old)
        stream.flush()
        os.fsync(stream.fileno())
    insist(launch("bootout", "gui/501/" + LABEL).returncode == 0,
           "KLM_BOOTOUT_REFUSED")
    try:
        atomic_plist(plist, new)
        insist(launch("bootstrap", "gui/501", str(plist)).returncode == 0,
               "KLM_BOOTSTRAP_NEW_FAILED")
        observed = launch("print", "gui/501/" + LABEL)
        insist(observed.returncode == 0 and NEW in observed.stdout
               and plist.read_bytes() == new,
               "KLM_NEW_SERVICE_READBACK_FAILED")
    except BaseException:
        launch("bootout", "gui/501/" + LABEL)
        atomic_plist(plist, old)
        restored = launch("bootstrap", "gui/501", str(plist))
        insist(restored.returncode == 0 and plist.read_bytes() == old,
               "KLM_ROLLBACK_REQUIRES_OWNER_REVIEW")
        raise
    return {"result": "APPLIED", "release_sha": NEW, "service": LABEL,
            "interval_seconds": 900, "rollback_backup_preserved": True,
            "unrelated_services_changed": False}

def apply_once():
    foundation, plist, releases = owner_paths()
    check_release(releases / OLD, OLD, OLD_HANDLER)
    if is_new_plist(plist, releases):
        check_release(releases / NEW, NEW, NEW_HANDLER)
        return {"result": "ALREADY_INSTALLED", "release_sha": NEW,
                "service": LABEL, "restarted": False}
    old, new = old_plist_and_new(plist, releases)
    dest = stage(releases)
    lease = compute_admission(foundation, releases)
    try:
        with lease.hold(max_wait_s=0):
            compute_admission(foundation, releases)
            insist(label_idle() and plist.read_bytes() == old,
                   "KLM_CUTOVER_RACE_BLOCKED")
            return switch(plist, old, new, dest)
    except Exception as exc:
        if type(exc).__name__ in {"HostComputeBusy", "HostComputeLeaseError"}:
            raise Denied("KLM_SHARED_LEASE_BUSY") from None
        raise

def validate_issue(event):
    """Only the exact owner-approved one-shot push, no generic issue commands."""
    insist(isinstance(event, dict)
           and event.get("repository", {}).get("full_name") == REPO
           and event.get("ref") == "refs/heads/ops/klm-nonworker-release-20261110"
           and event.get("head_commit", {}).get("message") ==
               "test(m1): apply pinned KLM non-worker parent release",
           "RELEASE_FIXED_PUSH_REQUIRED")
    return 587

def checked_request(event, token):
    n = validate_issue(event)
    base = f"/repos/{REPO}/issues/{n}"
    live = bridge._github_api("GET", base, token)
    insist(live.get("user", {}).get("login") == OWNER and live.get("state") == "open"
           and live.get("title") == TITLE and live.get("body") == BODY,
           "RELEASE_LIVE_ISSUE_MISMATCH")
    comments = bridge._github_api("GET", base + "/comments?per_page=100", token)
    insist(isinstance(comments, list) and len(comments) < 100,
           "RELEASE_RECEIPT_WINDOW_INCOMPLETE")
    # Failed attempts remain as immutable evidence. Only an APPLIED or
    # ALREADY_INSTALLED receipt closes the one-shot release gate.
    prior_success = any(
        MARKER + str(n) + " -->" in c.get("body", "")
        and c.get("user", {}).get("login") == "github-actions[bot]"
        and ('"result": "APPLIED"' in c.get("body", "")
             or '"result": "ALREADY_INSTALLED"' in c.get("body", ""))
        for c in comments)
    insist(not prior_success, "RELEASE_ALREADY_APPLIED")
    return n, base

def main():
    e = os.environ
    insist(e.get("GITHUB_REPOSITORY") == REPO and e.get("GITHUB_WORKFLOW") == WORKFLOW
           and e.get("GITHUB_EVENT_NAME") == "push"
           and e.get("GITHUB_REF") ==
               "refs/heads/ops/klm-nonworker-release-20261110"
           and e.get("GITHUB_EVENT_PATH") and e.get("GITHUB_TOKEN")
           and re.fullmatch(r"[0-9]{1,20}", e.get("GITHUB_RUN_ID", "")),
           "RELEASE_FIXED_WORKFLOW_REQUIRED")
    bridge.require_m1()
    issue = json.loads(pathlib.Path(e["GITHUB_EVENT_PATH"]).read_text())
    n, base = checked_request(issue, e["GITHUB_TOKEN"])
    try:
        outcome = apply_once()
    except Exception as exc:
        outcome = {"result": "DENIED", "reason_code":
                   str(exc) if isinstance(exc, Denied) else
                   "UNEXPECTED_" + type(exc).__name__}
    # A normal development/lease/scheduler conflict is a deferral, never
    # approval consumption or a release attempt to force through an active job.
    if (outcome["result"] == "DENIED" and outcome.get("reason_code") in {
            "KLM_DEVELOPMENT_PRIORITY_NOT_IDLE", "KLM_SHARED_LEASE_BUSY",
            "KLM_SCHEDULED_TICK_RUNNING", "KLM_WORK_ACTIVE",
            "KLM_CUTOVER_RACE_BLOCKED"}):
        print("KLM_RESEARCH_RELEASE=DEFERRED:" + outcome["reason_code"])
        return
    receipt = (MARKER + str(n) + " -->\n"
               + "**Pinned KLM release receipt** (no private data)\n\n~~~json\n"
               + json.dumps({"schema": 1, "issue": n, "run_id": e["GITHUB_RUN_ID"],
                             **outcome}, sort_keys=True) + "\n~~~")
    bridge._github_api("POST", base + "/comments", e["GITHUB_TOKEN"],
                       {"body": receipt})
    print("KLM fixed release: " + outcome["result"])
    if outcome["result"] == "DENIED":
        raise SystemExit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("KLM fixed release denied: " +
              (str(exc) if isinstance(exc, Denied) else type(exc).__name__),
              file=sys.stderr)
        raise SystemExit(2)
