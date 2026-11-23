import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from ai_foundation.agent import AgentResult
from ai_foundation.agent_tools import CapabilityAgentTools, GuardedToolGateway, ReadCapability, WriteCapability
from ai_foundation.coding import CodingSpecialist
from ai_foundation.core import CanonContract, GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.development_loop import run_development_loop


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root/'value.py').write_text('VALUE = 0\n')
        (self.root/'accept.py').write_text('from value import VALUE\nassert VALUE == 2\n')
        root = self.root
        class Files:
            def observe(self, plan): return Path(plan.target).read_text()
            def execute(self, plan): Path(plan.target).write_text(plan.text)
        class Tests:
            def run_tests(self, target):
                cp = subprocess.run([sys.executable, '-B', target], cwd=root,
                                    capture_output=True, text=True, timeout=5)
                if cp.returncode: raise RuntimeError(cp.stderr)
                return 'PASS'
        self.guard = GuardCore(GuardState())
        tools = CapabilityAgentTools(GuardedToolGateway(self.guard, CanonContract('code','v1'),Files()),
                                     'loop-fixture', 'v1', ReadCapability(str(root)),WriteCapability(str(root)))
        self.specialist = CodingSpecialist(tools, Tests())

    def run_loop(self, outputs, **kwargs):
        self.prompts = []
        prompts = self.prompts
        candidates = iter(outputs)
        class Agent:
            def run(self, request):
                prompts.append(json.loads(request.instruction))
                return AgentResult(next(candidates))
        return self.specialist.develop(agent=Agent(),
            instruction='Set VALUE to two', target='value.py',
            acceptance_target=str(self.root/'accept.py'), **kwargs)

    def test_real_guard_files_test_failure_repair_and_delivery(self):
        delivered=[]
        result=self.run_loop(['VALUE = 1\n','VALUE = 2\n'],
            publish_draft=lambda **packet: delivered.append(packet) or 'draft:fixture')
        self.assertEqual((result.status,result.attempts),('DRAFT_PR_PRESENTED',2))
        self.assertIn('AssertionError',self.prompts[1]['test_feedback'])
        self.assertEqual(len(self.guard.state.effects),2)
        self.assertEqual(delivered[0]['source_sha256'],result.source_sha256)
        self.assertEqual((self.root/'accept.py').read_text(),'from value import VALUE\nassert VALUE == 2\n')

    def test_exhaustion_and_identical_failure_stop_without_delivery(self):
        self.assertEqual(self.run_loop(['VALUE = 1\n','VALUE = 3\n']).status,'REPAIR_BUDGET_EXHAUSTED')
        self.assertEqual(self.run_loop(['VALUE = 3\n']).status,'NO_PROGRESS')

    def test_separate_harness_repair_and_review_before_draft(self):
        import hashlib
        from ai_foundation.development_harness_roles import (
            HarnessRoleRuntime, HarnessReviewGate)
        from ai_foundation.agent import AgentRequest, AgentResult
        initial, repair, reviewed, delivered = [], [], [], []
        class First:
            def run(self, request):
                initial.append(json.loads(request.instruction))
                return AgentResult("VALUE = 1\n")
        class Fix:
            def run(self, request):
                repair.append(json.loads(request.instruction))
                return AgentResult("VALUE = 2\n")
        class Reviewer:
            def run(self, request):
                packet = json.loads(request.instruction)
                reviewed.append(packet)
                return AgentResult(json.dumps({
                    "verdict": "PASS", "source_sha256": packet["source_sha256"],
                    "reason_code": "SOURCE_MATCHES_REQUIREMENT",
                }))
        roles = HarnessRoleRuntime({
            "implementation": First(), "repair": Fix(), "review": Reviewer()})
        result = self.specialist.develop(
            agent=roles.agent("implementation"), repair_agent=roles.agent("repair"),
            review_agent=HarnessReviewGate(roles), instruction="Set VALUE to two",
            target="value.py", acceptance_target=str(self.root/"accept.py"),
            publish_draft=lambda **packet: delivered.append(packet) or "draft:reviewed")
        self.assertEqual(result.status, "DRAFT_PR_PRESENTED")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(len(initial), 1)
        self.assertEqual(len(repair), 1)
        self.assertIn("AssertionError", repair[0]["test_feedback"])
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(reviewed[0]["source_sha256"],
                         hashlib.sha256(b"VALUE = 2\n").hexdigest())
        self.assertEqual(len(delivered), 1)

    def test_harness_review_veto_cannot_publish(self):
        from ai_foundation.development_harness_roles import (
            HarnessRoleRuntime, HarnessReviewGate)
        from ai_foundation.agent import AgentResult
        class ApprovedSource:
            def run(self, request):
                return AgentResult("VALUE = 2\n")
        class Reject:
            def run(self, request):
                packet = json.loads(request.instruction)
                return AgentResult(json.dumps({
                    "verdict": "BLOCK", "source_sha256": packet["source_sha256"],
                    "reason_code": "NEEDS_REWORK",
                }))
        published = []
        result = self.specialist.develop(
            agent=ApprovedSource(),
            instruction="Set VALUE to two",
            target="value.py", acceptance_target=str(self.root/"accept.py"),
            review_agent=HarnessReviewGate(HarnessRoleRuntime({"review": Reject()})),
            publish_draft=lambda **kwargs: published.append(kwargs) or "draft:unsafe")
        self.assertEqual(result.status, "REVIEW_BLOCKED")
        self.assertEqual(published, [])

    def test_failed_harness_invocation_stops_without_repair_or_private_leak(self):
        class FailedHarness:
            def __init__(self, exception):
                self.exception = exception
                self.calls = 0
            def run(self, request):
                self.calls += 1
                raise self.exception
        for error, status in (
            (RuntimeError("SYNTHETIC_PRIVATE_STDERR"), "PROPOSAL_RUNTIME_UNAVAILABLE"),
            (TimeoutError("SYNTHETIC_PRIVATE_TIMEOUT"), "PROPOSAL_RUNTIME_UNAVAILABLE"),
            (PermissionError("SYNTHETIC_PRIVATE_DENIAL"), "PROPOSAL_POLICY_DENIED"),
            (ValueError("SYNTHETIC_PRIVATE_INVALID"), "PROPOSAL_INVALID"),
        ):
            with self.subTest(status=status, error=type(error).__name__):
                before = (self.root/'value.py').read_text()
                agent = FailedHarness(error)
                published = []
                result = self.specialist.develop(
                    agent=agent, instruction="code", target="value.py",
                    acceptance_target=str(self.root/'accept.py'),
                    max_repairs=2, publish_draft=lambda **kw: published.append(kw))
                self.assertEqual(result.status, status)
                self.assertEqual(result.attempts, 1)
                self.assertEqual(agent.calls, 1)
                self.assertEqual(published, [])
                self.assertEqual((self.root/'value.py').read_text(), before)
                self.assertNotIn("SYNTHETIC_PRIVATE", repr(result))

    def test_cancelled_guard_stops_before_tests_or_repair(self):
        self.guard.cancel('loop-fixture')
        result=self.run_loop(['VALUE = 2\n'])
        self.assertEqual(result.status,'WRITE_NOT_VERIFIED')
        self.assertEqual((self.root/'value.py').read_text(),'VALUE = 0\n')

    def test_acceptance_same_as_edit_is_rejected_before_model(self):
        class Never:
            def run(self, request): raise AssertionError('model must not run')
        with self.assertRaises(ValueError):
            run_development_loop(specialist=self.specialist,agent=Never(),instruction='x',
                                 target='value.py',acceptance_target='value.py')

if __name__ == '__main__': unittest.main()
