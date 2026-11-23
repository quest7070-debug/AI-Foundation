"""One-shot exact owner GitHub Issue -> existing Guard -> Operator-only rollback release."""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.operator_release_transaction import OperatorOnlyCutover
from ai_foundation.release_gate import GuardReleaseGate
from ai_foundation.store import SQLiteGuardStore
from scripts.m1_operator_release_cli import _guard_path
from scripts.m1_operator_release_canon import observe_release_canon
from scripts.m1_operator_release_host import FixedOperatorHost
from scripts.m1_p4_release_inventory import operator_only_release_scope
from ai_foundation.toolhive_owner_runtime import (owner_toolhive_binary, TOOLHIVE_OWNER_DIR)

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 owner main Operator release"
PREFIX = "Foundation M1 Operator Release: "
API = "https://api.github.com/repos/" + REPO + "/issues/"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")

class ReleaseDenied(RuntimeError):
    pass

def require(ok, reason):
    if not ok:
        raise ReleaseDenied(reason)

def event_identity(event, env, live=None):
    require(env.get("GITHUB_REPOSITORY") == REPO and
            env.get("GITHUB_WORKFLOW") == WORKFLOW and
            env.get("GITHUB_EVENT_NAME") == "issues" and
            env.get("GITHUB_ACTOR") == OWNER and
            event.get("action") == "opened" and
            event.get("sender", {}).get("login") == OWNER and
            event.get("repository", {}).get("full_name") == REPO,
            "OWNER_EVENT_REQUIRED")
    issue = event.get("issue")
    require(type(issue) is dict and
            issue.get("user", {}).get("login") == OWNER and
            issue.get("state") == "open" and
            type(issue.get("number")) is int and
            0 < issue["number"] < 2**31, "OWNER_ISSUE_REQUIRED")
    commit = env.get("GITHUB_SHA")
    require(type(commit) is str and SHA40.fullmatch(commit) is not None
            and issue.get("title") == PREFIX + commit
            and issue.get("body") == "<!-- foundation-m1-operator-release:v1:" + commit + " -->",
            "EXACT_MAIN_RELEASE_ISSUE_REQUIRED")
    if live is not None:
        require(type(live) is dict and live.get("number") == issue["number"]
                and live.get("title") == issue["title"]
                and live.get("body") == issue["body"]
                and live.get("state") == "open"
                and live.get("user", {}).get("login") == OWNER,
                "OWNER_ISSUE_CHANGED")
    return issue["number"], commit

def live_issue(number, token):
    require(type(token) is str and bool(token), "GITHUB_TOKEN_REQUIRED")
    request = urllib.request.Request(
        API + str(number),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "foundation-owner-one-shot-release"})
    try:
        with urllib.request.urlopen(request, timeout=12) as reply:
            raw = reply.read(65537)
        require(len(raw) <= 65536, "GITHUB_ISSUE_TOO_LARGE")
        return json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ReleaseDenied("LIVE_GITHUB_ISSUE_UNAVAILABLE") from exc

class OwnerIssueGate:
    def __init__(self, event, env, token, scope, run, ref):
        self.event, self.env, self.token = event, env, token
        self.binding = (scope.scope_ref, run, ref)

    def verify_exact_release(self, scope, run, ref):
        if self.binding != (scope.scope_ref, run, ref):
            return False
        try:
            number, _ = event_identity(self.event, self.env)
            event_identity(self.event, self.env,
                           live=live_issue(number, self.token))
            return True
        except ReleaseDenied:
            return False

def prepare_pinned_toolhive(home):
    # ToolHive is the existing reviewed OSS containment CLI, not a model
    # or new service. Install once in an owner-only stable path; the verified
    # source stage intentionally contains only tracked Python files.
    destination = Path(home) / TOOLHIVE_OWNER_DIR
    environment = {
        "HOME": str(home),
        "PATH": "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "AI_FOUNDATION_TOOLHIVE_DIR": str(destination),
        "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
    }
    try:
        proc = subprocess.run(
            ["/bin/sh", str(ROOT / "scripts/bootstrap-toolhive.sh")],
            env=environment, capture_output=True, timeout=180, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseDenied("PINNED_TOOLHIVE_BOOTSTRAP_UNAVAILABLE") from exc
    # Distinguish the pinned download/install failure from the existing
    # owner-only SHA256/permission readback without exporting subprocess
    # stderr, the owner path, or any untrusted ToolHive output.
    failure_codes = {
        21: "PINNED_TOOLHIVE_EXISTING_PROVENANCE_MISSING",
        22: "PINNED_TOOLHIVE_EXISTING_VERSION_MISMATCH",
        31: "PINNED_TOOLHIVE_ARCHIVE_DOWNLOAD_FAILED",
        32: "PINNED_TOOLHIVE_ARCHIVE_DIGEST_MISMATCH",
        33: "PINNED_TOOLHIVE_ARCHIVE_EXTRACT_FAILED",
        34: "PINNED_TOOLHIVE_ARCHIVE_EXECUTABLE_MISSING",
        35: "PINNED_TOOLHIVE_STAGE_FAILED",
        36: "PINNED_TOOLHIVE_EXTRACTED_VERSION_MISMATCH",
        37: "PINNED_TOOLHIVE_INSTALL_COMMIT_FAILED",
    }
    require(proc.returncode == 0,
            failure_codes.get(proc.returncode, "PINNED_TOOLHIVE_BOOTSTRAP_FAILED"))
    require(owner_toolhive_binary(home) == destination / "thv",
            "PINNED_TOOLHIVE_PROVENANCE_READBACK_FAILED")


def run(event, env, token):
    require(platform.system() == "Darwin" and platform.machine() == "arm64"
            and os.getuid() == 501 and os.geteuid() == 501,
            "OWNER_M1_REQUIRED")
    number, commit = event_identity(event, env)
    event_identity(event, env, live=live_issue(number, token))
    import subprocess
    head = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=8, check=False)
    clean = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "status",
                            "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, timeout=8, check=False)
    require(head.returncode == 0 and head.stdout.strip() == commit
            and clean.returncode == 0 and not clean.stdout.strip(),
            "PINNED_MAIN_SOURCE_REQUIRED")
    canon = observe_release_canon(ROOT)
    require(canon.get("source_main") == commit
            and str(canon.get("canon_revision", "")).startswith("canon-source/v1:"),
            "CURRENT_CANON_UNVERIFIED")
    home = Path.home()
    scope, details = operator_only_release_scope(home=home, root=ROOT)
    require(scope is not None and details.get("status") == "OBSERVED"
            and details.get("candidate_sha") == commit
            and scope.candidate_authority == "github-commit:" + commit,
            "EXACT_OPERATOR_SCOPE_UNVERIFIED")
    host = FixedOperatorHost(ROOT, home=home)
    live = host._human()
    require(host._registered() and host._pid_owned() and
            type(live) is dict and type(live.get("activity")) is list
            and not live["activity"], "OPERATOR_NOT_IDLE_OR_PID_BOUND")
    guard_db, _ = _guard_path(home)
    registry = guard_db.parent / (
        "operator-owner-main-release-" + scope.scope_ref[:20] + ".json")
    require(not registry.exists() and not registry.is_symlink(),
            "RELEASE_ALREADY_PREPARED_OR_CONSUMED")
    store = SQLiteGuardStore(guard_db)
    gate = GuardReleaseGate(store, registry)
    pending = gate.prepare(scope, canon_revision=canon["canon_revision"])
    require(pending.get("ok") is True
            and pending.get("status") == "WAITING_HUMAN",
            "GUARD_REQUEST_PREPARE_DENIED")
    owner = OwnerIssueGate(event, env, token, scope,
                           pending["run_id"], pending["request_ref"])
    require(owner.verify_exact_release(
        scope, pending["run_id"], pending["request_ref"]),
        "OWNER_CONTEXT_DRIFT")
    guard = GuardCore(store.runtime_state(), store=store)
    approved = OperatorActions(guard).approve_pending(
        pending["run_id"], pending["request_ref"])
    require(approved.ok and approved.status == "APPROVED",
            "GUARD_OWNER_DECISION_DENIED")
    prepare_pinned_toolhive(home)
    receipt = OperatorOnlyCutover(gate, host, owner).execute(
        scope, pending["run_id"], pending["request_ref"])
    require(receipt.status == "VERIFIED" and receipt.guard_approved
            and receipt.operator_only, "POST_RELEASE_READBACK_UNVERIFIED")
    return {"status": "VERIFIED", "main": commit,
            "scope_ref": scope.scope_ref, "operator_only": True,
            "local9b_changed": False, "model_calls": 0, "native_effects": 0,
            "pinned_toolhive_cli": "OWNER_PROVENANCE_VERIFIED"}


RECEIPT_PREFIX = "<!-- foundation-m1-operator-release-receipt:v1:"

RELEASE_RECEIPT_REASONS = frozenset({
    "OWNER_EVENT_REQUIRED", "OWNER_ISSUE_REQUIRED",
    "EXACT_MAIN_RELEASE_ISSUE_REQUIRED", "OWNER_ISSUE_CHANGED",
    "GITHUB_TOKEN_REQUIRED", "GITHUB_ISSUE_TOO_LARGE",
    "LIVE_GITHUB_ISSUE_UNAVAILABLE",
    "PINNED_TOOLHIVE_BOOTSTRAP_UNAVAILABLE",
    "PINNED_TOOLHIVE_EXISTING_PROVENANCE_MISSING",
    "PINNED_TOOLHIVE_EXISTING_VERSION_MISMATCH",
    "PINNED_TOOLHIVE_ARCHIVE_DOWNLOAD_FAILED",
    "PINNED_TOOLHIVE_ARCHIVE_DIGEST_MISMATCH",
    "PINNED_TOOLHIVE_ARCHIVE_EXTRACT_FAILED",
    "PINNED_TOOLHIVE_ARCHIVE_EXECUTABLE_MISSING",
    "PINNED_TOOLHIVE_STAGE_FAILED",
    "PINNED_TOOLHIVE_EXTRACTED_VERSION_MISMATCH",
    "PINNED_TOOLHIVE_INSTALL_COMMIT_FAILED",
    "PINNED_TOOLHIVE_BOOTSTRAP_FAILED",
    "PINNED_TOOLHIVE_PROVENANCE_READBACK_FAILED",
    "OWNER_M1_REQUIRED", "PINNED_MAIN_SOURCE_REQUIRED",
    "CURRENT_CANON_UNVERIFIED", "EXACT_OPERATOR_SCOPE_UNVERIFIED",
    "OPERATOR_NOT_IDLE_OR_PID_BOUND",
    "RELEASE_ALREADY_PREPARED_OR_CONSUMED",
    "GUARD_REQUEST_PREPARE_DENIED", "OWNER_CONTEXT_DRIFT",
    "GUARD_OWNER_DECISION_DENIED", "POST_RELEASE_READBACK_UNVERIFIED",
    "RELEASE_RECEIPT_HISTORY_UNBOUNDED",
})



def _receipt_body(number, result):
    """Only fixed host-owned status codes, never raw errors, argv or config."""
    status = result.get("status") if type(result) is dict else None
    if status not in {"VERIFIED", "BLOCKED"}:
        status = "BLOCKED"
    output = {"schema": 1, "status": status,
              "operator_only": status == "VERIFIED",
              "model_calls": 0, "native_effects": 0}
    if status == "VERIFIED":
        value = result.get("main")
        if type(value) is str and SHA40.fullmatch(value):
            output["main"] = value
    else:
        reason = result.get("reason") if type(result) is dict else None
        output["reason"] = (reason if type(reason) is str
                            and reason in RELEASE_RECEIPT_REASONS
                            else "RELEASE_UNVERIFIED")
    return (RECEIPT_PREFIX + str(number) + " -->\n"
            + "M1 owner Operator release receipt (no private source/output)\n\n"
            + "```json\n" + json.dumps(output, sort_keys=True)
            + "\n```")


def _receipt_history(number, token):
    from scripts import m1_development_bridge as bridge
    prefix = f"/repos/{REPO}/issues/{number}"
    rows = bridge._github_api("GET", prefix + "/comments?per_page=100", token)
    require(type(rows) is list and len(rows) < 100,
            "RELEASE_RECEIPT_HISTORY_UNBOUNDED")
    marker = RECEIPT_PREFIX + str(number) + " -->"
    return prefix, any(type(row) is dict
                       and marker in row.get("body", "")
                       and row.get("user", {}).get("login") == "github-actions[bot]"
                       for row in rows)


def publish_release_receipt(event, env, token, result, *, api=None):
    from scripts import m1_development_bridge as bridge
    number, _ = event_identity(event, env)
    event_identity(event, env, live=live_issue(number, token))
    prefix, exists = _receipt_history(number, token)
    if exists:
        return "ALREADY_RECORDED"
    (bridge._github_api if api is None else api)(
        "POST", prefix + "/comments", token,
        {"body": _receipt_body(number, result)})
    return "RECORDED"



def main():
    try:
        env = os.environ
        event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
        token = env.get("GITHUB_TOKEN", "")
        number, _ = event_identity(event, env)
        event_identity(event, env, live=live_issue(number, token))
        _, prior = _receipt_history(number, token)
        if prior:
            print(json.dumps({"status": "ALREADY_RECORDED_NO_REDISPATCH"}))
            return 0
    except Exception as exc:
        reason = str(exc) if type(exc) is ReleaseDenied else type(exc).__name__
        print(json.dumps({"status": "BLOCKED", "reason": reason}, sort_keys=True))
        return 2
    try:
        result = run(event, env, token)
    except Exception as exc:
        reason = str(exc) if type(exc) is ReleaseDenied else "RELEASE_UNVERIFIED"
        result = {"status": "BLOCKED", "reason": reason}
    print(json.dumps(result, sort_keys=True))
    # A completed Guard/service attempt must never be resent because only
    # receipt publication failed. The exact owner Issue is the durable log.
    try:
        publish_release_receipt(event, env, token, result)
    except Exception:
        print(json.dumps({"status": "RECEIPT_UNVERIFIED_NO_REDISPATCH"}))
        return 2
    return 0 if result.get("status") == "VERIFIED" else 2

if __name__ == "__main__":
    raise SystemExit(main())
