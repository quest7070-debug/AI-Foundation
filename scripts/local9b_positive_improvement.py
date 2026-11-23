"""Finite reviewed positive-feature Issue -> existing local9B worker queue.

A genuine *new feature* on a reviewed local9b/ branch may have a failing
fixed acceptance test without being a regression of main. This dedicated
path does NOT reuse the standing main-regression authority. It first requires
an exact trusted host-scope, the unchanged branch and test, independently
reproduced known baseline failure, same-plan current Guard ALLOW, and then
a source-bound ready Issue whose live GitHub body is read back in full.

No model command, auto service installation, production deploy, or main merge.
Unknown issue-create outcomes require reconciliation and are never retried
blindly. Each issue is still consumed at most once by the installed worker.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from ai_foundation.development_admission import HostContract
from ai_foundation.development_guard_admission import GuardAdmissionPort
from ai_foundation.development_improvement_contract import HostImprovementScope
from local9b_admission_handoff import (
    ApprovedIssueBinding, ExistingApprovedIssueExecutor, HandoffDenied,
    _digest, _owned_existing_dir,
)
from local9b_issue_bridge import READY_LABEL, _gh, issue_task
from local9b_task_recipe import FixedPytest
from m1_owner_improvement_source import observed_feature_test

REPOSITORY = "quest7070-dev/AI-Foundation"
_TARGET = "src/ai_foundation/literal_code_search.py"
_TEST = "tests/test_literal_code_search.py"
_CANDIDATE = "ripgrep-14.1.1"
_BASE = "local9b/candidate-ripgrep-search-20261109"
_FAILURE = "REVIEWED_LOCAL_RIPGREP_FEATURE_NOT_IMPLEMENTED"
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_DOC = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")
_URL = re.compile(
    r"https://github\.com/quest7070-dev/AI-Foundation/issues/([1-9][0-9]{0,9})\Z"
)
_INSTRUCTION = (
    "Implement the already reviewed local ripgrep literal-search positive "
    "feature in " + _TARGET + " by changing only that file. "
    "The existing immutable new-feature acceptance at " + _TEST +
    " must pass. Use argv-only offline subprocess, no installation, "
    "no network, no dynamic shell or secrets. Preserve all existing "
    "public APIs. Do not modify tests or any other file."
)


def _owned_directory(path):
    root = Path(path)
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise HandoffDenied("REVIEWED_OWNER_DIRECTORY_REQUIRED")
    meta = root.lstat()
    if (not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid()
            or meta.st_mode & 0o022 or root.resolve(strict=True) != root):
        raise HandoffDenied("REVIEWED_OWNER_DIRECTORY_UNTRUSTED")
    return root


def _positive_baseline(scope, checkout, workspace):
    task = {
        "recipe": "python-fixed-test", "base": scope.base_branch,
        "base_sha": scope.base_sha, "target": scope.target,
        "test": scope.acceptance_test,
        "test_sha256": scope.acceptance_sha256,
        "instruction": _INSTRUCTION,
    }
    fixed = FixedPytest(task, checkout, workspace)
    try:
        fixed.run_tests("reviewed-positive-feature")
    except RuntimeError as exc:
        # A failed infrastructure or an unrelated failure is not permission
        # to auto-ready a new Issue. A missing feature has a distinct,
        # pre-reviewed source-level sentinel; it is not a main regression.
        if _FAILURE not in str(exc):
            raise HandoffDenied("POSITIVE_BASELINE_FAILURE_UNVERIFIED") from None
    else:
        raise HandoffDenied("POSITIVE_FEATURE_ALREADY_PASSES")
    return task


def _marker(task, candidate_id, plan_digest):
    blob = json.dumps(
        {"task": task, "candidate": candidate_id, "plan_sha256": plan_digest},
        sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "<!-- foundation-positive-feature:" + sha256(blob).hexdigest() + " -->"


def _github_publish(task, marker, workspace):
    """Host-only bounded gh issue publisher; one exact ready Issue.

    The caller must already hold the compute lease and current Guard ALLOW.
    On GitHub failures after request send, don't retry: independent
    reconciliation by immutable marker is required.
    """
    query = marker.split(":")[1].split(" ")[0]
    rows = _gh("issue", "list", "--repo", REPOSITORY, "--state", "all",
               "--search", query, "--limit", "100",
               "--json", "number,body")
    if type(rows) is not list or len(rows) >= 100:
        raise HandoffDenied("POSITIVE_ISSUE_DEDUP_UNVERIFIED")
    matches = [r for r in rows if type(r) is dict and
               type(r.get("body")) is str and r["body"].startswith(marker + "\n")]
    if len(matches) > 1:
        raise HandoffDenied("POSITIVE_ISSUE_DUPLICATE_UNVERIFIED")
    if len(matches) == 1:
        number = matches[0].get("number")
        if type(number) is not int or number <= 0:
            raise HandoffDenied("POSITIVE_EXISTING_ISSUE_UNVERIFIED")
        return {"status": "EXISTING", "issue": number}
    body = (marker + "\n\n"
            "Reviewed new local OSS feature, not a regression in main. "
            "One isolated Draft-only implementation. No paid models, "
            "install, personal data scan, main merge or deployment.\n\n"
            "```foundation-autodev-task\n"
            + json.dumps(task, sort_keys=True) + "\n```\n")
    bodypath = workspace / "reviewed-positive-issue.md"
    with bodypath.open("x", encoding="utf-8") as stream:
        stream.write(body)
    bodypath.chmod(0o600)
    try:
        url = subprocess.check_output(
            ["/opt/homebrew/bin/gh", "issue", "create", "--repo",
             REPOSITORY, "--title",
             "Implement reviewed local ripgrep literal search (Draft only)",
             "--body-file", str(bodypath), "--label", READY_LABEL],
            text=True, timeout=45, stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        raise HandoffDenied("POSITIVE_GITHUB_PUBLICATION_UNCERTAIN") from None
    return {"status": "AUTO_READY", "url": url}


class ReviewedPositiveFeatureExecutor:
    """One reviewed candidate/test pair; no generic new-feature authority."""
    def __init__(self, *, scope, checkout, work, inbox,
                 guard_port, publisher=None, read_issue=None,
                 baseline=None):
        if (type(scope) is not HostImprovementScope
                or scope.candidate_id != _CANDIDATE
                or scope.base_branch != _BASE
                or scope.target != _TARGET
                or scope.acceptance_test != _TEST
                or type(guard_port) is not GuardAdmissionPort):
            raise ValueError("FINITE_POSITIVE_FEATURE_SCOPE_REQUIRED")
        self.scope = scope
        self.checkout, self.work, self.inbox = (
            Path(checkout), Path(work), Path(inbox))
        self.guard = guard_port
        self.publisher = _github_publish if publisher is None else publisher
        self.read_issue = (lambda number: _gh(
            "issue", "view", str(number), "--repo", REPOSITORY,
            "--json", "number,body,labels,state,updatedAt"
        )) if read_issue is None else read_issue
        self.baseline = _positive_baseline if baseline is None else baseline
        if not all(callable(x) for x in
                   (self.publisher, self.read_issue, self.baseline)):
            raise ValueError("TRUSTED_HOST_PORTS_REQUIRED")

    def submit(self, contract, plan_id, digest):
        scope = self.scope
        if (not scope.validated(contract) or
                type(contract) is not HostContract or
                type(plan_id) is not str or not _DOC.fullmatch(plan_id) or
                type(digest) is not str or not _SHA.fullmatch(digest) or
                contract.effect != "draft_code" or
                contract.guard_scope != "development:fixed-test"):
            raise HandoffDenied("POSITIVE_FEATURE_CONTRACT_CHANGED")
        inbox = _owned_existing_dir(self.inbox)
        checkout = _owned_directory(self.checkout)
        work = _owned_directory(self.work)
        if checkout == work or work.is_relative_to(checkout):
            raise HandoffDenied("POSITIVE_WORKSPACE_NOT_ISOLATED")
        if observed_feature_test(scope, checkout) != scope.acceptance_sha256:
            raise HandoffDenied("POSITIVE_FEATURE_SOURCE_CHANGED")
        task = self.baseline(scope, checkout, work)
        expected = {
            "recipe": "python-fixed-test", "base": scope.base_branch,
            "base_sha": scope.base_sha, "target": _TARGET, "test": _TEST,
            "test_sha256": scope.acceptance_sha256,
            "instruction": _INSTRUCTION,
        }
        if type(task) is not dict or task != expected:
            raise HandoffDenied("POSITIVE_BASELINE_CONTRACT_CHANGED")
        if self.guard.authorize(contract, plan_id, digest) != "ALLOW":
            raise HandoffDenied("POSITIVE_GUARD_RECHECK_DENIED")
        marker = _marker(task, scope.candidate_id, digest)
        published = self.publisher(task, marker, work)
        if type(published) is not dict:
            raise HandoffDenied("POSITIVE_PUBLICATION_UNVERIFIED")
        if published.get("status") == "AUTO_READY":
            url = published.get("url")
            match = _URL.fullmatch(url) if type(url) is str else None
            if match is None:
                raise HandoffDenied("POSITIVE_NEW_ISSUE_ID_UNVERIFIED")
            number = int(match.group(1))
        elif published.get("status") == "EXISTING":
            number = published.get("issue")
            if type(number) is not int or number <= 0:
                raise HandoffDenied("POSITIVE_EXISTING_ISSUE_ID_UNVERIFIED")
        else:
            raise HandoffDenied("POSITIVE_ISSUE_NOT_READY")
        issue = self.read_issue(number)
        if (type(issue) is not dict or type(issue.get("body")) is not str
                or not issue["body"].startswith(marker + "\n")):
            raise HandoffDenied("POSITIVE_GITHUB_MARKER_MISMATCH")
        # Existing intake also revalidates exact live body, ready label and
        # fixed recipe; no fast path to bypass the installed queue.
        accepted = issue_task(issue)
        if any(accepted.get(name) != value
               for name, value in task.items()):
            raise HandoffDenied("POSITIVE_GITHUB_TASK_CHANGED")
        binding = ApprovedIssueBinding(
            number, accepted["id"], _digest(accepted),
            scope.base_sha, _TARGET, scope.acceptance_sha256)
        return ExistingApprovedIssueExecutor(
            binding=binding, inbox=inbox, guard_port=self.guard,
            read_issue=self.read_issue,
        ).submit(contract, plan_id, digest)
