"""Source-only tests of existing read-only bridge -> benefit/M1 admission adapter."""
import unittest
from dataclasses import replace
from unittest.mock import Mock

from ai_foundation.development_host_evidence import (
    GIB, hardware_from_bridge, measured_benefit_from_fixed_port,
    submit_with_existing_lease,
)
from ai_foundation.development_admission import (
    CostReceipt, BenefitReceipt, HardwareReceipt, HostContract,
)
from ai_foundation.host_compute_lease import HostComputeBusy

NOW = 1794230000.0


def hardware_values():
    return {
        "snapshot": {"platform": "macOS/arm64", "checkout_free_gib": 23.0},
        "triage": {"memory": {"physical_gib": 16.0,
                              "reclaimable_estimate_gib": 8.0}},
        "runtime": {"compute_lease": {"state": "AVAILABLE_AT_PROBE"},
                    "autodev": {"state": "SCHEDULED_IDLE",
                                "uncompleted_start_count": 0,
                                "claim_without_start_or_result_count": 0}},
        "storage": {"filesystems": {
            "system": {"state": "OBSERVED", "available_gib": 30.0,
                       "read_only": False},
            "installed_worker": {"state": "OBSERVED", "available_gib": 20.0,
                                 "read_only": False},
        }},
        "chip": "Apple M1", "observed_at": NOW, "now": NOW,
    }


class BenchmarkPort:
    metric = "latency_ms"
    direction = "lower"
    test_sha256 = "a"*64
    def __init__(self, pairs=None):
        self.pairs = pairs or [(10.0, 7.0)] * 5
        self.calls = []
    def observe_pair(self, candidate_id, index):
        self.calls.append((candidate_id, index))
        return self.pairs[index]


class HardwareTest(unittest.TestCase):
    def test_observes_existing_bridge_without_claiming_full_ram(self):
        receipt = hardware_from_bridge(**hardware_values())
        self.assertEqual(receipt.device, "Apple M1")
        self.assertEqual(receipt.available_ram_bytes, 4*GIB)
        self.assertEqual(receipt.free_disk_bytes, 20*GIB)
        self.assertFalse(receipt.competing_work)
        self.assertTrue(receipt.proof.startswith("m1:hardware-"))

    def test_macos_sealed_system_volume_is_not_an_installation_blocker(self):
        data = hardware_values()
        data["storage"]["filesystems"]["system"]["read_only"] = True
        receipt = hardware_from_bridge(**data)
        self.assertIsNotNone(receipt)
        self.assertFalse(receipt.competing_work)
        data["storage"]["filesystems"]["installed_worker"]["read_only"] = True
        self.assertIsNone(hardware_from_bridge(**data))

    def test_host_is_not_m1(self):
        data = hardware_values()
        data["snapshot"]["platform"] = "Linux/x86_64"
        self.assertIsNone(hardware_from_bridge(**data))

    def test_rejects_intel_or_unknown_chip(self):
        for chip in ("Intel Core i7", "Apple M2", "", "Apple M1; rm -rf /"):
            with self.subTest(chip=chip):
                self.assertIsNone(hardware_from_bridge(**{**hardware_values(),
                                                           "chip": chip}))

    def test_stale_snapshot_denied(self):
        data = hardware_values()
        data["observed_at"] -= 31
        self.assertIsNone(hardware_from_bridge(**data))

    def test_memory_omission_denied(self):
        data = hardware_values()
        data["triage"]["memory"].pop("reclaimable_estimate_gib")
        self.assertIsNone(hardware_from_bridge(**data))

    def test_no_disk_evidence_denied(self):
        data = hardware_values()
        data["storage"]["filesystems"]["installed_worker"]["state"] = "UNAVAILABLE"
        self.assertIsNone(hardware_from_bridge(**data))

    def test_shared_lease_conflict_does_not_admit(self):
        data = hardware_values()
        data["runtime"]["compute_lease"]["state"] = "EXCLUSIVE_HELD_AT_PROBE"
        receipt = hardware_from_bridge(**data)
        self.assertTrue(receipt.competing_work)

    def test_owned_lease_context_allows_self_only(self):
        data = hardware_values()
        data["runtime"]["compute_lease"]["state"] = "EXCLUSIVE_HELD_AT_PROBE"
        data["runtime"]["autodev"]["state"] = "RUNNING"
        receipt = hardware_from_bridge(**{**data, "owned_lease": True})
        self.assertFalse(receipt.competing_work)

    def test_claimed_work_denies_idle_claim(self):
        data = hardware_values()
        data["runtime"]["autodev"]["claim_without_start_or_result_count"] = 1
        receipt = hardware_from_bridge(**data)
        self.assertTrue(receipt.competing_work)

    def test_bad_physical_memory_denied(self):
        data = hardware_values()
        data["triage"]["memory"]["physical_gib"] = 0
        self.assertIsNone(hardware_from_bridge(**data))


class MeasuredEffectTest(unittest.TestCase):
    def test_five_host_selected_fixed_pairs(self):
        port = BenchmarkPort()
        receipt = measured_benefit_from_fixed_port(
            "candidate-1", port=port, clock=lambda: NOW)
        self.assertTrue(receipt.independently_measured)
        self.assertEqual((receipt.baseline, receipt.observed), (10.0, 7.0))
        self.assertEqual(port.calls,
                         [("candidate-1", index) for index in range(5)])
        self.assertTrue(receipt.proof.startswith("m1:fixed-benchmark-"))

    def test_noisy_benchmark_rejected(self):
        port = BenchmarkPort([(10, 7), (10, 7), (10, 7), (100, 7), (10, 7)])
        self.assertIsNone(measured_benefit_from_fixed_port("candidate-1", port=port))

    def test_nan_benchmark_rejected(self):
        port = BenchmarkPort([(10, 7)] * 4 + [(10, float("nan"))])
        self.assertIsNone(measured_benefit_from_fixed_port("candidate-1", port=port))

    def test_untrusted_benchmark_contract_denied_before_calls(self):
        port = BenchmarkPort()
        port.test_sha256 = "un-pinned"
        self.assertIsNone(measured_benefit_from_fixed_port("candidate-1", port=port))
        self.assertEqual(port.calls, [])

    def test_benchmark_id_restricted(self):
        port = BenchmarkPort()
        self.assertIsNone(measured_benefit_from_fixed_port("../model", port=port))
        self.assertEqual(port.calls, [])


class LeaseTest(unittest.TestCase):
    def test_lease_covers_drive_and_execution(self):
        events = []
        class Lease:
            def hold(self, max_wait_s=0):
                self_case = self
                self_case.within = False
                class Ctx:
                    def __enter__(self):
                        events.append("lease_enter")
                        self_case.within = True
                    def __exit__(self, *_):
                        self_case.within = False
                        events.append("lease_exit")
                return Ctx()
        class Verifiers:
            def cost(self, _): return CostReceipt(NOW, "m1:local-license-1", True, 0, 0, "NOT_APPLICABLE_LOCAL")
            def benefit(self, _): return BenefitReceipt(NOW, "m1:measured-proof", "latency_ms", 10, 7, "lower", True)
            def hardware(self, _): return HardwareReceipt(NOW, "m1:hardware-proof", "macOS", "arm64", "Apple M1",
                                                           4*GIB, 20*GIB, False)
        class Drive:
            def create_once(self, digest, text):
                self.body = text
                events.append("drive_create")
                return "driveplanid1234"
            def read(self, _): return self.body
        class Guard:
            def authorize(self, contract, plan_id, digest):
                events.append("guard")
                return "ALLOW"
        class Executor:
            def submit(self, contract, plan_id, digest):
                events.append("submit")
                return "draft:1"
        contract = HostContract("draft_code", "src/ai_foundation/task_result.py",
                                "a"*64, GIB, GIB, 0.1, "development:fixed-test")
        status = submit_with_existing_lease(Lease(), "candidate-1",
                                            contract=contract, verifiers=Verifiers(),
                                            drive=Drive(), guard=Guard(), executor=Executor(),
                                            now=NOW)
        self.assertEqual(status["status"], "SUBMITTED_UNVERIFIED")
        self.assertEqual(events[0], "lease_enter")
        self.assertEqual(events[-1], "lease_exit")
        self.assertLess(events.index("guard"), events.index("submit"))

    def test_busy_lease_never_starts_model_or_drive(self):
        class Lease:
            def hold(self, max_wait_s=0):
                raise HostComputeBusy("BUSY")
        response = submit_with_existing_lease(
            Lease(), "candidate", contract=None, verifiers=None,
            drive=None, guard=None, executor=None)
        self.assertEqual(response, {"status": "DEFERRED",
                                    "reason": "HOST_COMPUTE_LEASE_BUSY"})


if __name__ == "__main__":
    unittest.main()
