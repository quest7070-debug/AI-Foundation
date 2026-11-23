"""Finite positive-feature Issue publisher uses existing Guard and 9B inbox.

These tests inject GitHub and the baseline proof; no external Issue/model,
OAuth, file-scanning of owner data or new permission grant is created.
The independent real-M1 baseline is separately checked by workflow.
"""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest

from ai_foundation.core import CanonContract, GuardState
from ai_foundation.development_admission import HostContract
from ai_foundation.development_guard_admission import GuardAdmissionPort
from ai_foundation.development_improvement_contract import HostImprovementScope
from ai_foundation.guard import GuardCore
from local9b_issue_bridge import READY_LABEL
from local9b_admission_handoff import HandoffDenied
from local9b_positive_improvement import (
    ReviewedPositiveFeatureExecutor, _INSTRUCTION, _marker,
)


def setup(tmp_path):
    home = (tmp_path / "reviewed-trial").resolve()
    checkout, work, inbox = (
        home / "feature-checkout", home / "isolated",
        home / "installed-state" / "inbox",
    )
    for folder in (home, checkout, work, inbox, inbox.parent / "results"):
        folder.mkdir(exist_ok=True, parents=True)
        folder.chmod(0o700)
    digest = sha256(b"immutable positive feature test bytes").hexdigest()
    scope = HostImprovementScope(
        "ripgrep-14.1.1", "local9b/candidate-ripgrep-search-20261109",
        "a" * 40, "src/ai_foundation/literal_code_search.py",
        "tests/test_literal_code_search.py", digest)
    contract = HostContract(
        "draft_code", scope.target, digest, 512, 512, 0.1,
        "development:fixed-test")
    core = GuardCore(GuardState())
    port = GuardAdmissionPort(
        core, CanonContract("code", "code-v1"),
        delegated_contracts=frozenset({contract}))
    state = {"issue": None, "publisher_calls": 0, "baseline_calls": 0}
    number = 912

    def publisher(task, marker, workspace):
        state["publisher_calls"] += 1
        assert workspace == work
        assert task["test_sha256"] == digest
        assert task["instruction"] == _INSTRUCTION
        state["issue"] = {
            "number": number, "state": "OPEN",
            "labels": [{"name": READY_LABEL}],
            "updatedAt": "2026-11-09T15:10:00Z",
            "body": marker + "\n\nHost-reviewed positive feature; no main regression.\n"
                    "```foundation-autodev-task\n" +
                    json.dumps(task, sort_keys=True) + "\n```",
        }
        return {"status": "AUTO_READY",
                "url": "https://github.com/quest7070-dev/AI-Foundation/issues/912"}

    def read_issue(n):
        assert n == number
        return state["issue"]

    def baseline(scope, checkout, work):
        state["baseline_calls"] += 1
        return {
            "recipe": "python-fixed-test",
            "base": scope.base_branch, "base_sha": scope.base_sha,
            "target": scope.target, "test": scope.acceptance_test,
            "test_sha256": scope.acceptance_sha256,
            "instruction": _INSTRUCTION,
        }

    executor = ReviewedPositiveFeatureExecutor(
        scope=scope, checkout=checkout, work=work, inbox=inbox,
        guard_port=port, publisher=publisher, read_issue=read_issue,
        baseline=baseline,
    )
    return scope, contract, core, port, state, inbox, executor


def test_exact_reviewed_positive_feature_enters_existing_queue_once(tmp_path):
    scope, contract, core, guard, state, inbox, executor = setup(tmp_path)
    with patch("local9b_positive_improvement.observed_feature_test",
               return_value=scope.acceptance_sha256):
        result = executor.submit(contract, "reviewedownerplan123", "f" * 64)
        assert result.startswith("queued:issue-912-")
        assert len(list(inbox.glob("issue-912-*.json"))) == 1
        assert executor.submit(contract, "reviewedownerplan123", "f" * 64) == result
    assert len(list(inbox.glob("issue-912-*.json"))) == 1
    assert state["baseline_calls"] == state["publisher_calls"] == 2
    assert not core.state.effects and not core.state.approvals
    issue = state["issue"]
    assert issue["body"].startswith("<!-- foundation-positive-feature:")
    assert "local9b/candidate-ripgrep-search-20261109" in issue["body"]


def test_unreviewed_or_changed_pins_rejected_before_publication(tmp_path):
    scope, contract, core, guard, state, inbox, executor = setup(tmp_path)
    for mismatch in (
        replace(contract, target="src/ai_foundation/guard.py"),
        replace(contract, test_sha256="e" * 64),
        replace(contract, effect="production_deploy"),
    ):
        with pytest.raises(HandoffDenied):
            executor.submit(mismatch, "reviewedownerplan123", "f" * 64)
    assert state["publisher_calls"] == state["baseline_calls"] == 0
    assert not list(inbox.glob("*.json"))


def test_missing_feature_source_does_not_create_ready_issue(tmp_path):
    scope, contract, core, guard, state, inbox, executor = setup(tmp_path)
    with patch("local9b_positive_improvement.observed_feature_test",
               return_value=None), pytest.raises(HandoffDenied):
        executor.submit(contract, "reviewedownerplan123", "f" * 64)
    assert state["baseline_calls"] == state["publisher_calls"] == 0


def test_guard_cancelled_plan_rejects_publication_after_fixed_baseline(tmp_path):
    scope, contract, core, guard, state, inbox, executor = setup(tmp_path)
    core.state.cancellations.add("foundation-admission-" + "f" * 32)
    with patch("local9b_positive_improvement.observed_feature_test",
               return_value=scope.acceptance_sha256), pytest.raises(HandoffDenied):
        executor.submit(contract, "reviewedownerplan123", "f" * 64)
    assert state["baseline_calls"] == 1
    assert state["publisher_calls"] == 0
    assert not list(inbox.glob("*.json"))


def test_unknown_github_publication_needs_reconciliation_not_queue(tmp_path):
    scope, contract, core, guard, state, inbox, executor = setup(tmp_path)
    executor.publisher = lambda *_: {"status": "UNCERTAIN"}
    with patch("local9b_positive_improvement.observed_feature_test",
               return_value=scope.acceptance_sha256), pytest.raises(HandoffDenied):
        executor.submit(contract, "reviewedownerplan123", "f" * 64)
    assert not list(inbox.glob("*.json"))


def test_changed_or_unready_readback_cannot_queue(tmp_path):
    scope, contract, core, guard, state, inbox, executor = setup(tmp_path)
    # The mock publisher may claim success; missing exact readback is not enough.
    executor.publisher = lambda *_: {
        "status":"AUTO_READY",
        "url":"https://github.com/quest7070-dev/AI-Foundation/issues/912"}
    executor.read_issue = lambda _: {
        "number":912, "body":"NO_MATCH", "state":"OPEN",
        "labels":[{"name":READY_LABEL}],
        "updatedAt":"2026-11-09T15:10:00Z"}
    with patch("local9b_positive_improvement.observed_feature_test",
               return_value=scope.acceptance_sha256), pytest.raises(HandoffDenied):
        executor.submit(contract, "reviewedownerplan123", "f" * 64)
    assert not list(inbox.glob("*.json"))
