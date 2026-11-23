"""One actual host-composition path; fake external effects, real canonical ports.

No model/network calls; uses the production offline cost verifier, five-pair
benchmark conversion, shared lease, GuardCore, ready-Issue identity, and
existing queue writer with a private synthetic owner tree.
"""
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ai_foundation.core import CanonContract, GuardState
from ai_foundation.development_admission import HostContract, HardwareReceipt, evaluate
from ai_foundation.development_guard_admission import GuardAdmissionPort
from ai_foundation.development_offline_cost import AuditedOfflinePackage, OfflineObservation, cost_from_pinned_offline_source
from ai_foundation.development_host_evidence import measured_benefit_from_fixed_port
from ai_foundation.guard import GuardCore
from ai_foundation.host_compute_lease import HostComputeLease
from local9b_admission_handoff import ApprovedIssueBinding, ExistingApprovedIssueExecutor, _digest
from local9b_issue_bridge import READY_LABEL, issue_task
from m1_owner_candidate_admission import (
    admit_trusted_owner_candidate, admit_source_reviewed_owner_candidate,
)

CANDIDATE = "fixed-m1-repair"
BASE = "a" * 40
TEST = "b" * 64
TARGET = "src/ai_foundation/task_result.py"
LICENSE = b"MIT License\n\nCopyright (c) 2026. Permission is hereby granted, free of charge, to any person obtaining a copy."


class FixedBenchmark:
    metric = "pass_count"
    direction = "higher"
    test_sha256 = TEST
    def __init__(self, *, noisy=False):
        self.calls = []
        self.noisy = noisy
    def observe_pair(self, candidate, index):
        self.calls.append((candidate, index))
        if self.noisy and index == 4:
            return (10, 100)
        return (10, 12)


class FakeDrive:
    def __init__(self):
        self.entries = {}
        self.writes = 0
    def create_once(self, digest, content):
        if digest not in self.entries:
            self.writes += 1
            self.entries[digest] = content
        return "driveplanid123456"
    def read(self, doc_id):
        assert doc_id == "driveplanid123456"
        assert len(self.entries) == 1
        return next(iter(self.entries.values()))


def fixture(tmp_path):
    now = time.time()
    package = AuditedOfflinePackage(
        CANDIDATE, "https://github.com/quest7070-dev/AI-Foundation",
        "c" * 40, "MIT", sha256(LICENSE).hexdigest(),
        False, False, False,
    )
    observation = OfflineObservation(
        now, package.pinned_commit, LICENSE, False, False, False, True, True,
    )
    contract = HostContract(
        "draft_code", TARGET, TEST, 1024, 1024, 0.1,
        "development:fixed-test",
    )
    guard = GuardAdmissionPort(
        GuardCore(GuardState()), CanonContract("code", "code-v1"),
        delegated_contracts=frozenset({contract}),
    )
    issue_number = 777
    spec = {
        "recipe": "python-fixed-test", "base": "main",
        "base_sha": BASE, "target": TARGET,
        "test": "tests/test_task_result.py", "test_sha256": TEST,
        "instruction": (
            "Repair the independently reproduced failure in tests/test_task_result.py "
            "by changing only src/ai_foundation/task_result.py. "
            "Preserve other behavior and all public APIs; do not change tests."
        ),
    }
    issue = {
        "number": issue_number, "state": "OPEN",
        "labels": [{"name": READY_LABEL}],
        "updatedAt": "2026-11-09T00:00:00Z",
        "body": "Host-authorized fixed task\n\n```foundation-autodev-task\n"
                + json.dumps(spec, sort_keys=True) + "\n```",
    }
    task = issue_task(issue)
    binding = ApprovedIssueBinding(
        issue_number, task["id"], _digest(task), BASE, TARGET, TEST,
    )
    inbox = tmp_path / "worker" / "inbox"
    inbox.mkdir(parents=True)
    (inbox.parent / "results").mkdir()
    executor = ExistingApprovedIssueExecutor(
        binding=binding, inbox=inbox, guard_port=guard,
        read_issue=lambda _: issue,
    )
    lock = tmp_path / "compute" / "compute.lock"
    lease = HostComputeLease(lock)
    drive = FakeDrive()
    calls = {"probe": 0, "hw": 0, "text_factory": 0}
    def text_factory():
        calls["text_factory"] += 1
        def probe():
            calls["probe"] += 1
        return SimpleNamespace(probe=probe), drive
    def hardware(*, lease_fd):
        calls["hw"] += 1
        return HardwareReceipt(time.time(), "m1:hardware-observed",
                               "macOS", "arm64", "Apple M1",
                               2 * 1024**3, 8 * 1024**3, False)
    return SimpleNamespace(
        catalogue={CANDIDATE: package}, observation=observation,
        contract=contract, guard_port=guard, executor=executor,
        lease=lease, drive=drive, calls=calls, inbox=inbox, task=task,
        hardware=hardware, text_factory=text_factory,
    )


def run(f, benchmark=None, **overrides):
    kw = dict(
        catalogue=f.catalogue, observation=f.observation,
        benchmark_port=benchmark or FixedBenchmark(),
        contract=f.contract, guard_port=f.guard_port,
        executor=f.executor, lease=f.lease,
    )
    kw.update(overrides)
    with patch("m1_owner_candidate_admission.observe_m1_hardware", f.hardware), \
         patch("m1_owner_candidate_admission.text_port", f.text_factory):
        return admit_trusted_owner_candidate(CANDIDATE, **kw)



def test_independent_three_evidence_preflight_is_admitted(tmp_path):
    f = fixture(tmp_path)
    cost = cost_from_pinned_offline_source(
        CANDIDATE, catalogue=f.catalogue, observed=f.observation)
    assert cost is not None, "cost host receipt absent"
    benefit = measured_benefit_from_fixed_port(
        CANDIDATE, port=FixedBenchmark())
    assert benefit is not None, "five-pair benchmark receipt absent"
    hardware = f.hardware(lease_fd=0)
    decision = evaluate(CANDIDATE, f.contract, cost, benefit, hardware)
    assert decision == "ADMITTED", {"decision": decision, "cost": cost is not None,
                                    "benefit": benefit is not None}


def test_one_real_port_chain_three_receipts_drive_guard_queue(tmp_path):
    f = fixture(tmp_path)
    bench = FixedBenchmark()
    result = run(f, bench)
    assert result["status"] == "SUBMITTED_UNVERIFIED", result
    assert result["execution_ref"].startswith("queued:issue-777-")
    assert (f.inbox / (f.task["id"] + ".json")).is_file()
    assert f.drive.writes == 1
    assert f.calls["probe"] == 1
    assert f.calls["hw"] >= 3
    assert bench.calls == [(CANDIDATE, x) for x in range(5)]
    assert not f.guard_port.guard.state.effects
    assert not f.guard_port.guard.state.approvals


def test_unknown_manifest_is_hold_before_lease_or_drive(tmp_path):
    f = fixture(tmp_path)
    result = run(f, catalogue={})
    assert result["reason"] == "TRUSTED_OWNER_CONTRACT_REQUIRED"
    assert f.calls["hw"] == f.calls["text_factory"] == 0


def test_paid_or_unverified_source_is_hold_before_benchmark(tmp_path):
    f = fixture(tmp_path)
    bad = OfflineObservation(
        f.observation.checked_at, f.observation.observed_commit,
        f.observation.license_bytes, False, False, False,
        False, True,
    )
    bench = FixedBenchmark()
    result = run(f, bench, observation=bad)
    assert result["reason"] == "COST_NOT_VERIFIED"
    assert bench.calls == []
    assert f.calls["text_factory"] == 0


def test_noisy_or_unmeasured_gain_never_opens_drive(tmp_path):
    f = fixture(tmp_path)
    result = run(f, FixedBenchmark(noisy=True))
    assert result["reason"] == "BENEFIT_NOT_VERIFIED"
    assert f.calls["text_factory"] == 0


def test_busy_shared_lease_defers_without_opening_drive(tmp_path):
    f = fixture(tmp_path)
    with f.lease.hold(max_wait_s=0):
        result = run(f)
    assert result == {"status": "DEFERRED", "reason": "HOST_COMPUTE_LEASE_BUSY"}
    assert f.calls["text_factory"] == f.calls["hw"] == 0


def test_owner_drive_unavailable_never_calls_guard_or_queue(tmp_path):
    f = fixture(tmp_path)
    def not_available():
        raise PermissionError("no owner grant")
    f.text_factory = not_available
    result = run(f)
    assert result["reason"] == "OWNER_DRIVE_UNAVAILABLE"
    assert not list(f.inbox.glob("*.json"))


def test_reject_forged_guard_and_wrong_executor_identity(tmp_path):
    f = fixture(tmp_path)
    result = run(f, guard_port=SimpleNamespace(allowed={f.contract}))
    assert result["reason"] == "TRUSTED_OWNER_CONTRACT_REQUIRED"
    result = run(f, executor=SimpleNamespace(submit=lambda *_: "fake"))
    assert result["reason"] == "TRUSTED_OWNER_CONTRACT_REQUIRED"
    assert f.calls["text_factory"] == 0


def test_source_reviewed_registry_requires_host_ports_before_any_effect(tmp_path):
    f = fixture(tmp_path)
    # Source only, without a real M1 binary or benchmark, must never be
    # mistaken for permission to create Drive plans or ready 9B Issues.
    result = admit_source_reviewed_owner_candidate(
        "ripgrep-14.1.1", observation=None, benchmark_port=FixedBenchmark(),
        contract=f.contract, guard_port=f.guard_port, executor=f.executor,
        lease=f.lease,
    )
    assert result == {"status": "HOLD", "reason": "OFFLINE_SOURCE_UNVERIFIED"}
    assert f.calls["hw"] == f.calls["text_factory"] == 0
    assert not list(f.inbox.glob("*.json"))


def test_unreviewed_id_does_not_share_other_candidate_evidence(tmp_path):
    f = fixture(tmp_path)
    result = admit_source_reviewed_owner_candidate(
        "random-free-api-model", observation=f.observation,
        benchmark_port=FixedBenchmark(), contract=f.contract,
        guard_port=f.guard_port, executor=f.executor, lease=f.lease,
    )
    assert result == {"status": "HOLD", "reason": "TRUSTED_OWNER_CONTRACT_REQUIRED"}
    assert f.calls["text_factory"] == 0
    assert not list(f.inbox.glob("*.json"))
