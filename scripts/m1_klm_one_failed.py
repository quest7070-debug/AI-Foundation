#!/usr/bin/env python3
"""Owner-triggered ONE historical failed KLM item acceptance on the pinned M1.

No generic commands, model selection, paths or source bytes are taken from Issue.
This is not part of the ordinary M1 diagnostic bridge or a recurring scheduler.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import stat
import subprocess
import sys
import time
from urllib import error, request
from urllib.parse import quote

if __package__:
    from . import m1_development_bridge as bridge
else:
    import m1_development_bridge as bridge

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
SHA = "369e74a4f8a9f19f369aa182f865b2d8fadb57c0"
LABEL = "dev.quest7070.ai-foundation.klm-drive"
TITLE = "Foundation KLM one failed recovery: 369e74a4"
BODY = ('<!-- foundation-klm-recovery: '
        '{"version":1,"release":"369e74a4f8a9f19f369aa182f865b2d8fadb57c0",'
        '"operation":"oldest-failed-once","effects":"klm-no-owner-write"} -->')
WORKFLOW = "Foundation KLM single failed recovery"
MARKER = "<!-- foundation-klm-recovery-receipt:v1:"
BLOBS = {
    "scripts/klm_drive_host_tick.py": "e1708c8d988ceb019f4d8d1325c00c620f14c74b",
    "src/ai_foundation/klm_9b_handler.py": "6f92ea5ebd9d5b67fdcc85484e43d3ae85b63676",
    "src/ai_foundation/knowledge_lifecycle.py": "fc651d7a47f0c5159e7fa35b9f977490000a7eaa",
    "src/ai_foundation/klm_drive_cycle.py": "312e60445e880debb5964a5fa2e9984b85e0d162",
    "src/ai_foundation/klm_drive_work.py": "38988c963520a9b4bdd693a899aa1bdb78dff75f",
    "src/ai_foundation/klm_projection.py": "1c598209f0da4ea6f827204ac0425ee2b646fa5e",
}
ALLOWED_RESULTS = frozenset({
    "READ_ONLY_VERIFIED", "FAILED", "DEFER_COMPUTE_BUSY", "WAIT_DEV_IDLE",
    "KLM_RECONCILE_REQUIRED", "SOURCE_CHANGED", "ALREADY_CLAIMED",
})
DB_STATES = frozenset({"PLANNED", "RUNNING", "FAILED", "VERIFIED", "WAITING_HUMAN", "CANCELLED"})

class Denied(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise Denied(message)

def gitblob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\x00" + data).hexdigest()

def owner_file(path, *, max_bytes=65536):
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "KLM_PATH_INVALID")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        st = os.fstat(fd)
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()
                and st.st_mode & 0o077 == 0 and st.st_size <= max_bytes,
                "KLM_OWNER_CONFIG_UNTRUSTED")
        return os.read(fd, max_bytes + 1)
    finally:
        os.close(fd)

def pinned_host():
    bridge.require_m1()
    require(os.getuid() == 501, "KLM_OWNER_M1_REQUIRED")
    home = Path.home()
    base = home / "Library/Application Support/AI-Foundation/klm-drive"
    releases = base / "releases"
    release = releases / SHA
    require(release.is_dir() and not release.is_symlink(),
            "KLM_PINNED_RELEASE_ABSENT")
    for name, expected in BLOBS.items():
        p = release / name
        require(p.is_file() and not p.is_symlink() and gitblob(p.read_bytes()) == expected,
                "KLM_INSTALLED_CODE_FINGERPRINT_MISMATCH")
    git = subprocess.run(["/usr/bin/git", "-C", str(release), "rev-parse", "HEAD"],
                         capture_output=True, text=True, timeout=8)
    require(git.returncode == 0 and git.stdout.strip() == SHA,
            "KLM_INSTALLED_SHA_MISMATCH")
    plist = home / "Library/LaunchAgents" / (LABEL + ".plist")
    # Plists are ordinarily owner-readable 0644, not private 0600.
    st = plist.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()
            and st.st_mode & 0o022 == 0 and st.st_size < 16384,
            "KLM_LAUNCH_AGENT_UNTRUSTED")
    spec = plistlib.loads(plist.read_bytes())
    args = spec.get("ProgramArguments")
    env = spec.get("EnvironmentVariables", {})
    require(spec.get("Label") == LABEL and spec.get("StartInterval") == 900
            and isinstance(args, list) and isinstance(env, dict)
            and sum(v == str(release / "scripts/klm_drive_host_tick.py")
                    for v in args if isinstance(v, str)) == 1
            and str(release / "src") in env.get("PYTHONPATH", ""),
            "KLM_LAUNCH_AGENT_SOURCE_MISMATCH")
    # Run only when the existing KLM tick is idle.
    ctl = subprocess.run(["/bin/launchctl", "print", "gui/501/" + LABEL],
                         capture_output=True, text=True, timeout=5)
    require(ctl.returncode == 0 and
            re.search(r"^\s*state = not running\s*$", ctl.stdout, re.M) is not None,
            "KLM_SCHEDULER_BUSY_OR_UNVERIFIED")
    cfg = json.loads(owner_file(base / "host.json"))
    require(set(cfg) == {"foundation_root", "roots", "owner_scope"},
            "KLM_HOST_BINDING_INVALID")
    root = Path(cfg["foundation_root"])
    require(root.is_absolute() and not root.is_symlink() and ".." not in root.parts,
            "KLM_FOUNDATION_ROOT_INVALID")
    foundation = json.loads(owner_file(root / "config.json"))
    data_root = Path(foundation.get("data_dir", root))
    if not data_root.is_absolute():
        data_root = root / data_root
    db = Path(foundation["work_db"])
    if not db.is_absolute():
        db = data_root / db
    st = db.lstat()
    require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid()
            and st.st_mode & 0o077 == 0 and st.st_size <= 1 << 30,
            "KLM_WORK_DB_NOT_PRIVATE")
    return root, release, db

def read_counts(db):
    uri = "file:" + quote(str(db), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=3) as con:
        con.execute("PRAGMA query_only=ON")
        states = dict(con.execute(
            "SELECT w.status,COUNT(*) FROM klm_drive_intake i JOIN work_steps w "
            "ON i.job_id=w.job_id WHERE w.position=0 GROUP BY w.status"))
        require(all(k in DB_STATES and type(v) is int and 0 <= v < 50000
                    for k,v in states.items()), "KLM_WORK_STATE_UNTRUSTED")
        names = {
            "atoms": "klm_atoms", "relations": "klm_relation_reviews",
            "placements": "klm_plans",
            "placement_candidates": "klm_placement_candidates",
        }
        available = {x[0] for x in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        totals = {}
        for key, name in names.items():
            totals[key] = (con.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
                           if name in available else None)
        totals["audits_verified"] = con.execute(
            "SELECT COUNT(*) FROM work_steps WHERE name='audit-derived-receipts' "
            "AND status='VERIFIED'").fetchone()[0]
    return {"work_states": {k: states.get(k, 0) for k in
                            ("VERIFIED","FAILED","PLANNED","RUNNING","WAITING_HUMAN")},
            **totals}

def compute_idle():
    processes = subprocess.run(["/bin/ps", "-axo", "comm="],
                               capture_output=True, text=True, timeout=6)
    if processes.returncode != 0:
        return False
    names = [Path(name.strip()).name for name in processes.stdout.splitlines()]
    # Exactly one GitHub Runner.Worker belongs to THIS one self-hosted job.
    if names.count("Runner.Worker") != 1:
        return False
    if any(n in {"llama-server", "llama-cli", "activation"} for n in names):
        return False
    op = request.build_opener(request.ProxyHandler({}))
    for port in (11434,11436):
        try:
            with op.open("http://127.0.0.1:" + str(port) + "/api/ps", timeout=2) as resp:
                if json.load(resp).get("models") != []:
                    return False
        except error.URLError as exc:
            if port != 11436 or not isinstance(exc.reason, ConnectionRefusedError):
                return False
        except (TimeoutError, ValueError, KeyError):
            return False
    return True

def one_failed():
    root, release, db = pinned_host()
    sys.path[:0] = [str(release / "src"), str(root / "local9b-autodev"),
                    str(root / "local9b-autodev/modules")]
    from ai_foundation.macos_keychain import MacOSKeychain
    from ai_foundation.klm_drive_auth import ReadonlyGoogleToken
    from ai_foundation.durable_work import SQLiteWorkStore
    from ai_foundation.klm_drive_input import DriveState
    from ai_foundation.klm_drive_work import IntakeQueue, IdleKlmWorker, read_development_state
    from ai_foundation.klm_drive_runtime import OwnerInboxHTTP
    from ai_foundation.klm_drive_cycle import NativeInboxReader
    from ai_foundation.klm_9b_handler import Existing9BKlmHandler
    from ai_foundation.knowledge_lifecycle import ReadonlyReceiptJournal
    from ai_foundation.host_compute_lease import HostComputeLease, HostComputeBusy, HostComputeLeaseError
    import local9b_issue_bridge as local_bridge
    import local9b_task_selection as selection

    worker_root = root / "local9b-autodev"
    observe_dev = lambda: read_development_state(worker_root, local_bridge, selection)
    require(observe_dev().idle(time.time()), "KLM_DEVELOPMENT_PRIORITY_NOT_IDLE")
    require(compute_idle(), "KLM_COMPUTE_NOT_IDLE")
    token = ReadonlyGoogleToken(MacOSKeychain())
    require(token.available(), "KLM_AUTH_UNAVAILABLE")
    work = SQLiteWorkStore(db)
    state = DriveState(work)
    queue = IntakeQueue(state)
    original = read_counts(db)
    require(original["work_states"]["PLANNED"] == 0 and
            original["work_states"]["RUNNING"] == 0, "KLM_OTHER_WORK_PENDING")
    with state.db() as sql:
        row = sql.execute("SELECT i.intake_id,i.source_revision,i.pointer "
                          "FROM klm_drive_intake i JOIN work_steps w ON w.job_id=i.job_id "
                          "WHERE w.position=0 AND w.status='FAILED' "
                          "ORDER BY i.created,i.intake_id LIMIT 1").fetchone()
    if row is None:
        return {"result": "NO_FAILED", "before": original, "after": original,
                "inbox_writes": 0, "external_owner_writes": 0}
    inbox = NativeInboxReader(OwnerInboxHTTP(token))
    pointer = json.loads(row["pointer"])
    current = inbox.source(pointer)
    raw = current.get("raw")
    require(current.get("revision") == row["source_revision"]
            and isinstance(raw, bytes) and 1 <= len(raw) <= 32768
            and hashlib.sha256(raw).hexdigest() == current.get("sha256"),
            "KLM_FAILED_SOURCE_IDENTITY_CHANGED")
    outcome = queue.requeue_failed(
        row["intake_id"], expected_revision=row["source_revision"],
        expected_sha256=current["sha256"], read_source=inbox.source)
    if outcome != "REQUEUED_ONE":
        return {"result": outcome, "before": original, "after": read_counts(db),
                "inbox_writes": 0, "external_owner_writes": 0}
    journal = ReadonlyReceiptJournal(db)
    worker = IdleKlmWorker(queue, observe_dev=observe_dev, lease=HostComputeLease(),
                           compute_idle=compute_idle,
                           busy_types=(HostComputeBusy,HostComputeLeaseError))
    inferred = worker.tick(read_source=inbox.source, handler=Existing9BKlmHandler(journal))
    after = read_counts(db)
    require(inferred in ALLOWED_RESULTS, "KLM_UNKNOWN_RESULT")
    return {"result": inferred, "before": original, "after": after,
            "one_selected_failed_item": True,
            "source_revision_reverified": True,
            "raw_source_published": False, "inbox_writes": 0,
            "external_owner_writes": 0}

def validate_issue(event):
    require(type(event) is dict and event.get("action") == "opened" and
            event.get("repository", {}).get("full_name") == REPO,
            "KLM_UNTRUSTED_EVENT")
    issue = event.get("issue", {})
    require(type(issue.get("number")) is int and issue["number"] > 0
            and issue.get("state") == "open" and
            issue.get("user", {}).get("login") == OWNER
            and issue.get("title") == TITLE and issue.get("body") == BODY,
            "KLM_EXACT_OWNER_REQUEST_REQUIRED")
    return issue["number"]

def live_request(event, token):
    n = validate_issue(event)
    base = "/repos/" + REPO + "/issues/" + str(n)
    issue = bridge._github_api("GET", base, token)
    require(issue.get("state") == "open" and issue.get("title") == TITLE
            and issue.get("body") == BODY and
            issue.get("user", {}).get("login") == OWNER,
            "KLM_LIVE_REQUEST_CHANGED")
    comments = bridge._github_api("GET", base + "/comments?per_page=100", token)
    require(isinstance(comments,list) and len(comments) < 100, "KLM_RECEIPT_WINDOW_INCOMPLETE")
    require(not any(isinstance(c,dict)
                    and MARKER + str(n) + " -->" in c.get("body","")
                    and c.get("user",{}).get("login") == "github-actions[bot]"
                    for c in comments), "KLM_RECOVERY_ALREADY_RECEIPTED")
    return n, base

def main():
    e = os.environ
    require(e.get("GITHUB_REPOSITORY") == REPO and
            e.get("GITHUB_EVENT_NAME") == "issues" and
            e.get("GITHUB_WORKFLOW") == WORKFLOW and
            e.get("GITHUB_EVENT_PATH") and e.get("GITHUB_TOKEN") and
            re.fullmatch(r"[0-9]{1,20}", e.get("GITHUB_RUN_ID", "")),
            "KLM_TRUSTED_WORKFLOW_REQUIRED")
    event = json.loads(Path(e["GITHUB_EVENT_PATH"]).read_text())
    n, base = live_request(event, e["GITHUB_TOKEN"])
    # Record the exact GitHub Action run BEFORE any private source read/model
    # request. A missing final receipt can then be diagnosed without guessing
    # run IDs or retrying an uncertain KLM effect.
    if sys.argv[1:] == ["--preflight"]:
        bridge._github_api("POST", base + "/comments", e["GITHUB_TOKEN"], {
            "body": ("<!-- foundation-klm-recovery-start:v1:" + str(n) +
                     " -->\nPinned KLM recovery preflight (no source accessed): " +
                     json.dumps({"run_id":e["GITHUB_RUN_ID"],
                                 "stage":"OWNER_ISSUE_ACCEPTED",
                                 "release":SHA},sort_keys=True))})
        print("KLM recovery preflight acknowledged")
        return
    require(sys.argv[1:] == [], "KLM_UNAUTHORIZED_CLI_ARGUMENT")
    try:
        outcome = one_failed()
    except Exception as exc:
        outcome = {"result":"DENIED", "reason_code":
                   str(exc) if isinstance(exc, Denied) else
                   "KLM_UNEXPECTED_" + type(exc).__name__}
    receipt = (MARKER + str(n) + " -->\n"
               + "**Single historical KLM recovery (non-private aggregate only)**\n\n~~~json\n"
               + json.dumps({"schema":1,"issue":n,"run_id":e["GITHUB_RUN_ID"],
                             "pinned_release":SHA,**outcome},sort_keys=True)
               + "\n~~~")
    bridge._github_api("POST", base + "/comments", e["GITHUB_TOKEN"],
                       {"body":receipt})
    print("KLM source-bound one-item recovery: " + outcome["result"])
    if outcome["result"] in {"DENIED","FAILED"}:
        raise SystemExit(1)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("KLM acceptance blocked: " +
              (str(exc) if isinstance(exc, Denied) else type(exc).__name__),
              file=sys.stderr)
        raise SystemExit(2)
