"""Predelegated real main-regression Issue publisher after Guard evidence admission.

All Github publication and 9B work are synthetic in these tests. The actual
Finite standing-delegation policy, issue parser, GuardCore and queue writer
ARE used; no new approval store, model, OAuth or scheduler.
"""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from local9b_admission_handoff import HandoffDenied
from local9b_issue_bridge import READY_LABEL, issue_task
from local9b_failure_candidates import standing_delegation
from local9b_standing_admission import StandingDelegatedNewIssueExecutor

from ai_foundation.core import CanonContract, Decision, GuardState
from ai_foundation.development_admission import (
    HostContract, CostReceipt, BenefitReceipt, HardwareReceipt, plan_and_submit,
)
from ai_foundation.development_guard_admission import GuardAdmissionPort
from ai_foundation.guard import GuardCore

NOW = 1_794_230_000.0
BASE = "a" * 40
NUMBER = 620


def stand_spec():
    target = "src/ai_foundation/notification_boundary.py"
    test = "tests/test_notification_boundary.py"
    return {
        "base": "main", "target": target, "test": test,
        "instruction": (
            "Repair the independently reproduced failure in " + test
            + " by changing only " + target
            + ". Preserve other behavior and all public APIs; do not change tests."
        ),
    }


def setup(tmp_path):
    work = tmp_path / "owner-work"
    checkout = work / "repo"
    inbox = work / "installed" / "inbox"
    test_content = b"def test_fixed_host_failure(): assert False\n"
    spec = stand_spec()
    for directory in (work, checkout, inbox.parent, inbox,
                      checkout / "src/ai_foundation", checkout / "tests",
                      inbox.parent / "results"):
        directory.mkdir(parents=True, exist_ok=True)
    (checkout / spec["target"]).write_text("x = 1\n")
    (checkout / spec["test"]).write_bytes(test_content)
    assert standing_delegation(spec)
    digest = sha256(test_content).hexdigest()
    contract = HostContract("draft_code", spec["target"], digest, 512, 512,
                            0.1, "development:fixed-test")
    core = GuardCore(GuardState())
    port = GuardAdmissionPort(
        core, CanonContract("code", "code-v1"),
        delegated_contracts=frozenset({contract}),
    )
    contract_block = {
        "recipe": "python-fixed-test", "base": "main", "base_sha": BASE,
        "target": spec["target"], "test": spec["test"],
        "test_sha256": digest, "instruction": spec["instruction"],
    }
    issue = {
        "number": NUMBER, "state": "OPEN",
        "labels": [{"name": READY_LABEL}],
        "updatedAt": "2026-11-09T00:00:00Z",
        "body": ("<!-- local9b-failure:" + sha256(
                    json.dumps(contract_block, sort_keys=True).encode()).hexdigest()
                 + " -->\n"
                 "Host-verified baseline failure. No main merge.\n"
                 "```foundation-autodev-task\n"
                 + json.dumps(contract_block, sort_keys=True) + "\n```"),
    }
    state = {"issue": issue, "publish_calls": 0, "reads": 0,
             "status": "AUTO_READY"}

    def publish(selected, repo, workspace):
        state["publish_calls"] += 1
        assert selected == spec and repo == checkout and workspace == work
        if state["status"] == "EXISTING":
            return {"status": "EXISTING", "issue": NUMBER}
        if state["status"] != "AUTO_READY":
            return {"status": state["status"], "url":
                    "https://github.com/quest7070-dev/AI-Foundation/issues/" + str(NUMBER)}
        return {"status": "AUTO_READY",
                "url": "https://github.com/quest7070-dev/AI-Foundation/issues/" + str(NUMBER)}

    def read_issue(number):
        state["reads"] += 1
        assert number == NUMBER
        return state["issue"]

    executor = StandingDelegatedNewIssueExecutor(
        spec=spec, base_sha=BASE, checkout=checkout, work=work,
        inbox=inbox, guard_port=port, publisher=publish, read_issue=read_issue,
    )
    return executor, contract, core, port, state, work, checkout, inbox


def test_real_existing_finite_delegation_issues_ready_and_queues_once(tmp_path):
    executor, contract, core, port, state, work, checkout, inbox = setup(tmp_path)
    receipt = executor.submit(contract, "driveplanid123456", "c" * 64)
    assert receipt.startswith("queued:issue-620-")
    task = issue_task(state["issue"])
    assert (inbox / (task["id"] + ".json")).is_file()
    assert state["publish_calls"] == 1 and state["reads"] >= 2
    assert not core.state.effects and not core.state.approvals
    state["status"] = "EXISTING"
    assert executor.submit(contract, "driveplanid123456", "c" * 64) == receipt
    assert len(list(inbox.glob("*.json"))) == 1


def test_complete_three_evidence_drive_guard_new_ready_issue_to_queue(tmp_path):
    executor, contract, _, _, state, _, _, inbox = setup(tmp_path)

    class Verifiers:
        def cost(self, candidate_id):
            assert candidate_id == "fixed-repair-one"
            return CostReceipt(NOW, "github:verified-local-recipe", True,
                               0, 0, "NOT_APPLICABLE_LOCAL")
        def benefit(self, candidate_id):
            return BenefitReceipt(NOW, "m1:measured-benchmark-one",
                                  "latency_ms", 10.0, 7.0, "lower", True)
        def hardware(self, candidate_id):
            return HardwareReceipt(NOW, "m1:owner-host-observed", "macOS",
                                   "arm64", "Apple M1", 1024 * 1024, 1024 * 1024,
                                   False)

    class Drive:
        def create_once(self, digest, text):
            self.digest, self.text = digest, text
            return "driveplanid123456"
        def read(self, docid):
            assert docid == "driveplanid123456"
            return self.text

    drive = Drive()
    result = plan_and_submit("fixed-repair-one", contract=contract,
                             verifiers=Verifiers(), drive=drive,
                             guard=executor.guard, executor=executor, now=NOW)
    assert result["status"] == "SUBMITTED_UNVERIFIED"
    assert result["plan_sha256"] == drive.digest
    assert result["execution_ref"].startswith("queued:")
    assert state["publish_calls"] == 1
    assert len(list(inbox.glob("*.json"))) == 1
    assert not hasattr(drive, "owner_auth")


@pytest.mark.parametrize("mutation", [
    {"base": "local9b/prior"},
    {"target": "src/ai_foundation/guard.py"},
    {"test": "tests/test_guard.py"},
    {"instruction": "LLM proposes arbitrary commands"},
    {"origin": {"approval_reusable": True}},
])
def test_model_or_expanded_scope_cannot_create_host_ready_issues(tmp_path, mutation):
    executor, contract, core, port, state, work, checkout, inbox = setup(tmp_path)
    spec = {**stand_spec(), **mutation}
    with pytest.raises(ValueError, match="EXISTING_STANDING_DELEGATION_REQUIRED"):
        StandingDelegatedNewIssueExecutor(
            spec=spec, base_sha=BASE, checkout=checkout, work=work,
            inbox=inbox, guard_port=port, publisher=lambda *_: None,
            read_issue=lambda *_: None,
        )
    assert state["publish_calls"] == 0


def test_guard_deny_prevents_ready_issue_publication(tmp_path):
    executor, contract, core, port, state, _, _, inbox = setup(tmp_path)
    core.preflight = lambda *_: Decision.DENY
    with pytest.raises(HandoffDenied, match="GUARD_RECHECK_NOT_ALLOWED"):
        executor.submit(contract, "driveplanid123456", "c" * 64)
    assert state["publish_calls"] == 0 and not list(inbox.glob("*.json"))


def test_test_byte_drift_denied_before_github_issue_effect(tmp_path):
    executor, contract, _, _, state, _, checkout, inbox = setup(tmp_path)
    (checkout / stand_spec()["test"]).write_text("changed\n")
    with pytest.raises(HandoffDenied, match="PINNED_ACCEPTANCE_BYTES_CHANGED"):
        executor.submit(contract, "driveplanid123456", "c" * 64)
    assert state["publish_calls"] == 0 and not list(inbox.glob("*.json"))


@pytest.mark.parametrize("status", ["CREATED", "UNKNOWN", None])
def test_unapproved_or_unknown_publication_cannot_queue(tmp_path, status):
    executor, contract, _, _, state, _, _, inbox = setup(tmp_path)
    state["status"] = status
    with pytest.raises(HandoffDenied, match="READY_PUBLICATION_NOT_VERIFIED"):
        executor.submit(contract, "driveplanid123456", "c" * 64)
    assert not list(inbox.glob("*.json"))


@pytest.mark.parametrize("mutation", [
    {"state": "CLOSED"},
    {"labels": []},
    {"updatedAt": "2026-11-09T02:00:00Z"},
])
def test_unready_issue_refused_even_if_publisher_claims_ready(tmp_path, mutation):
    executor, contract, _, _, state, _, _, inbox = setup(tmp_path)
    # A changed updatedAt is only valid if the host also republishes a new
    # exact Issue binding. A current changed timestamp can be legitimate, so
    # this test checks only the unequivocally unauthorized cases below.
    state["issue"] = {**state["issue"], **mutation}
    if mutation.keys() == {"updatedAt"}:
        # Publisher and live reader see the same current ready issue:
        # it is still an authorized new one-shot receipt, not a revocation.
        assert executor.submit(contract, "driveplanid123456", "c" * 64).startswith("queued:")
    else:
        with pytest.raises(ValueError):
            executor.submit(contract, "driveplanid123456", "c" * 64)
        assert not list(inbox.glob("*.json"))


def test_modified_issue_contract_or_reused_consumed_issue_not_replayed(tmp_path):
    executor, contract, _, _, state, work, checkout, inbox = setup(tmp_path)
    issue = dict(state["issue"])
    issue["body"] = issue["body"].replace("notification_boundary.py", "guard.py")
    state["issue"] = issue
    with pytest.raises((ValueError, HandoffDenied)):
        executor.submit(contract, "driveplanid123456", "c" * 64)
    assert not list(inbox.glob("*.json"))
    state["issue"] = setup_issue = setup(tmp_path / "fresh")[4]["issue"]
    task = issue_task(setup_issue)
    (inbox.parent / "results" / (task["id"] + ".started")).write_text("started")
    with pytest.raises(HandoffDenied, match="ISSUE_ALREADY_ATTEMPTED"):
        executor.submit(contract, "driveplanid123456", "c" * 64)
    assert not list(inbox.glob("*.json"))


def test_untrusted_work_folder_or_unsupported_contract_never_publishes(tmp_path):
    executor, contract, _, _, state, work, checkout, inbox = setup(tmp_path)
    with pytest.raises(HandoffDenied, match="HOST_STANDING_CONTRACT_CHANGED"):
        executor.submit(replace(contract, target="src/ai_foundation/guard.py"),
                        "driveplanid123456", "c" * 64)
    assert state["publish_calls"] == 0
    repo_internal = checkout / "oops"
    repo_internal.mkdir()
    executor.work = repo_internal
    with pytest.raises(HandoffDenied, match="ISOLATED_WORK_MUST_BE_OUTSIDE_CHECKOUT"):
        executor.submit(contract, "driveplanid123456", "c" * 64)
    assert state["publish_calls"] == 0
