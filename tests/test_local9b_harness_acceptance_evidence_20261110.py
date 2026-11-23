"""Independent host-fixed RED baseline: no Draft for empty acceptance evidence.

E2E acceptance target: src/ai_foundation/development_loop.py only.
No model, GitHub write, filesystem effect, network or Guard bypass is performed.
"""
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from ai_foundation.agent import AgentResult
from ai_foundation.development_loop import TestAcceptanceReceipt, run_development_loop
from ai_foundation.coding_adapter import PytestPort


class InMemoryTools:
    def __init__(self):
        self.source = "VALUE = 1\n"
        self.write_capability = SimpleNamespace(authorize_target=lambda target: target)
        self.read_capability = SimpleNamespace(authorize_target=lambda target: target)

    def read(self, target):
        return self.source

    def write(self, target, candidate):
        self.source = candidate
        return "VERIFIED_COMPLETE"


def run_with_test_evidence(evidence):
    submitted = []
    tools = InMemoryTools()
    specialist = SimpleNamespace(
        tools=tools,
        protected=None,
        tests=SimpleNamespace(run_tests=lambda target: evidence),
    )
    agent = SimpleNamespace(run=lambda request: AgentResult("VALUE = 2\n"))
    result = run_development_loop(
        specialist=specialist,
        agent=agent,
        instruction="Repair the one reviewed file without touching tests",
        target="src/ai_foundation/development_loop.py",
        acceptance_target="tests/test_fixed_independent_acceptance.py",
        max_repairs=0,
        publish_draft=lambda **kwargs: submitted.append(kwargs) or "draft/1",
    )
    return result, submitted


class AcceptanceEvidenceBoundaryTests(unittest.TestCase):
    def test_empty_acceptance_result_cannot_publish_draft(self):
        result, published = run_with_test_evidence("")
        self.assertEqual(result.status, "TEST_ACCEPTANCE_UNVERIFIED")
        self.assertEqual(published, [])

    def test_whitespace_acceptance_result_cannot_publish_draft(self):
        result, published = run_with_test_evidence(" \t\n ")
        self.assertEqual(result.status, "TEST_ACCEPTANCE_UNVERIFIED")
        self.assertEqual(published, [])

    def test_non_text_acceptance_result_cannot_publish_draft(self):
        result, published = run_with_test_evidence({"passed": 2})
        self.assertEqual(result.status, "TEST_ACCEPTANCE_UNVERIFIED")
        self.assertEqual(published, [])

    def test_none_acceptance_result_cannot_publish_draft(self):
        result, published = run_with_test_evidence(None)
        self.assertEqual(result.status, "TEST_ACCEPTANCE_UNVERIFIED")
        self.assertEqual(published, [])

    def test_boolean_acceptance_result_cannot_publish_draft(self):
        result, published = run_with_test_evidence(True)
        self.assertEqual(result.status, "TEST_ACCEPTANCE_UNVERIFIED")
        self.assertEqual(published, [])

    def test_explicit_failure_receipts_cannot_publish_draft(self):
        for evidence in ("FAILED", "fail", " ERROR ", "TESTS_FAILED"):
            with self.subTest(evidence=evidence):
                result, published = run_with_test_evidence(evidence)
                self.assertEqual(result.status, "TEST_ACCEPTANCE_FAILED")
                self.assertEqual(published, [])

    def test_explicit_passing_test_result_allows_existing_delivery(self):
        result, published = run_with_test_evidence("2 passed in 0.01s")
        self.assertEqual(result.status, "DRAFT_PR_PRESENTED")
        self.assertEqual(len(published), 1)

    def test_arbitrary_nonempty_text_is_not_a_success_receipt(self):
        for evidence in ("completed", "all good", "0 tests collected", "1 passed, 1 failed in 0.01s"):
            with self.subTest(evidence=evidence):
                result, published = run_with_test_evidence(evidence)
                self.assertIn(result.status, {"TEST_ACCEPTANCE_UNVERIFIED", "TEST_ACCEPTANCE_FAILED"})
                self.assertEqual(published, [])

    def test_typed_host_exit_code_receipts_are_authoritative(self):
        passed, published = run_with_test_evidence(TestAcceptanceReceipt(True, "tests completed"))
        self.assertEqual(passed.status, "DRAFT_PR_PRESENTED")
        self.assertEqual(len(published), 1)

        failed, published = run_with_test_evidence(TestAcceptanceReceipt(False, "1 failed in 0.01s"))
        self.assertEqual(failed.status, "REPAIR_BUDGET_EXHAUSTED")
        self.assertEqual(published, [])

    def test_contradictory_typed_success_receipt_cannot_publish(self):
        result, published = run_with_test_evidence(
            TestAcceptanceReceipt(True, "1 failed in 0.01s"))
        self.assertEqual(result.status, "TEST_ACCEPTANCE_UNVERIFIED")
        self.assertEqual(published, [])

    def test_typed_success_warning_text_does_not_block_a_real_passing_exit(self):
        for detail in (
            "UserWarning: Using fallback for error reporting\n1 passed, 1 warning in 0.01s",
            "0 failed, 1 passed in 0.01s",
            "Traceback is mentioned in a passing test's log\n1 passed in 0.01s",
        ):
            with self.subTest(detail=detail):
                result, published = run_with_test_evidence(
                    TestAcceptanceReceipt(True, detail))
                self.assertEqual(result.status, "DRAFT_PR_PRESENTED")
                self.assertEqual(len(published), 1)

    def test_typed_success_conflicting_pytest_summary_blocks_delivery(self):
        for detail in (
            "1 failed in 0.01s",
            "1 passed, 1 failed in 0.01s",
            "=== 1 failed, 1 passed in 0.01s ===",
            "1 error, 1 passed in 0.01s",
            "FAILED",
        ):
            with self.subTest(detail=detail):
                result, published = run_with_test_evidence(
                    TestAcceptanceReceipt(True, detail))
                self.assertEqual(result.status, "TEST_ACCEPTANCE_UNVERIFIED")
                self.assertEqual(published, [])

    def test_malformed_or_empty_typed_receipt_fails_closed(self):
        for evidence in (
            TestAcceptanceReceipt(1, "1 passed in 0.01s"),
            TestAcceptanceReceipt(True, ""),
            TestAcceptanceReceipt(True, None),
        ):
            with self.subTest(evidence=evidence):
                result, published = run_with_test_evidence(evidence)
                self.assertEqual(result.status, "TEST_ACCEPTANCE_UNVERIFIED")
                self.assertEqual(published, [])

    def test_host_typed_runner_exception_is_not_a_code_repair_or_draft(self):
        calls, published, model_calls = [], [], []
        tools = InMemoryTools()
        def runner(target):
            calls.append(target)
            raise RuntimeError("SYNTHETIC_PRIVATE_HOST_PATH_MUST_NOT_LEAK")
        specialist = SimpleNamespace(tools=tools, protected=None,
                                     tests=SimpleNamespace(run_acceptance=runner))
        class Agent:
            def run(self, request):
                model_calls.append(request)
                return AgentResult("VALUE = 2\\n")
        result = run_development_loop(
            specialist=specialist, agent=Agent(),
            instruction="Synthetic fixed acceptance", target="source.py",
            acceptance_target="independent.py", max_repairs=2,
            publish_draft=lambda **kw: published.append(kw) or "draft/unsafe")
        self.assertEqual(result.status, "TEST_RUNNER_UNAVAILABLE")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.feedback, "RuntimeError")
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(model_calls), 1)
        self.assertEqual(published, [])
        self.assertNotIn("SYNTHETIC_PRIVATE", repr(result))

    def test_fixed_m1_runner_returns_typed_receipt_and_never_hides_infrastructure_failure(self):
        # The existing fixed runner performs source/test digest verification
        # and checks subprocess exit status in run_tests. No new runner/model.
        from scripts.local9b_task_recipe import FixedPytest

        port = object.__new__(FixedPytest)
        with patch.object(FixedPytest, "run_tests", return_value="2 passed in 0.01s"):
            receipt = port.run_acceptance("fixed-host")
            self.assertIs(type(receipt), TestAcceptanceReceipt)
            self.assertIs(receipt.passed, True)
        with patch.object(FixedPytest, "run_tests", side_effect=RuntimeError("1 failed")):
            receipt = port.run_acceptance("fixed-host")
            self.assertIs(type(receipt), TestAcceptanceReceipt)
            self.assertIs(receipt.passed, False)
        with patch.object(FixedPytest, "run_tests", side_effect=ValueError("FIXED_TEST_INFRASTRUCTURE_FAILED")):
            with self.assertRaisesRegex(ValueError, "FIXED_TEST_INFRASTRUCTURE_FAILED"):
                port.run_acceptance("fixed-host")

    def test_real_pytest_adapter_receipt_uses_exit_status_not_stdout(self):
        with tempfile.TemporaryDirectory() as root:
            port = PytestPort(root)
            for code in (0, 1, 5):
                process = SimpleNamespace(
                    returncode=code, stdout="1 passed in 0.01s", stderr=""
                )
                with self.subTest(exit_code=code), patch(
                    "ai_foundation.coding_adapter.subprocess.run", return_value=process
                ):
                    receipt = port.run_acceptance("")
                    self.assertIs(type(receipt), TestAcceptanceReceipt)
                    self.assertIs(receipt.passed, code == 0)
                    self.assertIn("1 passed", receipt.detail)


if __name__ == "__main__":
    unittest.main()
