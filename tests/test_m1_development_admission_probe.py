"""Read-only bridge + actual host-lease admission evidence tests (no model)."""
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from ai_foundation.development_admission import (
    BenefitReceipt, CostReceipt, HostContract, evaluate,
)
from ai_foundation.host_compute_lease import HostComputeLease
from scripts.m1_development_admission_probe import (
    CHIP_COMMAND, HardwareEvidenceUnavailable, observe_m1_hardware,
)


class FixedM1:
    def __init__(self):
        self.require_calls = 0
        self.reads = []
        self.platform = "macOS/arm64"
        self.chip = "Apple M1"
        self.available = 4.5
        self.disk = 20.0
        self.raw = None
        self.worker_state = "SCHEDULED_IDLE"

    def require_m1(self):
        self.require_calls += 1

    def snapshot(self):
        self.reads.append("snapshot")
        return {"platform": self.platform, "checkout_free_gib": self.disk,
                "secret_local_path": "/PRIVATE/owner/model"}

    def triage(self):
        self.reads.append("triage")
        return {"memory": {"physical_gib": 16.0,
                           "reclaimable_estimate_gib": self.available},
                "secret_private_argv": "NEVER_EXPORT"}

    def _fixed_command(self, argv):
        self.reads.append(tuple(argv))
        assert argv == list(CHIP_COMMAND)
        return self.raw if self.raw is not None else json.dumps({
            "SPHardwareDataType": [{"chip_type": self.chip}]
        })

    def runtime_status(self, *, now):
        self.reads.append("runtime")
        return {"compute_lease": {"state": "EXCLUSIVE_HELD_AT_PROBE"},
                "autodev": {"state": self.worker_state,
                            "uncompleted_start_count": 0,
                            "claim_without_start_or_result_count": 0}}

    def storage_status(self, *, now):
        self.reads.append("storage")
        return {"filesystems": {
            "installed_worker": {"state": "OBSERVED", "available_gib": self.disk,
                                 "read_only": False},
            "system": {"state": "OBSERVED", "available_gib": 22.0,
                       "read_only": True},
        }}


def _lease(tmp_path):
    return HostComputeLease(tmp_path / "owner-private" / "compute.lock")


def test_actual_borrowed_lease_and_existing_fixed_m1_probes_make_receipt(tmp_path):
    lease = _lease(tmp_path)
    bridge = FixedM1()
    with lease.hold(max_wait_s=0) as fd:
        receipt = observe_m1_hardware(
            lease_fd=fd, lock_path=lease.path, host_bridge=bridge, host_runtime=bridge,
            now=1800000000.0)
        assert receipt.checked_at == 1800000000.0
        assert receipt.proof.startswith("m1:hardware-")
        assert receipt.os_name == "macOS" and receipt.arch == "arm64"
        assert receipt.device == "Apple M1" and not receipt.competing_work
        assert 2 * (1024**3) < receipt.available_ram_bytes < 2.5 * (1024**3)
        assert 19 * (1024**3) < receipt.free_disk_bytes <= 20 * (1024**3)
        assert bridge.reads == ["snapshot", "triage", CHIP_COMMAND, "runtime", "storage"]
        contract = HostContract("draft_code", "src/ai_foundation/task_result.py",
                                "a" * 64, 2 * (1024**3), 1 * (1024**3),
                                0.1, "development:fixed-test")
        cost = CostReceipt(1800000000.0, "github:local-free-terms", True,
                           0, 0, "NOT_APPLICABLE_LOCAL")
        benefit = BenefitReceipt(1800000000.0, "m1:fixed-benchmark-abc",
                                 "latency_ms", 10.0, 8.0, "lower", True)
        assert evaluate("local-free-candidate", contract, cost, benefit,
                        receipt, now=1800000000.0) == "ADMITTED"
    assert bridge.require_calls == 1
    assert "/PRIVATE" not in str(receipt)
    assert "NEVER_EXPORT" not in str(receipt)


def test_wrong_or_missing_actual_lease_is_rejected_before_ever_probing_m1(tmp_path):
    lease = _lease(tmp_path)
    other = _lease(tmp_path / "different")
    bridge = FixedM1()
    with lease.hold() as fd:
        with pytest.raises(HardwareEvidenceUnavailable, match="LEASE_UNVERIFIED"):
            observe_m1_hardware(lease_fd=fd, lock_path=other.path,
                                host_bridge=bridge, host_runtime=bridge)
        with pytest.raises(HardwareEvidenceUnavailable, match="LEASE_REQUIRED"):
            observe_m1_hardware(lease_fd="model-asserts-lease",
                                lock_path=lease.path, host_bridge=bridge, host_runtime=bridge)
    assert bridge.reads == [] and bridge.require_calls == 0


def test_competing_compute_owner_blocks_probe_without_model_or_host_probe(tmp_path):
    lease = _lease(tmp_path)
    bridge = FixedM1()
    with lease.hold():
        fd = os.open(lease.path, os.O_RDONLY)
        try:
            with pytest.raises(HardwareEvidenceUnavailable, match="LEASE_UNVERIFIED"):
                observe_m1_hardware(lease_fd=fd, lock_path=lease.path,
                                    host_bridge=bridge, host_runtime=bridge)
        finally:
            os.close(fd)
    assert bridge.reads == []


@pytest.mark.parametrize("field,value", [
    ("platform", "Linux/arm64"),
    ("platform", "macOS/x86_64"),
    ("chip", "Apple M2"),
    ("chip", "Apple M10"),
    ("chip", "Intel Core i7"),
    ("available", -1.0),
    ("available", float("nan")),
    ("available", None),
    ("disk", None),
    ("disk", -1.0),
    ("raw", "{}"),
])
def test_missing_or_incompatible_host_facts_hold_even_under_valid_lease(
        tmp_path, field, value):
    lease = _lease(tmp_path)
    bridge = FixedM1()
    setattr(bridge, field, value)
    with lease.hold() as fd:
        with pytest.raises(HardwareEvidenceUnavailable):
            observe_m1_hardware(lease_fd=fd, lock_path=lease.path,
                                host_bridge=bridge, host_runtime=bridge, now=1800000000.0)


def test_stale_readonly_receipt_does_not_allow_host_trial(tmp_path):
    lease = _lease(tmp_path)
    bridge = FixedM1()
    with lease.hold() as fd:
        evidence = observe_m1_hardware(
            lease_fd=fd, lock_path=lease.path, host_bridge=bridge, host_runtime=bridge,
            now=1800000000.0)
    contract = HostContract("isolated_trial",
                            "src/ai_foundation/task_result.py", "a" * 64,
                            1024, 1024, 0.1, "development:fixed-test")
    cost = CostReceipt(1800000000.0, "github:local-free-terms", True, 0, 0,
                       "NOT_APPLICABLE_LOCAL")
    benefit = BenefitReceipt(1800000000.0, "m1:measured-baseline-proof",
                             "latency_ms", 10.0, 7.0, "lower", True)
    assert evaluate("local-free-candidate", contract, cost, benefit,
                    evidence, now=1800000301.0) == "M1_FIT_NOT_VERIFIED"


def test_bridge_runtime_competing_work_does_not_produce_approvable_receipt(tmp_path):
    lease = _lease(tmp_path)
    bridge = FixedM1()
    bridge.worker_state = "UNKNOWN"
    with lease.hold() as fd:
        with pytest.raises(HardwareEvidenceUnavailable, match="M1_HOST_FACTS_UNAVAILABLE"):
            observe_m1_hardware(lease_fd=fd, lock_path=lease.path,
                                host_bridge=bridge, host_runtime=bridge,
                                now=1800000000.0)
