"""Bounded owner-local delegation of ordinary CODE source+fixed-test review.

The grant is created/revoked only by an authenticated Operator browser POST.
It replaces repeated *source review* for allowed paths, not Guard, model
admission, Work claims, independent tests, Draft privileges or release consent.
No grant is created by MCP JSON, an LLM, a GitHub commit or a missing file.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile

from ai_foundation.sensitive_input_scan import contains_sensitive_value

_VERSION = 1
_FILENAME = "scope-delegation.json"
_ALLOWED_KEYS = frozenset({
    "version", "enabled", "model", "public_source_egress", "allow_draft_delivery",
    "generation"
})
# Guard, identity, privacy, authority, runtime and deployment sources always
# require an exact owner review. This is a *deny* boundary, not a privacy
# classifier and cannot make a private instruction safe to export.
_PROTECTED = (
    "guard", "auth", "owner", "operator", "mcp", "release",
    "human_model", "humanmodel", "privacy", "security", "sensitive",
    "credential", "secret", "approval", "permission", "policy",
    "storage", "payment", "billing", "migration", "store",
    "development", "harness", "routing", "execution", "capability",
    "tool", "work", "host", "code", "network", "keychain",
    "browser", "model", "compute", "task", "config", "deploy",
)


def _path(root):
    root = Path(root).resolve(strict=True)
    return root / "development" / _FILENAME


def _private_dir(path):
    path = Path(path)
    if path.is_symlink():
        raise PermissionError("OWNER_DELEGATION_PATH_UNTRUSTED")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise PermissionError("OWNER_DELEGATION_DIR_UNTRUSTED")
    return path


def _validated(row):
    if (type(row) is not dict or set(row) != _ALLOWED_KEYS
            or type(row["version"]) is not int or row["version"] != _VERSION
            or type(row["enabled"]) is not bool
            or type(row["allow_draft_delivery"]) is not bool
            or type(row["public_source_egress"]) is not bool
            or type(row["generation"]) is not str
            or re.fullmatch(r"[0-9a-f]{32}", row["generation"]) is None
            or row["model"] not in ("m1", "auto")
            or (row["model"] == "auto") != row["public_source_egress"]):
        raise PermissionError("OWNER_DELEGATION_CONTRACT_INVALID")
    return row


def _digest(row):
    return sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_scope(root):
    """Read an existing 0600 owner grant, never create one on an MCP probe."""
    path = _path(root)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    parent = path.parent.lstat()
    if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid()
            or parent.st_mode & 0o077
            or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or not 0 < info.st_size <= 2048):
        raise PermissionError("OWNER_DELEGATION_FILE_UNTRUSTED")
    # Owner-controlled file, no symlinks. Duplicate JSON keys fail closed.
    from m1_development_ticket_factory import _strict_json
    return _validated(_strict_json(path.read_bytes()))


def _save(root, data, *, create_only=False):
    path = _path(root)
    folder = _private_dir(path.parent)
    if path.is_symlink():
        raise PermissionError("OWNER_DELEGATION_FILE_UNTRUSTED")
    if path.exists():
        load_scope(root)  # Existing immutable structure must be valid.
    data = _validated(data)
    payload = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    if len(payload) > 2048:
        raise ValueError("OWNER_DELEGATION_TOO_LARGE")
    fd, temporary = tempfile.mkstemp(prefix=".scope-delegation-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as file:
            os.fchmod(file.fileno(), 0o600)
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        if create_only:
            # Never overwrite a concurrent legacy owner grant or a revocation.
            # Link a fully fsynced complete file into the existing scope path.
            os.link(temporary, path, follow_symlinks=False)
        else:
            os.replace(temporary, path)
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    if load_scope(root) != data:
        raise OSError("OWNER_DELEGATION_READBACK_FAILED")
    return data


def enable_scope(root, *, model, allow_draft_delivery, confirmed=False):
    """One intentional M1 owner UI action; no callable by model/MCP routes."""
    if (os.getuid() != 501 or os.geteuid() != os.getuid()
            or confirmed is not True or type(model) is not str
            or model not in ("m1", "auto")
            or type(allow_draft_delivery) is not bool):
        raise PermissionError("EXPLICIT_OWNER_SCOPE_DELEGATION_REQUIRED")
    # 'auto' is a separate affirmative owner decision to send *public* source
    # to the existing Strata route; no cloud/free-tier authorization is added.
    current = load_scope(root)
    if current is not None and current["enabled"]:
        if (current["model"] != model or
                current["allow_draft_delivery"] != allow_draft_delivery):
            raise PermissionError("OWNER_DELEGATION_CHANGE_REQUIRES_REVOKE")
        return {"status": "ALREADY_ENABLED", "execution_started": False}
    _save(root, {
        "version": 1, "enabled": True, "model": model,
        "generation": secrets.token_hex(16),
        "public_source_egress": model == "auto",
        "allow_draft_delivery": allow_draft_delivery,
    })
    return {"status": "DELEGATION_ENABLED", "execution_started": False}


def revoke_scope(root, *, confirmed=False):
    if (os.getuid() != 501 or os.geteuid() != os.getuid()
            or confirmed is not True):
        raise PermissionError("EXPLICIT_OWNER_SCOPE_REVOCATION_REQUIRED")
    current = load_scope(root)
    if current is None or not current["enabled"]:
        return {"status": "ALREADY_DISABLED", "execution_started": False}
    _save(root, {**current, "enabled": False})
    return {"status": "DELEGATION_DISABLED", "execution_started": False}


def scope_active(root, scope_ref):
    """Revocation or any grant change blocks future Work and Draft claims."""
    if type(scope_ref) is not str or re.fullmatch(r"[0-9a-f]{64}", scope_ref) is None:
        return False
    try:
        row = load_scope(root)
    except (OSError, ValueError, PermissionError):
        return False
    return row is not None and row["enabled"] is True and _digest(row) == scope_ref


def delegated_record(root, repo, ticket_id, *, expected_instruction_sha256=None,
                     work_db="work.db"):
    """Derive one exact, pinned CODE record from an already-enabled owner scope.

    Publicness is owner-scoped, *and* checked with a conservative detector. A
    hash alone never grants authority, and a missing/malformed grant fails
    closed. All other immutable owner-ticket admission rules remain unchanged.
    """
    policy = load_scope(root)
    if policy is None or policy["enabled"] is not True:
        return None
    row = _eligible_snapshot(root, repo, ticket_id,
                             expected_instruction_sha256=expected_instruction_sha256,
                             work_db=work_db)
    if row is None:
        return None
    from m1_development_ticket_factory import _validate_ticket
    record = {key: row[key] for key in (
        "ticket_id", "base_sha", "instruction", "target", "test",
        "source_sha256", "test_sha256"
    )}
    record.update(
        model=policy["model"],
        source_origin="owner-scope-delegation-v1",
        scope_ref=_digest(policy),
        allow_draft_delivery=policy["allow_draft_delivery"],
    )
    if policy["model"] == "auto":
        record["public_source_sha256"] = row["source_sha256"]
        record["public_instruction_sha256"] = row["instruction_sha256"]
    _validate_ticket(record)
    return record


def _eligible_snapshot(root, repo, ticket_id, *, expected_instruction_sha256=None,
                       work_db="work.db"):
    """Technical scope checks, never a grant or a Work admission."""
    from m1_development_review_candidate import snapshot
    row = snapshot(root, repo, ticket_id, work_db=work_db)
    target = row["target"]
    name = Path(target).stem
    if (not re.fullmatch(r"src/ai_foundation/[A-Za-z0-9_]+\.py", target)
            or any(name.startswith(prefix) for prefix in _PROTECTED)):
        return None
    if expected_instruction_sha256 is not None and (
            type(expected_instruction_sha256) is not str
            or row["instruction_sha256"] != expected_instruction_sha256):
        return None
    source = (Path(repo) / target).read_text(encoding="utf-8")
    test = (Path(repo) / row["test"]).read_text(encoding="utf-8")
    if any(contains_sensitive_value(text) for text in
           (row["instruction"], source, test)):
        return None
    return row


# The original durable Guard is the only decision authority for this
# replacement of the legacy scope-enable screen. No user-selected model,
# caller-provided target, fake reviewed flag, or new private authority store.
_SCOPE_RUN = "development-scope-ordinary-v1"
_SCOPE_ACTION = "development_scope"


def _guard_scope_binding(canon):
    """One immutable versioned contract for activation and unattended claims."""
    revision = canon.get("canon_revision") if type(canon) is dict else None
    if (type(canon) is not dict or canon.get("status") != "CANON_SOURCE_VERIFIED"
            or type(revision) is not str
            or re.fullmatch(r"canon-source/v1:[a-f0-9]{64}", revision) is None):
        raise PermissionError("CURRENT_SCOPE_CANON_UNVERIFIED")
    contract = {
        "version": 1, "model": "auto", "public_source_egress": True,
        "allow_draft_delivery": True, "protected": list(_PROTECTED),
        "source": "tracked-one-source-one-fixed-test",
        "production_release": False, "paid_routes": False,
        "autonomous_idle_worker": True,
        "discovery": "pinned-assertion-regression-one-per-cycle-v1",
    }
    digest = _digest(contract)
    target = "ordinary-code-scope:" + digest
    effect = _SCOPE_RUN + ":" + digest
    from ai_foundation.core import CanonContract, TaskPlan
    plan = TaskPlan(run_id=_SCOPE_RUN, action=_SCOPE_ACTION, target=target,
                    canon_revision=revision, effect_id=effect,
                    target_precondition="ABSENT", exclusive_target=True)
    current_canon = CanonContract("canonical-github-source", revision, clear=True)
    policy = {
        "version": 1, "enabled": True, "model": "auto",
        "generation": sha256((revision + ":" + digest).encode()).hexdigest()[:32],
        "public_source_egress": True, "allow_draft_delivery": True,
    }
    return plan, current_canon, policy


def autonomous_scope(root, *, guard, canon):
    """No unattended execution under a legacy, revoked, stale or missing grant."""
    active = load_scope(root)
    if active is None or active["enabled"] is not True:
        return None
    plan, current_canon, policy = _guard_scope_binding(canon)
    if active != policy:
        return None
    store = guard.store
    if (store is None or store.is_cancelled(plan.run_id)
            or not store.is_approved_for(plan.run_id, plan.action, plan.target,
                                         current_canon.revision, plan.effect_id)):
        return None
    effect = store.get_effect(plan.effect_id)
    if (effect is None or effect.status.value != "VERIFIED"
            or effect.run_id != plan.run_id or effect.target != plan.target
            or effect.expected != _digest(active)):
        return None
    return _digest(active)


def prepare_guard_scope(root, repo, ticket_ids, *, guard, canon_observer,
                        storage, work_db="work.db"):
    """Propose or consume the single exact existing-scope decision.

    Called only by the installed owner-host CODE cycle after ordinary Work
    eligibility checks. Read/status/UI GET paths never call this method.
    Existing grants, including explicitly disabled grants, are untouched.
    """
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise PermissionError("M1_OWNER_SESSION_REQUIRED")
    if load_scope(root) is not None:
        return None
    store = guard.store
    if store is None or not hasattr(store, 'is_approved_for'):
        raise PermissionError('DURABLE_GUARD_REQUIRED')
    eligible = False
    for ticket_id in ticket_ids:
        try:
            if _eligible_snapshot(root, repo, ticket_id, work_db=work_db) is not None:
                eligible = True
                break
        except (OSError, ValueError, PermissionError, RuntimeError, UnicodeError):
            continue
    if not eligible or store.is_cancelled(_SCOPE_RUN):
        return None
    from ai_foundation.core import Decision
    plan, current_canon, policy = _guard_scope_binding(canon_observer())
    revision, target, effect = current_canon.revision, plan.target, plan.effect_id
    expected = _digest(policy)
    if not store.is_approved_for(_SCOPE_RUN, _SCOPE_ACTION, target, revision, effect):
        if store.is_approved(_SCOPE_RUN):
            return {"state": "SCOPE_AUTHORITY_STALE", "execution_started": False}
        storage.require("ordinary CODE scope request")
        decision = guard.preflight(plan, current_canon)
        if decision is Decision.WAITING_HUMAN and store.has_pending(_SCOPE_RUN):
            return {"state": "SCOPE_APPROVAL_REQUIRED", "execution_started": False,
                    "decision_surface": "OPERATOR_NOTIFICATIONS"}
        return {"state": "SCOPE_PREPARATION_BLOCKED", "execution_started": False}

    # Existing Guard one-shot effect, claims and readback own consumption.
    # A lost scope after a verified effect must never resurrect an old grant.
    class ScopePort:
        def execute(self, candidate):
            if (candidate != plan
                    or not store.is_approved_for(_SCOPE_RUN, _SCOPE_ACTION, target, revision, effect)
                    or store.is_cancelled(_SCOPE_RUN)):
                raise PermissionError("EXACT_SCOPE_AUTHORITY_REQUIRED")
            _save(root, policy, create_only=True)
        def observe(self, candidate):
            if candidate != plan:
                raise PermissionError("EXACT_SCOPE_REQUIRED")
            actual = load_scope(root)
            return "ABSENT" if actual is None else _digest(actual)
    storage.require("ordinary CODE scope readback")
    port = ScopePort()
    result = guard.execute(plan, current_canon, port, expected)
    if result == "VERIFIED_COMPLETE" and port.observe(plan) == expected:
        return {"state": "SCOPE_ACTIVATED", "execution_started": False}
    return {"state": "SCOPE_EFFECT_NOT_VERIFIED", "execution_started": False}
