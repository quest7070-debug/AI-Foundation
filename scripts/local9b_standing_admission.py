"""Admit a newly observed *standing-delegated* main regression into local9B.

This is an optional, trusted-host executor for development_admission.plan_and_submit.
It REUSES local9b_failure_candidates.publish_candidate, its finite three-pair
standing delegation and independently failing fixed-test gate. It REUSES the
existing approved-Issue queue writer and live GitHub issue_task revalidation.
No new authority store, generic model-defined recipe, provider, scheduler,
machine login, GitHub token discovery or fresh inference is introduced.

Must be instantiated by the trusted host with a pinned checkout/test and
within the existing M1 compute lease. On any ambiguous Github publication,
the enclosing admission controller holds for reconciliation, never retries.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat

from ai_foundation.development_admission import HostContract
from ai_foundation.development_guard_admission import GuardAdmissionPort

from local9b_admission_handoff import (
    ApprovedIssueBinding, ExistingApprovedIssueExecutor, HandoffDenied,
    _digest, _owned_existing_dir,
)
from local9b_failure_candidates import publish_candidate, standing_delegation
from local9b_issue_bridge import _gh, issue_task

_SHA40 = re.compile(r"[a-f0-9]{40}\Z")
_SHA64 = re.compile(r"[a-f0-9]{64}\Z")
_DOC = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")
_NEW_ISSUE = re.compile(
    r"https://github\.com/quest7070-dev/AI-Foundation/issues/([1-9][0-9]{0,9})\Z"
)



def _source_directory(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise HandoffDenied("HOST_OWNED_ISOLATED_SOURCE_REQUIRED")
    info = path.stat(follow_symlinks=False)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022):
        raise HandoffDenied("UNTRUSTED_ISOLATED_SOURCE")
    return path


class StandingDelegatedNewIssueExecutor:
    """Ready Issue publication only in the existing finite standing delegation.

    `spec` and `base_sha` are host-pinned inputs, not model/Drive/Issue prose.
    The caller's Guard and Work effect ownership still cover this submission.
    """
    def __init__(self, *, spec, base_sha, checkout, work, inbox,
                 guard_port, publisher=None, read_issue=None):
        if (type(spec) is not dict or not standing_delegation(spec)
                or type(base_sha) is not str or not _SHA40.fullmatch(base_sha)
                or type(guard_port) is not GuardAdmissionPort):
            raise ValueError("EXISTING_STANDING_DELEGATION_REQUIRED")
        self.spec = dict(spec)
        self.base_sha = base_sha
        self.checkout = Path(checkout)
        self.work = Path(work)
        self.inbox = Path(inbox)
        self.guard = guard_port
        self.publisher = publish_candidate if publisher is None else publisher
        self.read_issue = (
            lambda n: _gh("issue", "view", str(n), "--repo",
                          "quest7070-dev/AI-Foundation",
                          "--json", "number,body,labels,state,updatedAt")
        ) if read_issue is None else read_issue
        if not callable(self.publisher) or not callable(self.read_issue):
            raise ValueError("HOST_GITHUB_ADAPTER_REQUIRED")

    def submit(self, contract, plan_id, digest):
        spec = self.spec
        if (type(contract) is not HostContract
                or contract.effect != "draft_code"
                or contract.target != spec["target"]
                or contract.guard_scope != "development:fixed-test"
                or type(contract.test_sha256) is not str
                or not _SHA64.fullmatch(contract.test_sha256)
                or type(plan_id) is not str or not _DOC.fullmatch(plan_id)
                or type(digest) is not str or not _SHA64.fullmatch(digest)
                or not standing_delegation(spec)):
            raise HandoffDenied("HOST_STANDING_CONTRACT_CHANGED")
        inbox = _owned_existing_dir(self.inbox)
        checkout = _source_directory(self.checkout)
        work = _source_directory(self.work)
        if work == checkout or work.is_relative_to(checkout):
            raise HandoffDenied("ISOLATED_WORK_MUST_BE_OUTSIDE_CHECKOUT")
        test = checkout / spec["test"]
        target = checkout / spec["target"]
        if (test.is_symlink() or not test.is_file() or target.is_symlink()
                or not target.is_file() or test.stat().st_size > 65536
                or not test.resolve(strict=True).is_relative_to(checkout.resolve())
                or not target.resolve(strict=True).is_relative_to(checkout.resolve())):
            raise HandoffDenied("PINNED_SOURCE_OR_TEST_MISSING")
        if sha256(test.read_bytes()).hexdigest() != contract.test_sha256:
            raise HandoffDenied("PINNED_ACCEPTANCE_BYTES_CHANGED")
        # Still the CURRENT existing Guard: the earlier plan-level ALLOW
        # is not a reusable permission to create fresh GitHub Issues.
        if self.guard.authorize(contract, plan_id, digest) != "ALLOW":
            raise HandoffDenied("GUARD_RECHECK_NOT_ALLOWED")

        # Existing publisher independently obtains the live main commit,
        # verifies the pinned test and REPRODUCES baseline test failure.
        # Only its standing_delegation path may label a new Issue ready.
        published = self.publisher(dict(spec), checkout, work)
        if type(published) is not dict:
            raise HandoffDenied("GITHUB_ISSUE_PUBLICATION_UNVERIFIED")
        if published.get("status") == "AUTO_READY":
            url = published.get("url")
            match = _NEW_ISSUE.fullmatch(url) if type(url) is str else None
            if match is None:
                raise HandoffDenied("GITHUB_ISSUE_ID_UNVERIFIED")
            issue_number = int(match.group(1))
        elif published.get("status") == "EXISTING":
            issue_number = published.get("issue")
            if type(issue_number) is not int or not 0 < issue_number < 1 << 31:
                raise HandoffDenied("EXISTING_ISSUE_ID_UNVERIFIED")
        else:
            # A CREATED-but-not-ready or ambiguous response is not approval.
            raise HandoffDenied("READY_PUBLICATION_NOT_VERIFIED")
        issue = self.read_issue(issue_number)
        # The producer's original marker is defined by the same immutable
        # fixed recipe, pinned current-main SHA and observed test bytes.
        # An unrelated ready-labelled Issue with a similar body is not enough.
        expected_task_contract = {
            "recipe": "python-fixed-test", "base": spec["base"],
            "base_sha": self.base_sha, "target": spec["target"],
            "test": spec["test"],
            "test_sha256": contract.test_sha256,
            "instruction": spec["instruction"],
        }
        marker = "<!-- local9b-failure:" + sha256(
            json.dumps(expected_task_contract, sort_keys=True).encode(
                "utf-8")).hexdigest() + " -->"
        if (type(issue) is not dict
                or type(issue.get("body")) is not str
                or not issue["body"].startswith(marker + "\n")):
            raise HandoffDenied("PUBLISHED_ISSUE_READBACK_INVALID")
        task = issue_task(issue)  # demands live ready label, OPEN, fixed recipe
        if (task.get("source_issue") != issue_number
                or task.get("recipe") != "python-fixed-test"
                or task.get("base") != "main"
                or task.get("base_sha") != self.base_sha
                or task.get("target") != spec["target"]
                or task.get("test") != spec["test"]
                or task.get("test_sha256") != contract.test_sha256
                or task.get("instruction") != spec["instruction"]):
            raise HandoffDenied("PUBLISHED_STANDING_CONTRACT_CHANGED")
        binding = ApprovedIssueBinding(
            issue_number, task["id"], _digest(task), self.base_sha,
            contract.target, contract.test_sha256,
        )
        # Exactly the same queue transport used for pre-approved Issues:
        # independent source reread, one-shot Issue claim and O_EXCL write.
        executor = ExistingApprovedIssueExecutor(
            binding=binding, inbox=inbox, guard_port=self.guard,
            read_issue=self.read_issue,
        )
        return executor.submit(contract, plan_id, digest)
