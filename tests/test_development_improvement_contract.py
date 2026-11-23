"""Positive OSS gain is a proposal, never a fabricated regression Issue."""
from dataclasses import replace
from hashlib import sha256
import json
import time

from ai_foundation.development_admission import (
    CostReceipt, BenefitReceipt, HardwareReceipt, HostContract, _plan,
)
from ai_foundation.development_improvement_contract import (
    HostImprovementScope, prepare_nonrunnable_improvement,
)


class DriveReadback:
    def __init__(self, contents):
        self.contents = contents
        self.reads = 0

    def read(self, plan_id):
        assert plan_id == "verifieddriveplan123"
        self.reads += 1
        return self.contents


def setup():
    now = time.time()
    source_test_sha = sha256(b"reviewed positive feature acceptance test").hexdigest()
    contract = HostContract(
        effect="draft_code", target="src/ai_foundation/task_result.py",
        test_sha256=source_test_sha, required_ram_bytes=1024,
        required_disk_bytes=1024, minimum_relative_gain=0.1,
        guard_scope="development:fixed-test",
    )
    scope = HostImprovementScope(
        "ripgrep-14.1.1", "local9b/oss-search-improvement-reviewed",
        "a" * 40, contract.target, "tests/test_task_result.py",
        source_test_sha,
    )
    cost = CostReceipt(
        now, "https://github.com/BurntSushi/ripgrep/commit/" +
        "4649aa9700619f94cf9c66876e9549d83420e16c",
        True, 0, 0, "NOT_APPLICABLE_LOCAL",
    )
    benefit = BenefitReceipt(now, "m1:independent-five-pair-benchmark",
                             "latency_ms", 10.0, 8.0, "lower", True)
    hardware = HardwareReceipt(now, "m1:owner-held-lease", "macOS",
                               "arm64", "Apple M1", 2**30, 2**30, False)
    body = json.dumps(_plan(scope.candidate_id, contract, cost, benefit, hardware),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"scope": scope, "contract": contract,
            "cost": cost, "benefit": benefit, "hardware": hardware,
            "plan_id": "verifieddriveplan123",
            "plan_digest": sha256(body.encode()).hexdigest(),
            "drive": DriveReadback(body),
            "source_test_sha256": source_test_sha, "now": now}


def test_reviewed_positive_improvement_is_nonrunnable():
    kw = setup()
    result = prepare_nonrunnable_improvement(**kw)
    assert result["status"] == "REVIEW_REQUIRED"
    assert result["ready_label"] is False
    assert result["queue_writes"] == 0
    assert result["model_calls"] == result["issue_writes"] == 0
    assert "foundation-autodev-task" not in result["proposal"]
    doc = json.loads(result["proposal"])
    assert doc["schema"] == "foundation-improvement-proposal/v1"
    assert doc["candidate_id"] == "ripgrep-14.1.1"
    assert doc["base_branch"].startswith("local9b/")
    assert doc["drive_plan_sha256"] == kw["plan_digest"]
    assert result["proposal_sha256"] == sha256(
        result["proposal"].encode()).hexdigest()
    assert kw["drive"].reads == 1


def test_main_branch_cannot_be_passed_as_preapproved_positive_improvement():
    kw = setup()
    kw["scope"] = replace(kw["scope"], base_branch="main")
    assert prepare_nonrunnable_improvement(**kw) == {
        "status": "HOLD", "reason": "IMPROVEMENT_SCOPE_NOT_REVIEWED",
    }
    assert kw["drive"].reads == 0


def test_no_unknown_oss_or_changed_target_is_predelegated():
    kw = setup()
    for scope in (
        replace(kw["scope"], candidate_id="unlisted-external-free-ai"),
        replace(kw["scope"], target="src/ai_foundation/guard.py"),
        replace(kw["scope"], base_branch="local9b/../unsafe"),
        replace(kw["scope"], acceptance_test="../private/test.py"),
    ):
        kw["scope"] = scope
        assert prepare_nonrunnable_improvement(**kw)["reason"] == (
            "IMPROVEMENT_SCOPE_NOT_REVIEWED"
        )
    assert kw["drive"].reads == 0


def test_unpinned_test_or_drive_id_does_not_read_owner_drive():
    kw = setup()
    for change in (
        {"source_test_sha256": "f" * 64},
        {"plan_id": "../secret"},
        {"plan_digest": "0" * 63},
    ):
        value = {**kw, **change}
        assert prepare_nonrunnable_improvement(**value)["status"] == "HOLD"
    assert kw["drive"].reads == 0


def test_missing_or_insufficient_independent_benchmark_has_no_proposal():
    kw = setup()
    for benefit in (
        replace(kw["benefit"], independently_measured=False),
        replace(kw["benefit"], observed=9.9),
        replace(kw["benefit"], checked_at=kw["now"] - 604801),
    ):
        assert prepare_nonrunnable_improvement(
            **{**kw, "benefit": benefit})["reason"] == (
                "CURRENT_IMPROVEMENT_EVIDENCE_NOT_ADMITTED"
            )
    assert kw["drive"].reads == 0


def test_paid_candidate_or_competing_m1_is_refused():
    kw = setup()
    assert prepare_nonrunnable_improvement(
        **{**kw, "cost": replace(kw["cost"], recurring_yen=1)}
    )["status"] == "HOLD"
    assert prepare_nonrunnable_improvement(
        **{**kw, "hardware": replace(kw["hardware"], competing_work=True)}
    )["status"] == "HOLD"
    assert kw["drive"].reads == 0


def test_missing_or_modified_drive_plan_never_becomes_execution_proposal():
    kw = setup()
    kw["drive"].contents = "{}"
    result = prepare_nonrunnable_improvement(**kw)
    assert result == {"status": "HOLD", "reason": "PLAN_READBACK_MISMATCH"}
    kw = setup()
    kw["plan_digest"] = "f" * 64
    assert prepare_nonrunnable_improvement(**kw)["reason"] == (
        "PLAN_RECEIPTS_NOT_BOUND"
    )
    assert kw["drive"].reads == 0


def test_scope_cannot_borrow_unrelated_host_contract():
    kw = setup()
    kw["contract"] = replace(kw["contract"],
                              test_sha256="f" * 64)
    assert prepare_nonrunnable_improvement(**kw)["reason"] == (
        "IMPROVEMENT_SCOPE_NOT_REVIEWED"
    )
    assert kw["drive"].reads == 0


def test_unrelated_free_source_receipt_cannot_bind_to_reviewed_candidate():
    kw = setup()
    kw["cost"] = replace(
        kw["cost"],
        proof="https://github.com/other/other/commit/" + "b" * 40,
    )
    result = prepare_nonrunnable_improvement(**kw)
    assert result == {"status": "HOLD", "reason": "SOURCE_COST_IDENTITY_NOT_BOUND"}
    assert kw["drive"].reads == 0
