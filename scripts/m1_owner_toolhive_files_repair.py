#!/usr/bin/env python3
"""Owner-only, at-most-once, Guard-journaled repair of existing ToolHive FILES.

No arbitrary Issue commands or paths, no workload rm/run, no model or network
provider, and never publish ToolHive's response, package, URL or host paths.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_foundation.core import CanonContract, GuardState, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.store import SQLiteGuardStore, approval_request_ref
from ai_foundation.toolhive_owner_runtime import owner_toolhive_binary
from scripts.m1_operator_release_cli import _guard_path
from scripts.m1_operator_release_canon import observe_release_canon
from scripts.m1_operator_release_host import FixedOperatorHost
from scripts import m1_development_bridge as bridge

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 owner ToolHive FILES one-shot repair"
PREFIX = "Foundation M1 ToolHive FILES Repair: "
MARKER = "<!-- foundation-m1-toolhive-files-repair-receipt:v1:"
NAME = "ai-foundation-fs"
# Reviewed canonical lifecycle scripts/toolhive-filesystem.sh pins this exact
# Docker image ID. A ToolHive status package is a Docker image reference,
# not an authority token: verify its resolved image ID on the owner host.
EXPECTED_IMAGE_ID = "sha256:720393842ef8b0f33713a42e2eebda51ff600756c19d53e1244645ec59496fef"
IMAGE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:@+-]{0,239}\Z")
DOCKER_BINARIES = (
    "/usr/local/bin/docker",
    "/opt/homebrew/bin/docker",
    "/Applications/Docker.app/Contents/Resources/bin/docker",
)
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
ALLOWED_RESULTS = frozenset({
    "VERIFIED_COMPLETE", "UNCERTAIN_RECONCILE_REQUIRED",
    "EFFECT_IN_PROGRESS", "EFFECT_STATE_CONFLICT",
    "FAILED_VERIFICATION", "TARGET_PRECONDITION_CONFLICT",
    "TARGET_IN_PROGRESS", "WAITING_HUMAN", "DENY", "LOCAL_ONLY",
    "FAILED_EFFECT", "CANCELLED_RECONCILE_REQUIRED",
})

class Denied(RuntimeError):
    pass

def require(ok, code):
    if not ok:
        raise Denied(code)

def check_event(event, env, live=None):
    require(env.get("GITHUB_REPOSITORY") == REPO
            and env.get("GITHUB_WORKFLOW") == WORKFLOW
            and env.get("GITHUB_EVENT_NAME") == "issues"
            and env.get("GITHUB_ACTOR") == OWNER
            and platform.system() == "Darwin"
            and platform.machine() == "arm64"
            and os.getuid() == 501 and os.geteuid() == 501,
            "OWNER_HOST_CONTEXT_REQUIRED")
    require(type(event) is dict and event.get("action") == "opened"
            and type(event.get("repository")) is dict
            and event["repository"].get("full_name") == REPO
            and type(event.get("sender")) is dict
            and event["sender"].get("login") == OWNER,
            "OWNER_EVENT_REQUIRED")
    issue = event.get("issue")
    sha = env.get("GITHUB_SHA")
    require(type(sha) is str and SHA40.fullmatch(sha) is not None
            and type(issue) is dict and type(issue.get("number")) is int
            and 0 < issue["number"] < 2**31
            and issue.get("state") == "open"
            and type(issue.get("user")) is dict
            and issue["user"].get("login") == OWNER
            and issue.get("title") == PREFIX + sha
            and issue.get("body") ==
               "<!-- foundation-m1-toolhive-files-repair:v1:" + sha + " -->",
            "PINNED_OWNER_ISSUE_REQUIRED")
    if live is not None:
        require(type(live) is dict and live.get("number") == issue["number"]
                and live.get("state") == "open" and
                live.get("title") == issue["title"] and
                live.get("body") == issue["body"] and
                type(live.get("user")) is dict and
                live["user"].get("login") == OWNER,
                "OWNER_ISSUE_CHANGED")
    return issue["number"], sha

def pinned_container_image(package):
    """Require exact local OCI content ID; never trust a CLI package spelling.

    Only the built-in fixed Docker command and the pinned sha256 result can
    authorize a workload start. No shell, pull, tag, install or private output.
    """
    require(type(package) is str and IMAGE_REF.fullmatch(package) is not None,
            "TOOLHIVE_IMAGE_REFERENCE_INVALID")
    docker = next((p for p in DOCKER_BINARIES if Path(p).is_file()), None)
    require(docker is not None, "PINNED_DOCKER_INSPECT_UNAVAILABLE")
    try:
        result = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", package],
            capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Denied("PINNED_DOCKER_INSPECT_UNAVAILABLE") from exc
    require(result.returncode == 0 and type(result.stdout) is str
            and result.stdout.strip() == EXPECTED_IMAGE_ID,
            "TOOLHIVE_DOCKER_IMAGE_ID_MISMATCH")


def verify_saved_files_config(binary):
    """v0.49 omits Package for non-running file-status records.

    Export only into an owner-private temporary directory; never print or
    persist its contents. Validate the configuration actually used by start.
    """
    with tempfile.TemporaryDirectory(prefix="foundation-files-check-") as directory:
        path = Path(directory) / "config.json"
        try:
            cp = subprocess.run(
                [str(binary), "export", NAME, str(path)],
                capture_output=True, timeout=7)
            require(cp.returncode == 0 and path.is_file()
                    and not path.is_symlink() and path.stat().st_size <= 262144,
                    "TOOLHIVE_SAVED_CONFIG_UNAVAILABLE")
            config = json.loads(path.read_text())
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            raise Denied("TOOLHIVE_SAVED_CONFIG_UNAVAILABLE") from exc
        require(type(config) is dict and config.get("name") == NAME
                and not config.get("remote_url")
                and config.get("isolate_network") is True,
                "TOOLHIVE_SAVED_CONFIG_IDENTITY_UNVERIFIED")
        pinned_container_image(config.get("image"))

def health_reason(row):
    """Fixed categories only; never publish ToolHive's free-form health text."""
    health = row.get("health")
    if type(health) is not str or not health:
        return "UNREPORTED"
    if health.startswith("proxy process not running:"):
        return "PROXY_NOT_RUNNING"
    if health.startswith("workload status mismatch:"):
        return "CONTAINER_STATUS_MISMATCH"
    if health.startswith("workload ") and "not found in runtime" in health:
        return "CONTAINER_NOT_FOUND"
    return "OTHER"

def cli_status(binary, *, timeout=5, observation=None):
    try:
        cp = subprocess.run([str(binary), "status", NAME, "--format", "json"],
                            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Denied("TOOLHIVE_STATUS_UNAVAILABLE") from exc
    require(cp.returncode == 0 and type(cp.stdout) is str
            and len(cp.stdout) <= 8192,
            "TOOLHIVE_STATUS_NOT_OK")
    try:
        row = json.loads(cp.stdout)
    except (ValueError, TypeError) as exc:
        raise Denied("TOOLHIVE_STATUS_INVALID") from exc
    require(type(row) is dict and row.get("name") == NAME
            and type(row.get("status")) is str,
            "TOOLHIVE_IDENTITY_UNVERIFIED")
    # ToolHive v0.49 package comes from Docker's container.Image, which is
    # not guaranteed to equal the original registry alias. Bind any ref to
    # the one reviewed OCI sha256 rather than extending string allowlists.
    if row.get("package") == "" and row["status"] in {
            "unhealthy", "starting", "stopped", "stopping"}:
        verify_saved_files_config(binary)
    else:
        pinned_container_image(row.get("package"))
    if observation is not None:
        observation["health_reason"] = health_reason(row)
        observation["state"] = (row["status"].upper() if row["status"] in {
            "running", "starting", "unhealthy", "stopped", "stopping", "error",
            "policy_stopped", "unauthenticated", "auth_retrying", "removing",
            "unknown"} else "OTHER")
    return row["status"]

class FixedFilesWorkload:
    def __init__(self, binary):
        self.binary = binary
        self.dispatches = 0
        self.readback = {}

    def observe(self, plan):
        require(plan.target == "toolhive:" + NAME,
                "TOOLHIVE_FIXED_TARGET_REQUIRED")
        # Before dispatch, a single independent observation must still match
        # the exact unhealthy precondition. After dispatch, allow ToolHive's
        # existing supervisor a bounded interval to become actually running.
        attempts = 1 if self.dispatches == 0 else 20
        for index in range(attempts):
            status = cli_status(self.binary, observation=self.readback)
            if self.dispatches == 0:
                return status.upper()
            if status == "running":
                return "RUNNING"
            if status in {"error", "unhealthy", "stopped", "policy_stopped",
                          "unauthenticated"}:
                break
            if index != attempts - 1:
                time.sleep(.4)
        return "NOT_VERIFIED"

    def execute(self, plan):
        require(self.dispatches == 0 and plan.target == "toolhive:" + NAME
                and plan.action == "production_deploy" and
                plan.target_precondition == "UNHEALTHY",
                "TOOLHIVE_FIXED_ONE_SHOT_REQUIRED")
        # Set the uncertain-effect barrier BEFORE this potentially effectful
        # ToolHive call. Never replay after a timeout or ambiguous exit.
        self.dispatches = 1
        # This is an authorized persistent workload, not a CI test child.
        # Keep runner cleanup active for all other subprocesses. Only this
        # exact start and its ToolHive supervisor outlive the GitHub job.
        child_env = dict(os.environ)
        child_env.pop("RUNNER_TRACKING_ID", None)
        child_env.pop("GITHUB_TOKEN", None)
        try:
            cp = subprocess.run([str(self.binary), "start", NAME],
                                capture_output=True, timeout=75, env=child_env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError("TOOLHIVE_START_OUTCOME_UNCERTAIN") from exc
        if cp.returncode:
            raise RuntimeError("TOOLHIVE_START_OUTCOME_UNCERTAIN")

def action(event, env, token):
    number, sha = check_event(event, env)
    prefix = f"/repos/{REPO}/issues/{number}"
    check_event(event, env, bridge._github_api("GET", prefix, token))
    history = bridge._github_api("GET", prefix + "/comments?per_page=100", token)
    require(type(history) is list and len(history) < 100
            and all(MARKER + str(number) + " -->" not in x.get("body", "")
                    for x in history if type(x) is dict),
            "REPAIR_RECEIPT_ALREADY_PRESENT")
    head = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=7)
    clean = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "status",
                            "--porcelain", "--untracked-files=no"],
                           capture_output=True, text=True, timeout=7)
    require(head.returncode == 0 and head.stdout.strip() == sha
            and clean.returncode == 0 and not clean.stdout.strip(),
            "PINNED_MAIN_CHECKOUT_REQUIRED")
    canon = observe_release_canon(ROOT)
    require(canon.get("source_main") == sha and
            str(canon.get("canon_revision","")).startswith("canon-source/v1:"),
            "LIVE_MAIN_CANON_REQUIRED")
    home = Path.home()
    binary = owner_toolhive_binary(home)
    require(binary is not None, "PINNED_TOOLHIVE_CLI_REQUIRED")
    host = FixedOperatorHost(ROOT, home=home)
    # Preserve every original admission condition, but return the exact
    # failed fixed predicate without PID, process, HTTP or owner details.
    require(host._registered(), "OPERATOR_LAUNCHD_UNVERIFIED")
    require(host._pid_owned(), "OPERATOR_PID_BINDING_UNVERIFIED")
    observed = host._human()
    require(type(observed) is dict and
            type(observed.get("activity")) is list,
            "OPERATOR_ACTIVITY_UNAVAILABLE")
    require(not observed["activity"], "OPERATOR_WORK_IN_PROGRESS")
    require(cli_status(binary) == "unhealthy",
            "TOOLHIVE_INITIAL_STATE_CHANGED")
    guard_path, _ = _guard_path(home)
    store = SQLiteGuardStore(guard_path)
    guard = GuardCore(store.runtime_state(), store=store)
    # The same exact-main revision cannot mint a second effect by posting
    # a new Issue after an ambiguous start outcome.
    run_id = "toolhive-files-repair-" + sha[:24]
    effect_id = run_id + ":start"
    target = "toolhive:" + NAME
    plan = TaskPlan(run_id, "production_deploy", target,
                    canon_revision=canon["canon_revision"],
                    target_precondition="UNHEALTHY",
                    exclusive_target=True, effect_id=effect_id)
    canon_contract = CanonContract("foundation-toolhive-files",
                                   canon["canon_revision"])
    require(store.request_approval(run_id, plan.action, target,
                                   plan.canon_revision, effect_id),
            "GUARD_EXACT_APPROVAL_REQUEST_DENIED")
    with store._connect() as conn:
        request = conn.execute(
            "SELECT action,target,request_nonce,canon_revision,effect_id "
            "FROM approval_requests WHERE run_id=?", (run_id,)).fetchone()
    require(request is not None, "GUARD_REQUEST_UNAVAILABLE")
    ref = approval_request_ref(run_id, *request)
    check_event(event, env, bridge._github_api("GET", prefix, token))
    decision = OperatorActions(guard).approve_pending(run_id, ref)
    require(decision.ok and decision.status == "APPROVED",
            "GUARD_OWNER_APPROVAL_DENIED")
    # Check the fixed work identity again after Guard approval, before execute.
    check_event(event, env, bridge._github_api("GET", prefix, token))
    require(cli_status(binary) == "unhealthy",
            "TOOLHIVE_LAST_MOMENT_STATE_CHANGED")
    port = FixedFilesWorkload(binary)
    outcome = guard.execute(plan, canon_contract, port, "RUNNING")
    require(outcome in ALLOWED_RESULTS, "GUARD_RESULT_UNKNOWN")
    return {"status": "VERIFIED" if outcome == "VERIFIED_COMPLETE" else "NOT_VERIFIED",
            "result": outcome, "toolhive_files": "RUNNING" if outcome == "VERIFIED_COMPLETE" else "UNVERIFIED",
            "dispatch_count": port.dispatches, "readback": port.readback,
            "other_workloads_affected": False, "model_calls": 0}

def main():
    env = os.environ
    require(type(env.get("GITHUB_TOKEN")) is str and env.get("GITHUB_TOKEN")
            and env.get("GITHUB_EVENT_PATH"), "GITHUB_CONTEXT_REQUIRED")
    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
    number, _ = check_event(event, env)
    token = env["GITHUB_TOKEN"]
    try:
        result = action(event, env, token)
    except Denied as exc:
        result = {"status": "BLOCKED", "reason": str(exc)}
    except (OSError, RuntimeError, ValueError, KeyError,
            subprocess.TimeoutExpired, TypeError) as exc:
        result = {"status": "BLOCKED", "reason": "UNEXPECTED_" + type(exc).__name__}
    prefix = f"/repos/{REPO}/issues/{number}"
    body = (MARKER + str(number) + " -->\n"
            + "Owner-pinned ToolHive FILES one-shot result (no CLI output)\n\n~~~json\n"
            + json.dumps(result,sort_keys=True) + "\n~~~")
    bridge._github_api("POST", prefix + "/comments", token, {"body":body})
    print(json.dumps({"status":result["status"],
                      "reason":result.get("reason",result.get("result","UNKNOWN"))}))
    if result["status"] != "VERIFIED":
        raise SystemExit(2)

if __name__ == "__main__":
    try:
        main()
    except (Denied,OSError,ValueError,RuntimeError) as exc:
        print("ToolHive owner repair denied: " +
              (str(exc) if isinstance(exc, Denied)
               else type(exc).__name__),file=sys.stderr)
        raise SystemExit(2)
