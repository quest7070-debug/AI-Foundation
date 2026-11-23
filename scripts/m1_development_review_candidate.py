#!/usr/bin/env python3
"""Owner-local review candidate from an existing MCP development_request.

A deterministic aid to human source/test review. This does NOT sign a review,
admit Work, invoke a model, run tests or publish to GitHub.
"""
from __future__ import annotations

import argparse
from hashlib import sha1, sha256
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from m1_development_ticket_factory import (
    _ID, _OWNER, _git, _owner_file, _owner_local_repo, _private_dir,
    _strict_json,
)

_TARGET = re.compile(r"(?<![A-Za-z0-9_/])src/ai_foundation/[A-Za-z0-9_]+\.py(?![A-Za-z0-9_/])")
_TEST = re.compile(r"(?<![A-Za-z0-9_/])tests/test_[A-Za-z0-9_]+\.py(?![A-Za-z0-9_/])")


def _saved_request(root: Path, ticket_id: str, *, work_db="work.db"):
    """Read one exact saved host request without opening the Work DB for writes."""
    if type(ticket_id) is not str or not _ID.fullmatch(ticket_id):
        raise ValueError("EXACT_DEVELOPMENT_REQUEST_ID_REQUIRED")
    path = root / work_db
    if not path.resolve().is_relative_to(root):
        raise PermissionError("WORK_DATABASE_OUTSIDE_OWNER_ROOT")
    info = path.lstat()
    if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise PermissionError("OWNER_WORK_DATABASE_UNVERIFIED")
    job_id = ("mcp-development-request:" + sha256(_OWNER.encode()).hexdigest()
              + ":" + ticket_id)
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                         uri=True, timeout=2) as db:
        db.execute("PRAGMA query_only=ON")
        row = db.execute(
            "SELECT name,status,result FROM work_steps WHERE job_id=? AND position=0",
            (job_id,)).fetchone()
    if row is None or row[:2] != ("development-request", "WAITING_HUMAN"):
        raise ValueError("REQUEST_NOT_WAITING_FOR_REVIEW")
    data = _strict_json(row[2])
    if (type(data) is not dict or set(data) != {"ticket_id", "instruction"}
            or data["ticket_id"] != ticket_id
            or type(data["instruction"]) is not str
            or not 0 < len(data["instruction"]) <= 4000):
        raise ValueError("REQUEST_CONTENT_INVALID")
    return data["instruction"]


def _tracked_file(repo: Path, relative: str) -> str:
    path = repo / relative
    if (path.is_symlink() or not path.is_file()
            or not path.resolve(strict=True).is_relative_to(repo)
            or not 0 < path.stat().st_size <= 262144
            or _git(repo, "ls-files", "--error-unmatch", "--", relative) != relative):
        raise ValueError("CANDIDATE_SOURCE_OR_TEST_UNVERIFIED")
    payload = path.read_bytes()
    # Index flags can hide worktree edits from git status. Pin the exact bytes
    # read here to HEAD, not just to index membership or apparent cleanliness.
    blob = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
    if (not 0 < len(payload) <= 262144
            or sha1(blob).hexdigest() != _git(repo, "rev-parse", "HEAD:" + relative)):
        raise ValueError("CANDIDATE_SOURCE_OR_TEST_UNVERIFIED")
    return sha256(payload).hexdigest()


def snapshot(root, repo, ticket_id, *, work_db="work.db"):
    """Read one current unsigned source/test snapshot without writing."""
    root, repo = Path(root).resolve(strict=True), Path(repo).resolve(strict=True)
    instruction = _saved_request(root, ticket_id, work_db=work_db)
    targets = set(_TARGET.findall(instruction))
    tests = set(_TEST.findall(instruction))
    if len(targets) != 1 or len(tests) > 1:
        raise ValueError("REVIEW_SCOPE_SELECTION_REQUIRED")
    target = next(iter(targets))
    test = next(iter(tests)) if tests else (
        "tests/test_" + Path(target).stem + ".py")
    if _git(repo, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("OWNER_CHECKOUT_NOT_CLEAN")
    base = _git(repo, "rev-parse", "HEAD")
    if not re.fullmatch("[0-9a-f]{40}", base):
        raise ValueError("OWNER_BASE_UNVERIFIED")
    source_sha = _tracked_file(repo, target)
    test_sha = _tracked_file(repo, test)
    # Recheck the source commit and pending Work after reading both files:
    # a concurrent owner edit, checkout switch or cancellation cannot leave
    # an apparently current review candidate. The later independent admit
    # still performs its authoritative exact checks.
    if (_git(repo, "rev-parse", "HEAD") != base
            or _git(repo, "status", "--porcelain", "--untracked-files=no")):
        raise ValueError("OWNER_CHECKOUT_CHANGED_DURING_REVIEW")
    if _saved_request(root, ticket_id, work_db=work_db) != instruction:
        raise ValueError("REQUEST_CHANGED_DURING_REVIEW")
    if ticket_id.startswith("discovered-"):
        from local9b_failure_candidates import discovered_contract
        expected_id, expected_instruction = discovered_contract(
            base, target, test, source_sha, test_sha)
        if ticket_id != expected_id or instruction != expected_instruction:
            raise ValueError("DISCOVERED_SOURCE_OR_TEST_MOVED")
        # Exact original observation must have completed in owner Work.
        job = "development-discovery:" + sha256(
            (base+"\0"+target+"\0"+test).encode()).hexdigest()
        with sqlite3.connect((root/work_db).resolve().as_uri()+"?mode=ro",
                             uri=True,timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            row=db.execute("SELECT name,status,result FROM work_steps WHERE job_id=? AND position=0",
                           (job,)).fetchone()
        if row is None or row[:2] != ("development-discovery", "VERIFIED"):
            raise PermissionError("DISCOVERY_EVIDENCE_REQUIRED")
        receipt=_strict_json(row[2])
        if (type(receipt) is not dict
                or receipt.get("state")!="DISCOVERY_REQUEST_RECORDED"
                or receipt.get("base_sha")!=base or receipt.get("target")!=target
                or receipt.get("test")!=test or receipt.get("ticket_id")!=ticket_id
                or type(receipt.get("failure_sha256")) is not str
                or not re.fullmatch("[a-f0-9]{64}",receipt["failure_sha256"])):
            raise PermissionError("DISCOVERY_EVIDENCE_CHANGED")
    document = {
        "version": 1,
        "review": "UNREVIEWED_CANDIDATE",
        "ticket_id": ticket_id,
        "instruction": instruction,
        "instruction_sha256": sha256(instruction.encode()).hexdigest(),
        "base_sha": base,
        "target": target, "source_sha256": source_sha,
        "test": test, "test_sha256": test_sha,
        "model": "OWNER_MUST_SELECT_AFTER_PUBLIC_EGRESS_REVIEW",
        "public_source_sha256": None,
        "public_instruction_sha256": None,
        "fixed_test_review": "REQUIRED",
        "execution_authority": False,
        "external_egress_authorized": False,
    }
    return document


def _installed_live_source_repo(owner_repo, *, home=None):
    """Resolve *only* a physically VERIFIED current Operator Git source.

    Running Operator imports release modules from an immutable copied archive
    while CI calls the same helpers from a Git checkout. The read-only Guard
    registry selector must therefore use the canonical owner repository, not
    the importing module's location. Loaded launchd, PID and API proof remain
    mandatory; a clean source-only stage or VERIFIED ledger alone is NEVER
    accepted as authority.
    """
    try:
        from scripts import m1_operator_release_cli as cli
    except ImportError:
        raise ValueError("OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED") from None
    home = Path.home() if home is None else Path(home)
    owner_repo = Path(owner_repo).resolve(strict=True)
    try:
        gate = cli._guard_gate(home, readonly=True, source_root=owner_repo)
        record = gate.registry.get("m1-operator")
        authority = getattr(record, "candidate_authority", None)
        if (getattr(record, "status", None) != "VERIFIED"
                or type(authority) is not str
                or re.fullmatch(r"github-commit:[a-f0-9]{40}", authority) is None):
            raise ValueError("VERIFIED_OPERATOR_RECEIPT_REQUIRED")
        sha = authority.removeprefix("github-commit:")
        stage = home / ".ai-foundation-tunnel-sources" / sha
        cli._owner_staged_source(sha, home, stage)
        host = cli.FixedOperatorHost(stage, home=home)
        if host.verified_current_release(record) is not True:
            raise ValueError("VERIFIED_LOADED_OPERATOR_REQUIRED")
        if _git(owner_repo, "cat-file", "-t", sha) != "commit":
            raise ValueError("REVIEW_GIT_OBJECT_NOT_OWNED")

        def common(repo):
            value = Path(_git(repo, "rev-parse", "--git-common-dir"))
            return (value if value.is_absolute()
                    else repo / value).resolve(strict=True)

        if common(owner_repo) != common(stage):
            raise ValueError("STAGED_SOURCE_NOT_OWNER_WORKTREE")
        # Exact immutable stage and original owner commit are rechecked by
        # snapshot(), preview() and the independent final admission. No
        # release permissions or CODE execution are granted here.
        return stage
    except (OSError, ValueError, PermissionError, RuntimeError,
            TypeError, KeyError):
        raise ValueError("OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED") from None


def select_review_repo(root, owner_repo, ticket_id, *, work_db="work.db"):
    """One pinned source selection for pending UI and actual owner preview.

    Never replace a dirty/stale owner's checkout or infer authority from
    a candidate staged by CI. Only missing tracked bytes can consult an
    independently installed and physically verified Operator release.
    """
    owner_repo = Path(owner_repo).resolve(strict=True)
    try:
        snapshot(root, owner_repo, ticket_id, work_db=work_db)
    except ValueError as error:
        if (len(error.args) != 1
                or error.args[0] != "CANDIDATE_SOURCE_OR_TEST_UNVERIFIED"):
            raise
        stage = _installed_live_source_repo(owner_repo)
        snapshot(root, stage, ticket_id, work_db=work_db)
        return stage
    return owner_repo


def resolve_review_snapshot(root, owner_repo, ticket_id, *, work_db="work.db"):
    """Exactly the same authoritative source + fixed-test gate everywhere.

    This read-only primitive is used by the list, preview and subsequent
    readback. It never returns PREVIEW_READY from a different checkout or
    from an unsigned incomplete target/test. UI readiness may be invalidated
    by a later source drift; preview independently checks it again.
    """
    selected = select_review_repo(root, owner_repo, ticket_id, work_db=work_db)
    return selected, snapshot(root, selected, ticket_id, work_db=work_db)


def candidate(root, repo, ticket_id, *, work_db="work.db"):
    """Persist an unsigned snapshot; this cannot be mistaken for owner review."""
    root = Path(root).resolve(strict=True)
    document = snapshot(root, repo, ticket_id, work_db=work_db)
    development = _private_dir(root / "development")
    folder = _private_dir(development / "review_candidates")
    path = folder / (ticket_id + ".json")
    payload = (json.dumps(document, ensure_ascii=False, sort_keys=True,
                          indent=2) + "\n").encode("utf-8")
    if len(payload) > 65536:
        raise ValueError("CANDIDATE_TOO_LARGE")
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                     0o600)
    except FileExistsError:
        if _owner_file(path) != payload:
            raise ValueError("CANDIDATE_DRIFT_REVIEW_REQUIRED") from None
        status = "CANDIDATE_ALREADY_PREPARED"
    else:
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(payload)
                out.flush()
                os.fsync(out.fileno())
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        status = "CANDIDATE_PREPARED"
    return {"status": status, "ticket_id": ticket_id,
            "independent_review_required": True, "work_modified": False,
            "model_calls": 0, "external_writes": 0}


def main():
    from m1_development_bridge import require_m1
    from m1_direct_development import installed_config
    require_m1()
    if os.getuid() != 501 or os.geteuid() != 501:
        raise SystemExit("M1_OWNER_SESSION_REQUIRED")
    parser = argparse.ArgumentParser()
    parser.add_argument("ticket_id")
    args = parser.parse_args()
    _, config, root = installed_config()
    repo = _owner_local_repo()
    try:
        source = select_review_repo(root, repo, args.ticket_id, work_db=config.work_db)
        result = candidate(root, source, args.ticket_id, work_db=config.work_db)
    except (OSError, ValueError, PermissionError, sqlite3.Error, RuntimeError) as exc:
        # Error categories only; never print private instruction or source.
        result = {"status": type(exc).__name__ + "_REVIEW_REQUIRED",
                  "ticket_id": args.ticket_id, "model_calls": 0,
                  "work_modified": False, "external_writes": 0}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in (
        "CANDIDATE_PREPARED", "CANDIDATE_ALREADY_PREPARED") else 2


if __name__ == "__main__":
    raise SystemExit(main())

