"""Exact owner-only, Guard-controlled P4 9B worker contention hotfix.

Preserves the deployed P4 code, all existing worker data/queues, the Operator,
and the shared Ollama. The sole changed runtime source is the reviewed worker
script at the pinned Git blob. An unknown layout or busy worker always aborts.
"""
from __future__ import annotations

from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import plistlib
import pwd
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.core import CanonContract, TaskPlan
from ai_foundation.guard import GuardCore
from ai_foundation.host_compute_lease import HostComputeLease
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.release_gate import GuardReleaseGate, ImmutableReleaseScope
from ai_foundation.store import SQLiteGuardStore

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
PR = 561
BRANCH = "fix/local9b-admission-false-contention-20261110"
WORKFLOW = "Foundation M1 local9B false contention release"
LABEL = "foundation-local9b-admission-once"
CANDIDATE = "3f63fb5bb7f3b986f61820341151150695c28eff"
P4_SHA = "09fdde256e372abcdb10d4378251eeb102abe9de"
OLD_WORKER = "5fe12016735aad3bd5ecf99a7670cfd93971ddfa4865ebb5a6a848979babcc1e"
OLD_WORKER_PLIST = "349d36fe65aa3cf52f11c7f44ef84aba83c5bb472710208aa298a6cf12aab500"
WORKER_LABEL = "dev.quest7070.ai-foundation.local9b-autodev"
OP_LABEL = "dev.quest7070.ai-foundation.operator"
CANON = ("docs/BOUNDARIES.md", "docs/HUMAN_ESCALATION_POLICY_2026-10-06.md")


class Denied(ValueError):
    pass


def require(cond, code):
    if not cond:
        raise Denied(code)


def sha(raw):
    return sha256(raw).hexdigest()


def read_owned(path, max_bytes=1048576):
    item = Path(path)
    meta = item.lstat()
    require(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid()
            and not meta.st_mode & 0o022 and 0 < meta.st_size <= max_bytes,
            "RELEASE_SOURCE_UNTRUSTED")
    return item.read_bytes()


def github(method, path, token, body=None):
    root = "/repos/" + REPO
    gets = {root + "/pulls/561", root + "/issues/561/labels"}
    gets.update(root + "/contents/" + k + "?ref=main" for k in CANON)
    allowed = ((method == "GET" and path in gets and body is None)
               or (method == "POST" and path == root + "/issues/561/comments"
                   and type(body) is dict and set(body) == {"body"}
                   and type(body["body"]) is str and len(body["body"]) <= 12000))
    require(allowed and bool(token), "RELEASE_GITHUB_SCOPE_INVALID")
    raw = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request("https://api.github.com" + path,
        data=raw, method=method, headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "foundation-m1-9b-exact-owner-release",
            **({"Content-Type": "application/json"} if raw is not None else {}),
        })
    try:
        with urllib.request.urlopen(req, timeout=12) as answer:
            response = answer.read(131073)
        require(len(response) <= 131072, "GITHUB_RESPONSE_TOO_LARGE")
        return json.loads(response)
    except (OSError, TimeoutError, UnicodeError, ValueError):
        raise Denied("GITHUB_OWNER_READBACK_UNAVAILABLE") from None


def owner_event(event, env, token):
    require(env.get("GITHUB_REPOSITORY") == REPO
            and env.get("GITHUB_WORKFLOW") == WORKFLOW
            and env.get("GITHUB_EVENT_NAME") == "pull_request"
            and env.get("GITHUB_ACTOR") == OWNER
            and event.get("action") == "labeled"
            and event.get("sender", {}).get("login") == OWNER
            and event.get("label", {}).get("name") == LABEL
            and event.get("repository", {}).get("full_name") == REPO,
            "EXACT_OWNER_LABEL_REQUIRED")
    pr = event.get("pull_request", {})
    require(pr.get("number") == PR and pr.get("state") == "open"
            and pr.get("user", {}).get("login") == OWNER
            and pr.get("head", {}).get("ref") == BRANCH
            and pr.get("head", {}).get("repo", {}).get("full_name") == REPO,
            "EXACT_OWNER_PR_REQUIRED")
    live = github("GET", "/repos/" + REPO + "/pulls/561", token)
    labels = github("GET", "/repos/" + REPO + "/issues/561/labels", token)
    require(live.get("state") == "open"
            and live.get("head", {}).get("sha") == pr.get("head", {}).get("sha")
            and live.get("head", {}).get("ref") == BRANCH
            and type(labels) is list and any(k.get("name") == LABEL for k in labels),
            "RELEASE_OWNER_EVENT_SUPERSEDED")
    rev = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
                         capture_output=True, text=True, timeout=8, check=False)
    require(rev.returncode == 0 and rev.stdout.strip() == env.get("RELEASE_HANDLER_SHA"),
            "IMMUTABLE_HANDLER_REQUIRED")
    candidate = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "hash-object",
                                "scripts/m1_local9b_admission_candidate.py"],
                               capture_output=True, text=True, timeout=8, check=False)
    require(candidate.returncode == 0 and candidate.stdout.strip() == CANDIDATE,
            "REVIEWED_WORKER_SOURCE_DRIFT")
    return pr["head"]["sha"]


def canon_revision(token):
    pins = {}
    for name in CANON:
        raw = (ROOT / name).read_bytes()
        object_id = sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        remote = github("GET", "/repos/" + REPO + "/contents/" + name + "?ref=main", token)
        require(remote.get("sha") == object_id, "CURRENT_CANON_CHANGED")
        pins[name] = object_id
    return "github-canon:" + sha(json.dumps(pins, sort_keys=True).encode())


def launch(*args):
    return subprocess.run(["/bin/launchctl", *args], capture_output=True,
                          text=True, timeout=18, check=False)


def installed(home):
    """Read only; current source/launch/queue roots are authoritative."""
    worker_plist = home / "Library/LaunchAgents" / (WORKER_LABEL + ".plist")
    original = read_owned(worker_plist, 32768)
    require(sha(original) == OLD_WORKER_PLIST, "WORKER_DEFINITION_CHANGED")
    row = plistlib.loads(original)
    args = row.get("ProgramArguments")
    require(row.get("Label") == WORKER_LABEL and type(args) is list
            and 2 <= len(args) <= 24, "WORKER_LAUNCH_UNVERIFIED")
    scripts = [x for x in args if type(x) is str and x.startswith("/")
               and x.endswith("/local9b_autodev_worker.py")]
    require(len(scripts) == 1, "WORKER_ENTRY_UNVERIFIED")
    entry = Path(scripts[0])
    require(sha(read_owned(entry, 2097152)) == OLD_WORKER, "WORKER_INSTALLED_SOURCE_DRIFT")
    release = entry.parents[2]
    require(release.name == P4_SHA and entry == release / "repo/scripts/local9b_autodev_worker.py",
            "P4_WORKER_BUNDLE_REQUIRED")
    manifest_raw = read_owned(release / "manifest.json", 262144)
    manifest = json.loads(manifest_raw)
    require(manifest.get("candidate_sha") == P4_SHA
            and type(manifest.get("files")) is dict
            and manifest["files"].get("repo/scripts/local9b_autodev_worker.py") == OLD_WORKER,
            "P4_SOURCE_MANIFEST_UNVERIFIED")
    env = row.get("EnvironmentVariables", {})
    state_root = env.get("AI_FOUNDATION_LOCAL9B_STATE_ROOT") if type(env) is dict else None
    require(type(state_root) is str and Path(state_root).is_absolute()
            and Path(state_root).is_dir() and
            all((Path(state_root) / part).is_dir() for part in ("inbox", "results")),
            "PRIOR_QUEUE_ROOT_UNVERIFIED")
    for rel, expected in manifest["files"].items():
        if not rel.startswith("repo/"):
            continue
        target = Path(rel)
        require(not target.is_absolute() and ".." not in target.parts and
                target.suffix == ".py", "P4_MANIFEST_PATH_UNTRUSTED")
        require(sha(read_owned(release / rel, 2097152)) == expected,
                "P4_SOURCE_BUNDLE_DRIFT")
    state = launch("print", "gui/501/" + WORKER_LABEL)
    require(state.returncode == 0 and str(entry) in state.stdout
            and re.search(r"^\s*state = not running\s*$", state.stdout, re.M) is not None,
            "WORKER_NOT_IDLE")
    return worker_plist, original, row, entry, release, manifest, state_root


def operator_guard_store(home):
    op_plist = home / "Library/LaunchAgents" / (OP_LABEL + ".plist")
    row = plistlib.loads(read_owned(op_plist, 32768))
    args = row.get("ProgramArguments")
    require(row.get("Label") == OP_LABEL and type(args) is list
            and args.count("--config") == 1, "OPERATOR_GUARD_BINDING_UNAVAILABLE")
    name = Path(args[args.index("--config") + 1])
    work = Path(row.get("WorkingDirectory", "/"))
    config = name if name.is_absolute() else work / name
    values = json.loads(read_owned(config, 65536))
    data = Path(values["data_dir"]).expanduser()
    if not data.is_absolute():
        data = work / data
    db_name = Path(values.get("guard_db", "guard.db"))
    require(not db_name.is_absolute() and ".." not in db_name.parts,
            "CANON_GUARD_DB_UNTRUSTED")
    target = data / db_name
    s = target.lstat()
    require(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid()
            and not s.st_mode & 0o022, "CANON_GUARD_DB_UNTRUSTED")
    return data, SQLiteGuardStore(target)


def private_root(home):
    path = home
    for name in ("Library", "Application Support", "AI-Foundation",
                 "local9b-admission-releases"):
        mode = path.lstat()
        require(stat.S_ISDIR(mode.st_mode) and mode.st_uid == os.getuid()
                and not mode.st_mode & 0o022, "PRIVATE_RELEASE_ROOT_UNTRUSTED")
        path = path / name
        if not path.exists() and not path.is_symlink():
            path.mkdir(mode=0o700)
    mode = path.lstat()
    require(stat.S_ISDIR(mode.st_mode) and mode.st_uid == os.getuid()
            and not mode.st_mode & 0o077, "PRIVATE_RELEASE_ROOT_UNTRUSTED")
    return path


def private_write(file, raw):
    fd = os.open(file, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as writer:
        writer.write(raw)
        writer.flush()
        os.fsync(writer.fileno())



OLD_GATE = "        names=subprocess.check_output([\"ps\",\"-axo\",\"comm=\"],text=True).splitlines()\n        if any(Path(n.strip()).name in (\"Runner.Worker\",\"llama-server\",\"llama-cli\",\"activation\") for n in names):raise HostComputeBusy(\"COMPETING_WORK\")\n        if api(11434,\"ps\")[\"models\"] != []:raise HostComputeBusy(\"SHARED_MODEL_BUSY\")\n        ensure_backend_port_available()"
NEW_GATE = "        # Process presence is not compute ownership. Keep the shared lease and\n        # reject actual shared-model residency before starting a second backend.\n        from ai_foundation.klm_compute_admission import AVAILABLE, RESOURCE_UNKNOWN, admit_local_9b\n        try:\n            shared=api(11434,\"ps\")\n        except (OSError, ValueError, KeyError, TimeoutError):\n            raise HostComputeBusy(\"SHARED_MODEL_STATE_UNKNOWN\") from None\n        if type(shared) is not dict or type(shared.get(\"models\")) is not list:\n            raise HostComputeBusy(\"SHARED_MODEL_STATE_UNKNOWN\")\n        if shared[\"models\"]:\n            raise HostComputeBusy(\"SHARED_MODEL_RESIDENT\")\n        try:\n            allowed,reason=admit_local_9b()\n        except Exception:\n            raise HostComputeBusy(RESOURCE_UNKNOWN) from None\n        if allowed is not True or reason != AVAILABLE:\n            raise HostComputeBusy(reason if type(reason) is str and reason in\n                                  (\"CPU_PRESSURE\",\"MEMORY_PRESSURE\",RESOURCE_UNKNOWN)\n                                  else RESOURCE_UNKNOWN)\n        ensure_backend_port_available()"


def require_exact_worker_delta(prior, candidate):
    """Reject every unreviewed source alteration beyond the fixed process veto."""
    old = OLD_GATE.encode()
    new = NEW_GATE.encode()
    require(type(prior) is bytes and type(candidate) is bytes
            and prior.count(old) == 1, "PRIOR_WORKER_GATE_CHANGED")
    require(candidate == prior.replace(old, new),
            "CANDIDATE_EXCEEDS_REVIEWED_WORKER_SCOPE")


def stage(home, previous):
    """Copy only P4-manifest-pinned source; replace precisely the worker file."""
    worker_plist, old_plist, row, entry, prior_release, manifest, state_root = previous
    root = private_root(home)
    final = root / CANDIDATE
    require(not final.exists() and not final.is_symlink(),
            "RELEASE_ALREADY_STAGED")
    temp = Path(tempfile.mkdtemp(prefix=".local9b-", dir=root))
    try:
        old_files = manifest["files"]
        files = {}
        require(1 <= len(old_files) <= 1024, "P4_SOURCE_SET_UNBOUNDED")
        for name, expected in old_files.items():
            if not name.startswith("repo/"):
                continue
            relative = Path(name)
            require(relative.suffix == ".py" and not relative.is_absolute()
                    and ".." not in relative.parts, "SOURCE_PATH_UNTRUSTED")
            raw = read_owned(prior_release / relative, 2097152)
            require(sha(raw) == expected, "P4_SOURCE_DRIFT")
            dest = temp / relative
            dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            private_write(dest, raw)
            files[name] = sha(raw)
        require(30 <= len(files) <= 512, "INCOMPLETE_P4_SOURCE_SET")
        target_name = "repo/scripts/local9b_autodev_worker.py"
        candidate = read_owned(ROOT / "scripts/m1_local9b_admission_candidate.py", 2097152)
        require_exact_worker_delta(read_owned(entry, 2097152), candidate)
        check = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "hash-object",
                                "scripts/m1_local9b_admission_candidate.py"],
                               capture_output=True, text=True, timeout=8, check=False)
        require(check.returncode == 0 and check.stdout.strip() == CANDIDATE,
                "CANDIDATE_SOURCE_NOT_REVIEWED")
        # Source change must be confined to the one reviewed entry.
        dest = temp / target_name
        dest.unlink()
        private_write(dest, candidate)
        files[target_name] = sha(candidate)
        private_write(temp / "prior.plist", old_plist)
        private_write(temp / "prior.entry", read_owned(entry, 2097152))
        new_row = dict(row)
        new_args = list(row["ProgramArguments"])
        new_args[new_args.index(str(entry))] = str(final / target_name)
        new_row["ProgramArguments"] = new_args
        require(new_row.get("EnvironmentVariables") == row.get("EnvironmentVariables"),
                "QUEUE_ROOT_CONFIG_CHANGED")
        proposal = plistlib.dumps(new_row)
        private_write(temp / "proposed.plist", proposal)
        content = json.dumps({
            "schema": 1, "candidate_blob": CANDIDATE, "prior_release": P4_SHA,
            "prior_entry_sha256": OLD_WORKER, "prior_plist_sha256": OLD_WORKER_PLIST,
            "preserved_queue_root": state_root, "files": files,
            "worker_only": True, "model_calls": 0,
        }, sort_keys=True).encode()
        private_write(temp / "manifest.json", content)
        for rel, expected in files.items():
            require(sha(read_owned(temp / rel, 2097152)) == expected,
                    "STAGED_SOURCE_READBACK_FAILED")
        # Existing Python interpreter and other services remain unchanged;
        # import only, never execute the __main__ polling/issue claim.
        interpreter = row["ProgramArguments"][0]
        require(Path(interpreter).is_absolute() and Path(interpreter).is_file(),
                "INSTALLED_INTERPRETER_UNAVAILABLE")
        test = ("import runpy,sys;from pathlib import Path;"
                "p=Path(sys.argv[1]);sys.path.insert(0,str(p.parent));"
                "d=runpy.run_path(str(p),run_name='__m1_import_check__');"
                "assert str(d['ROOT'])==sys.argv[2];"
                "from ai_foundation.klm_compute_admission import admit_local_9b;"
                "assert callable(admit_local_9b);"
                "print('P4_9B_ADMISSION_IMPORT_VERIFIED')")
        check_env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
                     "PYTHONDONTWRITEBYTECODE": "1",
                     "AI_FOUNDATION_LOCAL9B_STATE_ROOT": state_root,
                     "HOME": str(home)}
        cp = subprocess.run([interpreter, "-B", "-c", test,
                             str(temp / target_name), state_root],
                            capture_output=True, text=True, env=check_env,
                            check=False, timeout=25)
        require(cp.returncode == 0 and
                cp.stdout.strip().endswith("P4_9B_ADMISSION_IMPORT_VERIFIED"),
                "STAGED_WORKER_IMPORT_FAILED")
        require(installed(home)[:4] == previous[:4], "PRIOR_WORKER_CHANGED_DURING_STAGING")
        os.replace(temp, final)
    finally:
        if temp.exists():
            shutil.rmtree(temp)
    return final


def atomic_plist(target, raw):
    fd, name = tempfile.mkstemp(prefix=".local9b-plist-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(raw)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, target.stat().st_mode & 0o777)
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def scope():
    return ImmutableReleaseScope(
        path="p4-worker-false-contention-" + CANDIDATE,
        source_sha=sha((P4_SHA + ":" + CANDIDATE).encode()),
        previous_authority="p4-worker:" + OLD_WORKER + ":" + OLD_WORKER_PLIST,
        previous_endpoint="launchd:" + WORKER_LABEL,
        candidate_authority="owner-reviewed-worker-blob:" + CANDIDATE,
        candidate_endpoint="private-p4-worker-overlay:" + CANDIDATE,
        rollback_procedure="RESTORE_EXACT_WORKER_PLIST;PRESERVE_P4_SOURCE_AND_QUEUES",
        switch_target="IDLE_WORKER_ONLY_LAUNCHD_SWITCH",
        readback_target="REGISTERED_PINNED_WORKER_AND_ORIGINAL_QUEUE_ROOT",
        rollback_readback_target="EXACT_OLD_WORKER_PLIST_AND_REGISTERED_SOURCE",
    )


def readback(worker_plist, final, queue):
    proposed = read_owned(final / "proposed.plist", 32768)
    status = launch("print", "gui/501/" + WORKER_LABEL)
    manifest = json.loads(read_owned(final / "manifest.json", 262144))
    require(worker_plist.read_bytes() == proposed and status.returncode == 0
            and str(final / "repo/scripts/local9b_autodev_worker.py") in status.stdout
            and manifest.get("candidate_blob") == CANDIDATE
            and manifest.get("preserved_queue_root") == queue,
            "WORKER_CONFIG_READBACK_UNVERIFIED")
    return True


def change_worker(home, previous, final, authorized):
    worker_plist, old_plist, row, entry, _, _, queue = previous
    require(authorized() and installed(home)[:4] == previous[:4],
            "RELEASE_AUTHORITY_OR_INSTALLED_STATE_CHANGED")
    proposed = read_owned(final / "proposed.plist", 32768)
    stopped = False
    try:
        require(launch("bootout", "gui/501/" + WORKER_LABEL).returncode == 0,
                "IDLE_WORKER_BOOTOUT_FAILED")
        stopped = True
        require(authorized(), "RELEASE_GRANT_REVOKED")
        atomic_plist(worker_plist, proposed)
        require(launch("bootstrap", "gui/501", str(worker_plist)).returncode == 0,
                "NEW_WORKER_BOOTSTRAP_FAILED")
        readback(worker_plist, final, queue)
        return {"status": "APPLIED", "worker_plist_switched": True,
                "worker_queue_root_preserved": True,
                "worker_import_test_verified": True,
                "operator_service_mutations": 0, "model_calls": 0, "native_dispatches": 0,
                "rollback_backup_preserved": True}
    except BaseException:
        if stopped:
            launch("bootout", "gui/501/" + WORKER_LABEL)
            atomic_plist(worker_plist, old_plist)
            restored = launch("bootstrap", "gui/501", str(worker_plist))
            state = launch("print", "gui/501/" + WORKER_LABEL)
            require(restored.returncode == 0
                    and worker_plist.read_bytes() == old_plist
                    and str(entry) in state.stdout, "ROLLBACK_REQUIRES_OWNER_REVIEW")
            raise Denied("WORKER_CUTOVER_FAILED_PRIOR_RESTORED") from None
        raise


def deploy(event, env, token):
    import platform
    require(platform.system() == "Darwin" and platform.machine() == "arm64"
            and os.getuid() == 501, "M1_OWNER_REQUIRED")
    request_head = owner_event(event, env, token)
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    with HostComputeLease().hold(max_wait_s=0):
        previous = installed(home)
        data, store = operator_guard_store(home)
        registry = data / ("local9b-admission-release-" + CANDIDATE[:12] + ".json")
        gate = GuardReleaseGate(store, registry)
        bound = scope()
        run_id = "local9b-false-contention-" + CANDIDATE[:12]
        require(store.get_effect("release:" + bound.scope_ref) is None
                and gate.registry.get(bound.path) is None,
                "RELEASE_CONSUMED_OR_REQUIRES_RECONCILIATION")
        canon = canon_revision(token)
        pending = gate.prepare(bound, run_id=run_id, canon_revision=canon)
        require(pending.get("ok") is True, "RELEASE_GRANT_PREPARE_FAILED")
        guard = GuardCore(store.runtime_state(), store=store)
        approved = OperatorActions(guard).approve_pending(run_id, pending["request_ref"])
        require(approved.ok, "RELEASE_GUARD_APPROVAL_REFUSED")
        def authorized():
            owner_event(event, env, token)
            return (not store.is_cancelled(run_id) and canon_revision(token) == canon
                    and gate.verify(bound, run_id, pending["request_ref"]).get("approved") is True)
        observed = {}
        final = None
        class Port:
            def execute(self, plan):
                nonlocal final
                try:
                    require(authorized(), "RELEASE_GRANT_REVOKED")
                    final = stage(home, previous)
                    observed.update(change_worker(home, previous, final, authorized))
                except Exception as exc:
                    observed.update(status="DENIED", reason=str(exc) if isinstance(exc, Denied)
                                    else "UNEXPECTED_" + type(exc).__name__)
                    raise
            def observe(self, plan):
                if observed.get("status") == "APPLIED" and final is not None:
                    try:
                        readback(previous[0], final, previous[-1])
                        return "P4_WORKER_ADMISSION:" + CANDIDATE
                    except (OSError, ValueError, TypeError, KeyError):
                        pass
                return "UNVERIFIED"
        plan = TaskPlan(run_id, "production_deploy", "release-scope:" + bound.scope_ref,
                        text="P4 local9B false-contention-only release",
                        canon_revision=canon, effect_id="release:" + bound.scope_ref,
                        provenance="github-owner-label:561:" + request_head)
        result = guard.execute(plan, CanonContract("GitHub Canon", canon),
                               Port(), "P4_WORKER_ADMISSION:" + CANDIDATE)
        require(result == "VERIFIED_COMPLETE", "RELEASE_GUARD_EFFECT_UNVERIFIED")
        return {**observed, "candidate_blob": CANDIDATE,
                "guard_effect_verified": True, "scope_ref": bound.scope_ref}


def main():
    env = os.environ
    token = env.get("GITHUB_TOKEN", "")
    require(bool(token) and bool(env.get("GITHUB_EVENT_PATH")), "OWNER_RELEASE_CONTEXT_MISSING")
    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_bytes())
    owner_event(event, env, token)
    try:
        result = deploy(event, env, token)
    except Exception as exc:
        result = {"status": "DENIED", "reason": str(exc) if isinstance(exc, Denied)
                  else "UNEXPECTED_" + type(exc).__name__,
                  "candidate_blob": CANDIDATE, "model_calls": 0, "native_dispatches": 0}
    print(json.dumps(result, sort_keys=True))
    github("POST", "/repos/" + REPO + "/issues/561/comments", token,
           {"body": "Fixed P4 local9B admission-only release receipt\n\n" +
            "~~~json\n" + json.dumps(result, sort_keys=True) + "\n~~~"})
    if result.get("status") != "APPLIED":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
