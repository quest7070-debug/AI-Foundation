"""Read-only, owner-host-verified release Canon *source* snapshot.

The GitHub canonical main policy sources are the authority for this source
revision, as docs/SOURCE_RELATIONSHIP.md declares. This mechanism does not
pretend that a Git commit is a running Operator policy revision; the snapshot
must be rechecked before a production_deploy decision is consumed.

No Guard writes, approval, launchd, model or Native effects.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import subprocess

REMOTE = "https://github.com/quest7070-dev/AI-Foundation.git"
MAIN_REF = "refs/heads/main"
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
CANON_FILES = (
    "docs/SOURCE_RELATIONSHIP.md",
    "docs/SYSTEM_ROLE_BOUNDARIES.md",
    "docs/BOUNDARIES.md",
    "src/ai_foundation/guard.py",
    "src/ai_foundation/release_gate.py",
    "policy/schema.cedarschema",
)
MAX_SOURCE_BYTES = 300000


class CanonSourceDenied(RuntimeError):
    """Only one of the fixed codes below is allowed to leave the host."""
    pass


def _git(repo, *args, timeout=15):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        cp = subprocess.run(
            ["/usr/bin/git", "-C", str(repo), *args],
            env=env, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CanonSourceDenied("CANON_SOURCE_GIT_UNAVAILABLE") from exc
    return cp


def _live_main(repo):
    # An already-fetched FETCH_HEAD / cached main is never accepted as proof
    # of the current GitHub canonical ref. This is always a fresh remote read.
    cp = _git(repo, "ls-remote", "--exit-code", REMOTE, MAIN_REF, timeout=30)
    if cp.returncode:
        raise CanonSourceDenied("CANON_SOURCE_REMOTE_UNAVAILABLE")
    try:
        lines = cp.stdout.decode("ascii").splitlines()
    except UnicodeError as exc:
        raise CanonSourceDenied("CANON_SOURCE_REMOTE_UNTRUSTED") from exc
    if len(lines) != 1:
        raise CanonSourceDenied("CANON_SOURCE_REMOTE_UNTRUSTED")
    fields = lines[0].split("\t")
    if (len(fields) != 2 or fields[1] != MAIN_REF
            or _SHA40.fullmatch(fields[0]) is None):
        raise CanonSourceDenied("CANON_SOURCE_REMOTE_UNTRUSTED")
    return fields[0]


def _source_blob(repo, main, path):
    cp = _git(repo, "show", main + ":" + path)
    if cp.returncode or not cp.stdout or len(cp.stdout) > MAX_SOURCE_BYTES:
        raise CanonSourceDenied("CANON_SOURCE_FILE_UNAVAILABLE")
    return cp.stdout


def observe_release_canon(repo, *, remote_main=None):
    """Obtain a deterministic source-policy revision, never a user-supplied tag.

    Requires (1) fresh independently-read GitHub main, (2) that exact commit
    available in the local git object store, (3) main being an ancestor of the
    pinned candidate checkout, (4) verified authoritative source declarations,
    and (5) a content digest of a fixed set of Canon/Guard contracts.
    """
    repo = Path(repo)
    main = remote_main if remote_main is not None else _live_main(repo)
    if type(main) is not str or _SHA40.fullmatch(main) is None:
        raise CanonSourceDenied("CANON_SOURCE_REMOTE_UNTRUSTED")

    checkout = _git(repo, "rev-parse", "HEAD")
    if checkout.returncode or not checkout.stdout:
        raise CanonSourceDenied("CANON_SOURCE_WORKTREE_UNTRUSTED")
    if _git(repo, "merge-base", "--is-ancestor", main,
            checkout.stdout.decode("ascii", "strict").strip()).returncode:
        raise CanonSourceDenied("CANON_SOURCE_MAIN_NOT_ANCESTOR")
    policy = {name: _source_blob(repo, main, name) for name in CANON_FILES}

    origin = policy["docs/SOURCE_RELATIONSHIP.md"]
    if (b"quest7070-dev/AI-Foundation" not in origin
            or b"canonical source of truth" not in origin
            or b"GitHub wins" not in origin):
        raise CanonSourceDenied("CANON_SOURCE_DECLARATION_INVALID")
    roles = policy["docs/SYSTEM_ROLE_BOUNDARIES.md"]
    # The ACTIVE CANON was reconciled on 2026-11-12: Foundation/Guard/
    # Harness own development authority, not the superseded Kandev-only
    # sentence. Keep requiring explicit current control boundaries; never
    # turn the release gate into a generic "file exists" check.
    # Both reviewed ACTIVE CANON phrasings explicitly exclude the old
    # Kandev-default role. The November 13 owner instruction strengthens
    # this to no active Kandev executor; do not reject that stronger policy
    # merely because it no longer repeats the historical exact sentence.
    kandev_not_default = any(marker in roles for marker in (
        b"are NOT required as the default development task owner",
        b"not active AI-Foundation development executors in the current owner workflow",
    ))
    if (b"Status: ACTIVE CANON" not in roles
            or b"Foundation owns Canon, Guard/Cedar" not in roles
            or b"Existing Foundation host / Guard / Harness" not in roles
            or not kandev_not_default):
        raise CanonSourceDenied("CANON_SOURCE_DECLARATION_INVALID")
    boundary = policy["docs/BOUNDARIES.md"]
    if b"Guard owns only Canon" not in boundary:
        raise CanonSourceDenied("CANON_SOURCE_DECLARATION_INVALID")
    if (b"production_deploy" not in policy["src/ai_foundation/guard.py"]
            or b"APPROVAL_ACTIONS" not in policy["src/ai_foundation/guard.py"]
            or b'RELEASE_ACTION = "production_deploy"' not in
                policy["src/ai_foundation/release_gate.py"]
            or b"production_deploy" not in policy["policy/schema.cedarschema"]):
        raise CanonSourceDenied("CANON_SOURCE_RELEASE_POLICY_MISSING")

    # Domain separation and explicit file identities prevent accidental hash
    # collisions across differently ordered files or future policy schemes.
    h = hashlib.sha256(b"foundation-operator-release-canon-source/v1\x00")
    for name in CANON_FILES:
        blob = policy[name]
        h.update(len(name).to_bytes(4, "big"))
        h.update(name.encode("ascii"))
        h.update(len(blob).to_bytes(8, "big"))
        h.update(blob)
    revision = "canon-source/v1:" + h.hexdigest()
    return {
        "status": "CANON_SOURCE_VERIFIED",
        "canon_revision": revision,
        "source_main": main,
        "source_count": len(CANON_FILES),
        "authority_kind": "CANONICAL_GITHUB_SOURCE_SNAPSHOT",
        "service_mutations": 0,
        "guard_writes": 0,
    }


def observe_installed_canon(repo):
    """Use only the independently verified installed M1 policy as local authority.

    No network fallback, caller-supplied revision, cached remote ref, or staged
    candidate can establish the incumbent. The existing owner-local registry
    and live Operator readback select its exact source. A successor must still
    descend from that source and pass its separately required Guard decision.
    The canonical published GitHub record is not the local execution trigger.
    """
    from scripts.m1_development_ticket_factory import _owner_local_repo
    from scripts.m1_development_review_candidate import _installed_live_source_repo
    owner_repo = _owner_local_repo()
    installed = _installed_live_source_repo(owner_repo)
    incumbent = _git(installed, "rev-parse", "HEAD")
    if incumbent.returncode:
        raise CanonSourceDenied("INSTALLED_CANON_SOURCE_UNVERIFIED")
    try:
        revision = incumbent.stdout.decode("ascii", "strict").strip()
    except UnicodeError:
        raise CanonSourceDenied("INSTALLED_CANON_SOURCE_UNVERIFIED") from None
    # The digest is deliberately derived from the verified incumbent, NOT
    # the candidate's possibly modified Guard or policy declarations.
    observed = observe_release_canon(repo, remote_main=revision)
    return {**observed, "authority_kind": "VERIFIED_M1_INSTALLED_SOURCE_SNAPSHOT"}
