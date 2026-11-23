"""Host-only Git Draft handoff for newly proposed SKILL.md files.

This is a narrowly scoped adapter to the EXISTING GitDraftPublisher. The
trusted development owner writes a candidate with existing Guard scope first.
The adapter merely allows Git's intent-to-add index entry for an otherwise
untracked Skill file; it never accepts a repository, branch, shell command,
credential, or publishing permission from a model.
"""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import os
import re
import stat

from .development_git_delivery import GitDraftPublisher
from .agent_skills import _parse

_SKILL_PATH = re.compile(r"skills/[a-z0-9]+(?:-[a-z0-9]+)*/SKILL\.md\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class NewSkillGitDraftHandoff:
    """Run only inside an isolated, already-authorized development checkout."""

    def __init__(self, *, root: Path, repository: str, branch: str,
                 stage_verified, base: str = "main"):
        self.root = Path(root).resolve(strict=True)
        self.stage_verified = stage_verified
        self.publisher = GitDraftPublisher(
            root=self.root, repository=repository, branch=branch, base=base
        )

    def __call__(self, *, target: str, content: str, source_sha256: str,
                 fingerprint: str) -> str:
        if (type(target) is not str or not _SKILL_PATH.fullmatch(target)
                or type(content) is not str or not content
                or type(source_sha256) is not str or not _DIGEST.fullmatch(source_sha256)
                or sha256(content.encode("utf-8")).hexdigest() != source_sha256
                or type(fingerprint) is not str or not _DIGEST.fullmatch(fingerprint)):
            raise ValueError("HOST_SKILL_DRAFT_INVALID")
        # The candidate must satisfy the same strict metadata/path contract as
        # the runtime loader before the Guard is asked to write anything.
        _parse(content.encode("utf-8"), target.split("/")[1])
        if not callable(self.stage_verified):
            raise PermissionError("HOST_GUARDED_STAGER_REQUIRED")
        # Reuse the existing Git owner to reject wrong branch, unrelated
        # dirty files, untracked files, staged changes and ambiguous retries.
        if (self.publisher.branch in ("main", "master", self.publisher.base)
                or self.publisher._run("git", "branch", "--show-current")
                != self.publisher.branch):
            raise PermissionError("ISOLATED_BRANCH_REQUIRED")
        if (self.publisher._run("git", "diff", "--name-only", "HEAD")
                or self.publisher._run("git", "diff", "--cached", "--name-only")
                or self.publisher._run("git", "ls-files", "--others",
                                       "--exclude-standard")):
            raise RuntimeError("SKILL_DRAFT_CHECKOUT_NOT_CLEAN")
        candidate = self.root / target
        if candidate.exists() or candidate.is_symlink():
            raise RuntimeError("SKILL_DRAFT_ALREADY_EXISTS")
        if (not candidate.parent.is_dir()
                or candidate.parent.resolve(strict=True) != candidate.parent):
            raise ValueError("HOST_PROVISIONED_SKILL_DIRECTORY_REQUIRED")
        # Host callback MUST use the existing development Guard and return its
        # successful independently verified write result. This is an input
        # requirement; the callback does not inherit model permissions.
        result = self.stage_verified(target=target, content=content)
        if result != "VERIFIED_COMPLETE":
            raise RuntimeError("GUARDED_SKILL_DRAFT_NOT_VERIFIED")
        # The Guard callback is a separate host boundary. Do not block on a
        # FIFO/device substituted after staging, or follow a replaced symlink.
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(candidate, flags)
        except OSError as exc:
            raise PermissionError("SKILL_DRAFT_UNSAFE_FILE") from exc
        try:
            info = os.fstat(fd)
            # A hard-linked candidate can alias an existing file outside the
            # authorized Skill target, even when its path and digest match.
            # Reject aliases before Git stages or publishes the new path.
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or info.st_mode & 0o022):
                raise PermissionError("SKILL_DRAFT_UNSAFE_FILE")
            if info.st_size != len(content.encode("utf-8")):
                raise RuntimeError("SKILL_DRAFT_INDEPENDENT_READBACK_MISMATCH")
            with os.fdopen(os.dup(fd), "rb") as stream:
                actual = stream.read(info.st_size + 1)
            if sha256(actual).hexdigest() != source_sha256:
                raise RuntimeError("SKILL_DRAFT_INDEPENDENT_READBACK_MISMATCH")
        finally:
            os.close(fd)
        # Git's intent-to-add makes the one *new* path satisfy the existing
        # publisher's tracked-file + diff-isolation checks without weakening
        # its logic. Do not commit or push independently.
        self.publisher._run("git", "add", "-N", "--", target)
        return self.publisher(target=target, source_sha256=source_sha256)



def run_public_skill_draft_on_existing_development_branch(
    *, root: Path, repository: str, branch: str, stage_verified,
    proposal_agent, public_objective: str, name: str, description: str,
    artifact, readback, public_source_id: str, source_revision: str,
    independently_test, base: str = "main",
):
    """Host-only P3 E2E composition with the EXISTING Guard/Git publisher.

    No user/model-facing tool is registered and no new execution queue is
    created. The caller owns the isolated checkout, exact repository and
    code-write grant, existing model/lease, public-source clearance, fixed
    acceptance tests, and reviewed Git credential scope.
    """
    from .skill_learning import run_evidence_bound_skill_learning
    publisher = NewSkillGitDraftHandoff(
        root=root, repository=repository, branch=branch, base=base,
        stage_verified=stage_verified,
    )
    return run_evidence_bound_skill_learning(
        proposal_agent=proposal_agent,
        public_objective=public_objective,
        name=name,
        description=description,
        artifact=artifact,
        readback=readback,
        public_source_id=public_source_id,
        source_revision=source_revision,
        independently_test=independently_test,
        publish_draft=publisher,
    )
