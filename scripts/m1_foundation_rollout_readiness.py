"""Fixed read-only M1 deployment readiness; no private HumanModel data exported.

Use the installed Operator launcher and existing official diagnostics. An
on-disk file hash is NOT proof that a process loaded the file, and no release
authority may be derived from these observations.
"""
from __future__ import annotations

import contextlib
from hashlib import sha256
import io
import json
from pathlib import Path
import stat
import sys

if __package__:
    from .m1_development_bridge import require_m1
    from . import m1_human_model_activation_readiness as readiness
    from .m1_runtime_status_probe import source_status
else:
    from m1_development_bridge import require_m1
    import m1_human_model_activation_readiness as readiness
    from m1_runtime_status_probe import source_status

_REPO = Path(__file__).resolve().parents[1]
_ALLOWED_BLOCKERS = frozenset({
    "EXISTING_EXTERNAL_LEDGER_NOT_UNIQUE", "NO_HUMANMODEL_EVIDENCE",
    "APPROVED_NONEMPTY_VIEW_NOT_UNIQUE", "APPROVED_SOURCE_SNAPSHOT_UNVERIFIED",
    "SERVER_OWNER_NOT_UNIQUE", "SERVER_OWNER_BINDING_MISMATCH",
    "CANONICAL_RELEASE_REQUIRES_CONTEXT_INTEGRATION",
})
# Class names only. Never expose the original exception message, stack,
# filenames, owner identifiers, ledger paths, credentials or query text.
_ALLOWED_ERROR_TYPES = frozenset({
    "RuntimeError", "ValueError", "FileNotFoundError", "PermissionError",
    "OSError", "CalledProcessError", "TimeoutExpired", "KeyError",
    "TypeError", "OperationalError", "ModuleNotFoundError", "JSONDecodeError",
})


def _observed_bool(mapping, field):
    """Distinguish an observed False from a field not reached by the probe."""
    if type(mapping) is not dict:
        return None
    value = mapping.get(field)
    return value if type(value) is bool else None

def _readiness_phase(report):
    """Only name the last verified milestone, never the hidden failure text.

    This uses fields the existing host probe already emits BEFORE its generic
    exception handler. No extra host calls, owner IDs, paths, DB reads or logs.
    """
    if _observed_bool(report, "diagnostic_complete") is True:
        return "DIAGNOSTIC_COMPLETE"
    if _observed_bool(report, "diagnostic_complete") is not False:
        return "UNKNOWN"
    if type(report.get("runtime")) is dict:
        return "FINAL_STATUS"
    if type(report.get("identity")) is dict:
        return "BINDING_LEDGER_OR_RUNTIME"
    if type(report.get("ledger_candidates")) is int:
        return "SERVER_OWNER_LOOKUP"
    return "HOST_OR_LEDGER_DISCOVERY"




def _owner_source_hash(path):
    """Only compare trusted regular owner files, not symlinks or file contents."""
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        return None
    info = p.stat()
    import os
    if (info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o022 or info.st_size > 262144):
        return None
    return sha256(p.read_bytes()).hexdigest()


def _humanmodel_readiness():
    # The established readiness audit already checks private-source owner,
    # approved nonempty View, source revision and local binding; only approved
    # structural booleans and fixed blocker codes leave the host.
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        readiness.main()
    try:
        report = json.loads(output.getvalue().strip().splitlines()[-1])
    except (ValueError, IndexError, TypeError):
        return {"status": "UNAVAILABLE", "blockers": ["READINESS_PROBE_FAILED"]}
    if type(report) is not dict:
        return {"status": "UNAVAILABLE", "blockers": ["READINESS_PROBE_FAILED"]}
    blockers = report.get("blockers", ())
    if type(blockers) is not list:
        blockers = ()
    error_type = report.get("error_type")
    if type(error_type) is not str:
        error_type = None
    elif error_type not in _ALLOWED_ERROR_TYPES:
        error_type = "OTHER"
    owner_state = report.get("owner_service_state")
    if type(owner_state) is not str:
        owner_state = None
    result = {
        "status": report.get("status") if report.get("status") in
                  {"BLOCKED", "CONTEXT_CODE_AND_SOURCE_READY",
                   "READY_FOR_REVIEWED_BINDING"} else "UNAVAILABLE",
        "diagnostic_complete": _observed_bool(report, "diagnostic_complete"),
        "diagnostic_phase": _readiness_phase(report),
        "diagnostic_error_type": error_type,
        "owner_service_state": (owner_state
                               if owner_state in
                               {"CONTAINER_RUNNING_QUERY_FAILED", "CONTAINER_STOPPED",
                                "CONTAINER_UNAVAILABLE_DAEMON_OK",
                                "DOCKER_DAEMON_INACCESSIBLE",
                                "DOCKER_INSPECT_UNAVAILABLE"}
                               else None),
        "binding_prerequisites_ready": _observed_bool(report, "binding_prerequisites_ready"),
        "single_server_owner": _observed_bool(report.get("identity"), "single_server_owner"),
        "nonempty_view_verified": _observed_bool(report.get("ledger"), "source_snapshot_verified"),
        "binding_owner_matches": _observed_bool(report.get("identity"), "binding_owner_matches"),
        "blockers": sorted(set(x for x in blockers if type(x) is str and x in _ALLOWED_BLOCKERS)),
    }
    # Unknown/missing remains null, never an asserted denial or grant. Only a
    # separately validated true is positive; release remains prohibited.
    return result



def _humanmodel_view_readback():
    """One guarded owner-local View read; never export original content.

    This is a functional *source* read through the existing context tool,
    not proof of a live model answer, persisted Guard approval or consent.
    """
    try:
        import os
        import shutil
        from ai_foundation.core import GuardState
        from ai_foundation.guard import GuardCore
        from ai_foundation.human_model_context import (
            HumanModelContext, _source_reader, load_bindings,
        )
        roots = readiness.existing_ledger_roots()
        installed = readiness.installed_paths()
        docker = shutil.which("docker") or next(
            (p for p in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker")
             if Path(p).is_file()), None)
        if len(roots) != 1 or installed is None or docker is None:
            return {"status": "UNAVAILABLE", "guarded_read": False}
        owner = readiness._owner_record(docker)
        if (type(owner) is not dict or owner.get("count") != 1
                or type(owner.get("owner")) is not str):
            return {"status": "UNAVAILABLE", "guarded_read": False}
        _script, data = installed
        binding = load_bindings(data / "human-model-bindings.json").get(owner["owner"])
        if (binding is None or Path(binding.root).resolve() != roots[0].resolve()
                or len(binding.scopes) != 1):
            return {"status": "UNAVAILABLE", "guarded_read": False}
        # Ephemeral, non-persistent Guard, matching the existing owner-local
        # source readback contract. Never call a model or publish records.
        context = HumanModelContext(binding, _source_reader(_REPO),
                                    guard=GuardCore(GuardState()),
                                    run_id="m1-view-functional-readonly")
        page = json.loads(context.read(owner["owner"], binding.scopes[0]))
        if (type(page) is not dict
                or page.get("status") not in {"AVAILABLE", "PARTIAL"}
                or type(page.get("records")) is not list
                or not page["records"]
                or type(page.get("view_revision")) is not int
                or page["view_revision"] < 1):
            return {"status": "UNAVAILABLE", "guarded_read": False}
        return {
            "status": "PARTIAL" if page["status"] == "PARTIAL" else "READ_VERIFIED",
            "guarded_read": True,
            "records_observed": len(page["records"]),
            "complete_view": page["status"] == "AVAILABLE",
            "model_calls": 0,
        }
    except (OSError, ValueError, TypeError, KeyError, RuntimeError,
            PermissionError, ImportError, IndexError):
        return {"status": "UNAVAILABLE", "guarded_read": False}


def _local9b_release_prerequisites(previous=None):
    """Read-only first-stage check of the existing one-shot worker release.

    Uses exactly the release script's incumbent manifest/module/idle checks.
    No Guard.prepare, queue claim, stage, launchctl mutation or model call.
    Only fixed missing-file categories may leave the private M1 host.
    """
    if previous is None:
        if __package__:
            from .m1_github_owner_local9b_release import previous_worker
        else:
            from m1_github_owner_local9b_release import previous_worker
        previous = previous_worker
    try:
        previous(Path.home())
    except FileNotFoundError as exc:
        # Never expose exc.filename or the owner's volume/layout.
        kind = {
            "manifest.json": "INSTALLED_WORKER_MANIFEST_MISSING",
            "native_code_compare.py": "PINNED_NATIVE_COMPARE_MISSING",
            "native_fake_e2e.py": "PINNED_NATIVE_E2E_MISSING",
            "local9b_autodev_worker.py": "INSTALLED_WORKER_SOURCE_MISSING",
        }.get(Path(exc.filename or "").name, "REQUIRED_RELEASE_FILE_MISSING")
        return {"status": "BLOCKED", "reason": kind}
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        # Denied carries a fixed internal precondition code, but do not
        # return exception content from an untrusted/corrupt manifest.
        return {"status": "BLOCKED", "reason": "PREVIOUS_WORKER_UNVERIFIED"}
    return {"status": "PREREQUISITES_OBSERVED", "reason": None}




def _toolhive_owner_readback(home=None):
    """Fixed, read-only local provenance classification without running the CLI.

    Do not return paths, hashes, contents, credentials, process output,
    usernames or untrusted failure text to the GitHub bridge.
    """
    import os
    from ai_foundation.toolhive_owner_runtime import (
        TOOLHIVE_OWNER_DIR, owner_toolhive_binary)
    root = (Path.home() if home is None else Path(home)) / TOOLHIVE_OWNER_DIR
    try:
        directory = root.lstat()
    except FileNotFoundError:
        return {"status": "INSTALL_DIRECTORY_ABSENT"}
    except OSError:
        return {"status": "OWNER_DIRECTORY_UNAVAILABLE"}
    if (not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != os.getuid()
            or directory.st_mode & 0o077):
        return {"status": "OWNER_DIRECTORY_UNTRUSTED"}
    binary = root / "thv"
    try:
        info = binary.lstat()
    except FileNotFoundError:
        return {"status": "EXECUTABLE_ABSENT"}
    except OSError:
        return {"status": "EXECUTABLE_UNAVAILABLE"}
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or not info.st_mode & stat.S_IXUSR):
        return {"status": "EXECUTABLE_UNTRUSTED"}
    for receipt in ("archive.sha256", "executable.sha256"):
        path = root / receipt
        try:
            record = path.lstat()
        except FileNotFoundError:
            return {"status": "PINNED_RECEIPT_MISSING"}
        except OSError:
            return {"status": "PINNED_RECEIPT_UNAVAILABLE"}
        if (not stat.S_ISREG(record.st_mode)
                or record.st_uid != os.getuid()
                or record.st_mode & 0o022 or record.st_size > 128):
            return {"status": "PINNED_RECEIPT_UNTRUSTED"}
    return {"status": "PINNED_PROVENANCE_VERIFIED"
            if owner_toolhive_binary(Path(home) if home is not None else None)
            is not None else "PINNED_PROVENANCE_MISMATCH"}



def _toolhive_files_runtime_readback(server="ai-foundation-fs"):
    """Pinned owner-only status of exactly one known Foundation workload."""
    if server not in {"ai-foundation-fs", "ai-foundation-repo"}:
        return {"status": "STATUS_INVALID"}
    import subprocess
    from ai_foundation.toolhive_owner_runtime import owner_toolhive_binary
    thv=owner_toolhive_binary()
    if thv is None:
        return {"status": "CLI_UNVERIFIED"}
    try:
        proc=subprocess.run([str(thv),"status",server,
                             "--format","json"],
                            capture_output=True,text=True,timeout=4)
    except (OSError,subprocess.TimeoutExpired):
        return {"status": "STATUS_UNAVAILABLE"}
    if proc.returncode != 0:
        return {"status": "STATUS_NOT_OK"}
    try:
        if type(proc.stdout) is not str or len(proc.stdout)>8192:
            raise ValueError("CLI_BODY_INVALID")
        result=json.loads(proc.stdout)
    except (ValueError,TypeError):
        return {"status": "STATUS_INVALID"}
    if type(result) is not dict or result.get("name")!=server:
        return {"status": "STATUS_INVALID"}
    states={
        "running":"RUNNING", "stopped":"STOPPED", "error":"ERROR",
        "starting":"STARTING", "stopping":"STOPPING",
        "unhealthy":"UNHEALTHY", "removing":"REMOVING",
        "unknown":"UNKNOWN", "unauthenticated":"UNAUTHENTICATED",
        "auth_retrying":"AUTH_RETRYING", "policy_stopped":"POLICY_STOPPED",
    }
    status=result.get("status")
    return {"status":states.get(status,"OTHER") if type(status) is str
            else "STATUS_INVALID"}



def _code_workspace_binding_readback(home=None):
    """Check explicit installed owner binding, not an inferred repository path.

    This is only the LaunchAgent definition; it is not a loaded-process check
    or permission to allow CODE access to a different source directory.
    """
    import os
    import plistlib
    root = Path.home() if home is None else Path(home)
    plist = root / "Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist"
    try:
        meta = plist.lstat()
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
                or meta.st_mode & 0o022 or not 0 < meta.st_size <= 32768):
            return "OWNER_LAUNCHAGENT_UNVERIFIED"
        data = plistlib.loads(plist.read_bytes())
        if type(data) is not dict or data.get("Label") != "dev.quest7070.ai-foundation.operator":
            return "OWNER_LAUNCHAGENT_UNVERIFIED"
        variables = data.get("EnvironmentVariables", {})
        if type(variables) is not dict:
            return "OWNER_LAUNCHAGENT_UNVERIFIED"
        value = variables.get("AI_FOUNDATION_REPO_ROOT")
        if not value:
            return "EXPLICIT_WORKSPACE_UNBOUND"
        if (type(value) is not str or len(value) > 4096
                or not Path(value).is_absolute() or ".." in Path(value).parts):
            return "WORKSPACE_BINDING_INVALID"
        workspace = Path(value)
        info = workspace.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022):
            return "WORKSPACE_BINDING_INVALID"
        return "EXPLICIT_WORKSPACE_PRESENT"
    except (OSError, ValueError, TypeError, KeyError, plistlib.InvalidFileException):
        return "OWNER_LAUNCHAGENT_UNVERIFIED"




def _existing_code_workspace_candidate(home=None):
    """Check one previously known owner checkout, never select or mount it.

    The response contains only a fixed category. Git remote strings, paths,
    owner names, and local state never leave the M1 runner.
    """
    import os
    import subprocess
    root = (Path.home() if home is None else Path(home)) / "Develop/AI-Foundation"
    try:
        info = root.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022
                or root.is_symlink()):
            return "CANDIDATE_UNTRUSTED"
        # Do not turn a nested checkout or an arbitrary identically named
        # folder into the Owner's live CODE target.
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=4)
        if result.returncode or result.stdout.strip() != str(root.resolve()):
            return "CANDIDATE_NOT_REPOSITORY_ROOT"
        # The owner's GitHub identity may be a separately named reviewed
        # remote, not origin. Never inspect arbitrary names or follow URLs.
        accepted = {
            prefix + suffix
            for prefix in (
                "git@github.com:quest7070-dev/AI-Foundation",
                "github-dev:quest7070-dev/AI-Foundation",
                "https://github.com/quest7070-dev/AI-Foundation",
            )
            for suffix in ("", ".git")
        }
        for name in ("origin", "github-dev"):
            remote = subprocess.run(
                ["/usr/bin/git", "-C", str(root), "config", "--get",
                 "remote." + name + ".url"],
                capture_output=True, text=True, timeout=4)
            if remote.returncode == 0 and remote.stdout.strip() in accepted:
                return "EXISTING_OWNER_CHECKOUT_VERIFIED"
        # An existing owner checkout can be a detached/offline replica with
        # no canonical named remote. Exact commit identity is stronger than a
        # remote string but does not make a different revision writable.
        import re
        source = subprocess.run(
            ["/usr/bin/git", "-C", str(_REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=4)
        candidate = subprocess.run(
            ["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=4)
        source_sha = source.stdout.strip()
        candidate_sha = candidate.stdout.strip()
        if (source.returncode == candidate.returncode == 0
                and re.fullmatch(r"[0-9a-f]{40}", source_sha)
                and re.fullmatch(r"[0-9a-f]{40}", candidate_sha)):
            if source_sha == candidate_sha:
                status = subprocess.run(
                    ["/usr/bin/git", "-C", str(root), "status",
                     "--porcelain", "--untracked-files=normal"],
                    capture_output=True, text=True, timeout=4)
                return ("EXISTING_OWNER_CHECKOUT_VERIFIED_BY_COMMIT"
                        if status.returncode == 0 and not status.stdout.strip()
                        else "CANDIDATE_WORKTREE_DIRTY")
            return "CANDIDATE_SOURCE_REVISION_MISMATCH"
        return "CANDIDATE_REPOSITORY_IDENTITY_UNVERIFIED"
    except FileNotFoundError:
        return "CANDIDATE_ABSENT"
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "CANDIDATE_UNVERIFIED"


def rollout_readiness():
    require_m1()
    sys.path.insert(0, str(_REPO / "src"))
    selected = None
    try:
        selected = readiness.installed_paths()
    except Exception:
        selected = None

    deployed = {"operator_launcher": "UNAVAILABLE",
                "operator_package": "UNVERIFIED", "view": "UNVERIFIED"}
    if selected is not None:
        script, _data = selected
        root = script.parent.parent
        launcher_digest = _owner_source_hash(script)
        canonical_script = _owner_source_hash(_REPO / "scripts/operator_server.py")
        if launcher_digest:
            deployed["operator_launcher"] = (
                "CURRENT_MAIN" if launcher_digest == canonical_script else "OTHER_VERSION"
            )
        installed = _owner_source_hash(root / "src/ai_foundation/operator_server.py")
        source = _owner_source_hash(_REPO / "src/ai_foundation/operator_server.py")
        if installed:
            deployed["operator_package"] = (
                "CURRENT_MAIN" if installed == source else "OTHER_VERSION"
            )

    observed = source_status()
    files = observed.get("files", {}) if type(observed) is dict else {}
    worker = files.get("worker", {}) if type(files) is dict else {}
    intake = files.get("failure_intake", {}) if type(files) is dict else {}
    current_worker = _owner_source_hash(_REPO / "scripts/local9b_autodev_worker.py")
    deployed["local9b_worker"] = (
        "CURRENT_MAIN" if current_worker and worker.get("sha256") == current_worker
        else "OTHER_VERSION" if worker.get("state") == "OBSERVED" else "UNAVAILABLE"
    )
    deployed["local9b_failure_intake"] = (
        "OBSERVED" if intake.get("state") == "OBSERVED" else "UNAVAILABLE"
    )
    # A previous-version release preflight is irrelevant when the trusted
    # installed worker source already matches this main. Do not weaken the
    # original manifest/owner/queue/idle checks for any mismatched or unknown
    # worker, and do not treat hash equality as loaded-process proof.
    prerequisites = (
        {"status": "NOT_APPLICABLE", "reason": "INSTALLED_SOURCE_CURRENT_MAIN"}
        if deployed["local9b_worker"] == "CURRENT_MAIN"
        else _local9b_release_prerequisites()
    )
    structural = _humanmodel_readiness()
    functional = (
        _humanmodel_view_readback()
        if (structural.get("status") == "CONTEXT_CODE_AND_SOURCE_READY"
            and structural.get("binding_prerequisites_ready") is True
            and structural.get("single_server_owner") is True
            and structural.get("binding_owner_matches") is True
            and structural.get("nonempty_view_verified") is True)
        else {"status": "NOT_CHECKED", "guarded_read": False}
    )
    return {
        "status": "OBSERVED",
        "deployed": deployed,
        "humanmodel": structural,
        "humanmodel_view_readback": functional,
        "local9b_release_prerequisites": prerequisites,
        "toolhive_owner": _toolhive_owner_readback(),
        "toolhive_files_runtime": _toolhive_files_runtime_readback(),
        "toolhive_code_runtime": _toolhive_files_runtime_readback("ai-foundation-repo"),
        "code_workspace_binding": _code_workspace_binding_readback(),
        "existing_code_workspace_candidate": _existing_code_workspace_candidate(),
        "release_permitted": False,
        "native_dispatches": 0,
        "service_mutations": 0,
        "note": "Read-only installed file comparison and approved View structural audit; no process identity, production or decision authority inferred.",
    }
