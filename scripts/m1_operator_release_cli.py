"""Owner-local, explicit Operator-only release entrypoint.

Run via an authenticated M1 owner's *interactive* SSH/terminal session.
Never called by CI, MCP, M1 Issue bridge or Operator HTTP.
No approval issuing, no shell interpolation, and no model/Native/9B effects.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import sqlite3
import stat
import subprocess
import sys

from ai_foundation.productization import load_config
from ai_foundation.release_gate import GuardReleaseGate
from ai_foundation.store import SQLiteGuardStore
from ai_foundation.operator_release_transaction import OperatorOnlyCutover
from scripts.m1_operator_release_host import FixedOperatorHost, OperatorHostDenied
from scripts.m1_operator_release_canon import (
    CanonSourceDenied, observe_release_canon,
)
from scripts.m1_p4_release_inventory import (
    LABELS, _owned_regular_bytes, operator_only_release_scope, require_m1,
)

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_REF64 = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REGISTRY = "operator-only-release-registry.json"
# Only documented, constant host rejection codes may cross the owner terminal
# boundary.  Never expose paths, stderr, environment variables or exception
# messages from launchctl, SQLite or other system libraries.
_SAFE_HOST_DENIALS = frozenset({
    "OPERATOR_LABEL_OR_ARGS_MISMATCH",
    "ORIGINAL_OPERATOR_ENTRY_MISMATCH",
    "UNREVIEWED_PYTHON_LAUNCHER",
    "UNREVIEWED_OPERATOR_OPTIONS",
    "OWNER_CONFIG_NOT_ABSOLUTE",
    "OPERATOR_PORT_CHANGED",
    "CANDIDATE_ROOT_UNTRUSTED",
    "PINNED_OPERATOR_ENTRY_MISSING",
    "M1_OWNER_SESSION_REQUIRED",
    "SCOPE_CHANGED_BEFORE_BACKUP",
    "STAGE_IDENTITY_MISMATCH",
    "STAGE_NOT_HOST_OWNED",
    "PRIVATE_STAGE_UNTRUSTED",
    "ROLLBACK_MANIFEST_MISMATCH",
    "ROLLBACK_BACKUP_MISMATCH",
    "PRIVATE_STAGE_UNVERIFIED",
    "PREVIOUS_OPERATOR_BACKUP_UNVERIFIED",
    "OPERATOR_PLIST_OWNER_CHANGED",
    "PINNED_CANDIDATE_REQUIRED",
    "LAST_MOMENT_SOURCE_CHANGE",
    "OPERATOR_BUSY_OR_NOT_PID_BOUND",
    "OPERATOR_BOOTOUT_REJECTED",
    "OPERATOR_BOOTOUT_SETTLE_TIMEOUT",
    "OPERATOR_BOOTSTRAP_REJECTED",
    "OPERATOR_BOOTSTRAP_REJECTED_LABEL_PRESENT",
    "OPERATOR_BOOTSTRAP_REJECTED_RETRY_EXHAUSTED",
    "OPERATOR_BOOTSTRAP_REJECTED_PERMISSION",
    "ROLLBACK_BOOTSTRAP_REJECTED_LABEL_PRESENT",
    "ROLLBACK_BOOTSTRAP_REJECTED_RETRY_EXHAUSTED",
    "ROLLBACK_BOOTSTRAP_REJECTED_PERMISSION",
    "ROLLBACK_BOOTOUT_REJECTED",
    "ROLLBACK_BOOTOUT_SETTLE_TIMEOUT",
    "ROLLBACK_BOOTSTRAP_REJECTED",
    "RELEASE_LEDGER_INVENTORY_UNBOUNDED",
    "RELEASE_LEDGER_UNTRUSTED",
    "RELEASE_LEDGER_AMBIGUOUS",
    "RELEASE_MULTIPLE_INFLIGHT",
    "RELEASE_MULTIPLE_VERIFIED_LOADED",
    "RELEASE_INFLIGHT_SCOPE_MISMATCH",
    "VERIFIED_INCUMBENT_UNIDENTIFIED",
})
_RELEASE_STATES = frozenset({"ROLLED_BACK", "PREPARED", "CUTOVER", "VERIFIED"})


def _safe_failure_reason(exc):
    if type(exc) is OwnerReleaseDenied:
        return str(exc)
    if type(exc) is OperatorHostDenied and str(exc) in _SAFE_HOST_DENIALS:
        return str(exc)
    return type(exc).__name__


def _release_canon(repo):
    """Resolve only a fresh, owner-host-verified canonical source snapshot."""
    try:
        return observe_release_canon(repo)
    except CanonSourceDenied as exc:
        # These are fixed, narrowly scoped read-only failure codes.
        raise OwnerReleaseDenied(str(exc)) from exc


def _live_preflight(repo, home, scope):
    """Bounded owner-local inspection, no Guard/launchd writes or approval.

    This cannot prove a future bootout/bootstrap will succeed.  It only
    narrows the failure class before any new release authorization is sought.
    """
    _, registry = _guard_path(home)
    host = FixedOperatorHost(repo, home=home)
    if next(registry.parent.glob("operator-owner-main-release-*.json"), None) is not None:
        registry = host.select_release_registry(registry, scope=scope)
    if registry.exists():
        raw = _owner_file(registry, limit=500000)
        doc = json.loads(raw)
        if type(doc) is not dict or type(doc.get("paths")) is not dict:
            raise OwnerReleaseDenied("RELEASE_REGISTRY_UNTRUSTED")
        record = doc["paths"].get(scope.path)
        if record is None:
            state = "ABSENT"
        elif type(record) is dict and record.get("status") in _RELEASE_STATES:
            state = record["status"]
        else:
            raise OwnerReleaseDenied("RELEASE_REGISTRY_UNTRUSTED")
    else:
        state = "ABSENT"
    incumbent_verified = False
    incumbent_reason = "NOT_APPLICABLE"
    if state == "VERIFIED":
        # The exact source, launchd command and PID must be proven live, not
        # merely present in the old registry. Only fixed reason codes leave M1.
        from types import SimpleNamespace
        prior = SimpleNamespace(
            status=state, release_scope_ref=record.get("release_scope_ref"),
            candidate_authority=record.get("candidate_authority"))
        diagnose = getattr(host, "diagnose_current_release", None)
        if callable(diagnose):
            incumbent_reason = diagnose(prior)
            incumbent_verified = incumbent_reason == "VERIFIED"
        else:
            incumbent_verified = host.verified_current_release(prior) is True
            incumbent_reason = ("VERIFIED" if incumbent_verified
                                else "PREDECESSOR_READBACK_UNVERIFIED")
    # A new request and continuation of that request are different stages.
    # PREPARED may resume only with the exact still-live Guard binding.
    prepared_bound = False
    if state == "PREPARED":
        run_id = record.get("release_run_id")
        request_ref = record.get("release_request_ref")
        if (record.get("release_scope_ref") == scope.scope_ref
                and record.get("release_scope") == scope.as_dict()
                and record.get("candidate_authority") == scope.candidate_authority
                and type(run_id) is str and _RUN.fullmatch(run_id)
                and type(request_ref) is str and _REF64.fullmatch(request_ref)):
            gate = _guard_gate(home, readonly=True, scope=scope)
            receipt = gate.verify(scope, run_id, request_ref, require_approved=False)
            if (receipt.get("ok") is True
                    and receipt.get("scope_ref") == scope.scope_ref
                    and not gate.store.is_cancelled(run_id)):
                if receipt.get("status") == "APPROVED" and receipt.get("approved") is True:
                    prepared_bound = True
                elif receipt.get("status") == "PENDING" and receipt.get("approved") is False:
                    pending = gate._request_row(run_id)
                    prepared_bound = (pending is not None
                                      and gate._request_ref(run_id, pending) == request_ref)
            # The scope binds the actual current plist/source/config bytes.
            # Also preserve independent incumbent proof for later generations.
            history = record.get("history")
            generation = record.get("generation")
            if prepared_bound and type(generation) is int and generation > 1:
                previous = history[-2] if type(history) is list and len(history) >= 2 else None
                if (type(previous) is not dict
                        or previous.get("generation") != generation - 1
                        or previous.get("status") not in ("VERIFIED", "ROLLED_BACK")):
                    prepared_bound = False
                elif previous["status"] == "VERIFIED":
                    from ai_foundation.release_gate import ImmutableReleaseScope
                    from types import SimpleNamespace
                    try:
                        prior = ImmutableReleaseScope(**previous["release_scope"])
                        prepared_bound = (
                            prior.scope_ref == previous.get("release_scope_ref")
                            and prior.candidate_authority == previous.get("candidate_authority")
                            and prior.candidate_endpoint == scope.previous_endpoint
                            and host.verified_current_release(SimpleNamespace(**previous)) is True)
                    except (KeyError, ValueError, TypeError):
                        prepared_bound = False
            elif prepared_bound and (type(generation) is not int or generation != 1):
                prepared_bound = False
    registered = host._registered()
    pid_bound = host._pid_owned()
    live = host._human()
    activity = live.get("activity") if type(live) is dict else None
    idle = type(activity) is list and len(activity) == 0
    return {
        "status": "OBSERVED_NO_EFFECT",
        "operator_only": True,
        "scope_ref": scope.scope_ref,
        "release_state": state,
        "verified_incumbent_loaded": incumbent_verified,
        **({"unreconciled_historical_prepared": host.superseded_prepared_count}
           if getattr(host, "superseded_prepared_count", 0) else {}),
        **({"incumbent_readback_reason": incumbent_reason}
           if state == "VERIFIED" else {}),
        "launchd_registered": registered,
        "pid_bound": pid_bound,
        "operator_api_readable": live is not None,
        "operator_idle": idle,
        "preflight_ok": (
            (state in ("ROLLED_BACK", "ABSENT") or incumbent_verified or prepared_bound)
            and registered and pid_bound and live is not None and idle
        ),
        "guard_writes": 0,
        "service_mutations": 0,
    }


class OwnerReleaseDenied(RuntimeError):
    pass


def _owner_session():
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise OwnerReleaseDenied("M1_OWNER_SESSION_REQUIRED")


def _owner_file(path, *, limit=65536):
    return _owned_regular_bytes(path, max_bytes=limit)


def _installed_config(home):
    """Discover only the current owner-installed Operator's exact --config."""
    label = LABELS[0][1]
    plist = home / "Library/LaunchAgents" / (label + ".plist")
    row = plistlib.loads(_owner_file(plist, limit=32768))
    args = row.get("ProgramArguments")
    if row.get("Label") != label or type(args) is not list:
        raise OwnerReleaseDenied("INSTALLED_OPERATOR_UNVERIFIED")
    if args.count("--config") != 1 or args.index("--config") + 1 >= len(args):
        raise OwnerReleaseDenied("CONFIG_BINDING_MISSING")
    cfg = args[args.index("--config") + 1]
    if type(cfg) is not str or not cfg.startswith("/") or ".." in Path(cfg).parts:
        raise OwnerReleaseDenied("CONFIG_BINDING_UNTRUSTED")
    _owner_file(Path(cfg))
    return load_config(cfg)


def _guard_path(home):
    config = _installed_config(home)
    root = Path(config.data_dir)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise OwnerReleaseDenied("AUTHORITY_ROOT_UNTRUSTED")
    info = root.stat()
    if info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise OwnerReleaseDenied("AUTHORITY_ROOT_UNTRUSTED")
    guard = root / config.guard_db
    # Never read a potentially huge production Guard database into memory.
    # Fail closed rather than creating a replacement for a missing authority DB.
    info = guard.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or info.st_size == 0):
        raise OwnerReleaseDenied("GUARD_STORE_UNTRUSTED")
    from ai_foundation.authority_manifest import verify as verify_authority
    if verify_authority(root, config).get("established") is not True:
        raise OwnerReleaseDenied("ESTABLISHED_AUTHORITY_REQUIRED")
    return guard, root / _REGISTRY


def _release_scope(repo, expected_head, home):
    if type(expected_head) is not str or not _SHA40.fullmatch(expected_head):
        raise OwnerReleaseDenied("PINNED_COMMIT_REQUIRED")
    # The immutable scope routine independently checks clean tracked worktree,
    # installed source/plist/config and critical candidate source bytes.
    scope, observation = operator_only_release_scope(home=home, root=repo)
    if (scope is None or observation.get("status") != "OBSERVED"
            or observation.get("candidate_sha") != expected_head
            or scope.candidate_authority != "github-commit:" + expected_head):
        raise OwnerReleaseDenied("SOURCE_OR_INSTALLED_SCOPE_MISMATCH")
    return scope


class ReadOnlyGuardStore(SQLiteGuardStore):
    """No schema initialization, migrations or DB writes during apply verify."""

    def _init_db(self):
        pass

    def _connect(self):
        db = sqlite3.connect(Path(self.path).resolve().as_uri() + "?mode=ro",
                             uri=True, timeout=5)
        db.execute("PRAGMA query_only=ON")
        return db


def _guard_gate(home, *, readonly=False, scope=None, source_root=None):
    """Resolve an existing original Guard ledger from an explicit trusted root.

    Runtime Operator code is installed under a copied release archive; CI
    source tools execute from a Git worktree. Source-sensitive historical
    ledger selection must not depend on which copy of this CLI was imported.
    The optional root is used *only* for the owner's read-only review;
    release effects keep their unchanged default context and Guard gate.
    """
    guard_path, registry_path = _guard_path(home)
    resolver_root = (Path(__file__).resolve().parents[1]
                     if source_root is None else Path(source_root).resolve(strict=True))
    if source_root is not None:
        if (not readonly or resolver_root.is_symlink()
                or not resolver_root.is_dir()):
            raise OwnerReleaseDenied("REVIEW_GUARD_SOURCE_UNVERIFIED")
        # Only an internally verified local owner Git repo is accepted:
        # arbitrary PR checkout paths or a caller-selected archive cannot
        # grant an alternate registry authority.
        from scripts.m1_development_ticket_factory import _owner_local_repo
        if resolver_root != _owner_local_repo().resolve(strict=True):
            raise OwnerReleaseDenied("REVIEW_GUARD_SOURCE_UNVERIFIED")
    # The original Guard database and registry selection remain authoritative.
    if next(registry_path.parent.glob("operator-owner-main-release-*.json"), None) is not None:
        registry_path = FixedOperatorHost(
            resolver_root, home=home).select_release_registry(
                registry_path, scope=scope)
    if registry_path.exists():
        _owner_file(registry_path, limit=500000)
    store = ReadOnlyGuardStore(guard_path) if readonly else SQLiteGuardStore(guard_path)
    return GuardReleaseGate(store, registry_path)


def _tty_confirm(prompt, phrase):
    """Only an active terminal belonging to the SSH owner can confirm."""
    fd = os.open("/dev/tty", os.O_RDWR | os.O_NOCTTY)
    try:
        if not os.isatty(fd):
            return False
        os.write(fd, (prompt + "\nType exactly: " + phrase + "\n> ").encode())
        collected = bytearray()
        while len(collected) <= 90:
            char = os.read(fd, 1)
            if not char:
                return False
            if char in (b"\n", b"\r"):
                break
            collected.extend(char)
        else:
            return False
        return collected.decode("utf-8", "strict") == phrase
    finally:
        os.close(fd)


class InteractiveOwnerGate:
    """Independent owner-session confirmation; Guard UI remains authoritative.

    This never mints a Guard approval. It only attests the one exact scope/run/ref
    locally once, for the two checks inside a single transaction.
    """

    def __init__(self, scope, run_id, request_ref, *, confirmer=_tty_confirm):
        _owner_session()
        self.binding = (scope.scope_ref, run_id, request_ref)
        phrase = "APPLY " + scope.scope_ref[:16]
        if not confirmer(
            "Operator-only production change. Existing owner Guard approval "
            "must already exist. 9B and Native are not targets.\n"
            "Release scope: " + scope.scope_ref + "\n"
            "Guard run: " + run_id + "\n"
            "Guard request: " + request_ref,
            phrase,
        ):
            raise OwnerReleaseDenied("OWNER_TERMINAL_CONFIRMATION_REQUIRED")

    def verify_exact_release(self, scope, run_id, request_ref):
        _owner_session()
        return (scope.scope_ref, run_id, request_ref) == self.binding


def _owner_staged_source(head, home, selected):
    """A trusted mobile owner client may select only a pre-staged exact commit.

    This does not create a second release path: run() still uses the existing
    Canon, Guard approval, backup, cutover, PID readback and rollback gates.
    A generic model/MCP caller cannot select a checkout here.
    """
    if type(head) is not str or _SHA40.fullmatch(head) is None:
        raise OwnerReleaseDenied("PINNED_COMMIT_REQUIRED")
    base = home / ".ai-foundation-tunnel-sources"
    path = base / head
    if (path != Path(selected) or base.is_symlink()
            or path.is_symlink() or not path.is_dir()):
        raise OwnerReleaseDenied("OWNER_STAGED_RELEASE_SOURCE_REQUIRED")
    for directory in (base, path):
        info = directory.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022):
            raise OwnerReleaseDenied("OWNER_STAGED_RELEASE_SOURCE_REQUIRED")
    try:
        for args in (("rev-parse", "HEAD"), ("status", "--porcelain", "--untracked-files=all")):
            cp = subprocess.run(
                ["/usr/bin/git", "-C", str(path), *args],
                capture_output=True, text=True, timeout=8, check=True)
            result = cp.stdout.strip()
            if args[0] == "rev-parse" and result != head:
                raise OwnerReleaseDenied("OWNER_STAGED_RELEASE_SOURCE_CHANGED")
            if args[0] == "status" and result:
                raise OwnerReleaseDenied("OWNER_STAGED_RELEASE_SOURCE_CHANGED")
    except (OSError, subprocess.SubprocessError):
        raise OwnerReleaseDenied("OWNER_STAGED_RELEASE_SOURCE_UNVERIFIED") from None
    return path


def run(args, *, confirmer=_tty_confirm, trusted_source_root=None):
    _owner_session()
    home = Path.home()
    repo = (Path(__file__).resolve().parents[1]
            if trusted_source_root is None
            else _owner_staged_source(args.expected_head, home, trusted_source_root))
    scope = _release_scope(repo, args.expected_head, home)
    if args.operation == "inspect":
        return {"status": "OBSERVED_NO_EFFECT", "operator_only": True,
                "scope_ref": scope.scope_ref, "candidate_sha": args.expected_head,
                "guard_writes": 0, "service_mutations": 0}
    if args.operation == "preflight":
        return _live_preflight(repo, home, scope)
    if args.operation == "canon-check":
        return _release_canon(repo)
    if args.operation == "request":
        # Never accept a caller-provided string as canonical authority.
        # The source policy snapshot is freshly resolved from GitHub main,
        # independently of the reviewed candidate commit and the LLM.
        source = _release_canon(repo)
        canon_revision = source["canon_revision"]
        if (args.canon_revision is not None
                and args.canon_revision != canon_revision):
            raise OwnerReleaseDenied("CANON_SOURCE_REVISION_MISMATCH")
        observer = _guard_gate(home, readonly=True, scope=scope)
        # A VERIFIED predecessor is not a terminal forever: it may be
        # superseded ONLY after fresh owner-local loaded-source/PID proof.
        # This grants no deploy authority; a NEW exact Guard request, owner
        # confirmation, backup/cutover and PID readback remain mandatory.
        registry = getattr(observer, "registry", None)
        predecessor = registry.get(scope.path) if registry is not None else None
        predecessor_kw = {}
        if predecessor is not None and predecessor.status == "VERIFIED":
            installed = FixedOperatorHost(repo, home=home)
            if installed.verified_current_release(predecessor) is not True:
                raise OwnerReleaseDenied("VERIFIED_PREDECESSOR_NOT_RUNNING")
            predecessor_kw["verified_predecessor_ref"] = predecessor.release_scope_ref
        elif predecessor is not None and predecessor.status != "ROLLED_BACK":
            raise OwnerReleaseDenied("RELEASE_PREDECESSOR_NOT_RECONCILED")
        if not confirmer(
            "Create an exact production_deploy Guard request, NOT an approval.\n"
            "Independently verified Canon *source* revision: "
            + canon_revision + "\n"
            "Current canonical GitHub main: " + source["source_main"] + "\n"
            "This verifies source policy, not installed runtime policy parity.\n"
            "Scope: " + scope.scope_ref,
            "REQUEST " + scope.scope_ref[:16],
        ):
            raise OwnerReleaseDenied("OWNER_TERMINAL_CONFIRMATION_REQUIRED")
        # Only after the interactive owner confirmation may the existing
        # Guard store be opened for a new approval request.
        prepared = _guard_gate(home, scope=scope).prepare(
            scope, canon_revision=canon_revision, **predecessor_kw)
        if (type(prepared) is not dict or prepared.get("ok") is not True
                or prepared.get("status") != "WAITING_HUMAN"
                or prepared.get("scope_ref") != scope.scope_ref
                or not isinstance(prepared.get("run_id"), str)
                or not isinstance(prepared.get("request_ref"), str)):
            raise OwnerReleaseDenied("GUARD_PREPARE_NOT_ACCEPTED")
        return {"status": prepared["status"], "scope_ref": scope.scope_ref,
                "run_id": prepared["run_id"],
                "request_ref": prepared["request_ref"],
                "approved": False, "service_mutations": 0}
    if (not isinstance(args.run_id, str) or not _RUN.fullmatch(args.run_id)
            or not isinstance(args.request_ref, str)
            or not _REF64.fullmatch(args.request_ref)):
        raise OwnerReleaseDenied("EXACT_GUARD_REQUEST_REQUIRED")
    gate = _guard_gate(home, readonly=True, scope=scope)
    # Guard authorization remains durable after rollback, but a consumed
    # release transaction is not replayable.  Check the *existing* journal
    # before any owner prompt, backup, stage or launchctl effects.
    prior = gate.registry.get(scope.path)
    if (prior is None or prior.status != "PREPARED"
            or prior.release_run_id != args.run_id
            or prior.release_request_ref != args.request_ref):
        raise OwnerReleaseDenied("RELEASE_STATE_NOT_PREPARED")
    # The currently authoritative source policy must STILL equal the one
    # the owner actually approved. A changed main or policy halts *before*
    # the owner prompt, backup, staging or service effects.
    if (not isinstance(prior.release_canon_revision, str)
            or not prior.release_canon_revision.startswith("canon-source/v1:")):
        raise OwnerReleaseDenied("CANON_SOURCE_REVISION_UNBOUND")
    source = _release_canon(repo)
    if source["canon_revision"] != prior.release_canon_revision:
        raise OwnerReleaseDenied("CANON_SOURCE_REVISION_CHANGED")
    verified = gate.verify(scope, args.run_id, args.request_ref)
    if (verified.get("status") != "APPROVED" or not verified.get("approved")
            or verified.get("scope_ref") != scope.scope_ref):
        raise OwnerReleaseDenied("EXACT_GUARD_APPROVAL_NOT_VERIFIED")
    owner_gate = InteractiveOwnerGate(
        scope, args.run_id, args.request_ref, confirmer=confirmer)
    host = FixedOperatorHost(repo, home=home)
    result = OperatorOnlyCutover(gate, host, owner_gate).execute(
        scope, args.run_id, args.request_ref)
    return {"status": result.status, "scope_ref": result.scope_ref,
            "operator_only": result.operator_only,
            "guard_approved": result.guard_approved}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "preflight", "canon-check", "request", "apply"))
    parser.add_argument("--expected-head", required=True,
                        help="Full, independently reviewed exact PR commit SHA")
    parser.add_argument("--canon-revision",
                        help="Optional expected Canon *source* revision; independently derived on owner host (request only)")
    parser.add_argument("--run-id", help="Existing exact approved Guard run (apply only)")
    parser.add_argument("--request-ref", help="Existing exact approved Guard ref (apply only)")
    args = parser.parse_args(argv)
    if args.operation == "request" and (args.run_id or args.request_ref):
        parser.error("request cannot take an existing Guard grant")
    if args.operation != "request" and args.canon_revision:
        parser.error("Canon revision only belongs to request")
    if args.operation != "apply" and (args.run_id or args.request_ref):
        parser.error("run/ref only belong to apply")
    try:
        result = run(args)
    except (OwnerReleaseDenied, OSError, ValueError, RuntimeError) as exc:
        # No paths, user identities, auth data or exception details exported.
        result = {"status": "BLOCKED", "reason": _safe_failure_reason(exc)}
        if (type(exc) is OperatorHostDenied
                and result["reason"] == "RELEASE_MULTIPLE_INFLIGHT"
                and type(exc.safe_contention) is dict):
            result["ledger_contention"] = exc.safe_contention
        print(json.dumps(result, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())

