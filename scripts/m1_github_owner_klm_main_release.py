"""One-shot owner-authored, Guard-bound KLM-only upgrade to exact main source.

Uses the existing immutable source stage, release gate, shared M1 lease,
KLM-specific idle checks and launchd rollback. No 9B inference/Drive writes.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.release_gate import GuardReleaseGate, ImmutableReleaseScope
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.host_compute_lease import HostComputeLease
from scripts.m1_operator_release_canon import observe_release_canon
from scripts.m1_operator_release_cli import _guard_path
from scripts.m1_operator_release_stage import stage_operator_only, verify_staged, _save
from scripts.m1_p4_release_inventory import operator_only_release_scope, _owned_regular_bytes
from scripts.m1_klm_fairness_release import (
    NEW as PREVIOUS_RELEASE, LABEL, ENTRY, NEW_HANDLER,
    owner_paths, check_release, compute_admission as legacy_compute_admission,
    label_idle, atomic_plist, launch,
)
from scripts.m1_github_owner_worker_release import github_issue
from scripts.m1_klm_previous_source import staged_previous_root

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 owner main KLM release"
PREFIX = "Foundation M1 KLM Main Release: "
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
MODULE = "src/ai_foundation/knowledge_lifecycle.py"
SOURCE_FILES = (ENTRY, MODULE, "src/ai_foundation/klm_drive_cycle.py",
                "src/ai_foundation/klm_drive_auth.py")


class Denied(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise Denied(code)


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
    commit = env.get("GITHUB_SHA")
    require(type(issue) is dict and type(issue.get("number")) is int
            and issue["number"] > 0 and issue.get("state") == "open"
            and issue.get("user", {}).get("login") == OWNER
            and type(commit) is str and SHA40.fullmatch(commit) is not None
            and issue.get("title") == PREFIX + commit
            and issue.get("body") ==
              "<!-- foundation-m1-klm-main-release:v1:" + commit + " -->",
            "EXACT_MAIN_KLM_ISSUE_REQUIRED")
    if live is not None:
        require(type(live) is dict
                and all(live.get(k) == issue.get(k)
                        for k in ("number", "title", "body", "state"))
                and live.get("user", {}).get("login") == OWNER,
                "LIVE_OWNER_ISSUE_CHANGED")
    return issue["number"], commit


def proposed_plist(old_plist, old_root, candidate_root):
    row = plistlib.loads(old_plist)
    old_entry = str(old_root / ENTRY)
    new_entry = str(candidate_root / ENTRY)
    args = row.get("ProgramArguments")
    environ = row.get("EnvironmentVariables")
    require(row.get("Label") == LABEL and row.get("StartInterval") == 900
            and type(args) is list and type(environ) is dict
            and args.count(old_entry) == 1,
            "KLM_PREVIOUS_LAUNCHAGENT_MISMATCH")
    path = environ.get("PYTHONPATH")
    require(type(path) is str and path.count(str(old_root)) == 1,
            "KLM_PREVIOUS_PYTHONPATH_MISMATCH")
    updated = dict(row)
    updated["ProgramArguments"] = [
        new_entry if x == old_entry else x for x in args
    ]
    updated["EnvironmentVariables"] = {
        **environ, "PYTHONPATH": path.replace(str(old_root), str(candidate_root))
    }
    return plistlib.dumps(updated)


def compute_admission(foundation, releases):
    # This host already imports its lease from the exact reviewed main tree.
    # Do not insert a stale legacy release into this process's import path.
    return legacy_compute_admission(foundation, releases, lease_factory=HostComputeLease)


def source_files(root):
    return {relative: _owned_regular_bytes(root / relative, max_bytes=2097152)
            for relative in SOURCE_FILES}


def source_digest(files):
    return sha256(json.dumps({name: sha256(raw).hexdigest() for name, raw in files.items()},
                             sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def previous_stage_approved(home, commit, module_hash):
    """Verify an existing VERIFIED KLM scope; never create an approval."""
    guard_db, _ = _guard_path(home)
    records = sorted(guard_db.parent.glob("owner-klm-main-*.json"))
    require(len(records) <= 100, "KLM_PREVIOUS_SCOPE_WINDOW_EXCEEDED")
    for path in records:
        data = json.loads(_owned_regular_bytes(path, max_bytes=131072))
        record = data.get("paths", {}).get("m1-klm-main-module", {})
        if (record.get("status") != "VERIFIED"
                or record.get("candidate_authority") != "github-commit:" + commit
                or record.get("candidate_endpoint") != "staged-klm:" + module_hash):
            continue
        scope = ImmutableReleaseScope(**record["release_scope"])
        if (scope.path != "m1-klm-main-module"
                or scope.candidate_authority != "github-commit:" + commit
                or scope.candidate_endpoint != "staged-klm:" + module_hash
                or record.get("release_scope_ref") != scope.scope_ref
                or path.name != "owner-klm-main-" + scope.scope_ref[:20] + ".json"):
            continue
        proof = GuardReleaseGate(SQLiteGuardStore(guard_db), path).verify(
            scope, record.get("release_run_id"), record.get("release_request_ref"))
        if proof.get("approved") is True:
            return True
    return False


def previous_root(old_plist, home, releases):
    legacy = releases / PREVIOUS_RELEASE
    args = plistlib.loads(old_plist).get("ProgramArguments", [])
    if type(args) is list and args.count(str(legacy / ENTRY)) == 1:
        check_release(legacy, PREVIOUS_RELEASE, NEW_HANDLER)
        proposed_plist(old_plist, legacy, legacy)  # validate existing service contract
        return legacy
    return staged_previous_root(
        old_plist, home, read_bytes=_owned_regular_bytes,
        verify_stage=verify_staged,
        guard_accepts=lambda commit, digest: previous_stage_approved(home, commit, digest))


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
                        github_issue(number, self.token))
            return True
        except (Denied, OSError, ValueError):
            return False


def release(event, env, token):
    require(platform.system() == "Darwin" and platform.machine() == "arm64"
            and os.getuid() == 501 and os.geteuid() == 501,
            "OWNER_M1_SESSION_REQUIRED")
    number, commit = owner_event(event, env)
    owner_event(event, env, github_issue(number, token))
    checkout = subprocess.run(
        ["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=8, check=False)
    require(checkout.returncode == 0 and checkout.stdout.strip() == commit,
            "EXACT_MAIN_CHECKOUT_REQUIRED")
    current = observe_release_canon(ROOT)
    require(current["source_main"] == commit, "CANON_MAIN_DRIFT")
    foundation, plist, releases = owner_paths()
    old_plist = _owned_regular_bytes(plist, max_bytes=32768)
    old_root = previous_root(old_plist, Path.home(), releases)
    old_sources = source_files(old_root)
    require(label_idle(), "KLM_TICK_ACTIVE")

    home = Path.home()
    op_scope, observed = operator_only_release_scope(home=home, root=ROOT)
    require(op_scope is not None and observed.get("status") == "OBSERVED"
            and observed.get("candidate_sha") == commit,
            "MAIN_SOURCE_STAGE_SCOPE_UNVERIFIED")
    stage_root = (home / "Library/Application Support/AI-Foundation"
                  / "operator-release-staging" / op_scope.scope_ref)
    if stage_root.exists():
        require(verify_staged(stage_root, op_scope.scope_ref),
                "STAGED_MAIN_SOURCE_UNVERIFIED")
    else:
        staged = stage_operator_only(ROOT, home)
        require(staged.get("backup_verified") is True
                and staged["scope_ref"] == op_scope.scope_ref,
                "STAGED_MAIN_SOURCE_UNVERIFIED")
    candidate = stage_root / "candidate"
    new_sources = source_files(candidate)
    new_module = new_sources[MODULE]
    entry = new_sources[ENTRY]
    compile(new_module, str(candidate / MODULE), "exec")
    compile(entry, str(candidate / ENTRY), "exec")
    require(old_sources != new_sources, "NO_KLM_SOURCE_DELTA")
    proposed = proposed_plist(old_plist, old_root, candidate)
    _save(stage_root / "previous-klm-launchagent.plist", old_plist)
    _save(stage_root / "candidate-klm-launchagent.plist", proposed)

    source_hash = sha256((commit + sha256(old_plist).hexdigest()
                          + source_digest(old_sources)
                          + source_digest(new_sources)).encode()).hexdigest()
    scope = ImmutableReleaseScope(
        path="m1-klm-main-module",
        source_sha=source_hash,
        previous_authority="owner-klm:" + source_digest(old_sources),
        previous_endpoint="launchd:" + LABEL,
        candidate_authority="github-commit:" + commit,
        candidate_endpoint="staged-klm:" + sha256(new_module).hexdigest(),
        rollback_procedure="RESTORE_EXACT_KLM_PLIST_AND_KEEP_DURABLE_WORK",
        switch_target="IDLE_KLM_ONLY_LAUNCHD_SWITCH",
        readback_target="KLM_MAIN_SOURCE_AND_PLIST",
        rollback_readback_target="EXACT_PRIOR_KLM_GENERATION",
    )
    guard_db, _ = _guard_path(home)
    registry = guard_db.parent / ("owner-klm-main-" + scope.scope_ref[:20] + ".json")
    require(not registry.exists() and not registry.is_symlink(),
            "KLM_RELEASE_ALREADY_ATTEMPTED")
    store = SQLiteGuardStore(guard_db)
    gate = GuardReleaseGate(store, registry)
    prepared = gate.prepare(scope, canon_revision=current["canon_revision"])
    require(prepared.get("ok") is True
            and prepared.get("status") == "WAITING_HUMAN",
            "GUARD_PREPARE_DENIED")
    owner = OwnerIssueGate(event, env, token, scope,
                           prepared["run_id"], prepared["request_ref"])
    require(owner.verify_exact_release(
        scope, prepared["run_id"], prepared["request_ref"]),
        "OWNER_RELEASE_CONTEXT_CHANGED")
    approved = OperatorActions(
        GuardCore(store.runtime_state(), store=store)
    ).approve_pending(prepared["run_id"], prepared["request_ref"])
    require(approved.ok and approved.status == "APPROVED",
            "OWNER_GUARD_APPROVAL_DENIED")
    gate_readback = gate.verify(
        scope, prepared["run_id"], prepared["request_ref"])
    require(gate_readback.get("approved") is True,
            "GUARD_DURABLE_READBACK_DENIED")

    lease = compute_admission(foundation, releases)
    with lease.hold(max_wait_s=0):
        # Fixed existing KLM Work admission and final source/owner/idle check.
        compute_admission(foundation, releases)
        require(plist.read_bytes() == old_plist
                and previous_root(old_plist, home, releases) == old_root
                and source_files(old_root) == old_sources
                and label_idle()
                and owner.verify_exact_release(
                    scope, prepared["run_id"], prepared["request_ref"])
                and verify_staged(stage_root, op_scope.scope_ref),
                "KLM_CUTOVER_RACE_BLOCKED")
        gate.registry.transition(scope.path, "PREPARED", "CUTOVER")
        stopped = False
        try:
            require(launch("bootout", "gui/501/" + LABEL).returncode == 0,
                    "KLM_BOOTOUT_DENIED")
            stopped = True
            atomic_plist(plist, proposed)
            require(launch("bootstrap", "gui/501", str(plist)).returncode == 0,
                    "KLM_BOOTSTRAP_DENIED")
            observed = launch("print", "gui/501/" + LABEL)
            require(observed.returncode == 0
                    and str(candidate / ENTRY) in observed.stdout
                    and plist.read_bytes() == proposed
                    and verify_staged(stage_root, op_scope.scope_ref),
                    "KLM_MAIN_READBACK_FAILED")
            gate.registry.transition(scope.path, "CUTOVER", "VERIFIED")
        except BaseException:
            if stopped:
                launch("bootout", "gui/501/" + LABEL)
                atomic_plist(plist, old_plist)
                restored = launch("bootstrap", "gui/501", str(plist))
                require(restored.returncode == 0
                        and plist.read_bytes() == old_plist,
                        "KLM_ROLLBACK_NOT_VERIFIED")
            gate.registry.transition(scope.path, "CUTOVER", "ROLLED_BACK")
            raise
    return {
        "status": "VERIFIED", "main": commit, "service": "KLM_ONLY",
        "rollback_preserved": True, "other_services_changed": False,
        "model_calls": 0, "owner_source_writes": 0,
    }


def readback(event, env, token):
    require(platform.system() == "Darwin" and platform.machine() == "arm64"
            and os.getuid() == 501, "OWNER_M1_SESSION_REQUIRED")
    number, commit = owner_event(event, env)
    owner_event(event, env, github_issue(number, token))
    _, plist, releases = owner_paths()
    installed = plistlib.loads(_owned_regular_bytes(plist, max_bytes=32768))
    scripts = [Path(x) for x in installed.get("ProgramArguments", [])
               if type(x) is str and x.endswith("/" + ENTRY)]
    require(len(scripts) == 1, "KLM_CURRENT_ENTRY_UNVERIFIED")
    candidate = scripts[0].parents[1]
    stage_root = candidate.parent
    manifest = json.loads(_owned_regular_bytes(
        stage_root / "manifest.json", max_bytes=2097152))
    require(manifest.get("candidate_commit") == commit
            and verify_staged(stage_root, manifest["scope_ref"]),
            "KLM_CURRENT_CANDIDATE_UNVERIFIED")
    old = _owned_regular_bytes(
        stage_root / "previous-klm-launchagent.plist", max_bytes=32768)
    require(installed.get("Label") == LABEL
            and installed.get("StartInterval") == 900
            and plist.read_bytes() == proposed_plist(
                old, previous_root(old, Path.home(), releases), candidate),
            "KLM_LAUNCHAGENT_CHANGED")
    actual = _owned_regular_bytes(candidate / MODULE, max_bytes=2097152)
    require(actual == _owned_regular_bytes(ROOT / MODULE, max_bytes=2097152),
            "KLM_INSTALLED_SOURCE_DRIFT")
    require(source_files(candidate) == source_files(ROOT), "KLM_INSTALLED_SOURCE_DRIFT")
    observed = launch("print", "gui/501/" + LABEL)
    require(observed.returncode == 0
            and str(candidate / ENTRY) in observed.stdout,
            "KLM_LAUNCHD_READBACK_DENIED")
    return {
        "status": "APPLIED_VERIFIED", "main": commit,
        "module_sha256": sha256(actual).hexdigest(),
        "rollback_preserved": True, "interval_seconds": 900,
        "new_database": False, "model_calls": 0, "owner_source_writes": 0,
    }


def main():
    try:
        mode = sys.argv[1:]
        require(mode in (["--release"], ["--readback"]), "EXACT_ACTION_REQUIRED")
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        fn = release if mode == ["--release"] else readback
        result = fn(event, os.environ, os.environ.get("GITHUB_TOKEN", ""))
        print("KLM_MAIN_RELEASE_RECEIPT=" + json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = str(exc) if type(exc) is Denied else type(exc).__name__
        print("KLM_MAIN_RELEASE_RECEIPT=" + json.dumps(
            {"status": "BLOCKED", "reason": code}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

