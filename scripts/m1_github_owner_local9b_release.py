"""Existing idle-worker release transaction; local Guard and legacy Issue adapters."""
from __future__ import annotations
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.guard import GuardCore
from ai_foundation.host_compute_lease import HostComputeLease
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.release_gate import GuardReleaseGate, ImmutableReleaseScope
from scripts.m1_operator_release_canon import observe_release_canon, observe_installed_canon
from scripts.m1_github_owner_operator_release import live_issue
from scripts.m1_local9b_admission_release import (
    WORKER_LABEL, read_owned, sha, launch, operator_guard_store,
    private_root, private_write, atomic_plist)

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
WORKFLOW = "Foundation M1 owner main local9B release"
TITLE = "Foundation M1 9B Release: "
SHA40 = re.compile(r"[0-9a-f]{40}\Z")

class Denied(RuntimeError):
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
            "EXACT_OWNER_EVENT_REQUIRED")
    issue = event.get("issue")
    require(type(issue) is dict and type(issue.get("number")) is int
            and 0 < issue["number"] < 2**31
            and issue.get("user", {}).get("login") == OWNER
            and issue.get("state") == "open", "OWNER_ISSUE_UNVERIFIED")
    commit = env.get("GITHUB_SHA")
    require(type(commit) is str and SHA40.fullmatch(commit) is not None
            and issue.get("title") == TITLE + commit
            and issue.get("body") == "<!-- foundation-m1-local9b-release:v1:" + commit + " -->",
            "OWNER_EXACT_MAIN_REQUIRED")
    if live is not None:
        require(type(live) is dict and
                all(live.get(k) == issue.get(k)
                    for k in ("number", "title", "body", "state"))
                and live.get("user", {}).get("login") == OWNER,
                "OWNER_ISSUE_CHANGED")
    return issue["number"], commit

class OwnerGate:
    def __init__(self, event, env, token, scope, run, ref):
        self.event, self.env, self.token = event, env, token
        self.identity = scope.scope_ref, run, ref
    def verify_exact_release(self, scope, run, ref):
        if self.identity != (scope.scope_ref, run, ref):
            return False
        try:
            number, _ = owner_event(self.event, self.env)
            owner_event(self.event, self.env, live_issue(number, self.token))
            return True
        except Denied:
            return False

def owner_file(path, *, limit=2097152):
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode)
            and info.st_uid == os.getuid()
            and not info.st_mode & 0o022
            and 0 <= info.st_size <= limit, "RELEASE_FILE_UNTRUSTED")
    return path.read_bytes()

def previous_worker(home):
    plist = home / "Library/LaunchAgents" / (WORKER_LABEL + ".plist")
    old = read_owned(plist, 32768)
    obj = plistlib.loads(old)
    args = obj.get("ProgramArguments")
    require(obj.get("Label") == WORKER_LABEL and type(args) is list
            and 2 <= len(args) <= 24, "WORKER_DEFINITION_UNVERIFIED")
    entries = [Path(p) for p in args if type(p) is str
               and p.startswith("/") and
               p.endswith("/local9b_autodev_worker.py")]
    require(len(entries) == 1, "WORKER_ENTRY_UNVERIFIED")
    entry = entries[0]
    old_entry = read_owned(entry, 2097152)
    release_root = entry.parents[2]
    if entry == release_root / "repo/scripts/local9b_autodev_worker.py":
        original_manifest = release_root / "manifest.json"
        if original_manifest.exists() or original_manifest.is_symlink():
            manifest = json.loads(read_owned(original_manifest, 262144))
            files = manifest.get("files")
        else:
            manifest = json.loads(read_owned(release_root / "release-manifest.json", 2000000))
            tracked = manifest.get("tracked")
            require(type(tracked) is dict and manifest.get("main") == release_root.name
                    and manifest.get("candidate_plist") == sha(old),
                    "PREVIOUS_9B_MANIFEST_MISMATCH")
            files = {"repo/" + k: v for k, v in tracked.items()}
    elif (entry == release_root / "candidate/scripts/local9b_autodev_worker.py"
          and release_root.parent == home / "Library/Application Support/AI-Foundation/operator-release-staging"
          and re.fullmatch(r"[a-f0-9]{64}", release_root.name)):
        from scripts.m1_operator_release_stage import verify_staged
        require(verify_staged(release_root, release_root.name) is True,
                "PREVIOUS_9B_MANIFEST_MISMATCH")
        manifest = json.loads(read_owned(release_root / "manifest.json", 2000000))
        entry_hash = manifest.get("tracked", {}).get("scripts/local9b_autodev_worker.py")
        files = {"repo/scripts/local9b_autodev_worker.py": entry_hash}
    else:
        raise Denied("IMMUTABLE_9B_LAYOUT_REQUIRED")
    require(type(files) is dict and
            files.get("repo/scripts/local9b_autodev_worker.py") == sha(old_entry),
            "PREVIOUS_9B_MANIFEST_MISMATCH")
    env = obj.get("EnvironmentVariables")
    require(type(env) is dict and
            type(env.get("AI_FOUNDATION_LOCAL9B_STATE_ROOT")) is str,
            "ORIGINAL_9B_STATE_ROOT_REQUIRED")
    state_path = Path(env["AI_FOUNDATION_LOCAL9B_STATE_ROOT"])
    require(state_path.is_absolute() and not state_path.is_symlink()
            and state_path.is_dir()
            and all((state_path / child).is_dir()
                    and not (state_path / child).is_symlink()
                    for child in ("inbox", "results")),
            "DURABLE_QUEUE_ROOT_UNVERIFIED")
    # The original interpreter, module directory and queue must remain intact.
    modules = {}
    for key, digest in files.items():
        if key.startswith("repo/scripts/modules/") and key.endswith(".py"):
            raw = owner_file(release_root / key)
            require(sha(raw) == digest, "PREVIOUS_MODULE_PIN_MISMATCH")
            modules[key] = raw
    # P4 manifests need not contain these two trusted external Harness helpers.
    # The incumbent worker already resolves them from this fixed owner-local
    # Harness path. Copy their exact verified bytes into the new private bundle
    # so the new worker does not depend on mutable external imports thereafter.
    harness = Path("/Volumes/StorageVolume/home-data/deepseek-harness-standalone"
                   "/handoff/harness9b-contract-20261106/experiments/harness9b")
    worker_main = owner_file(ROOT / "scripts/local9b_autodev_worker.py")
    require(b'HARNESS=Path("/Volumes/StorageVolume/home-data/deepseek-harness-standalone/handoff/harness9b-contract-20261106")' in worker_main,
            "MAIN_HARNESS_BINDING_CHANGED")
    for name in ("native_code_compare", "native_fake_e2e"):
        key = "repo/scripts/modules/" + name + ".py"
        if key not in modules:
            # Only existing owner-owned regular source; never download or
            # synthesize a module or accept a symlink.
            modules[key] = owner_file(harness / (name + ".py"))
    require(all("repo/scripts/modules/" + name + ".py" in modules
                for name in ("native_code_compare", "native_fake_e2e")),
            "PINNED_9B_NATIVE_MODULES_REQUIRED")
    status = launch("print", "gui/501/" + WORKER_LABEL)
    require(status.returncode == 0 and str(entry) in status.stdout
            and re.search(r"^\s*state = not running\s*$",
                          status.stdout, re.M) is not None,
            "WORKER_MUST_BE_IDLE")
    return plist, old, obj, entry, old_entry, state_path, modules

def stage(commit, prev, home):
    old_plist, old, row, entry, old_entry, state_root, modules = prev
    parent = private_root(home) / "main-worker"
    parent.mkdir(mode=0o700, exist_ok=True)
    info = parent.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
            and not info.st_mode & 0o077, "PRIVATE_STAGE_UNTRUSTED")
    final = parent / commit
    require(not final.exists() and not final.is_symlink(),
            "RELEASE_ALREADY_STAGED")
    tmp = Path(tempfile.mkdtemp(prefix=".main-", dir=parent))
    try:
        listing = subprocess.run(["/usr/bin/git", "-C", str(ROOT),
                                  "ls-tree", "-r", "-z", "--full-tree",
                                  commit, "--", "scripts", "src", "experiments"],
                                 capture_output=True, timeout=15, check=False)
        require(listing.returncode == 0
                and listing.stdout.endswith(b"\0"),
                "TRACKED_MAIN_FILES_UNAVAILABLE")
        paths = listing.stdout[:-1].split(b"\0")
        require(10 < len(paths) < 15000, "TRACKED_SOURCE_SET_UNVERIFIED")
        tracked = {}
        total = 0
        for value in paths:
            metadata, raw_path = value.split(b"\t", 1)
            mode, kind, digest = metadata.split(b" ")
            require(mode in (b"100644", b"100755") and kind == b"blob"
                    and re.fullmatch(b"[a-f0-9]{40}", digest) is not None,
                    "TRACKED_SOURCE_OBJECT_UNVERIFIED")
            rel = raw_path.decode("utf-8", "strict")
            target = Path(rel)
            require(not target.is_absolute() and ".." not in target.parts
                    and not rel.startswith(".git/"), "TRACKED_MAIN_PATH_INVALID")
            data = owner_file(ROOT / rel, limit=6_000_000)
            blob = b"blob " + str(len(data)).encode("ascii") + b"\0" + data
            require(sha1(blob).hexdigest().encode("ascii") == digest,
                    "TRACKED_COMMIT_BYTES_CHANGED")
            total += len(data)
            require(total < 300_000_000, "STAGED_SIZE_EXCEEDED")
            output = tmp / "repo" / rel
            output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            private_write(output, data)
            tracked[rel] = sha(data)
        for key, data in modules.items():
            rel = key.removeprefix("repo/")
            require(rel not in tracked, "MAIN_MODULE_CONFLICT")
            output = tmp / key
            output.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            private_write(output, data)
            tracked[rel] = sha(data)
        worker = tmp / "repo/scripts/local9b_autodev_worker.py"
        require(worker.is_file()
                and b"AI_FOUNDATION_LOCAL9B_STATE_ROOT" in worker.read_bytes()
                and b"STATE_ROOT" in worker.read_bytes(),
                "MAIN_QUEUE_ROOT_DECOUPLING_MISSING")
        private_write(tmp / "previous-worker.plist", old)
        private_write(tmp / "previous-worker.py", old_entry)
        updated = dict(row)
        args = list(row["ProgramArguments"])
        args[args.index(str(entry))] = str(final / "repo/scripts/local9b_autodev_worker.py")
        updated["ProgramArguments"] = args
        updated["WorkingDirectory"] = str(final / "repo")
        newenv = dict(row["EnvironmentVariables"])
        current_py = newenv.get("PYTHONPATH", "")
        newenv["PYTHONPATH"] = (str(final / "repo/src") +
                               (":" + current_py if current_py else ""))
        newenv["PYTHONDONTWRITEBYTECODE"] = "1"
        updated["EnvironmentVariables"] = newenv
        candidate = plistlib.dumps(updated)
        private_write(tmp / "candidate-worker.plist", candidate)
        private_write(tmp / "release-manifest.json", json.dumps({
            "schema": 1, "main": commit, "worker": tracked[
                "scripts/local9b_autodev_worker.py"],
            "prior_plist": sha(old), "prior_entry": sha(old_entry),
            "candidate_plist": sha(candidate),
            "state_root_sha": sha(str(state_root).encode()),
            "tracked": tracked}, sort_keys=True).encode())
        for rel, digest in tracked.items():
            require(sha(owner_file(tmp / "repo" / rel, limit=6_000_000)) == digest,
                    "STAGED_SOURCE_CHANGED")
        interpreter = args[0]
        require(type(interpreter) is str and Path(interpreter).is_absolute()
                and Path(interpreter).is_file(), "OWNER_PYTHON_UNVERIFIED")
        smoke = ("import runpy,sys;from pathlib import Path;"
                 "d=runpy.run_path(sys.argv[1],run_name='__owner_import_test__');"
                 "assert d['STATE_ROOT']==Path(sys.argv[2]).resolve();"
                 "import ai_foundation.development_host as h;"
                 "assert str(Path(h.__file__).resolve()).startswith(sys.argv[3]);"
                 "print('MAIN_9B_IMPORT_VERIFIED')")
        env = {**os.environ,
               "AI_FOUNDATION_LOCAL9B_STATE_ROOT": str(state_root),
               "PYTHONPATH": str(tmp / "repo/src") + ":" + str(tmp / "repo/scripts"),
               "PYTHONDONTWRITEBYTECODE": "1"}
        test = subprocess.run([interpreter, "-B", "-c", smoke,
            str(worker), str(state_root), str(tmp / "repo/src")],
            env=env, capture_output=True, text=True, timeout=30, check=False)
        require(test.returncode == 0
                and "MAIN_9B_IMPORT_VERIFIED" in test.stdout,
                "PINNED_9B_IMPORT_SMOKE_FAILED")
        os.replace(tmp, final)
        return final, candidate
    finally:
        if tmp.exists():
            shutil.rmtree(tmp)

def release(event, env, token):
    require(platform.system() == "Darwin" and platform.machine() == "arm64"
            and os.getuid() == 501 and os.geteuid() == 501, "M1_OWNER_REQUIRED")
    number, commit = owner_event(event, env)
    owner_event(event, env, live_issue(number, token))
    head = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=8, check=False)
    clean = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "status", "--porcelain",
                            "--untracked-files=no"],
                           capture_output=True, text=True, timeout=8, check=False)
    require(head.returncode == 0 and head.stdout.strip() == commit
            and clean.returncode == 0 and not clean.stdout.strip(),
            "CURRENT_MAIN_CHECKOUT_REQUIRED")
    canon = observe_release_canon(ROOT)
    require(canon.get("source_main") == commit, "CANON_SOURCE_MISMATCH")
    return release_transaction(
        commit, canon,
        observe=lambda: observe_release_canon(ROOT),
        legacy_owner=lambda scope, run, ref: OwnerGate(event, env, token, scope, run, ref))


def local_reconcile():
    """Fixed trusted M1 service entrypoint; never approve on behalf of the owner."""
    from scripts.m1_operator_release_cli import _owner_session
    from scripts.m1_development_ticket_factory import _owner_local_repo
    from scripts.m1_development_review_candidate import _installed_live_source_repo
    _owner_session()
    installed = _installed_live_source_repo(_owner_local_repo())
    require(ROOT == installed, "INSTALLED_LOCAL_RELEASE_SOURCE_REQUIRED")
    canon = observe_installed_canon(ROOT)
    require(canon.get("source_main") == ROOT.name, "INSTALLED_CANON_SOURCE_CHANGED")
    return release_transaction(ROOT.name, canon,
                               observe=lambda: observe_installed_canon(ROOT))


def release_transaction(commit, canon, *, observe, legacy_owner=None):
    """One existing transaction. Local calls consume ONLY an original Guard decision.

    The old Issue adapter is retained for historical workflows, not required
    by the installed maintenance path. No second approval or queue store.
    """
    require(type(commit) is str and SHA40.fullmatch(commit) is not None,
            "EXACT_SOURCE_REQUIRED")
    with HostComputeLease().hold(max_wait_s=0):
        home = Path.home()
        previous = previous_worker(home)
        plist, old, row, entry, old_entry, state, modules = previous
        # Include the exact external native helper bytes in the immutable
        # Guard scope; never allow an unbound source to join this release.
        modules_sha = sha(json.dumps(
            {key: sha(value) for key, value in modules.items()},
            sort_keys=True, separators=(",", ":")).encode())
        candidate_worker = owner_file(ROOT / "scripts/local9b_autodev_worker.py")
        # A registered exact bundle is not a request for another cutover.
        if (entry == private_root(home) / "main-worker" / commit /
                "repo/scripts/local9b_autodev_worker.py" and old_entry == candidate_worker):
            return {"status": "WORKER_REGISTERED", "candidate_main": commit,
                    "worker_updated": False, "queue_preserved": True,
                    "model_dispatch_by_release": False}
        scope = ImmutableReleaseScope(
            path="m1-local9b-main",
            source_sha=sha((commit + ":" + sha(old) + ":" + sha(old_entry)
                             + ":" + sha(candidate_worker)
                             + ":" + modules_sha).encode()),
            previous_authority="installed-worker:" + sha(old_entry),
            previous_endpoint="launchd:" + WORKER_LABEL,
            candidate_authority="github-commit:" + commit,
            candidate_endpoint="owner-private-worker-overlay:" + commit,
            rollback_procedure="RESTORE_EXACT_WORKER_PLIST_AND_QUEUE_UNCHANGED",
            switch_target="IDLE_WORKER_ONLY",
            readback_target="PINNED_WORKER_PLIST_AND_PRESERVED_9B_QUEUE",
            rollback_readback_target="EXACT_PREVIOUS_WORKER_PLIST_AND_SOURCE")
        _, store = operator_guard_store(home)
        registry = private_root(home) / (
            "main-worker-guard-" + scope.scope_ref[:20] + ".json")
        exists = registry.exists() or registry.is_symlink()
        if exists:
            require(legacy_owner is None and not registry.is_symlink(),
                    "RELEASE_ALREADY_CONSUMED")
            read_owned(registry, 500000)
        gate = GuardReleaseGate(store, registry)
        if not exists:
            pending = gate.prepare(scope, canon_revision=canon["canon_revision"])
            require(pending.get("ok") is True and
                    pending.get("status") == "WAITING_HUMAN",
                    "GUARD_REQUEST_PREPARE_DENIED")
            if legacy_owner is None:
                return {"status": "WAITING_HUMAN", "scope_ref": scope.scope_ref,
                        "candidate_main": commit, "worker_updated": False,
                        "decision_surface": "OPERATOR_NOTIFICATIONS",
                        "model_dispatch_by_release": False}
        else:
            record = gate.registry.get(scope.path)
            require(record is not None and record.status == "PREPARED"
                    and record.release_scope == scope.as_dict()
                    and record.release_scope_ref == scope.scope_ref
                    and record.release_canon_revision == canon["canon_revision"],
                    "EXACT_PREPARED_WORKER_SCOPE_REQUIRED")
            pending = {"run_id": record.release_run_id,
                       "request_ref": record.release_request_ref}
        run_id, request_ref = pending["run_id"], pending["request_ref"]
        if store.is_cancelled(run_id):
            return {"status": "DENIED", "scope_ref": scope.scope_ref,
                    "worker_updated": False, "model_dispatch_by_release": False}
        owner = None
        if legacy_owner is not None:
            owner = legacy_owner(scope, run_id, request_ref)
            require(owner.verify_exact_release(scope, run_id, request_ref),
                    "OWNER_ISSUE_CHANGED")
            approved = OperatorActions(
                GuardCore(store.runtime_state(), store=store)).approve_pending(
                    run_id, request_ref)
            require(approved.ok, "GUARD_RELEASE_APPROVAL_DENIED")
        if gate.verify(scope, run_id, request_ref).get("approved") is not True:
            require(legacy_owner is None, "GUARD_RELEASE_APPROVAL_DENIED")
            return {"status": "WAITING_HUMAN", "scope_ref": scope.scope_ref,
                    "candidate_main": commit, "worker_updated": False,
                    "decision_surface": "OPERATOR_NOTIFICATIONS",
                    "model_dispatch_by_release": False}
        final, candidate = stage(commit, previous, home)
        current = observe()
        require((owner is None or owner.verify_exact_release(scope, run_id, request_ref))
                and not store.is_cancelled(run_id)
                and gate.verify(scope, run_id, request_ref).get("approved") is True
                and current.get("source_main") == commit
                and current.get("canon_revision") == canon["canon_revision"]
                and previous_worker(home) == previous,
                "RELEASE_CHANGED_BEFORE_SWITCH")
        gate.registry.transition(scope.path, "PREPARED", "CUTOVER")
        switched = False
        try:
            require(launch("bootout", "gui/501/" + WORKER_LABEL).returncode == 0,
                    "WORKER_BOOTOUT_FAILED")
            switched = True
            atomic_plist(plist, candidate)
            require(launch("bootstrap", "gui/501", str(plist)).returncode == 0,
                    "WORKER_BOOTSTRAP_FAILED")
            status = launch("print", "gui/501/" + WORKER_LABEL)
            require(status.returncode == 0
                    and str(final / "repo/scripts/local9b_autodev_worker.py")
                    in status.stdout
                    and sha(read_owned(plist, 32768)) == sha(candidate)
                    and sha(read_owned(final / "repo/scripts/local9b_autodev_worker.py"))
                    == sha(candidate_worker)
                    and state.is_dir()
                    and (state / "inbox").is_dir()
                    and (state / "results").is_dir(),
                    "LOCAL9B_MAIN_READBACK_FAILED")
            gate.registry.transition(scope.path, "CUTOVER", "VERIFIED")
        except BaseException:
            if switched:
                # Never terminate a newly started model/worker to manufacture
                # rollback success. An ambiguous active cutover stays CUTOVER.
                observed = launch("print", "gui/501/" + WORKER_LABEL)
                if (observed.returncode == 0 and re.search(
                        r"^\s*state = not running\s*$", observed.stdout, re.M) is None):
                    raise Denied("ACTIVE_WORKER_CUTOVER_RECONCILE_REQUIRED")
                if observed.returncode == 0:
                    require(launch("bootout", "gui/501/" + WORKER_LABEL).returncode == 0,
                            "WORKER_ROLLBACK_RECONCILE_REQUIRED")
                atomic_plist(plist, old)
                restored = launch("bootstrap", "gui/501", str(plist))
                check = launch("print", "gui/501/" + WORKER_LABEL)
                require(restored.returncode == 0
                        and sha(read_owned(plist, 32768)) == sha(old)
                        and str(entry) in check.stdout,
                        "WORKER_ROLLBACK_REQUIRES_OWNER")
            gate.registry.transition(scope.path, "CUTOVER", "ROLLED_BACK")
            raise
        return {"status": "VERIFIED", "candidate_main": commit,
                "scope_ref": scope.scope_ref, "worker_updated": True,
                "queue_preserved": True, "operator_updated": False,
                "model_dispatch_by_release": False}

def main():
    try:
        if sys.argv[1:] == ["--local-reconcile"]:
            result = local_reconcile()
        else:
            require(not sys.argv[1:], "UNKNOWN_RELEASE_OPERATION")
            event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
            result = release(event, os.environ, os.environ.get("GITHUB_TOKEN", ""))
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        code = str(exc) if type(exc) is Denied else type(exc).__name__
        print(json.dumps({"status": "BLOCKED", "reason": code}, sort_keys=True))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
