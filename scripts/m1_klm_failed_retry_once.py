#!/usr/bin/env python3
"""Stage only one historical KLM FAILED source for existing unattended 9B.

Exactly one trusted owner Issue is allowed. The old error is preserved in the
existing retry journal. No shell/paths from Issue, model call, new scheduler,
source publication, Guard/Native effect or service modification.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import runpy
import sqlite3
import stat
import sys
import time
from urllib.parse import quote

import m1_development_bridge as bridge
import m1_klm_fairness_release as release

REPO = "quest7070-dev/AI-Foundation"
TITLE = "Foundation KLM retry one FAILED: 799a1ad8"
BODY = "<!-- foundation-klm-retry-once: {\"version\":1,\"release\":\"799a1ad8a0584da6e2a852a363e5edfd61454bf8\",\"scope\":\"one-failed-no-effect\",\"intent\":\"2026-11-13-owner-continue\"} -->"
WORKFLOW = "Foundation M1 KLM single failed retry"
MARKER = "<!-- foundation-klm-failed-retry-receipt:v1:"

class Denied(ValueError):
    pass


def insist(ok, code):
    if not ok:
        raise Denied(code)


def check_issue(event, token):
    insist(type(event) is dict and event.get("action") == "opened"
           and event.get("repository", {}).get("full_name") == REPO,
           "RETRY_EVENT_UNTRUSTED")
    issue = event.get("issue", {})
    insist(type(issue.get("number")) is int and issue["number"] > 0
           and issue.get("user", {}).get("login") == release.OWNER
           and issue.get("state") == "open"
           and issue.get("title") == TITLE and issue.get("body") == BODY,
           "RETRY_OWNER_INTENT_INVALID")
    number = issue["number"]
    prefix = f"/repos/{REPO}/issues/{number}"
    live = bridge._github_api("GET", prefix, token)
    insist(live.get("state") == "open"
           and live.get("user", {}).get("login") == release.OWNER
           and live.get("title") == TITLE and live.get("body") == BODY,
           "RETRY_LIVE_OWNER_INTENT_MISMATCH")
    comments = bridge._github_api("GET", prefix + "/comments?per_page=100", token)
    insist(type(comments) is list and len(comments) < 100,
           "RETRY_HISTORY_NOT_COMPLETE")
    insist(not any(MARKER + str(number) + " -->" in c.get("body", "")
                   and c.get("user", {}).get("login") == "github-actions[bot]"
                   for c in comments), "RETRY_ALREADY_RECEIPTED")
    return number, prefix


def inspect_oldest_failed(work_path):
    """Oldest ValueError first, then oldest other FAILED; no private data returned."""
    path = Path(work_path)
    info = path.lstat()
    insist(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
           and info.st_mode & 0o077 == 0 and info.st_size < (1 << 30),
           "RETRY_PRIVATE_WORK_DB_REQUIRED")
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=3) as db:
        db.execute("PRAGMA query_only=ON")
        active = db.execute("""SELECT COUNT(*) FROM klm_drive_intake i
            JOIN work_steps w ON w.job_id=i.job_id
            WHERE w.status IN ('PLANNED','RUNNING')""").fetchone()[0]
        insist(active == 0, "RETRY_ACTIVE_INTAKE_PRESENT")
        count = db.execute("""SELECT COUNT(*) FROM klm_drive_intake i
            JOIN work_steps w ON w.job_id=i.job_id
            WHERE w.status='FAILED'""").fetchone()[0]
        insist(0 <= count <= 1000, "RETRY_FAILED_WINDOW_UNBOUNDED")
        if count == 0:
            return None, 0
        row = db.execute("""SELECT i.intake_id,i.source_revision,i.pointer
            FROM klm_drive_intake i JOIN work_steps w ON w.job_id=i.job_id
            WHERE w.status='FAILED'
            ORDER BY CASE WHEN w.result LIKE '%ValueError%' THEN 0 ELSE 1 END,
                     w.updated_at, i.intake_id LIMIT 1""").fetchone()
        insist(row is not None, "RETRY_FAILED_ROW_MISSING")
        return {"intake_id": row[0], "revision": row[1], "pointer": row[2]}, count


def pinned_existing_work_db(releases):
    """Resolve the installed, pinned KLM DB path helper without running a host tick."""
    source = Path(releases) / release.NEW / "scripts" / "klm_drive_host_tick.py"
    insist(source.is_file() and not source.is_symlink(),
           "RETRY_PINNED_KLM_ENTRY_MISSING")
    # Caller has already run release.check_release, including the exact entry blob.
    # Non-main run_name prevents execution of the script's guarded main().
    namespace = runpy.run_path(str(source), run_name="_klm_retry_db_helper_only")
    helper = namespace.get("existing_work_db")
    insist(callable(helper), "RETRY_PINNED_DB_HELPER_MISSING")
    return helper



RECOVERY_STAGES = frozenset({
    "LIVE_OWNER_VALIDATED", "M1_RELEASE_CHECK", "DEV_IDLE_CHECK",
    "DB_CHECK", "RECEIPT_POST", "INTENT_STAGE_BEGIN", "INTENT_STAGED"
})


def trace_stage(label):
    """Only fixed non-private stages appear in Action logs on cancellation."""
    if label not in RECOVERY_STAGES:
        raise Denied("RETRY_STAGE_UNTRUSTED")
    print("KLM_RETRY_STAGE:" + label, flush=True)



def stage_retry_intent(work_path, selected):
    """Request GUI-host source verification without reading Keychain or Drive.

    The Work ID is derived only from an existing private FAILED intake. The
    installed 900s service must re-read exact source and atomically requeue
    original FAILED Work; this Action never changes that Work status.
    """
    from ai_foundation.durable_work import SQLiteWorkStore
    intake_id = selected.get("intake_id")
    insist(type(intake_id) is str
           and re.fullmatch(r"[0-9a-f]{64}", intake_id) is not None,
           "RETRY_EXACT_INTAKE_REQUIRED")
    job = "klm-retry-intent:" + intake_id
    uri = "file:" + quote(str(work_path), safe="/") + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=3) as db:
        db.execute("PRAGMA query_only=ON")
        existing = db.execute(
            "SELECT name,status FROM work_steps WHERE job_id=? AND position=0",
            (job,)).fetchone()
        if existing is not None:
            insist(existing[0] == "klm-source-verified-retry",
                   "RETRY_INTENT_PLAN_CHANGED")
            return "INTENT_ALREADY_PRESENT"
        active = db.execute(
            "SELECT COUNT(*) FROM work_steps WHERE name=? "
            "AND job_id LIKE 'klm-retry-intent:%' "
            "AND status IN ('PLANNED','RUNNING','WAITING_HUMAN')",
            ("klm-source-verified-retry",)).fetchone()[0]
        insist(active == 0, "RETRY_OTHER_INTENT_PENDING")
    store = SQLiteWorkStore(work_path)
    store.ensure(job, ["klm-source-verified-retry"])
    steps = store.load(job)
    insist(len(steps) == 1 and steps[0].name == "klm-source-verified-retry",
           "RETRY_INTENT_READBACK_FAILED")
    return "STAGED_ONE_FOR_OWNER_VERIFY"


def execute_once():
    # This file is from trusted main; the running KLM implementation is pinned.
    trace_stage("M1_RELEASE_CHECK")
    bridge.require_m1()
    foundation, plist, releases = release.owner_paths()
    insist(release.is_new_plist(plist, releases), "RETRY_KLM_RELEASE_CHANGED")
    release.check_release(releases / release.NEW, release.NEW, release.NEW_HANDLER)
    insist(release.label_idle(), "RETRY_KLM_SERVICE_TICK_ACTIVE")
    worker_root = foundation / "local9b-autodev"
    sys.path.insert(0, str(releases / release.NEW / "src"))
    sys.path.extend([str(worker_root), str(worker_root / "modules")])
    from ai_foundation.klm_drive_work import read_development_state
    import local9b_issue_bridge as issue_bridge
    import local9b_task_selection as task_selection

    observe = lambda: read_development_state(worker_root, issue_bridge, task_selection)
    trace_stage("DEV_IDLE_CHECK")
    if not observe().idle(time.time()):
        return {"result": "WAIT_DEV_IDLE", "requeued": 0}
    trace_stage("DB_CHECK")
    foundation_cfg = json.loads((foundation / "config.json").read_text())
    # This helper belongs to the already fingerprint-verified installed release,
    # NOT the trusted-main checkout: main intentionally has no KLM host entry.
    # Load only that exact script by absolute path, not a broad sys.path entry.
    existing_work_db = pinned_existing_work_db(releases)
    work_path = existing_work_db(foundation_cfg, foundation)
    selected, before = inspect_oldest_failed(work_path)
    if selected is None:
        return {"result": "NO_FAILED", "failed_before": 0, "requeued": 0}
    trace_stage("INTENT_STAGE_BEGIN")
    outcome = stage_retry_intent(work_path, selected)
    trace_stage("INTENT_STAGED")
    return {"result": outcome, "failed_before": before,
            "requeued": 0,
            "staged": 1 if outcome == "STAGED_ONE_FOR_OWNER_VERIFY" else 0,
            "source_verified_in_action": False,
            "next_owner": "EXISTING_KLM_900S_CYCLE"}


def main():
    e = os.environ
    insist(e.get("GITHUB_REPOSITORY") == REPO
           and e.get("GITHUB_WORKFLOW") == WORKFLOW
           and e.get("GITHUB_EVENT_NAME") == "issues"
           and e.get("GITHUB_EVENT_PATH") and e.get("GITHUB_TOKEN")
           and re.fullmatch(r"[0-9]{1,20}", e.get("GITHUB_RUN_ID", "")),
           "RETRY_FIXED_RUNNER_CONTEXT_REQUIRED")
    event = json.loads(Path(e["GITHUB_EVENT_PATH"]).read_text())
    number, prefix = check_issue(event, e["GITHUB_TOKEN"])
    trace_stage("LIVE_OWNER_VALIDATED")
    try:
        outcome = execute_once()
    except Exception as exc:
        outcome = {"result": "DENIED", "reason_code": (
            str(exc) if isinstance(exc, Denied) else "UNEXPECTED_" + type(exc).__name__)}
    receipt = (MARKER + str(number) + " -->\n"
               + "**One historical KLM FAILED retry** (no source data)\n\n~~~json\n"
               + json.dumps({"schema": 1, "issue": number, "run_id": e["GITHUB_RUN_ID"],
                             **outcome}, sort_keys=True) + "\n~~~")
    trace_stage("RECEIPT_POST")
    bridge._github_api("POST", prefix + "/comments", e["GITHUB_TOKEN"],
                       {"body": receipt})
    print("KLM one-failure retry: " + outcome["result"])
    if outcome["result"] == "DENIED":
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("Fixed KLM retry denied: " +
              (str(exc) if isinstance(exc, Denied) else type(exc).__name__),
              file=sys.stderr)
        raise SystemExit(2)
