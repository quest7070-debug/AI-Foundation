"""Fixed owner CODE recovery: isolated public checkout, existing Guard, one run.

Never reuse the owner's divergent checkout, remove workloads, stop models,
change FILES or restart Operator. Operator binding remains a separate release.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from scripts import m1_development_bridge as bridge
from scripts.m1_owner_toolhive_files_repair import (
    Denied, require, pinned_container_image, DOCKER_BINARIES, EXPECTED_IMAGE_ID)
from scripts.m1_operator_release_canon import observe_release_canon
from scripts.m1_operator_release_cli import _guard_path
from scripts.m1_operator_release_host import FixedOperatorHost
from ai_foundation.core import TaskPlan, CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.store import SQLiteGuardStore, approval_request_ref
from ai_foundation.toolhive_owner_runtime import owner_toolhive_binary

NAME = "ai-foundation-repo"
WORKFLOW = "Foundation M1 owner isolated CODE recovery"
PREFIX = "Foundation M1 CODE Recovery: "
MARKER = "<!-- foundation-m1-code-recovery-receipt:v1:"


def identity(event, env, live=None):
    sha = env.get("GITHUB_SHA", "")
    require(platform.system() == "Darwin" and platform.machine() == "arm64"
            and os.getuid() == os.geteuid() == 501,
            "OWNER_M1_REQUIRED")
    require(env.get("GITHUB_REPOSITORY") == bridge.REPOSITORY
            and env.get("GITHUB_WORKFLOW") == WORKFLOW
            and env.get("GITHUB_EVENT_NAME") == "issues"
            and env.get("GITHUB_ACTOR") == bridge.OWNER_LOGIN
            and re.fullmatch(r"[a-f0-9]{40}", sha) is not None,
            "EXACT_OWNER_CONTEXT_REQUIRED")
    issue = event.get("issue", {})
    require(event.get("action") == "opened"
            and event.get("repository", {}).get("full_name") == bridge.REPOSITORY
            and event.get("sender", {}).get("login") == bridge.OWNER_LOGIN
            and issue.get("user", {}).get("login") == bridge.OWNER_LOGIN
            and issue.get("state") == "open"
            and type(issue.get("number")) is int and 0 < issue["number"] < 2**31
            and issue.get("title") == PREFIX + sha
            and issue.get("body") == "<!-- foundation-m1-code-recovery:v1:" + sha + " -->",
            "EXACT_OWNER_ISSUE_REQUIRED")
    if live is not None:
        require(all(live.get(k) == issue.get(k) for k in ("number", "title", "body", "state"))
                and live.get("user", {}).get("login") == bridge.OWNER_LOGIN,
                "OWNER_ISSUE_CHANGED")
    return issue["number"], sha


def clean_env():
    return {"HOME": str(Path.home()), "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
            "USER": os.environ.get("USER", ""), "TMPDIR": os.environ.get("TMPDIR", "/tmp")}


def command(argv, timeout=10):
    cp = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=clean_env())
    require(cp.returncode == 0 and len(cp.stdout) <= 262144, "FIXED_COMMAND_UNVERIFIED")
    return cp.stdout.strip()


def git(root, *args):
    return command(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "-C", str(root), *args], 40)


def prepare_workspace(sha, home=None):
    home = Path.home() if home is None else Path(home)
    parent = home / "Develop"
    info = parent.lstat()
    import stat
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022, "OWNER_DEVELOP_DIRECTORY_UNVERIFIED")
    destination = parent / "AI-Foundation-CODE"
    require(not destination.is_symlink(), "CODE_WORKSPACE_ALIAS")
    if not destination.exists():
        # Own object store: no shared .git, alternates or hardlinks to the
        # owner's original repository or disposable runner checkout.
        command(["/usr/bin/git", "-c", "core.hooksPath=/dev/null", "clone",
                 "--no-hardlinks", "--no-checkout", str(ROOT), str(destination)], 90)
        git(destination, "checkout", "--detach", sha)
        git(destination, "remote", "remove", "origin")
    info = destination.lstat()
    metadata = destination / ".git"
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o022
            and not metadata.is_symlink() and metadata.is_dir()
            and git(destination, "rev-parse", "--git-common-dir") == ".git"
            and git(destination, "rev-parse", "--show-toplevel") == str(destination.resolve())
            and git(destination, "rev-parse", "HEAD") == sha
            and not git(destination, "status", "--porcelain")
            # Porcelain hides ignored .env/SQLite files; never mount those via MCP.
            and not git(destination, "ls-files", "--others", "--ignored", "--exclude-standard", "--directory")
            and not (destination / ".git/objects/info/alternates").exists(),
            "CODE_WORKSPACE_REVIEW_REQUIRED")
    require((destination / "pyproject.toml").read_bytes() == (ROOT / "pyproject.toml").read_bytes(),
            "CODE_WORKSPACE_SOURCE_MISMATCH")
    return destination


class FixedCodeWorkload:
    def __init__(self, binary, workspace, docker):
        self.binary, self.workspace, self.docker = binary, workspace, docker
        self.dispatches = 0

    def observe(self, plan):
        require(plan.target == "toolhive:" + NAME, "FIXED_CODE_TARGET_REQUIRED")
        rows = json.loads(command([str(self.binary), "list", "--all", "--format", "json"]))
        require(type(rows) is list and len(rows) <= 100
                and all(type(r) is dict and type(r.get("name")) is str for r in rows),
                "TOOLHIVE_INVENTORY_UNVERIFIED")
        found = [r for r in rows if r["name"] == NAME]
        if not found:
            names = command([self.docker, "ps", "-a", "--format", "{{.Names}}",
                             "--filter", "name=^/" + NAME + "$"])
            require(not names, "CODE_CONTAINER_REGISTRY_CONFLICT")
            return "ABSENT"
        if self.dispatches == 0:
            return "EXISTING_WORKLOAD_REVIEW_REQUIRED"
        for _ in range(20):
            row = json.loads(command([str(self.binary), "status", NAME, "--format", "json"]))
            if row.get("name") == NAME and row.get("status") == "running":
                mounts = json.loads(command([self.docker, "inspect", "--format", "{{json .Mounts}}", NAME]))
                require(type(mounts) is list
                        and [m for m in mounts if m.get("Type") == "bind"] == [next(
                            (m for m in mounts if m.get("Type") == "bind"
                             and m.get("Source") == str(self.workspace.resolve())
                             and m.get("Destination") == "/projects" and m.get("RW") is True), None)],
                        "CODE_MOUNT_IDENTITY_UNVERIFIED")
                image = command([self.docker, "inspect", "--format", "{{.Image}}", NAME])
                isolated = command([self.docker, "inspect", "--format",
                                    '{{index .Config.Labels "toolhive-network-isolation"}}', NAME])
                require(image == EXPECTED_IMAGE_ID and isolated == "true", "CODE_CONTAINMENT_UNVERIFIED")
                response = json.loads(command([str(self.binary), "mcp", "call", "read_text_file",
                    "--server", NAME, "--format", "json", "--args", '{"path":"/projects/pyproject.toml"}'], 20))
                require(type(response) is dict and response.get("isError", False) is False
                        and type(response.get("content")) is list
                        and all(type(c) is dict and c.get("type") == "text" and type(c.get("text")) is str
                                for c in response["content"])
                        and "".join(c["text"] for c in response["content"]) ==
                            (self.workspace / "pyproject.toml").read_text(), "CODE_MCP_READBACK_UNVERIFIED")
                return "RUNNING_VERIFIED_MOUNT"
            time.sleep(.5)
        return "NOT_VERIFIED"

    def execute(self, plan):
        require(self.dispatches == 0 and plan.target == "toolhive:" + NAME
                and plan.action == "production_deploy" and plan.target_precondition == "ABSENT",
                "FIXED_ONE_SHOT_CODE_REQUIRED")
        self.dispatches = 1
        command([str(self.binary), "run", "--transport", "stdio", "--proxy-mode", "streamable-http",
                 "--name", NAME, "--isolate-network", "--image-verification", "warn", "--enable-audit",
                 "--volume", str(self.workspace) + ":/projects", EXPECTED_IMAGE_ID, "--", "/projects"], 75)


def approve_unused_plan(store, guard, plan):
    # Resume only the exact previously approved plan if no durable effect has
    # ever been created. Never re-arm a dispatched/uncertain effect or silently
    # carry an approval across a different main/Canon revision.
    require(store.get_effect(plan.effect_id) is None, "CODE_EFFECT_ALREADY_RECORDED")
    if store.is_approved_for(plan.run_id, plan.action, plan.target,
                             plan.canon_revision, plan.effect_id):
        return
    require(store.request_approval(plan.run_id, plan.action, plan.target,
                                   plan.canon_revision, plan.effect_id), "GUARD_REQUEST_DENIED")
    with store._connect() as con:
        request = con.execute("SELECT action,target,request_nonce,canon_revision,effect_id FROM approval_requests WHERE run_id=?", (plan.run_id,)).fetchone()
    require(request is not None, "GUARD_REQUEST_UNAVAILABLE")
    decision = OperatorActions(guard).approve_pending(
        plan.run_id, approval_request_ref(plan.run_id, *request))
    require(decision.ok and decision.status == "APPROVED", "GUARD_OWNER_DECISION_DENIED")


def action(event, env, token):
    number, sha = identity(event, env)
    prefix = f"/repos/{bridge.REPOSITORY}/issues/{number}"
    identity(event, env, bridge._github_api("GET", prefix, token))
    require(git(ROOT, "rev-parse", "HEAD") == sha and not git(ROOT, "status", "--porcelain", "--untracked-files=no"),
            "PINNED_MAIN_SOURCE_REQUIRED")
    canon = observe_release_canon(ROOT)
    require(canon.get("source_main") == sha and str(canon.get("canon_revision", "")).startswith("canon-source/v1:"),
            "CURRENT_MAIN_CANON_REQUIRED")
    binary = owner_toolhive_binary()
    require(binary is not None, "PINNED_TOOLHIVE_REQUIRED")
    docker = next((p for p in DOCKER_BINARIES if Path(p).is_file()), None)
    require(docker is not None, "DOCKER_REQUIRED")
    pinned_container_image(EXPECTED_IMAGE_ID)
    host = FixedOperatorHost(ROOT)
    live = host._human()
    require(host._registered() and host._pid_owned() and type(live) is dict
            and live.get("activity") == [], "OPERATOR_NOT_IDLE_OR_PID_BOUND")
    workspace = prepare_workspace(sha)
    port = FixedCodeWorkload(binary, workspace, docker)
    store = SQLiteGuardStore(_guard_path(Path.home())[0])
    guard = GuardCore(store.runtime_state(), store=store)
    run_id = "toolhive-code-isolated-recovery-v1"
    plan = TaskPlan(run_id, "production_deploy", "toolhive:" + NAME,
                    canon_revision=canon["canon_revision"], target_precondition="ABSENT",
                    exclusive_target=True, effect_id=run_id + ":create")
    require(port.observe(plan) == "ABSENT", "CODE_WORKLOAD_ALREADY_EXISTS")
    identity(event, env, bridge._github_api("GET", prefix, token))
    approve_unused_plan(store, guard, plan)
    identity(event, env, bridge._github_api("GET", prefix, token))
    live = host._human()
    require(host._pid_owned() and type(live) is dict and live.get("activity") == [],
            "OPERATOR_NOT_IDLE_OR_PID_BOUND")
    outcome = guard.execute(plan, CanonContract("foundation-toolhive-code", canon["canon_revision"]), port,
                            "RUNNING_VERIFIED_MOUNT")
    return {"status": "VERIFIED" if outcome == "VERIFIED_COMPLETE" else "NOT_VERIFIED",
            "guard_result": outcome, "dispatch_count": port.dispatches, "model_calls": 0,
            "original_checkout_changed": False, "operator_binding_changed": False,
            "files_workload_changed": False}


def main():
    env = os.environ
    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_text())
    number, _ = identity(event, env)
    try:
        result = action(event, env, env["GITHUB_TOKEN"])
    except Denied as exc:
        result = {"status": "BLOCKED", "reason": str(exc)}
    except Exception as exc:
        result = {"status": "BLOCKED", "reason": "UNEXPECTED_" + type(exc).__name__}
    bridge._github_api("POST", f"/repos/{bridge.REPOSITORY}/issues/{number}/comments", env["GITHUB_TOKEN"],
                       {"body": MARKER + str(number) + " -->\n~~~json\n" + json.dumps(result, sort_keys=True) + "\n~~~"})
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
