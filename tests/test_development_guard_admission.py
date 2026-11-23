"""Real GuardCore admission preflight with an immutable host registry."""
import unittest
from dataclasses import replace

from ai_foundation.core import CanonContract, Decision, GuardState
from ai_foundation.development_admission import HostContract
from ai_foundation.development_guard_admission import GuardAdmissionPort
from ai_foundation.guard import GuardCore

DIGEST = "a"*64
TEST = "b"*64
PLAN = "driveplanid123456"


class PortTest(unittest.TestCase):
    def setUp(self):
        self.contract = HostContract(
            "draft_code", "src/ai_foundation/task_result.py",
            TEST, 1024, 2048, 0.10, "development:fixed-test")
        self.canon = CanonContract("foundation-code", "code-v1")
        self.guard = GuardCore(GuardState(), monthly_limit=0)
        self.port = GuardAdmissionPort(
            self.guard, self.canon, delegated_contracts=frozenset({self.contract}))

    def test_exact_registry_and_current_guard_allow(self):
        self.assertEqual(self.port.authorize(self.contract, PLAN, DIGEST), "ALLOW")
        self.assertEqual(self.guard.state.spent, 0)

    def test_unregistered_target_does_not_reach_guard(self):
        other = replace(self.contract, target="src/ai_foundation/mcp_host.py")
        self.guard.preflight = lambda *_: self.fail("Guard should not be called")
        self.assertEqual(self.port.authorize(other, PLAN, DIGEST), "DENY")

    def test_test_pin_change_requires_new_delegation(self):
        changed = replace(self.contract, test_sha256="c"*64)
        self.assertEqual(self.port.authorize(changed, PLAN, DIGEST), "DENY")

    def test_guard_policy_denial_preserved(self):
        self.guard.preflight = lambda *_: Decision.DENY
        self.assertEqual(self.port.authorize(self.contract, PLAN, DIGEST), "DENY")

    def test_waiting_human_not_silently_promoted(self):
        self.guard.preflight = lambda *_: Decision.WAITING_HUMAN
        self.assertEqual(self.port.authorize(self.contract, PLAN, DIGEST),
                         Decision.WAITING_HUMAN.value)

    def test_stale_or_invalid_plan_identity_denied(self):
        self.assertEqual(self.port.authorize(self.contract, "bad", DIGEST), "DENY")
        self.assertEqual(self.port.authorize(self.contract, PLAN, "bad"), "DENY")

    def test_unknown_effect_denied(self):
        changed = replace(self.contract, effect="production_deploy")
        self.assertEqual(self.port.authorize(changed, PLAN, DIGEST), "DENY")

    def test_different_scope_denied(self):
        changed = replace(self.contract, guard_scope="development:unrestricted")
        self.assertEqual(self.port.authorize(changed, PLAN, DIGEST), "DENY")

    def test_registry_must_be_explicit_and_immutable(self):
        with self.assertRaisesRegex(ValueError, "REGISTRY_REQUIRED"):
            GuardAdmissionPort(self.guard, self.canon, delegated_contracts=set())
        with self.assertRaisesRegex(ValueError, "REGISTRY_REQUIRED"):
            GuardAdmissionPort(self.guard, self.canon, delegated_contracts=frozenset())

    def test_guard_plan_identity_is_digest_pinned(self):
        received = []
        def inspect(plan, canon):
            received.append(plan)
            return Decision.ALLOW
        self.guard.preflight = inspect
        self.assertEqual(self.port.authorize(self.contract, PLAN, DIGEST), "ALLOW")
        self.assertEqual(received[0].effect_id, DIGEST)
        self.assertEqual(received[0].paid_cost, 0)
        self.assertEqual(received[0].canon_revision, "code-v1")
        self.assertEqual(received[0].target, self.contract.target)
        self.assertTrue(received[0].exclusive_target)


if __name__ == "__main__":
    unittest.main()
