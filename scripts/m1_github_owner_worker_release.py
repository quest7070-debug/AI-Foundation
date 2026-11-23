"""One-shot exact GitHub owner/Guard release of the idle 9B worker.

Preserves the previously consumed queue, modules, results and all other
services. Reuses existing immutable full-source staging and Guard ledger.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import stat
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.host_compute_lease import HostComputeLease
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.release_gate import GuardReleaseGate, ImmutableReleaseScope
from ai_foundation.store import SQLiteGuardStore
from scripts.m1_operator_release_cli import _guard_path
from scripts.m1_operator_release_canon import observe_release_canon
from scripts.m1_operator_release_stage import stage_operator_only, verify_staged, _save
from scripts.m1_p4_release_inventory import _owned_regular_bytes, operator_only_release_scope
from scripts.m1_local9b_admission_release import atomic_plist, launch

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 owner main 9B worker release"
LABEL = "dev.quest7070.ai-foundation.local9b-autodev"
PREFIX = "Foundation M1 Worker Release: "
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
ISSUE_URL = "https://api.github.com/repos/" + REPO + "/issues/"

class Denied(ValueError):
    pass

def require(ok, reason):
    if not ok:
        raise Denied(reason)

def owner_event(event, env, live=None):
    require(env.get("GITHUB_REPOSITORY") == REPO
            and env.get("GITHUB_WORKFLOW") == WORKFLOW
            and env.get("GITHUB_EVENT_NAME") == "issues"
            and env.get("GITHUB_ACTOR") == OWNER
            and event.get("action") == "opened"
            and event.get("sender", {}).get("login") == OWNER
            and event.get("repository", {}).get("full_name") == REPO,
            "EXACT_OWNER_ISSUE_REQUIRED")
    issue = event.get("issue")
    sha = env.get("GITHUB_SHA")
    require(type(issue) is dict and type(issue.get("number")) is int
            and 0 < issue["number"] < 2**31
            and issue.get("state") == "open"
            and issue.get("user", {}).get("login") == OWNER
            and type(sha) is str and SHA40.fullmatch(sha) is not None
            and issue.get("title") == PREFIX + sha
            and issue.get("body") == "<!-- foundation-m1-worker-release:v1:" + sha + " -->",
            "PINNED_OWNER_WORKER_ISSUE_REQUIRED")
    if live is not None:
        require(type(live) is dict and live.get("number") == issue["number"]
                and live.get("title") == issue["title"]
                and live.get("body") == issue["body"]
                and live.get("state") == "open"
                and live.get("user", {}).get("login") == OWNER,
                "OWNER_ISSUE_CHANGED")
    return issue["number"], sha

def github_issue(number, token):
    require(type(token) is str and token, "GITHUB_TOKEN_REQUIRED")
    req = urllib.request.Request(
        ISSUE_URL + str(number),
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "foundation-m1-owner-worker-release"})
    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            raw = response.read(65537)
        require(len(raw) <= 65536, "ISSUE_SIZE_EXCEEDED")
        return json.loads(raw)
    except (OSError, ValueError) as exc:
        raise Denied("LIVE_OWNER_ISSUE_UNAVAILABLE") from exc

def owned_directory(root):
    root = Path(root)
    require(root.is_absolute() and ".." not in root.parts
            and not root.is_symlink() and root.resolve(strict=True) == root,
            "WORKER_STATE_ROOT_UNTRUSTED")
    for part in ("", "inbox", "results"):
        path = root / part
        info = path.lstat()
        require(not path.is_symlink() and stat.S_ISDIR(info.st_mode)
                and info.st_uid == os.getuid() and not info.st_mode & 0o022,
                "WORKER_STATE_COMPONENT_UNTRUSTED")
    return root

def worker_queue_contract(raw):
    """Recognize modern main as well as historical installed worker roots."""
    if b"ROOT=configure_worker_paths(" in raw:
        return "helper"
    if (b'_STATE=os.environ.get("AI_FOUNDATION_LOCAL9B_STATE_ROOT")' in raw
            and b'STATE_ROOT=Path(_STATE).resolve(strict=True) if _STATE else ROOT' in raw
            and b'STATE_ROOT/"inbox"' in raw
            and b'STATE_ROOT/"results"' in raw):
        return "state-root"
    if b"ROOT=Path(__file__).resolve().parent" in raw:
        return "legacy"
    raise Denied("WORKER_QUEUE_BINDING_UNKNOWN")

def installed_worker(home):
    plist = home / "Library/LaunchAgents" / (LABEL + ".plist")
    original = _owned_regular_bytes(plist, max_bytes=32768)
    row = plistlib.loads(original)
    args = row.get("ProgramArguments")
    require(row.get("Label") == LABEL and type(args) is list
            and 2 <= len(args) <= 24, "INSTALLED_WORKER_PLIST_INVALID")
    scripts = [x for x in args if type(x) is str and x.startswith("/")
               and x.endswith("/local9b_autodev_worker.py")]
    require(len(scripts) == 1, "INSTALLED_WORKER_SCRIPT_AMBIGUOUS")
    old = Path(scripts[0])
    raw = _owned_regular_bytes(old, max_bytes=2097152)
    # Old worker physically anchors inbox/modules/results to script directory.
    # The installed P4 worker uses the owner LaunchAgent's state-root.
    # Older standalone workers anchor the queue to the script directory.
    mode = worker_queue_contract(raw)
    old_env = row.get("EnvironmentVariables") or {}
    require(type(old_env) is dict, "OLD_WORKER_ENV_UNTRUSTED")
    selected = old_env.get("AI_FOUNDATION_LOCAL9B_STATE_ROOT")
    require(selected is None or type(selected) is str,
            "OLD_WORKER_QUEUE_ENV_INVALID")
    queue = owned_directory(old.parent if mode == "legacy"
                            else selected or old.parent)
    status = launch("print", "gui/501/" + LABEL)
    require(status.returncode == 0 and str(old) in status.stdout
            and re.search(r"^\s*state = not running\s*$",
                          status.stdout, re.MULTILINE) is not None,
            "WORKER_NOT_SCHEDULED_IDLE")
    return plist, original, row, old, raw, queue

def new_scope(commit, previous, candidate):
    plist, original, row, old, oldraw, queue = previous
    candidate_hash = sha256(_owned_regular_bytes(candidate, max_bytes=2097152)).hexdigest()
    fingerprint = sha256(json.dumps({
        "schema": 1, "commit": commit,
        "prior_plist": sha256(original).hexdigest(),
        "prior_source": sha256(oldraw).hexdigest(),
        "candidate_worker": candidate_hash,
        "queue_path_sha256": sha256(str(queue).encode()).hexdigest(),
    }, sort_keys=True).encode()).hexdigest()
    return ImmutableReleaseScope(
        path="m1-local9b-main-worker",
        source_sha=fingerprint,
        previous_authority="owner-installed:" + sha256(oldraw).hexdigest()
                + ":" + sha256(original).hexdigest(),
        previous_endpoint="launchd:" + LABEL,
        candidate_authority="github-commit:" + commit,
        candidate_endpoint="staged-worker:" + candidate_hash,
        rollback_procedure="RESTORE_EXACT_OLD_WORKER_PLIST;KEEP_QUEUE_AND_MODULES",
        switch_target="IDLE_9B_WORKER_ONLY_LAUNCHD_SWITCH",
        readback_target="REGISTERED_MAIN_WORKER_AND_PRESERVED_QUEUE",
        rollback_readback_target="EXACT_PREVIOUS_WORKER_AND_EXISTING_QUEUE",
    )

class OwnerIssueGate:
    def __init__(self, event, env, token, scope, run, ref):
        self.event, self.env, self.token = event, env, token
        self.binding = (scope.scope_ref, run, ref)

    def verify_exact_release(self, scope, run, ref):
        if (scope.scope_ref, run, ref) != self.binding:
            return False
        try:
            number, _ = owner_event(self.event, self.env)
            owner_event(self.event, self.env,
                        live=github_issue(number, self.token))
            return True
        except Denied:
            return False

def worker_release(event, env, token):
    require(platform.system() == "Darwin" and platform.machine() == "arm64"
            and os.getuid() == 501 and os.geteuid() == 501, "OWNER_M1_REQUIRED")
    number, commit = owner_event(event, env)
    owner_event(event, env, live=github_issue(number, token))
    checked = subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=8)
    require(checked.returncode == 0 and checked.stdout.strip() == commit,
            "EXACT_MAIN_COMMIT_REQUIRED")
    current = observe_release_canon(ROOT)
    require(current.get("source_main") == commit, "LIVE_MAIN_CHANGED")
    home = Path.home()
    with HostComputeLease().hold(max_wait_s=120):
        previous = installed_worker(home)
        op_scope, record = operator_only_release_scope(home=home, root=ROOT)
        require(op_scope is not None and record.get("status") == "OBSERVED"
                and record.get("candidate_sha") == commit,
                "CURRENT_SOURCE_STAGING_SCOPE_UNVERIFIED")
        staged = stage_operator_only(ROOT, home)
        require(staged.get("backup_verified") is True
                and staged.get("scope_ref") == op_scope.scope_ref,
                "OPERATOR_SOURCE_STAGING_FAILED")
        directory = (home / "Library/Application Support/AI-Foundation"
                     / "operator-release-staging" / op_scope.scope_ref)
        require(verify_staged(directory, op_scope.scope_ref) is True,
                "STAGED_MAIN_SOURCE_UNVERIFIED")
        candidate_root = directory / "candidate"
        target = candidate_root / "scripts/local9b_autodev_worker.py"
        require(target.exists() and not target.is_symlink(),
                "MAIN_WORKER_SOURCE_UNAVAILABLE")
        data = _owned_regular_bytes(target, max_bytes=2097152)
        mode = worker_queue_contract(data)
        require(mode in ("helper", "state-root")
                and b"AI_FOUNDATION_LOCAL9B_STATE_ROOT" in data
                and (mode != "helper" or
                     (candidate_root / "scripts/local9b_worker_paths.py").is_file()),
                "WORKER_QUEUE_BINDING_NOT_REVIEWED")
        compile(data, str(target), "exec")
        scope = new_scope(commit, previous, target)
        p, old_plist, row, old, raw, queue = previous
        args = list(row["ProgramArguments"])
        args[args.index(str(old))] = str(target)
        updated = dict(row)
        updated["ProgramArguments"] = args
        environment = dict(row.get("EnvironmentVariables") or {})
        environment["AI_FOUNDATION_LOCAL9B_STATE_ROOT"] = str(queue)
        former_path = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = (
            str(candidate_root / "src") + ":" + str(candidate_root / "scripts")
            + (":" + former_path if former_path else ""))
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        updated["EnvironmentVariables"] = environment
        proposed = plistlib.dumps(updated)
        _save(directory / "previous-worker-launchagent.plist", old_plist)
        _save(directory / "previous-worker-entry.py", raw)
        _save(directory / "proposed-worker-launchagent.plist", proposed)
        original_sha = sha256(old_plist).hexdigest()
        require(_owned_regular_bytes(p, max_bytes=32768) == old_plist
                and installed_worker(home)[:4] == previous[:4],
                "WORKER_CHANGED_DURING_STAGING")
        guard_db, _ = _guard_path(home)
        registry = guard_db.parent / (
            "owner-worker-release-" + scope.scope_ref[:20] + ".json")
        require(not registry.exists() and not registry.is_symlink(),
                "WORKER_RELEASE_ALREADY_ATTEMPTED")
        store = SQLiteGuardStore(guard_db)
        gate = GuardReleaseGate(store, registry)
        prepared = gate.prepare(scope, canon_revision=current["canon_revision"])
        require(prepared.get("ok") is True
                and prepared.get("status") == "WAITING_HUMAN",
                "WORKER_GUARD_REQUEST_FAILED")
        owner = OwnerIssueGate(event, env, token, scope,
                               prepared["run_id"], prepared["request_ref"])
        require(owner.verify_exact_release(
            scope, prepared["run_id"], prepared["request_ref"]),
            "OWNER_RELEASE_CONTEXT_CHANGED")
        guard = GuardCore(store.runtime_state(), store=store)
        approve = OperatorActions(guard).approve_pending(
            prepared["run_id"], prepared["request_ref"])
        require(approve.ok and approve.status == "APPROVED",
                "WORKER_GUARD_APPROVAL_DENIED")
        verification = gate.verify(scope, prepared["run_id"],
                                   prepared["request_ref"])
        require(verification.get("approved") is True,
                "WORKER_DURABLE_GUARD_READBACK_DENIED")
        require(installed_worker(home)[:4] == previous[:4]
                and owner.verify_exact_release(
                    scope, prepared["run_id"], prepared["request_ref"]),
                "WORKER_RELEASE_SCOPE_CHANGED")
        gate.registry.transition(scope.path, "PREPARED", "CUTOVER")
        stopped = False
        try:
            require(launch("bootout", "gui/501/" + LABEL).returncode == 0,
                    "IDLE_WORKER_BOOTOUT_DENIED")
            stopped = True
            atomic_plist(p, proposed)
            require(launch("bootstrap", "gui/501", str(p)).returncode == 0,
                    "NEW_WORKER_BOOTSTRAP_DENIED")
            current_state = launch("print", "gui/501/" + LABEL)
            require(current_state.returncode == 0
                    and str(target) in current_state.stdout
                    and p.read_bytes() == proposed
                    and owned_directory(queue) == queue
                    and verify_staged(directory, op_scope.scope_ref) is True,
                    "MAIN_WORKER_READBACK_NOT_VERIFIED")
            gate.registry.transition(scope.path, "CUTOVER", "VERIFIED")
        except BaseException:
            if stopped:
                launch("bootout", "gui/501/" + LABEL)
                atomic_plist(p, old_plist)
                restored = launch("bootstrap", "gui/501", str(p))
                status = launch("print", "gui/501/" + LABEL)
                require(restored.returncode == 0
                        and p.read_bytes() == old_plist
                        and sha256(p.read_bytes()).hexdigest() == original_sha
                        and str(old) in status.stdout,
                        "WORKER_ROLLBACK_NOT_VERIFIED")
            gate.registry.transition(scope.path, "CUTOVER", "ROLLED_BACK")
            raise
    return {"status": "VERIFIED", "main": commit,
            "scope_ref": scope.scope_ref, "prior_queue_preserved": True,
            "prior_modules_preserved": True, "operator_changed": False,
            "model_calls": 0, "native_dispatches": 0}

def main():
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        output = worker_release(event, os.environ,
                                os.environ.get("GITHUB_TOKEN", ""))
        print(json.dumps(output, sort_keys=True))
        return 0
    except Exception as exc:
        # Safe error taxonomy only, no paths, secret, Guard rows, or raw source.
        label = str(exc) if type(exc) is Denied else type(exc).__name__
        print(json.dumps({"status": "BLOCKED", "reason": label}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
