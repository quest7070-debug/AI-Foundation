"""Synthetic provider-neutral Harness role tests; no live model calls."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_foundation.agent import AgentRequest, AgentResult
from ai_foundation.development_harness_roles import (
    HarnessRoleRuntime, HarnessReviewGate, HostBoundHarnessAgent,
)


class Port:
    def __init__(self, output):
        self.output = output
        self.prompts = []

    def run(self, request):
        self.prompts.append(request.instruction)
        return AgentResult(self.output)


class HarnessDevelopmentRolesTests(unittest.TestCase):
    def test_roles_are_host_bound_not_model_selected(self):
        p = Port("VALUE = 2\n")
        runtime = HarnessRoleRuntime({"implementation": p})
        self.assertEqual(runtime.invoke("implementation", "fix source"), "VALUE = 2\n")
        self.assertEqual(p.prompts, ["fix source"])
        with self.assertRaisesRegex(RuntimeError, "HARNESS_ROLE_UNBOUND"):
            runtime.invoke("repair", "fix test failure")
        with self.assertRaisesRegex(ValueError, "UNKNOWN_HARNESS_ROLE"):
            runtime.agent("billing")
        with self.assertRaisesRegex(ValueError, "INVALID_HARNESS_ROLE_BINDINGS"):
            HarnessRoleRuntime({"unreviewed": p})

    def test_independent_review_pass_only_on_exact_digest(self):
        source = "VALUE = 2\n"
        digest = hashlib.sha256(source.encode()).hexdigest()
        p = Port(json.dumps({"verdict": "PASS", "source_sha256": digest,
                             "reason_code": "READABLE_AND_TESTED"}))
        reviewer = HarnessReviewGate(HarnessRoleRuntime({"review": p}))
        self.assertTrue(reviewer.review(
            target="value.py", source=source, source_sha256=digest,
            acceptance_target="tests/test_value.py", feedback="PASS"))
        prompt = json.loads(p.prompts[0])
        self.assertEqual(prompt["role"], "review")
        self.assertEqual(prompt["source_sha256"], digest)
        self.assertEqual(prompt["fixed_test_feedback"], "PASS")
        self.assertNotIn("model", prompt)
        with self.assertRaisesRegex(ValueError, "REVIEW_SOURCE_DIGEST_MISMATCH"):
            reviewer.review(target="value.py", source=source, source_sha256="f" * 64,
                            acceptance_target="test.py", feedback="PASS")

    def test_review_can_block_but_not_change_authority(self):
        source = "VALUE = 2\n"
        digest = hashlib.sha256(source.encode()).hexdigest()
        p = Port(json.dumps({"verdict": "BLOCK", "source_sha256": digest,
                             "reason_code": "WRONG_BEHAVIOR"}))
        reviewer = HarnessReviewGate(HarnessRoleRuntime({"review": p}))
        kwargs = {"target": "value.py", "source": source, "source_sha256": digest,
                  "acceptance_target": "test.py", "feedback": "PASS"}
        self.assertFalse(reviewer.review(**kwargs))
        p.output = json.dumps({"verdict": "PASS", "source_sha256": "0" * 64,
                               "reason_code": "WRONG_DIGEST"})
        with self.assertRaisesRegex(ValueError, "HARNESS_REVIEW_INVALID"):
            reviewer.review(**kwargs)
        p.output = '{"verdict":"PASS","verdict":"BLOCK","source_sha256":"%s","reason_code":"X"}' % digest
        with self.assertRaisesRegex(ValueError, "HARNESS_DUPLICATE_JSON_KEY"):
            reviewer.review(**kwargs)

    def test_host_bound_text_agent_no_shell_or_implicit_fallback(self):
        agent = HostBoundHarnessAgent(("/usr/bin/sandbox-exec", "-f",
                                       "/host/policy.sb", "/host/dsh",
                                       "--profile", "headless"),
                                      "/host/private", {"PATH": "/usr/bin"}, 90)
        class Done:
            returncode = 0
        def fake_call(argv, **kw):
            self.assertEqual(argv[-1], "review source")
            self.assertEqual(argv[0], "/usr/bin/sandbox-exec")
            self.assertNotIn("shell", kw)
            self.assertEqual(kw["env"], {"PATH": "/usr/bin"})
            kw["stdout"].write(json.dumps('{"verdict":"BLOCK"}').encode())
            return Done()
        with patch("ai_foundation.development_harness_roles.subprocess.run", fake_call):
            self.assertEqual(agent.run(AgentRequest("review source")).output,
                             '{"verdict":"BLOCK"}')


    def test_decomposition_is_host_scoped_and_cannot_authorize(self):
        from ai_foundation.development_harness_roles import propose_decomposition
        steps = [
            {"id": "s1", "target": "src/a.py", "purpose": "Repair the parser",
             "depends_on": []},
            {"id": "s2", "target": "src/b.py", "purpose": "Repair the serializer",
             "depends_on": ["s1"]},
        ]
        port = Port(json.dumps({"steps": steps}))
        runtime = HarnessRoleRuntime({"decomposition": port})
        result = propose_decomposition(
            runtime, issue_number=30, base_sha="a" * 40,
            reviewed_scope={"src/a.py": "tests/test_a.py",
                            "src/b.py": "tests/test_b.py"})
        self.assertEqual(result["status"], "PROPOSAL_ONLY")
        self.assertIs(result["execution_authorized"], False)
        self.assertEqual(result["steps"][0]["acceptance_path"], "tests/test_a.py")
        self.assertEqual(result["steps"][1]["depends_on"], ["s1"])
        self.assertEqual(len(result["proposal_sha256"]), 64)
        prompt = json.loads(port.prompts[0])
        self.assertEqual(prompt["host_write_targets"], ["src/a.py", "src/b.py"])
        self.assertNotIn("model", prompt)
        self.assertNotIn("execute", result)

        port.output = json.dumps({"steps": [dict(steps[0], target="secrets/token.py"),
                                                   steps[1]]})
        with self.assertRaisesRegex(ValueError, "DECOMPOSITION_STEP_INVALID"):
            propose_decomposition(runtime, issue_number=30, base_sha="a" * 40,
                                  reviewed_scope={"src/a.py": "tests/test_a.py",
                                                  "src/b.py": "tests/test_b.py"})

    def test_decomposition_includes_only_exact_host_findings(self):
        from ai_foundation.development_harness_roles import propose_decomposition
        scope = {"src/a.py": "tests/test_a.py"}
        findings = {"src/a.py": "Reject None output before a model reply"}
        port = Port(json.dumps({"steps": [
            {"id": "s1", "target": "src/a.py",
             "purpose": "Reject absent result", "depends_on": []}]}))
        runtime = HarnessRoleRuntime({"decomposition": port})
        proposal = propose_decomposition(
            runtime, issue_number=31, base_sha="b" * 40,
            reviewed_scope=scope, reviewed_instructions=findings)
        self.assertIs(proposal["execution_authorized"], False)
        prompt = json.loads(port.prompts[-1])
        self.assertEqual(prompt["host_fixed_instructions"], findings)
        self.assertNotIn("github_token", json.dumps(prompt).lower())
        with self.assertRaisesRegex(ValueError,
                                    "DECOMPOSITION_HOST_INSTRUCTIONS_INVALID"):
            propose_decomposition(
                runtime, issue_number=31, base_sha="b" * 40,
                reviewed_scope=scope,
                reviewed_instructions={"src/other.py": "Unreviewed new target"})
        self.assertEqual(len(port.prompts), 1)

    def test_decomposition_rejects_cycles_gaps_and_duplicate_keys(self):
        from ai_foundation.development_harness_roles import propose_decomposition
        source = {"src/a.py": "tests/test_a.py", "src/b.py": "tests/test_b.py"}
        steps = [{"id": "s1", "target": "src/a.py", "purpose": "Fix parser",
                  "depends_on": ["s2"]},
                 {"id": "s2", "target": "src/b.py", "purpose": "Fix serializer",
                  "depends_on": ["s1"]}]
        port = Port(json.dumps({"steps": steps}))
        runtime = HarnessRoleRuntime({"decomposition": port})
        def plan():
            return propose_decomposition(runtime, issue_number=9,
                                         base_sha="a" * 40, reviewed_scope=source)
        with self.assertRaisesRegex(ValueError, "DECOMPOSITION_DEPENDENCY_CYCLE"):
            plan()
        port.output = json.dumps({"steps": steps[:1]})
        with self.assertRaisesRegex(ValueError, "DECOMPOSITION_SCOPE_INCOMPLETE"):
            plan()
        port.output = '{"steps":[],"steps":[]}'
        with self.assertRaisesRegex(ValueError, "HARNESS_DUPLICATE_JSON_KEY"):
            plan()

    def test_decomposition_requires_serialization_of_overlap(self):
        from ai_foundation.development_harness_roles import propose_decomposition
        scope = {"src/package": "tests/test_a.py",
                 "src/package/module.py": "tests/test_b.py"}
        rows = [{"id": "s1", "target": "src/package", "purpose": "Review package",
                 "depends_on": []},
                {"id": "s2", "target": "src/package/module.py",
                 "purpose": "Repair module", "depends_on": []}]
        port = Port(json.dumps({"steps": rows}))
        runtime = HarnessRoleRuntime({"decomposition": port})
        def plan():
            return propose_decomposition(runtime, issue_number=9,
                                         base_sha="b" * 40, reviewed_scope=scope)
        with self.assertRaisesRegex(ValueError, "DECOMPOSITION_UNSERIALIZED_WRITE_CONFLICT"):
            plan()
        rows[1]["depends_on"] = ["s1"]
        port.output = json.dumps({"steps": rows})
        self.assertEqual(plan()["steps"][1]["depends_on"], ["s1"])



if __name__ == "__main__":
    unittest.main()
