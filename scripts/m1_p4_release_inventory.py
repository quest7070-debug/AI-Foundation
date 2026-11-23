"""Fixed, read-only P4 Operator/local9B release inventory and immutable scope.

No installation, command invocation from a plist, backup write, restart, model
use, credential read, source export, or Native dispatch is allowed here.
An inventory scope is a review reference, NOT production authorization.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess

if __package__:
    from .m1_development_bridge import require_m1
else:
    from m1_development_bridge import require_m1

ROOT = Path(__file__).resolve().parents[1]
LABELS = (
    ("operator", "dev.quest7070.ai-foundation.operator", "scripts/operator_server.py"),
    ("local9b", "dev.quest7070.ai-foundation.local9b-autodev", "scripts/local9b_autodev_worker.py"),
)
CANDIDATES = (
    "scripts/operator_server.py",
    "src/ai_foundation/operator_server.py",
    "scripts/local9b_autodev_worker.py",
    "src/ai_foundation/mcp_host.py",
)


def _owned_regular_bytes(path, *, max_bytes=1048576):
    p = Path(path)
    info = p.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or not 0 < info.st_size <= max_bytes):
        raise ValueError("untrusted owner file")
    return p.read_bytes()


def _digest(raw):
    return sha256(raw).hexdigest()


def _source_from_plist(raw, label, service):
    row = plistlib.loads(raw)
    if type(row) is not dict or row.get("Label") != label:
        raise ValueError("unexpected service label")
    args = row.get("ProgramArguments")
    if type(args) is not list or not 1 <= len(args) <= 24:
        raise ValueError("untrusted launch agent arguments")
    if any(type(x) is not str or len(x) > 4096 for x in args):
        raise ValueError("untrusted launch agent arguments")
    # A pinned M1 release can rename or wrap the canonical Operator entry.
    # The independently owner-authored *installed* LaunchAgent is the
    # source of the actual Python entrypoint, not a guessed old basename.
    # This is a READ-ONLY inventory, never permission to run this script.
    if any(arg in {"-c", "-m", "--"} for arg in args):
        raise ValueError("ambiguous Python launcher arguments")
    found = [Path(x) for x in args if x.startswith("/") and x.endswith(".py")]
    if (len(found) != 1 or not found[0].is_absolute()
            or ".." in found[0].parts):
        raise ValueError("installed service script binding unknown")
    return found[0]


def _script_binding_shape(raw, label):
    """Return bounded, non-sensitive argument SHAPE only, never executable paths."""
    try:
        row = plistlib.loads(raw)
        if type(row) is not dict or row.get("Label") != label:
            return "INVALID_LABEL"
        args = row.get("ProgramArguments")
        if (type(args) is not list or not 1 <= len(args) <= 24
                or any(type(x) is not str or len(x) > 4096 for x in args)):
            return "INVALID_ARGS"
        scripts = [Path(x) for x in args if x.startswith("/")
                   and x.endswith(".py")]
        if not scripts:
            return "NO_ABSOLUTE_PYTHON_ENTRY"
        if len(scripts) != 1:
            return "MULTIPLE_PYTHON_ENTRIES"
        script = scripts[0]
        if script.name not in {"operator_server.py", "human_model_operator_launcher.py"}:
            return "UNRECOGNIZED_PYTHON_ENTRY"
        if script.parent.name != "scripts":
            return "KNOWN_ENTRY_VERSIONED_LAYOUT"
        return "KNOWN_ENTRY_CANONICAL_LAYOUT"
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
        return "INVALID_PLIST"


def release_inventory(*, home=None, root=ROOT, git_run=subprocess.run):
    require_m1()
    home = Path.home() if home is None else Path(home)
    root = Path(root)
    result = {
        "status": "BLOCKED", "candidate_main_sha": None,
        "release_scope_ref": None, "services": {},
        "mcp_source_present": False, "external_mcp_transport_verified": False,
        "rollback_contract": "PRESERVE_EXACT_PRIOR_PLISTS_AND_SOURCE_OR_ABORT",
        "installed_process_source_verified": False,
        "human_release_gate": "REQUIRED_NOT_GRANTED",
        "release_permitted": False, "service_mutations": 0, "native_dispatches": 0,
    }
    stage = "CANDIDATE_COMMIT"
    operator_plist_raw = None
    try:
        git = git_run(["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"],
                      capture_output=True, text=True, timeout=8, check=False)
        sha = git.stdout.strip()
        if git.returncode or re.fullmatch("[0-9a-f]{40}", sha) is None:
            return {**result, "reason": "CANDIDATE_SOURCE_UNVERIFIED"}
        result["candidate_main_sha"] = sha

        candidate_hashes = {}
        for relative in CANDIDATES:
            stage = "CANDIDATE_SOURCE"
            candidate_hashes[relative] = _digest(
                _owned_regular_bytes(root / relative))
        result["mcp_source_present"] = bool(candidate_hashes["src/ai_foundation/mcp_host.py"])
        bound = []
        for service, label, candidate in LABELS:
            stage = service.upper() + "_PLIST"
            plist = home / "Library/LaunchAgents" / (label + ".plist")
            raw = _owned_regular_bytes(plist, max_bytes=32768)
            if service == "operator":
                operator_plist_raw = raw
            stage = service.upper() + "_SOURCE_BINDING"
            script = _source_from_plist(raw, label, service)
            stage = service.upper() + "_INSTALLED_SOURCE"
            source = _owned_regular_bytes(script)
            entry = {
                "definition_sha256": _digest(raw),
                "installed_entry_sha256": _digest(source),
                "candidate_entry_sha256": candidate_hashes[candidate],
                "entry_matches_candidate": _digest(source) == candidate_hashes[candidate],
                "existing_source_available": True,
                "prior_plist_readable": True,
                "rollback_backup_present": False,
                "status": "OBSERVED",
            }
            result["services"][service] = entry
            bound.append({
                "label": label, "definition_sha256": entry["definition_sha256"],
                "installed_entry_sha256": entry["installed_entry_sha256"],
                "candidate_entry_sha256": entry["candidate_entry_sha256"],
            })
        stage = "IMMUTABLE_RELEASE_SCOPE"
        # The opaque digest contains only fixed labels, revision and file
        # fingerprints. The original plist/script content remains on M1.
        contract = {
            "schema": 1, "repository": "quest7070-dev/AI-Foundation",
            "candidate": sha, "services": bound,
            "rollback": result["rollback_contract"],
            # Package/worker/MCP sources are all bound, not merely launchers.
            "candidate_files_sha256": candidate_hashes,
        }
        result["release_scope_ref"] = _digest(json.dumps(
            contract, sort_keys=True, separators=(",", ":")).encode())
        result["status"] = "OBSERVED"
        result["note"] = (
            "Hash-bound source/plist inventory only. Separate trusted release "
            "authority, staged rollback and loaded-process verification required."
        )
    except (OSError, ValueError, TypeError, plistlib.InvalidFileException, KeyError):
        result["status"] = "BLOCKED"
        result["reason"] = "HOST_INVENTORY_UNVERIFIED"
        # Exact allowlisted stage only, not the path, plist, SHA or exception.
        result["failed_stage"] = stage
        if stage == "OPERATOR_SOURCE_BINDING" and operator_plist_raw is not None:
            result["operator_binding_shape"] = _script_binding_shape(
                operator_plist_raw, LABELS[0][1])
        result["release_scope_ref"] = None
    return result


def operator_live_preflight(*, home=None, root=ROOT, host_factory=None):
    """Read-only launchd PID+Operator API idle gate for the existing release.

    This supplies NO Guard approval, TTY confirmation, source deployment or
    production entitlement. Never read private Guard rows or execute plist argv.
    """
    require_m1()
    home = Path.home() if home is None else Path(home)
    blocked = {
        "status": "UNVERIFIED", "launchd_registered": False,
        "pid_bound_to_operator_port": False,
        "operator_http_readable": False, "operator_idle": None,
        "preflight_prerequisites_observed": False,
        "guard_owner_approval_verified": False,
        "service_mutations": 0, "model_calls": 0, "native_dispatches": 0,
    }
    try:
        if host_factory is None:
            if __package__:
                from .m1_operator_release_host import FixedOperatorHost
            else:
                from m1_operator_release_host import FixedOperatorHost
            host_factory = FixedOperatorHost
        host = host_factory(root, home=home)
        registered = host._registered() is True
        pid_bound = host._pid_owned() is True if registered else False
        # Only the existing loopback Operator (no new listener or auth).
        view = host._human() if pid_bound else None
        readable = type(view) is dict
        activity = view.get("activity") if readable else None
        idle = len(activity) == 0 if type(activity) is list else None
        return {**blocked, "status": "OBSERVED",
                "launchd_registered": registered,
                "pid_bound_to_operator_port": pid_bound,
                "operator_http_readable": readable,
                "operator_idle": idle,
                "preflight_prerequisites_observed": registered and pid_bound
                    and readable and idle is True}
    except (OSError, RuntimeError, ValueError, TypeError, KeyError,
            subprocess.TimeoutExpired):
        return blocked


def operator_only_release_scope(*, home=None, root=ROOT, git_run=subprocess.run):
    """Review a precise Operator-only Guard scope. Read-only, NEVER activation.

    The installed Operator is a separate authority from local9B, KLM and Native.
    This scope binds exact currently installed plist/source bytes and the
    candidate committed Python code. A scoped Guard approval and recoverable
    installation are separate future owner actions.
    """
    from ai_foundation.release_gate import ImmutableReleaseScope
    require_m1()
    home = Path.home() if home is None else Path(home)
    root = Path(root)
    result = {
        "status": "BLOCKED", "stage": "SOURCE_REVISION",
        "operator_only": True, "scope_ref": None,
        "previous_plist_sha256": None, "previous_entry_sha256": None,
        "candidate_sha": None, "release_permitted": False,
        "guard_owner_approval_verified": False,
        "rollback_backup_verified": False, "loaded_process_verified": False,
        "service_mutations": 0, "guard_mutations": 0, "native_dispatches": 0,
    }
    try:
        rev = git_run(["/usr/bin/git", "-C", str(root), "rev-parse", "HEAD"],
                      capture_output=True, text=True, timeout=8, check=False)
        if rev.returncode or not re.fullmatch("[0-9a-f]{40}", rev.stdout.strip()):
            return None, result
        commit = rev.stdout.strip()
        result["candidate_sha"] = commit
        result["stage"] = "WORKTREE"
        clean = git_run(
            ["/usr/bin/git", "-C", str(root), "status", "--porcelain",
             "--untracked-files=no"], capture_output=True, text=True,
            timeout=8, check=False)
        if clean.returncode or clean.stdout.strip():
            return None, result
        result["stage"] = "CANDIDATE_PACKAGE"
        # Fixed reviewed source set. A commit SHA binds other tracked
        # dependencies; these hashes prevent accidental partial rollout.
        candidate = {
            name: _digest(_owned_regular_bytes(root / name))
            for name in (
                "scripts/operator_server.py",
                "src/ai_foundation/operator_server.py",
                "src/ai_foundation/human_model_context.py",
                "src/ai_foundation/mcp_owner_grants.py",
                "src/ai_foundation/release_gate.py",
            )
        }
        result["stage"] = "INSTALLED_OPERATOR"
        label = LABELS[0][1]
        plist = home / "Library/LaunchAgents" / (label + ".plist")
        original = _owned_regular_bytes(plist, max_bytes=32768)
        original_sha = _digest(original)
        script = _source_from_plist(original, label, "operator")
        original_source_sha = _digest(_owned_regular_bytes(script))
        args = plistlib.loads(original)["ProgramArguments"]
        # Owner-bound config must survive the cutover unchanged. Missing
        # explicit config is not a safe release, even when HTTP is online.
        if args.count("--config") != 1 or args.index("--config") + 1 >= len(args):
            raise ValueError("missing owner config binding")
        config_path = Path(args[args.index("--config") + 1])
        if not config_path.is_absolute() or ".." in config_path.parts:
            raise ValueError("unknown owner config binding")
        config_sha = _digest(_owned_regular_bytes(config_path, max_bytes=65536))
        result["stage"] = "RELEASE_SCOPE"
        manifest = {
            "schema": 1, "candidate_commit": commit, "candidate_files": candidate,
            "previous_plist_sha256": original_sha,
            "previous_entry_sha256": original_source_sha,
            "existing_config_sha256": config_sha,
            "service": label, "target": "operator-only",
        }
        source_hash = _digest(json.dumps(
            manifest, sort_keys=True, separators=(",", ":")).encode())
        scope = ImmutableReleaseScope(
            path="m1-operator",
            source_sha=source_hash,
            previous_authority="owner-installed:" + original_sha + ":" + original_source_sha,
            previous_endpoint="launchd:" + label + "@127.0.0.1:8766",
            candidate_authority="github-commit:" + commit,
            candidate_endpoint="launchd:" + label + "@127.0.0.1:8766",
            rollback_procedure=(
                "preserve exact previous plist and source; on failure restore "
                "original launchd definition then independently verify /api/human"
            ),
            switch_target="operator-launchctl-only-after-exact-Guard-owner-gate",
            readback_target="pid-bound-/api/human-factory-wiring-and-owner-View",
            rollback_readback_target="previous-operator-pid-bound-/api/human",
        )
        result.update(status="OBSERVED", stage="COMPLETE",
                      previous_plist_sha256=original_sha,
                      previous_entry_sha256=original_source_sha,
                      scope_ref=scope.scope_ref)
        return scope, result
    except (OSError, ValueError, TypeError, KeyError,
            plistlib.InvalidFileException):
        # Return only a fixed stage label. No path, exception, config,
        # owner identity, model/Guard data, or source content may escape.
        return None, result
