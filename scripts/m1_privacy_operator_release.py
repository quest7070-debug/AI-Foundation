"""One-shot, owner-labeled Operator-only overlay. No 9B or main mutation.

Source byte pins and prior installed hashes come from independent M1 readback.
A source/label/Guard conflict always aborts. Only the Operator LaunchAgent may
be booted out, with a byte-identical plist rollback on failure.
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
import time
from urllib.request import Request, urlopen, ProxyHandler, build_opener

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
PR = 612
BRANCH = "feat/no-model-privacy-humanmodel-fastpath-20261110"
WORKFLOW = "Foundation M1 Operator privacy release"
LABEL = "foundation-operator-privacy-61612"
CANDIDATE = "61612fb4edcadf6fc508cfbdd36ad6d559e99d11"
OP_LABEL = "dev.quest7070.ai-foundation.operator"
WORKER_LABEL = "dev.quest7070.ai-foundation.local9b-autodev"
OLD_PLIST = "9bb6decbf24ef6710a318e2cb2a4f681d6fceff81ad8b8e228899aa49b58dc03"
OLD_ENTRY = "b313f97061000785c6b303e982ee821d01e97ee9b646142810c362ddf8488452"
WORKER_PLIST = "349d36fe65aa3cf52f11c7f44ef84aba83c5bb472710208aa298a6cf12aab500"
PINS = {
    "guard.py": ("9ce9300924ed53d013aa068cf4f20f70acdeb0d563ccd8549102dffbe907f880", "449cea3bd1acd11d1bdcf191ac7542e8b234d7314d110a02359c4f7ea3381f5a"),
    "human_model_context.py": ("4a5c85c1b042a92978a735b3149791d0e4ec1e46bc323ccc645bebc06bb024bc", "d6904a5e42771d179c040585d2eef8c103757d06e0b79bd6a2cd6ea7f4769468"),
    "inference_service.py": ("c53cc68bce3b5427cb29af75c70472739f4548e650b293e56105ebb285647ff2", "28c67c419fb3a07a37a00432503adbc3da9051a1dad5235c77fcb96c85bb4f47"),
    "routed_agent_model.py": ("a77a24712ecbac05ea514de15af6ceace913f6a834c2b947ffad159e22dd9bae", "d37ec38dd6309317411f4c8ad0c1b46a2ab7e06106c8d3b42c17e5893572667c"),
    "sensitive_input_scan.py": (None, "e898585fa1b38d4388090e92c6cba62879f5d4a8ca2d6fb32b4611743e01c9fd"),
}
CANON_FILES = ("docs/BOUNDARIES.md", "docs/HUMAN_ESCALATION_POLICY_2026-10-06.md")
HTTP = build_opener(ProxyHandler({}))


class Denied(ValueError): pass


def insist(ok, reason):
    if not ok: raise Denied(reason)


def digest(raw): return sha256(raw).hexdigest()


def owned_bytes(path, max_bytes=1048576):
    p = Path(path); s = p.lstat()
    insist(stat.S_ISREG(s.st_mode) and s.st_uid == os.getuid()
           and not s.st_mode & 0o022 and 0 < s.st_size <= max_bytes, "SOURCE_FILE_UNTRUSTED")
    return p.read_bytes()


def api(method, path, token, body=None):
    prefix = "/repos/" + REPO
    gets = {prefix + "/pulls/612", prefix + "/issues/612/labels"}
    gets.update(prefix + "/contents/" + n + "?ref=main" for n in CANON_FILES)
    insist((method == "GET" and path in gets and body is None)
           or (method == "POST" and path == prefix + "/issues/612/comments"
               and type(body) is dict and set(body) == {"body"}
               and len(body["body"]) <= 12000), "GITHUB_API_SCOPE_DENIED")
    raw = json.dumps(body).encode() if body is not None else None
    request = Request("https://api.github.com" + path, data=raw, method=method,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "foundation-privacy-exact-release",
                 **({"Content-Type": "application/json"} if raw is not None else {})})
    try:
        with urlopen(request, timeout=12) as response: data = response.read(131073)
        insist(len(data) <= 131072, "GITHUB_RESPONSE_OVERFLOW")
        return json.loads(data)
    except (OSError, TimeoutError, ValueError):
        raise Denied("GITHUB_API_UNAVAILABLE") from None


def owner_request(event, env, token):
    insist(env.get("GITHUB_REPOSITORY") == REPO and env.get("GITHUB_WORKFLOW") == WORKFLOW
           and env.get("GITHUB_EVENT_NAME") == "pull_request"
           and env.get("GITHUB_ACTOR") == OWNER and event.get("action") == "labeled"
           and event.get("sender", {}).get("login") == OWNER
           and event.get("label", {}).get("name") == LABEL
           and event.get("repository", {}).get("full_name") == REPO, "OWNER_REQUEST_REQUIRED")
    pr = event.get("pull_request", {})
    insist(pr.get("number") == PR and pr.get("state") == "open"
           and pr.get("user", {}).get("login") == OWNER
           and pr.get("head", {}).get("ref") == BRANCH
           and pr.get("head", {}).get("repo", {}).get("full_name") == REPO, "EXACT_PR_REQUIRED")
    live = api("GET", "/repos/" + REPO + "/pulls/612", token)
    labels = api("GET", "/repos/" + REPO + "/issues/612/labels", token)
    insist(live.get("state") == "open" and live.get("head", {}).get("sha") == pr["head"]["sha"]
           and live.get("head", {}).get("ref") == BRANCH
           and type(labels) is list and any(x.get("name") == LABEL for x in labels),
           "REQUEST_CHANGED")
    head = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "rev-parse", "HEAD"],
                          capture_output=True, text=True, timeout=8)
    insist(head.returncode == 0 and head.stdout.strip() == env.get("RELEASE_HANDLER_SHA"),
           "PINNED_RELEASE_HANDLER_REQUIRED")
    return pr["head"]["sha"]


def canon_revision(token):
    pins = {}
    for name in CANON_FILES:
        raw = (ROOT / name).read_bytes()
        current = sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        remote = api("GET", "/repos/" + REPO + "/contents/" + name + "?ref=main", token)
        insist(remote.get("sha") == current, "CANON_SOURCE_CHANGED")
        pins[name] = current
    return "github-canon:" + digest(json.dumps(pins, sort_keys=True).encode())


def prior(home):
    plist = home / "Library/LaunchAgents" / (OP_LABEL + ".plist")
    worker_plist = home / "Library/LaunchAgents" / (WORKER_LABEL + ".plist")
    raw = owned_bytes(plist, 32768)
    insist(digest(raw) == OLD_PLIST and digest(owned_bytes(worker_plist, 32768)) == WORKER_PLIST,
           "INSTALLED_SERVICE_CHANGED")
    row = plistlib.loads(raw)
    args = row.get("ProgramArguments")
    insist(row.get("Label") == OP_LABEL and type(args) is list
           and 2 <= len(args) <= 24, "INSTALLED_OPERATOR_CONTRACT_CHANGED")
    entries = [x for x in args if type(x) is str and x.startswith("/") and x.endswith(".py")]
    insist(len(entries) == 1 and Path(entries[0]).name == "operator_server.py"
           and digest(owned_bytes(entries[0])) == OLD_ENTRY, "INSTALLED_ENTRY_CHANGED")
    entry = Path(entries[0]); package = entry.parent.parent / "src/ai_foundation"
    env = row.get("EnvironmentVariables", {})
    insist(type(env) is dict and type(env.get("PYTHONPATH")) is str
           and str(package.parent) in env["PYTHONPATH"].split(os.pathsep), "OPERATOR_IMPORT_BOUNDARY_CHANGED")
    for name, (old, _) in PINS.items():
        current = package / name
        if old is None:
            insist(not current.exists() and not current.is_symlink(), "SCANNER_ALREADY_INSTALLED")
        else:
            insist(digest(owned_bytes(current)) == old, "INSTALLED_SOURCE_CHANGED")
    return plist, raw, row, entry, package


def idle():
    with HTTP.open("http://127.0.0.1:8766/api/human", timeout=5) as response:
        data = json.loads(response.read(2 * 1024 * 1024))
    return type(data) is dict and type(data.get("activity")) is list and not data["activity"]


def launch(*args):
    return subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True,
                          check=False, timeout=18)


def private_root(home):
    path = home
    for item in ("Library", "Application Support", "AI-Foundation", "privacy-operator-releases"):
        st = path.lstat()
        insist(stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid()
               and not st.st_mode & 0o022, "RELEASE_DIRECTORY_UNTRUSTED")
        path = path / item
        if not path.exists() and not path.is_symlink(): path.mkdir(mode=0o700)
    st = path.lstat()
    insist(stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid()
           and not st.st_mode & 0o077, "PRIVATE_RELEASE_DIRECTORY_REQUIRED")
    return path


def write_private(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as file:
        file.write(raw); file.flush(); os.fsync(file.fileno())


def stage(home, source, token):
    plist, original, row, entry, package = source
    root = private_root(home)
    final = root / CANDIDATE[:12]
    insist(not final.exists() and not final.is_symlink(), "RELEASE_ALREADY_STAGED")
    tmp = Path(tempfile.mkdtemp(prefix=".privacy-stage-", dir=root))
    try:
        dest = tmp / "src/ai_foundation"
        # Exclude source escapes and oversized packages before copying any data.
        all_sources = list(package.rglob("*"))
        insist(len(all_sources) <= 2048 and not any(p.is_symlink() for p in all_sources),
               "SOURCE_TREE_UNTRUSTED")
        insist(sum(p.stat().st_size for p in all_sources if p.is_file()) <= 16 * 1024 * 1024,
               "SOURCE_TREE_TOO_LARGE")
        shutil.copytree(package, dest, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
                        dirs_exist_ok=False)
        for name, (old, new) in PINS.items():
            raw = owned_bytes(ROOT / "src/ai_foundation" / name)
            insist(digest(raw) == new, "REVIEWED_CANDIDATE_CHANGED")
            target = dest / name
            if target.exists(): target.unlink()
            target.write_bytes(raw)
            os.chmod(target, 0o600)
        files = {}
        for item in dest.rglob("*"):
            if item.is_symlink(): raise Denied("STAGED_SYMLINK_REJECTED")
            if item.is_file():
                rel = item.relative_to(tmp).as_posix()
                files[rel] = digest(item.read_bytes())
        insist(1 <= len(files) <= 512, "RELEASE_PACKAGE_UNBOUNDED")
        launcher_raw = owned_bytes(ROOT / "scripts/m1_privacy_operator_launcher.py")
        write_private(tmp / "launcher.py", launcher_raw)
        manifest = {"schema": 1, "candidate_sha": CANDIDATE,
                    "prior_entry": str(entry), "prior_plist_sha256": OLD_PLIST,
                    "worker_plist_sha256": WORKER_PLIST,
                    "launcher_sha256": digest(launcher_raw), "files": files}
        write_private(tmp / "manifest.json", json.dumps(manifest, sort_keys=True).encode())
        write_private(tmp / "prior.plist", original)
        proposed = dict(row)
        args = list(proposed["ProgramArguments"])
        idx = args.index(str(entry))
        # Keep the original interpreter and all original --config/--port arguments.
        args[idx] = str(final / "launcher.py")
        proposed["ProgramArguments"] = args
        vars = dict(row["EnvironmentVariables"])
        roots = vars["PYTHONPATH"].split(os.pathsep)
        roots[roots.index(str(package.parent))] = str(final / "src")
        vars["PYTHONPATH"] = os.pathsep.join(roots)
        proposed["EnvironmentVariables"] = vars
        new_plist = plistlib.dumps(proposed)
        write_private(tmp / "proposed.plist", new_plist)
        insist(prior(home)[:2] == source[:2], "PRIOR_STATE_DRIFT")
        # Verify the temporary bundle before publication, so a failed import
        # leaves neither a published release nor an altered service.
        python = row["ProgramArguments"][0]
        insist(Path(python).is_absolute(), "PRIOR_INTERPRETER_UNVERIFIED")
        test_env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin",
                    "PYTHONPATH": str(tmp / "src"),
                    "HOME": str(home), "PYTHONDONTWRITEBYTECODE": "1"}
        check = subprocess.run([python, "-B", str(tmp / "launcher.py"), "--self-check"],
                               env=test_env, capture_output=True, text=True,
                               check=False, timeout=35)
        insist(check.returncode == 0 and check.stdout.strip() == "PRIVATE_OPERATOR_RELEASE_VERIFIED",
               "STAGED_IMPORT_SELFCHECK_FAILED")
        os.replace(tmp, final)
    finally:
        if tmp.exists(): shutil.rmtree(tmp)
    return final


def atomic_plist(path, data):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".privacy-plist-")
    try:
        with os.fdopen(fd, "wb") as f: f.write(data); f.flush(); os.fsync(f.fileno())
        os.chmod(temporary, path.stat().st_mode & 0o777)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def verify_new(home, final, timeout=35):
    deadline = time.monotonic() + timeout
    manifest_raw = owned_bytes(final / "manifest.json", 262144)
    while True:
        try:
            cmd = launch("print", "gui/501/" + OP_LABEL)
            pid = re.search(r"^\s*pid = ([0-9]+)\s*$", cmd.stdout, re.M)
            with HTTP.open("http://127.0.0.1:8766/internal/privacy-fastpath-release", timeout=3) as r:
                proof = json.loads(r.read(8192))
            insist(cmd.returncode == 0 and pid is not None
                   and str(final / "launcher.py") in cmd.stdout
                   and proof.get("pid") == int(pid.group(1))
                   and proof.get("candidate_sha") == CANDIDATE
                   and proof.get("manifest_sha256") == digest(manifest_raw)
                   and proof.get("startup_sources_verified") is True, "OPERATOR_LOAD_NOT_VERIFIED")
            insist(idle(), "OPERATOR_PROJECTION_UNAVAILABLE")
            return True
        except (OSError, ValueError, KeyError, TypeError):
            if time.monotonic() >= deadline: raise Denied("OPERATOR_READBACK_FAILED") from None
            time.sleep(1)


def cutover(home, source, final, authorized):
    plist, raw, _row, entry, _package = source
    insist(authorized() and idle(), "RELEASE_AUTH_OR_IDLE_CHANGED")
    insist(prior(home)[:2] == source[:2], "PRIOR_CHANGED_BEFORE_CUTOVER")
    newraw = owned_bytes(final / "proposed.plist", 32768)
    stopped = False
    try:
        insist(launch("bootout", "gui/501/" + OP_LABEL).returncode == 0,
               "OPERATOR_BOOTOUT_FAILED")
        stopped = True
        insist(authorized(), "RELEASE_GRANT_REVOKED")
        atomic_plist(plist, newraw)
        insist(launch("bootstrap", "gui/501", str(plist)).returncode == 0, "OPERATOR_BOOTSTRAP_FAILED")
        verify_new(home, final)
        insist(digest(owned_bytes(home / "Library/LaunchAgents" / (WORKER_LABEL + ".plist"), 32768))
               == WORKER_PLIST, "WORKER_CHANGED_DURING_OPERATOR_RELEASE")
        return {"status": "APPLIED", "operator_loaded_source_verified": True,
                "worker_service_mutations": 0, "operator_service_mutations": 1,
                "prior_plist_backup_verified": True, "model_calls": 0, "native_dispatches": 0}
    except BaseException:
        if stopped:
            launch("bootout", "gui/501/" + OP_LABEL)
            atomic_plist(plist, raw)
            restored = launch("bootstrap", "gui/501", str(plist))
            try:
                state = launch("print", "gui/501/" + OP_LABEL)
                insist(restored.returncode == 0 and str(entry) in state.stdout
                       and owned_bytes(plist, 32768) == raw and idle(), "ROLLBACK_UNVERIFIED")
            except (OSError, ValueError, TypeError, KeyError):
                raise Denied("ROLLBACK_REQUIRES_OWNER_REVIEW") from None
            raise Denied("CUTOVER_FAILED_PRIOR_OPERATOR_RESTORED") from None
        raise


def release_scope():
    return ImmutableReleaseScope(
        path="m1-operator-privacy-" + CANDIDATE,
        source_sha=CANDIDATE,
        previous_authority="operator-entries:" + OLD_PLIST + ":" + OLD_ENTRY,
        previous_endpoint="launchd:" + OP_LABEL,
        candidate_authority="approved-branch-scanner-five:" + CANDIDATE,
        candidate_endpoint="owner-private-operator-overlay:" + CANDIDATE[:12],
        rollback_procedure="RESTORE_EXACT_PRIOR_OPERATOR_PLIST;PRESERVE_PRIOR_PACKAGE_AND_WORKER",
        switch_target="IDLE_OPERATOR_ONLY_LAUNCHD_SWITCH",
        readback_target="PID_BOUND_OPERATOR_MANIFEST_AND_PRIOR_WORKER_HASH",
        rollback_readback_target="EXACT_PRIOR_OPERATOR_PLIST_AND_HTTP",
    )


def deploy(event, env, token):
    import platform
    insist(platform.system() == "Darwin" and platform.machine() == "arm64"
           and os.getuid() == 501, "M1_OWNER_REQUIRED")
    head = owner_request(event, env, token)
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    with HostComputeLease().hold(max_wait_s=0):
        insist(idle(), "OPERATOR_BUSY")
        before = prior(home)
        _plist, _raw, row, _entry, _package = before
        configargs = row["ProgramArguments"]
        insist(configargs.count("--config") == 1, "OPERATOR_CONFIG_UNBOUND")
        config = Path(configargs[configargs.index("--config") + 1])
        if not config.is_absolute(): config = Path(row.get("WorkingDirectory", "/")) / config
        vals = json.loads(owned_bytes(config, 65536))
        data = Path(vals["data_dir"]).expanduser()
        if not data.is_absolute(): data = Path(row.get("WorkingDirectory", "/")) / data
        db = data / vals.get("guard_db", "guard.db")
        insist(not Path(vals.get("guard_db", "guard.db")).is_absolute()
               and ".." not in Path(vals.get("guard_db", "guard.db")).parts,
               "GUARD_STORE_UNBOUND")
        insist(db.is_file() and db.stat().st_uid == os.getuid(), "GUARD_STORE_UNTRUSTED")
        store = SQLiteGuardStore(db)
        scope = release_scope()
        registry = data / ("privacy-release-" + CANDIDATE[:12] + ".json")
        gate = GuardReleaseGate(store, registry)
        run_id = "operator-privacy-61612"
        insist(store.get_effect("release:" + scope.scope_ref) is None
               and gate.registry.get(scope.path) is None, "RELEASE_ALREADY_CONSUMED")
        canon = canon_revision(token)
        pending = gate.prepare(scope, run_id=run_id, canon_revision=canon)
        insist(pending.get("ok") is True, "GUARD_RELEASE_PREPARE_FAILED")
        guard = GuardCore(store.runtime_state(), store=store)
        approval = OperatorActions(guard).approve_pending(run_id, pending["request_ref"])
        insist(approval.ok, "OWNER_GUARD_APPROVAL_REFUSED")
        def authorized():
            owner_request(event, env, token)
            return not store.is_cancelled(run_id) and canon_revision(token) == canon and (
                gate.verify(scope, run_id, pending["request_ref"]).get("approved") is True)
        final = None
        observed = {}
        class Port:
            def execute(self, plan):
                nonlocal final
                try:
                    insist(authorized(), "RELEASE_GRANT_REVOKED")
                    final = stage(home, before, token)
                    observed.update(cutover(home, before, final, authorized))
                except Exception as exc:
                    observed.update(status="DENIED",
                                    reason=str(exc) if isinstance(exc, Denied)
                                    else "UNEXPECTED_" + type(exc).__name__)
                    raise
            def observe(self, plan):
                if observed.get("status") == "APPLIED" and final is not None:
                    try:
                        if verify_new(home, final, timeout=4):
                            return "OPERATOR_PRIVACY:" + CANDIDATE
                    except (OSError, ValueError, TypeError):
                        pass
                return "UNKNOWN"
        plan = TaskPlan(run_id, "production_deploy", "release-scope:" + scope.scope_ref,
                        text="Operator source-only privacy overlay",
                        canon_revision=canon, effect_id="release:" + scope.scope_ref,
                        provenance="owner-github-label:612:" + head)
        result = guard.execute(plan, CanonContract("GitHub Canon", canon), Port(),
                               "OPERATOR_PRIVACY:" + CANDIDATE)
        insist(result == "VERIFIED_COMPLETE", "GUARD_RELEASE_NOT_VERIFIED")
        return {**observed, "status": "APPLIED", "scope_ref": scope.scope_ref,
                "candidate_sha": CANDIDATE, "guard_effect_verified": True}


def main():
    env = dict(os.environ)
    token = env.get("GITHUB_TOKEN", "")
    insist(bool(token) and bool(env.get("GITHUB_EVENT_PATH")), "RELEASE_CONTEXT_MISSING")
    event = json.loads(Path(env["GITHUB_EVENT_PATH"]).read_bytes())
    owner_request(event, env, token)
    try:
        result = deploy(event, env, token)
    except Exception as exc:
        result = {"status": "DENIED", "reason": str(exc) if isinstance(exc, Denied)
                  else "UNEXPECTED_" + type(exc).__name__, "candidate_sha": CANDIDATE,
                  "service_mutations": "UNVERIFIED", "native_dispatches": 0, "model_calls": 0}
    print(json.dumps(result, sort_keys=True))
    api("POST", "/repos/" + REPO + "/issues/612/comments", token,
        {"body": "Exact Operator-only privacy release receipt\n\n```json\n"
         + json.dumps(result, sort_keys=True) + "\n```"})
    if result.get("status") != "APPLIED": raise SystemExit(1)


if __name__ == "__main__":
    main()
