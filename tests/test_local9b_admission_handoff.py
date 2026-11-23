"""Only already-approved, immutable GitHub Issue may enter existing 9B queue."""
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from local9b_issue_bridge import READY_LABEL, issue_task, previous_issue_attempt
from local9b_admission_handoff import (
    ApprovedIssueBinding, ExistingApprovedIssueExecutor, HandoffDenied, _digest,
)

from ai_foundation.core import CanonContract, Decision, GuardState
from ai_foundation.development_admission import (
    BenefitReceipt, CostReceipt, HardwareReceipt, HostContract, plan_and_submit,
)
from ai_foundation.development_guard_admission import GuardAdmissionPort
from ai_foundation.guard import GuardCore


NOW = 1794200000.0
PLAN_ID = "driveplanid123456"
DIGEST = "d" * 64


def sample_issue():
    data = {
        "recipe": "python-fixed-test",
        "base": "main",
        "base_sha": "1" * 40,
        "target": "src/ai_foundation/task_result.py",
        "test": "tests/test_task_result.py",
        "test_sha256": "a" * 64,
        "instruction": "Return source that passes the fixed independent regression.",
    }
    return {
        "number": 502,
        "state": "OPEN",
        "updatedAt": "2026-11-09T00:00:00Z",
        "labels": [{"name": READY_LABEL}],
        "body": "Approved finite test\n```foundation-autodev-task\n"
                + json.dumps(data, sort_keys=True)
                + "\n```",
    }


def fixture(tmp_path):
    issue = sample_issue()
    task = issue_task(issue)
    binding = ApprovedIssueBinding(
        issue["number"], task["id"], _digest(task), task["base_sha"],
        task["target"], task["test_sha256"],
    )
    contract = HostContract(
        "draft_code", task["target"], task["test_sha256"], 1024, 2048,
        0.1, "development:fixed-test",
    )
    guard = GuardCore(GuardState())
    port = GuardAdmissionPort(
        guard, CanonContract("code", "code-v1"),
        delegated_contracts=frozenset({contract}),
    )
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (tmp_path / "results").mkdir()
    state = {"issue": issue, "reads": 0}
    def read(number):
        state["reads"] += 1
        assert number == 502
        return state["issue"]
    executor = ExistingApprovedIssueExecutor(
        binding=binding, inbox=inbox, guard_port=port, read_issue=read,
    )
    return issue, task, binding, contract, guard, port, inbox, state, executor


def test_existing_approved_9b_issue_queued_once_no_model_or_new_label(tmp_path):
    issue, task, binding, contract, guard, port, inbox, state, executor = fixture(tmp_path)
    receipt = executor.submit(contract, PLAN_ID, DIGEST)
    assert receipt == "queued:" + task["id"]
    expected = json.dumps(task, sort_keys=True, separators=(",", ":"))
    assert (inbox / (task["id"] + ".json")).read_text() == expected
    assert executor.submit(contract, PLAN_ID, DIGEST) == receipt
    assert len(list(inbox.glob("*.json"))) == 1
    assert state["reads"] == 2
    assert guard.state.effects == {}
    assert guard.state.approvals == set()


def test_full_development_admission_plan_to_existing_9b_queue(tmp_path):
    _, task, _, contract, guard, port, inbox, state, executor = fixture(tmp_path)
    class Verifiers:
        def cost(self, candidate_id):
            assert candidate_id == "local-safe-oss"
            return CostReceipt(NOW, "github:fixed-reviewed-license", True, 0, 0,
                               "NOT_APPLICABLE_LOCAL")
        def benefit(self, candidate_id):
            return BenefitReceipt(NOW, "m1:fixed-benchmark-evidence",
                                  "latency_ms", 10.0, 7.0, "lower", True)
        def hardware(self, candidate_id):
            return HardwareReceipt(NOW, "m1:fixed-hardware", "macOS", "arm64",
                                   "Apple M1", 1_000_000, 20_000_000, False)
    class Drive:
        def create_once(self, digest, body):
            self.body = body
            self.digest = digest
            return PLAN_ID
        def read(self, document_id):
            assert document_id == PLAN_ID
            return self.body
    d = Drive()
    result = plan_and_submit(
        "local-safe-oss", contract=contract, verifiers=Verifiers(),
        drive=d, guard=port, executor=executor, now=NOW,
    )
    assert result["status"] == "SUBMITTED_UNVERIFIED"
    assert result["execution_ref"] == "queued:" + task["id"]
    assert result["plan_sha256"] == d.digest
    assert len(list(inbox.glob("*.json"))) == 1
    # No direct 9B launch, main merge or Guard effect.
    assert not guard.state.effects


@pytest.mark.parametrize("change", [
    {"state": "CLOSED"},
    {"updatedAt": "2026-11-09T00:01:00Z"},
    {"labels": []},
    {"body": "unreviewed prose"},
])
def test_changed_or_unready_issue_cannot_queue(tmp_path, change):
    _, _, _, contract, _, _, inbox, state, executor = fixture(tmp_path)
    state["issue"] = dict(state["issue"], **change)
    with pytest.raises((ValueError, HandoffDenied)):
        executor.submit(contract, PLAN_ID, DIGEST)
    assert not list((tmp_path / "inbox").glob("*.json"))


def test_guard_rejected_or_contract_changed_never_reaches_issue_source(tmp_path):
    _, task, _, contract, guard, _, inbox, state, executor = fixture(tmp_path)
    guard.preflight = lambda *_: Decision.DENY
    with pytest.raises(HandoffDenied, match="GUARD_RECHECK_NOT_ALLOWED"):
        executor.submit(contract, PLAN_ID, DIGEST)
    assert state["reads"] == 0
    with pytest.raises(HandoffDenied, match="HOST_PINNED_EXECUTION_CONTRACT_REQUIRED"):
        executor.submit(replace(contract, target="src/ai_foundation/other.py"),
                        PLAN_ID, DIGEST)
    assert state["reads"] == 0 and not list(inbox.glob("*.json"))


@pytest.mark.parametrize("receipt", [".started", ".json"])
def test_consumed_or_uncertain_existing_issue_never_requeues(tmp_path, receipt):
    _, task, binding, contract, _, _, inbox, _, executor = fixture(tmp_path)
    (tmp_path / "results" / (task["id"] + receipt)).write_text("attempted")
    with pytest.raises(HandoffDenied, match="ISSUE_ALREADY_ATTEMPTED"):
        executor.submit(contract, PLAN_ID, DIGEST)
    assert not list(inbox.glob("*.json"))


def test_modified_existing_queue_file_is_not_replaced(tmp_path):
    _, task, _, contract, _, _, inbox, _, executor = fixture(tmp_path)
    current = inbox / (task["id"] + ".json")
    current.write_text("tampered")
    with pytest.raises(HandoffDenied, match="QUEUE_CONTENT_CONFLICT"):
        executor.submit(contract, PLAN_ID, DIGEST)
    assert current.read_text() == "tampered"


def test_symlink_queue_is_never_followed(tmp_path):
    _, task, _, contract, _, _, inbox, _, executor = fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.write_text("PRIVATE")
    (inbox / (task["id"] + ".json")).symlink_to(outside)
    with pytest.raises(HandoffDenied, match="UNTRUSTED_QUEUED_TASK"):
        executor.submit(contract, PLAN_ID, DIGEST)
    assert outside.read_text() == "PRIVATE"


def test_issue_revision_or_test_pin_change_needs_new_host_delegation(tmp_path):
    issue, task, binding, contract, guard, port, inbox, state, _ = fixture(tmp_path)
    bad = replace(binding, test_sha256="b" * 64)
    executor = ExistingApprovedIssueExecutor(
        binding=bad, inbox=inbox, guard_port=port, read_issue=lambda _: issue)
    with pytest.raises(HandoffDenied, match="HOST_PINNED_EXECUTION_CONTRACT_REQUIRED"):
        executor.submit(contract, PLAN_ID, DIGEST)
    changed = dict(issue)
    changed["body"] += "\nA new paragraph after owner approval"
    executor = ExistingApprovedIssueExecutor(
        binding=binding, inbox=inbox, guard_port=port, read_issue=lambda _: changed)
    with pytest.raises(HandoffDenied, match="APPROVED_ISSUE_CONTRACT_CHANGED"):
        executor.submit(contract, PLAN_ID, DIGEST)
    assert not list(inbox.glob("*.json"))


def test_no_creation_of_worker_inbox_or_results(tmp_path):
    issue = sample_issue()
    task = issue_task(issue)
    binding = ApprovedIssueBinding(502, task["id"], _digest(task),
                                   task["base_sha"], task["target"], task["test_sha256"])
    contract = HostContract("draft_code", task["target"], task["test_sha256"],
                            1024, 2048, 0.1, "development:fixed-test")
    port = GuardAdmissionPort(
        GuardCore(GuardState()), CanonContract("code", "code-v1"),
        delegated_contracts=frozenset({contract}))
    executor = ExistingApprovedIssueExecutor(
        binding=binding, inbox=tmp_path / "missing-inbox",
        guard_port=port, read_issue=lambda _: issue)
    with pytest.raises(HandoffDenied, match="EXISTING_OWNER_WORKER_INBOX_REQUIRED"):
        executor.submit(contract, PLAN_ID, DIGEST)
    assert not (tmp_path / "missing-inbox").exists()
