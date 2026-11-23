"""Guard-bound handoff to the EXISTING approved-Issue local9B intake.

No GitHub Issue creation, approval-label creation, model invocation, scheduler,
terminal command, merge, service restart or new permission store. The only
effect is creating one exact preapproved Issue task in the existing inbox.
The installed worker still re-resolves GitHub Issue identity before starting.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

from ai_foundation.development_admission import HostContract
from ai_foundation.development_guard_admission import GuardAdmissionPort

from local9b_issue_bridge import _gh, issue_task, previous_issue_attempt

_SHA = re.compile(r"[a-f0-9]{64}\Z")
_TASK = re.compile(r"issue-[1-9][0-9]*-[a-f0-9]{16}\Z")
_DOC = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")


class HandoffDenied(ValueError):
    pass


@dataclass(frozen=True)
class ApprovedIssueBinding:
    """Pinned by the owner host after GitHub ready-label and test verification.

    Raw Drive/Issue/model text may never create or modify this object.
    """
    issue_number: int
    task_id: str
    task_sha256: str
    base_sha: str
    target: str
    test_sha256: str

    def __post_init__(self):
        if (type(self.issue_number) is not int or self.issue_number < 1
                or type(self.task_id) is not str or not _TASK.fullmatch(self.task_id)
                or not self.task_id.startswith("issue-" + str(self.issue_number) + "-")
                or type(self.task_sha256) is not str
                or not _SHA.fullmatch(self.task_sha256)
                or type(self.base_sha) is not str
                or re.fullmatch(r"[a-f0-9]{40}", self.base_sha) is None
                or type(self.target) is not str
                or re.fullmatch(r"src/ai_foundation/[A-Za-z0-9_]+\.py",
                                self.target) is None
                or type(self.test_sha256) is not str
                or not _SHA.fullmatch(self.test_sha256)):
            raise ValueError("INVALID_HOST_PINNED_ISSUE_BINDING")


def _digest(task):
    return sha256(json.dumps(task, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True).encode("utf-8")).hexdigest()


def _owned_existing_dir(path):
    """Do not follow a symlink or create a new runner inbox authority."""
    path = Path(path)
    if (not path.is_absolute() or path.is_symlink()
            or not path.is_dir() or not (path.parent / "results").is_dir()
            or (path.parent / "results").is_symlink()):
        raise HandoffDenied("EXISTING_OWNER_WORKER_INBOX_REQUIRED")
    for candidate in (path, path.parent / "results"):
        info = candidate.stat(follow_symlinks=False)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o022):
            raise HandoffDenied("OWNER_INBOX_UNTRUSTED")
    return path


class ExistingApprovedIssueExecutor:
    """One exact ready Issue -> existing local9B queue, after CURRENT Guard.

    Never infer approval from a candidate's benefit, document or Issue prose.
    An already-consumed Issue is not retried even if its source changes.
    """
    def __init__(self, *, binding, inbox, guard_port, read_issue=None):
        if (type(binding) is not ApprovedIssueBinding
                or type(guard_port) is not GuardAdmissionPort):
            raise ValueError("HOST_BINDING_AND_EXISTING_GUARD_REQUIRED")
        self.binding = binding
        self.inbox = Path(inbox)
        self.guard = guard_port
        self.read_issue = (lambda number: _gh(
            "issue", "view", str(number), "--repo",
            "quest7070-dev/AI-Foundation", "--json",
            "number,body,labels,state,updatedAt"
        )) if read_issue is None else read_issue
        if not callable(self.read_issue):
            raise ValueError("TRUSTED_ISSUE_READER_REQUIRED")

    def submit(self, contract, plan_id, digest):
        binding = self.binding
        if (type(contract) is not HostContract
                or contract.effect != "draft_code"
                or contract.target != binding.target
                or contract.test_sha256 != binding.test_sha256
                or type(plan_id) is not str or not _DOC.fullmatch(plan_id)
                or type(digest) is not str or not _SHA.fullmatch(digest)):
            raise HandoffDenied("HOST_PINNED_EXECUTION_CONTRACT_REQUIRED")
        inbox = _owned_existing_dir(self.inbox)
        # A current scoped Guard verdict is required again at the actual
        # inbox-write boundary; stale prior plan allowance is not enough.
        if self.guard.authorize(contract, plan_id, digest) != "ALLOW":
            raise HandoffDenied("GUARD_RECHECK_NOT_ALLOWED")
        issue = self.read_issue(binding.issue_number)
        task = issue_task(issue)  # exact ready label + finite Python recipe
        if (task.get("source_issue") != binding.issue_number
                or task.get("id") != binding.task_id
                or task.get("recipe") != "python-fixed-test"
                or task.get("base_sha") != binding.base_sha
                or task.get("target") != binding.target
                or task.get("test_sha256") != binding.test_sha256
                or _digest(task) != binding.task_sha256):
            raise HandoffDenied("APPROVED_ISSUE_CONTRACT_CHANGED")
        if previous_issue_attempt(inbox, binding.issue_number):
            raise HandoffDenied("ISSUE_ALREADY_ATTEMPTED_RECONCILE")
        path = inbox / (binding.task_id + ".json")
        content = json.dumps(task, sort_keys=True, separators=(",", ":"))
        # Existing queue entry from the same exactly pinned source may be
        # reported as already queued, but never re-created or replaced.
        if path.is_symlink():
            raise HandoffDenied("UNTRUSTED_QUEUED_TASK")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
        except FileExistsError:
            try:
                if path.is_symlink() or path.read_text() != content:
                    raise HandoffDenied("QUEUE_CONTENT_CONFLICT")
            except OSError as exc:
                raise HandoffDenied("QUEUE_READBACK_UNAVAILABLE") from exc
        else:
            # If the acknowledgement is lost after create, leave the exact
            # queue record for independent reconciliation, never submit again.
            with os.fdopen(fd, "w", encoding="utf-8") as out:
                out.write(content)
                out.flush()
                os.fsync(out.fileno())
        if path.is_symlink() or path.read_text(encoding="utf-8") != content:
            raise HandoffDenied("QUEUE_READBACK_MISMATCH")
        # The worker still must independently validate the live Issue and
        # consume its exclusive one-shot claim. This is NOT 9B E2E success.
        return "queued:" + binding.task_id
