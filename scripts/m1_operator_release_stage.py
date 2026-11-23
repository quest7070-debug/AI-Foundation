"""Operator-only private release staging, without touching live services/Guard.

Copies only tracked candidate files plus exact incumbent LaunchAgent and entry.
Nothing in this module authorizes or performs a production cutover.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess

from scripts.m1_p4_release_inventory import (
    LABELS, _owned_regular_bytes, _source_from_plist, operator_only_release_scope,
    require_m1,
)


class StagingDenied(RuntimeError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _save(path, data):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
    finally:
        pass


def _read_private(path, limit=32_000_000, *, allow_empty=False):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077 or info.st_size > limit
            or (info.st_size == 0 and not allow_empty)):
        raise StagingDenied("PRIVATE_RELEASE_FILE_UNTRUSTED")
    return path.read_bytes()


def _read_tracked(path, limit=32_000_000):
    """Repository may validly track zero-length regular files."""
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or info.st_size > limit):
        raise StagingDenied("TRACKED_SOURCE_UNTRUSTED")
    return path.read_bytes()


def stage_operator_only(root, home, *, git_run=subprocess.run):
    """Stage exact old plist/entry and clean candidate in owner-private space.

    Staging has no Guard write or LaunchAgent effect. Cutover is separately
    authorized by OperatorOnlyCutover and an authenticated owner host gate.
    """
    require_m1()
    root, home = Path(root), Path(home)
    scope, record = operator_only_release_scope(home=home, root=root, git_run=git_run)
    if scope is None or record.get("status") != "OBSERVED":
        raise StagingDenied("OPERATOR_SCOPE_UNVERIFIED")
    label = LABELS[0][1]
    old_plist_path = home / "Library/LaunchAgents" / (label + ".plist")
    old_plist = _owned_regular_bytes(old_plist_path, max_bytes=32768)
    old_script_path = _source_from_plist(old_plist, label, "operator")
    old_source = _owned_regular_bytes(old_script_path)
    stage_parent = home / "Library/Application Support/AI-Foundation/operator-release-staging"
    stage_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (stage_parent.is_symlink() or stage_parent.stat().st_uid != os.getuid()
            or stage_parent.stat().st_mode & 0o077):
        raise StagingDenied("OWNER_PRIVATE_STAGE_ROOT_UNTRUSTED")
    target = stage_parent / scope.scope_ref
    if target.exists() or target.is_symlink():
        raise StagingDenied("STAGE_SCOPE_ALREADY_EXISTS")
    listed = git_run(["/usr/bin/git", "-C", str(root), "ls-files", "-z"],
                     capture_output=True, timeout=15, check=False)
    if listed.returncode or not isinstance(listed.stdout, bytes):
        raise StagingDenied("TRACKED_CANDIDATE_UNAVAILABLE")
    names = listed.stdout.split(b"\0")
    if names[-1:] != [b""] or not 1 < len(names) <= 25001:
        raise StagingDenied("INVALID_TRACKED_CANDIDATE_LIST")
    files = []
    total = 0
    for raw in names[:-1]:
        try:
            rel = raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise StagingDenied("INVALID_TRACKED_PATH") from exc
        relative = Path(rel)
        if (relative.is_absolute() or ".." in relative.parts or not rel
                or rel.startswith(".git/") or "\n" in rel):
            raise StagingDenied("INVALID_TRACKED_PATH")
        original = root / relative
        data = _read_tracked(original)
        total += len(data)
        if total > 500_000_000:
            raise StagingDenied("STAGED_SOURCE_SIZE_EXCEEDED")
        files.append((rel, data))
    target.mkdir(mode=0o700)
    try:
        _save(target / "previous-launchagent.plist", old_plist)
        _save(target / "previous-operator-entry.py", old_source)
        digests = {}
        for rel, data in files:
            _save(target / "candidate" / rel, data)
            digests[rel] = _sha(data)
        # Reject any changed target or candidate between inventory and stage.
        verify, latest = operator_only_release_scope(
            home=home, root=root, git_run=git_run)
        if verify is None or verify.scope_ref != scope.scope_ref:
            raise StagingDenied("SCOPE_CHANGED_DURING_STAGE")
        manifest = {
            "schema": 1, "scope_ref": scope.scope_ref,
            "candidate_commit": record["candidate_sha"],
            "prior_plist_sha256": _sha(old_plist),
            "prior_entry_sha256": _sha(old_source),
            "prior_entry_path": str(old_script_path),
            "tracked": digests,
        }
        _save(target / "manifest.json",
              (json.dumps(manifest, sort_keys=True) + "\n").encode())
        verify_staged(target, scope.scope_ref)
        return {"status": "STAGED_NO_DEPLOY", "scope_ref": scope.scope_ref,
                "tracked_files": len(files), "backup_verified": True,
                "guard_writes": 0, "service_mutations": 0, "native_dispatches": 0}
    except BaseException:
        shutil.rmtree(target)
        raise


def verify_staged(target, scope_ref):
    target = Path(target)
    if (target.is_symlink() or not target.is_dir()
            or target.stat().st_uid != os.getuid()
            or target.stat().st_mode & 0o077):
        raise StagingDenied("STAGE_DIRECTORY_UNTRUSTED")
    manifest = json.loads(_read_private(target / "manifest.json"))
    if (manifest.get("schema") != 1 or manifest.get("scope_ref") != scope_ref
            or not isinstance(manifest.get("tracked"), dict)
            or not manifest["tracked"]):
        raise StagingDenied("STAGE_MANIFEST_UNTRUSTED")
    for saved, field in (
        ("previous-launchagent.plist", "prior_plist_sha256"),
        ("previous-operator-entry.py", "prior_entry_sha256"),
    ):
        if _sha(_read_private(target / saved)) != manifest.get(field):
            raise StagingDenied("PREVIOUS_RELEASE_BACKUP_MISMATCH")
    for rel, digest in manifest["tracked"].items():
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise StagingDenied("TRACKED_STAGE_PATH_UNTRUSTED")
        if _sha(_read_private(target / "candidate" / path, allow_empty=True)) != digest:
            raise StagingDenied("PINNED_CANDIDATE_CHANGED")
    return True
