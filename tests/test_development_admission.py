"""Host-port contract tests: no paid call, M1 command or Drive mutation."""
import json
import unittest
from unittest import mock
from dataclasses import replace

from ai_foundation.development_admission import (
    BenefitReceipt, CostReceipt, HardwareReceipt, HostContract,
    evaluate, plan_and_submit,
)

NOW = 1_794_230_000.0


class Host:
    def __init__(self):
        self.cost_receipt = CostReceipt(NOW, "https://example.org/license", True, 0, 0,
                                        "NOT_APPLICABLE_LOCAL")
        self.benefit_receipt = BenefitReceipt(NOW, "m1:benchmark-123", "latency_ms",
                                             10.0, 7.0, "lower", True)
        self.hardware_receipt = HardwareReceipt(NOW, "m1:host-probe-123", "macOS",
                                                "arm64", "Apple M1",
                                                4_000_000_000, 20_000_000_000, False)
        self.contract = HostContract("draft_code", "src/ai_foundation/notification_boundary.py",
                                     "a"*64, 1_000_000_000, 2_000_000_000, 0.1,
                                     "development:fixed-test")
        self.docs = {}
        self.events = []
        self.guard_result = "ALLOW"
        self.exec_ref = "draft:pending-123"
        self.change_second = False
        self.mutate_on_guard = False

    def cost(self, _):
        return self.cost_receipt

    def benefit(self, _):
        return self.benefit_receipt

    def hardware(self, _):
        if self.change_second and any(x[0] == "drive_create" for x in self.events):
            return replace(self.hardware_receipt, competing_work=True)
        return self.hardware_receipt

    def create_once(self, key, text):
        self.events.append(("drive_create", key))
        self.docs["driveplanid123456"] = text
        return "driveplanid123456"

    def read(self, plan_id):
        self.events.append(("drive_read", plan_id))
        return self.docs[plan_id]

    def authorize(self, contract, plan_id, digest):
        self.events.append(("guard", plan_id))
        if self.mutate_on_guard:
            self.docs[plan_id] = "{}"
        return self.guard_result

    def submit(self, contract, plan_id, digest):
        self.events.append(("execute", plan_id))
        return self.exec_ref

    def run(self):
        return plan_and_submit(
            "sample-oss", contract=self.contract,
            verifiers=self, drive=self, guard=self, executor=self, now=NOW)


class AdmissionTest(unittest.TestCase):
    def setUp(self):
        self.h = Host()

    def test_measured_zero_cost_fit_and_exact_drive_readback(self):
        result = self.h.run()
        self.assertEqual(result["status"], "SUBMITTED_UNVERIFIED")
        self.assertEqual(result["plan_id"], "driveplanid123456")
        self.assertEqual([e[0] for e in self.h.events],
                         ["drive_create", "drive_read", "guard", "drive_read", "execute"])
        plan = json.loads(self.h.docs[result["plan_id"]])
        self.assertEqual(plan["decision"], "TRIAL_CANDIDATE_PENDING_GUARD")
        self.assertEqual(plan["status"], "PLAN_ONLY_NOT_PRODUCTION_AUTHORITY")
        self.assertNotIn("password", self.h.docs[result["plan_id"]])
        self.assertNotIn("shell", self.h.docs[result["plan_id"]])

    def test_cost_initial_fee_fails_before_drive(self):
        self.h.cost_receipt = replace(self.h.cost_receipt, initial_yen=1)
        self.assertEqual(self.h.run()["reason"], "COST_NOT_VERIFIED")
        self.assertEqual(self.h.events, [])

    def test_recurring_fee_fails(self):
        self.h.cost_receipt = replace(self.h.cost_receipt, recurring_yen=1)
        self.assertEqual(self.h.run()["reason"], "COST_NOT_VERIFIED")

    def test_unverified_automatic_billing_fails(self):
        self.h.cost_receipt = replace(self.h.cost_receipt, billing="UNKNOWN")
        self.assertEqual(self.h.run()["reason"], "COST_NOT_VERIFIED")

    def test_license_unknown_fails(self):
        self.h.cost_receipt = replace(self.h.cost_receipt, license_free=False)
        self.assertEqual(self.h.run()["reason"], "COST_NOT_VERIFIED")

    def test_stale_cost_fails(self):
        self.h.cost_receipt = replace(self.h.cost_receipt, checked_at=NOW-86401)
        self.assertEqual(self.h.run()["reason"], "COST_NOT_VERIFIED")

    def test_effect_must_be_independently_measured(self):
        self.h.benefit_receipt = replace(self.h.benefit_receipt, independently_measured=False)
        self.assertEqual(self.h.run()["reason"], "BENEFIT_NOT_VERIFIED")

    def test_small_effect_does_not_admit(self):
        self.h.benefit_receipt = replace(self.h.benefit_receipt, observed=9.9)
        self.assertEqual(self.h.run()["reason"], "BENEFIT_BELOW_THRESHOLD")

    def test_nan_effect_rejected(self):
        self.h.benefit_receipt = replace(self.h.benefit_receipt, observed=float("nan"))
        self.assertEqual(self.h.run()["reason"], "BENEFIT_NOT_VERIFIED")

    def test_fresh_m1_sample_created_after_entry_is_not_future_dated(self):
        # Simulate a clock tick during the hardware probe. The old code
        # sampled 'now' on entry, before the probe, and rejected the valid
        # new receipt as future-dated even with all other proofs admitted.
        clock = {"now": NOW}
        original = self.h.hardware

        def sampled(candidate):
            value = original(candidate)
            clock["now"] = NOW + 1
            return replace(value, checked_at=NOW + 1)

        self.h.hardware = sampled
        with mock.patch("ai_foundation.development_admission.time.time",
                        side_effect=lambda: clock["now"]):
            result = plan_and_submit(
                "sample-oss", contract=self.h.contract,
                verifiers=self.h, drive=self.h, guard=self.h,
                executor=self.h, now=None)
        self.assertEqual(result["status"], "SUBMITTED_UNVERIFIED", result)
        self.assertEqual([event[0] for event in self.h.events],
                         ["drive_create", "drive_read", "guard", "drive_read",
                          "execute"])

    def test_hardware_stale_rejected(self):
        self.h.hardware_receipt = replace(self.h.hardware_receipt, checked_at=NOW-301)
        self.assertEqual(self.h.run()["reason"], "M1_FIT_NOT_VERIFIED")

    def test_hardware_wrong_arch_rejected(self):
        self.h.hardware_receipt = replace(self.h.hardware_receipt, arch="x86_64")
        self.assertEqual(self.h.run()["reason"], "M1_FIT_NOT_VERIFIED")

    def test_hardware_disk_shortage_rejected(self):
        self.h.hardware_receipt = replace(self.h.hardware_receipt, free_disk_bytes=0)
        self.assertEqual(self.h.run()["reason"], "M1_FIT_NOT_VERIFIED")

    def test_hardware_ram_shortage_rejected(self):
        self.h.hardware_receipt = replace(self.h.hardware_receipt, available_ram_bytes=0)
        self.assertEqual(self.h.run()["reason"], "M1_FIT_NOT_VERIFIED")

    def test_competing_work_deferred(self):
        self.h.hardware_receipt = replace(self.h.hardware_receipt, competing_work=True)
        self.assertEqual(self.h.run()["reason"], "M1_FIT_NOT_VERIFIED")

    def test_privileged_guard_source_denied(self):
        self.h.contract = replace(self.h.contract, target="src/ai_foundation/guard.py")
        self.assertEqual(self.h.run()["reason"], "INVALID_HOST_CONTRACT")

    def test_traversal_target_denied(self):
        self.h.contract = replace(self.h.contract, target="../etc/passwd")
        self.assertEqual(self.h.run()["reason"], "INVALID_HOST_CONTRACT")

    def test_bad_fixed_test_hash_denied(self):
        self.h.contract = replace(self.h.contract, test_sha256="abc")
        self.assertEqual(self.h.run()["reason"], "INVALID_HOST_CONTRACT")

    def test_expanded_effect_denied(self):
        self.h.contract = replace(self.h.contract, effect="production_deploy")
        self.assertEqual(self.h.run()["reason"], "INVALID_HOST_CONTRACT")

    def test_invalid_model_candidate_id_denied(self):
        result = plan_and_submit("../../private", contract=self.h.contract,
                                 verifiers=self.h, drive=self.h, guard=self.h,
                                 executor=self.h, now=NOW)
        self.assertEqual(result["reason"], "INVALID_CANDIDATE")
        self.assertEqual(self.h.events, [])

    def test_drive_readback_mismatch_denies_execute(self):
        def changed(_):
            return "{}"
        self.h.read = changed
        self.assertEqual(self.h.run()["reason"], "DRIVE_READBACK_MISMATCH")
        self.assertFalse(any(x[0] == "guard" for x in self.h.events))

    def test_unknown_drive_write_requires_reconciliation(self):
        def fails(*_):
            raise RuntimeError("API timeout after write")
        self.h.create_once = fails
        self.assertEqual(self.h.run()["reason"], "DRIVE_PLAN_UNVERIFIED")
        self.assertFalse(any(x[0] == "execute" for x in self.h.events))

    def test_change_after_plan_denies_execution(self):
        self.h.change_second = True
        self.assertEqual(self.h.run()["reason"], "EVIDENCE_CHANGED_AFTER_PLAN")
        self.assertFalse(any(x[0] == "guard" for x in self.h.events))

    def test_exact_host_chip_family_only_no_M10_false_positive(self):
        for chip in ("Apple M1", "Apple M1 Pro", "Apple M1 Max", "Apple M1 Ultra"):
            with self.subTest(chip=chip):
                self.h = Host()
                self.h.hardware_receipt = replace(self.h.hardware_receipt, device=chip)
                self.assertEqual(self.h.run()["status"], "SUBMITTED_UNVERIFIED")
        for chip in ("Apple M10", "Apple M1 16GB", "Apple M1;sh", "Apple M2", "", None):
            with self.subTest(chip=chip):
                self.h = Host()
                self.h.hardware_receipt = replace(self.h.hardware_receipt, device=chip)
                self.assertEqual(self.h.run()["reason"], "M1_FIT_NOT_VERIFIED")
                self.assertFalse(any(e[0] == "drive_create" for e in self.h.events))

    def test_explicit_guard_wait_is_the_only_owner_handoff(self):
        self.h.guard_result = "WAITING_HUMAN"
        result = self.h.run()
        self.assertEqual(result["status"], "WAITING_HUMAN")
        self.assertEqual(result["reason"], "GUARD_NOT_AUTHORIZED")
        self.assertFalse(any(x[0] == "execute" for x in self.h.events))

    def test_explicit_guard_deny_is_not_promoted_to_owner_approval(self):
        self.h.guard_result = "DENY"
        result = self.h.run()
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["reason"], "GUARD_DENIED")
        self.assertTrue(result["plan_id"])
        self.assertFalse(any(x[0] == "execute" for x in self.h.events))

    def test_guard_local_only_never_submits_to_github_9b_boundary(self):
        self.h.guard_result = "LOCAL_ONLY"
        result = self.h.run()
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["reason"], "GUARD_LOCAL_ONLY")
        self.assertFalse(any(x[0] == "execute" for x in self.h.events))

    def test_unknown_guard_response_is_not_approval_or_human_request(self):
        for value in (None, True, 1, "", "SCHEDULED", "WAITING_OWNER", {"decision":"ALLOW"}):
            with self.subTest(value=value):
                self.h = Host()
                self.h.guard_result = value
                result = self.h.run()
                self.assertEqual(result["status"], "HOLD")
                self.assertEqual(result["reason"], "GUARD_RESULT_UNVERIFIED")
                self.assertFalse(any(x[0] == "execute" for x in self.h.events))

    def test_drive_mutation_after_guard_denies_execution(self):
        self.h.mutate_on_guard = True
        self.assertEqual(self.h.run()["reason"], "PLAN_CHANGED_BEFORE_EXECUTION")
        self.assertFalse(any(x[0] == "execute" for x in self.h.events))

    def test_execution_result_is_not_claimed_as_accepted(self):
        self.h.exec_ref = "draft:submitted"
        self.assertEqual(self.h.run()["status"], "SUBMITTED_UNVERIFIED")

    def test_empty_execution_result_denied(self):
        self.h.exec_ref = ""
        self.assertEqual(self.h.run()["reason"], "EXECUTION_RECEIPT_UNVERIFIED")



    def test_initial_host_verifier_exception_is_hold_not_scheduler_retry(self):
        def unavailable(_candidate):
            raise RuntimeError("PRIVATE_BILLING_ERROR")
        self.h.cost = unavailable
        result = self.h.run()
        self.assertEqual(result, {"status": "HOLD",
                                  "reason": "HOST_EVIDENCE_UNAVAILABLE"})
        self.assertEqual(self.h.events, [])
        self.assertNotIn("PRIVATE", repr(result))

    def test_post_drive_verifier_failure_is_hold_and_never_guard_or_execute(self):
        original = self.h.hardware
        def unavailable_after_write(candidate):
            if any(row[0] == "drive_create" for row in self.h.events):
                raise ConnectionError("PRIVATE_HOST_PATH")
            return original(candidate)
        self.h.hardware = unavailable_after_write
        result = self.h.run()
        self.assertEqual(result["reason"], "HOST_EVIDENCE_RECHECK_UNAVAILABLE")
        self.assertTrue(result["plan_id"])
        self.assertFalse(any(row[0] in ("guard", "execute") for row in self.h.events))

    def test_guard_exception_has_explicit_uncertain_outcome_and_no_execution(self):
        def uncertain(_contract, plan_id, plan_digest):
            self.assertEqual(len(plan_digest), 64)
            self.h.events.append(("guard", plan_id))
            raise TimeoutError("GUARD_COMMIT_UNKNOWN")
        self.h.authorize = uncertain
        result = self.h.run()
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["reason"], "GUARD_OUTCOME_UNCERTAIN")
        self.assertIs(result["reconciliation_required"], True)
        self.assertFalse(any(row[0] == "execute" for row in self.h.events))

    def test_final_drive_read_exception_denies_executor_submission(self):
        original = self.h.read
        calls = []
        def uncertain(plan_id):
            calls.append(plan_id)
            if len(calls) == 2:
                raise TimeoutError("GOOGLE_STALE")
            return original(plan_id)
        self.h.read = uncertain
        result = self.h.run()
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["reason"], "PLAN_READBACK_UNAVAILABLE")
        self.assertFalse(any(row[0] == "execute" for row in self.h.events))

    def test_executor_timeout_after_submission_is_uncertain_not_failed_or_replayed(self):
        def lost_ack(_contract, plan_id, plan_digest):
            self.h.events.append(("execute", plan_id))
            raise TimeoutError("DRAFT_CREATED_ACK_LOST")
        self.h.submit = lost_ack
        result = self.h.run()
        self.assertEqual(result["status"], "HOLD")
        self.assertEqual(result["reason"], "EXECUTION_OUTCOME_UNCERTAIN")
        self.assertIs(result["reconciliation_required"], True)
        self.assertEqual(sum(row[0] == "execute" for row in self.h.events), 1)

    def test_missing_executor_receipt_requires_reconciliation(self):
        self.h.exec_ref = ""
        result = self.h.run()
        self.assertEqual(result["reason"], "EXECUTION_RECEIPT_UNVERIFIED")
        self.assertIs(result["reconciliation_required"], True)


    def test_new_valid_hardware_sample_after_drive_is_not_false_drift(self):
        original = self.h.hardware
        def fresh(identifier):
            receipt = original(identifier)
            if any(x[0] == "drive_create" for x in self.h.events):
                return replace(receipt, checked_at=receipt.checked_at - 1,
                               available_ram_bytes=receipt.available_ram_bytes + 1,
                               proof="m1:new-hardware-recheck")
            return receipt
        self.h.hardware = fresh
        self.assertEqual(self.h.run()["status"], "SUBMITTED_UNVERIFIED")

    def test_hardware_disappearing_after_plan_denied(self):
        original = self.h.hardware
        def lost(identifier):
            receipt = original(identifier)
            if any(x[0] == "drive_create" for x in self.h.events):
                return replace(receipt, free_disk_bytes=0)
            return receipt
        self.h.hardware = lost
        self.assertEqual(self.h.run()["reason"], "EVIDENCE_CHANGED_AFTER_PLAN")
        self.assertFalse(any(x[0] == "execute" for x in self.h.events))

if __name__ == "__main__":
    unittest.main()
