"""No-model regressions for optional compact 9B source edits.

All tests use a deterministic fake public-text Agent; no Ollama or Harness
process starts and the existing production worker is not modified.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from unittest.mock import patch

from ai_foundation.agent import AgentRequest, AgentResult
from ai_foundation.development_compact_edit import (
    CompactEditProposalAgent, CompactEditRejected, OwnerBoundHarnessTextAgent,
    OneFastThenDeepAgent,
    compose_exact_python_edit, compact_first_eligible, MAX_WORKER_COMPACT_SOURCE_BYTES,
)
from ai_foundation.agent_tools import (
    CapabilityAgentTools, GuardedToolGateway, ReadCapability, WriteCapability,
)
from ai_foundation.coding import CodingSpecialist
from ai_foundation.core import CanonContract, GuardState
from ai_foundation.guard import GuardCore


SOURCE = "def example(x):\n    return x - 1\n"
PATCH = {"search": "return x - 1", "replace": "return x + 1"}


class Raw:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def run(self, request):
        self.requests.append(json.loads(request.instruction))
        return AgentResult(next(self.replies))


class CompactEditTests(unittest.TestCase):
    def test_exact_edit_returns_complete_python(self):
        self.assertEqual(
            compose_exact_python_edit(SOURCE, json.dumps(PATCH)),
            "def example(x):\n    return x + 1\n",
        )

    def test_accepts_unicode_in_exact_substring(self):
        source = 'message = "旧"\n'
        result = compose_exact_python_edit(
            source, json.dumps({"search": '"旧"', "replace": '"新"'}))
        self.assertEqual(result, 'message = "新"\n')

    def test_delete_exact_unique_substring(self):
        result = compose_exact_python_edit(
            "x = 1\ny = 2\n", '{"search":"y = 2\\n","replace":""}')
        self.assertEqual(result, "x = 1\n")

    def test_repeated_or_missing_search_rejected(self):
        for source, old in [("x = 1\nx = 1\n", "x = 1"),
                            (SOURCE, "return x + 3")]:
            with self.subTest(source=source, old=old):
                with self.assertRaisesRegex(
                        CompactEditRejected, "SEARCH_NOT_UNIQUE_OR_NOT_PRESENT"):
                    compose_exact_python_edit(source,
                                              json.dumps({"search":old,"replace":"pass"}))

    def test_invalid_json_and_schema_rejected(self):
        malformed = [
            "Not a JSON patch",
            "{\"search\":\"x\",\"search\":\"y\",\"replace\":\"z\"}",
            '{"search":"x","replace":"y","command":"rm -rf /"}',
            '{"search":"","replace":"x"}',
            '{"search":1,"replace":"x"}',
            '{"search":"x","replace":1}',
        ]
        for reply in malformed:
            with self.subTest(reply=reply), self.assertRaises(CompactEditRejected):
                compose_exact_python_edit(SOURCE, reply)

    def test_identical_and_oversized_edits_rejected(self):
        with self.assertRaisesRegex(CompactEditRejected, "NO_CHANGE"):
            compose_exact_python_edit(SOURCE,
                                      json.dumps({"search":"def","replace":"def"}))
        with self.assertRaisesRegex(CompactEditRejected, "EDIT_FRAGMENT_TOO_LARGE"):
            compose_exact_python_edit(SOURCE,
                json.dumps({"search":"def","replace":"x" * 9000}))

    def test_invalid_result_is_syntax_error_before_write(self):
        with self.assertRaises(SyntaxError):
            compose_exact_python_edit(SOURCE,
                json.dumps({"search":"return x - 1","replace":"return ("}))

    def test_compact_agent_wraps_original_prompt_and_rebuilds(self):
        raw = Raw([json.dumps(PATCH)])
        agent = CompactEditProposalAgent(raw)
        original = SOURCE + ("unrelated_line = 123\n" * 25)
        packet = {"instruction":"Fix increment","current_source":original,
                  "test_feedback":"failed"}
        answer = agent.run(AgentRequest(json.dumps(packet)))
        self.assertIn("return x + 1", answer.output)
        self.assertEqual(raw.requests[0]["current_source"], original)
        self.assertEqual(len(raw.requests), 1)
        self.assertIn("search", raw.requests[0]["response_format"])
        self.assertLess(len(json.dumps(PATCH)), len(answer.output))

    def test_host_request_cannot_pick_command_or_target(self):
        raw = Raw([])
        agent = CompactEditProposalAgent(raw)
        with self.assertRaisesRegex(CompactEditRejected,
                                    "INVALID_HOST_PROMPT_FIELDS"):
            agent.run(AgentRequest(json.dumps({"current_source":SOURCE})))
        self.assertEqual(raw.requests, [])

    def test_raw_harness_decodes_json_string_without_running_model(self):
        raw_patch = json.dumps(PATCH)
        wrapped = json.dumps(raw_patch).encode()
        def fake_run(argv, **kwargs):
            self.assertEqual(argv[0], "/usr/bin/sandbox-exec")
            self.assertIn("fixed task", argv[-1])
            kwargs["stdout"].write(wrapped)
            return subprocess.CompletedProcess(argv, 0)
        transport = OwnerBoundHarnessTextAgent(
            ("/usr/bin/sandbox-exec", "pinned"), "/private/owned",
            {"OLLAMA_HOST":"127.0.0.1:11436"}, 20)
        with patch("ai_foundation.development_compact_edit.subprocess.run",
                   side_effect=fake_run):
            answer=transport.run(AgentRequest("fixed task"))
        self.assertEqual(answer.output, raw_patch)

    def test_guarded_develop_still_receives_complete_file_and_repairs(self):
        with tempfile.TemporaryDirectory(prefix="compact-guard-") as tmp:
            root = Path(tmp)
            (root / "value.py").write_text("VALUE = 0\n")
            (root / "accept.py").write_text(
                "from value import VALUE\nassert VALUE == 2\n")
            class Port:
                def observe(self, plan): return Path(plan.target).read_text()
                def execute(self, plan): Path(plan.target).write_text(plan.text)
            class Tests:
                def run_tests(self, target):
                    run=subprocess.run([sys.executable,"-B",target],
                                       cwd=root,capture_output=True,text=True,
                                       timeout=5)
                    if run.returncode:
                        raise RuntimeError(run.stderr)
                    return "PASS"
            guard=GuardCore(GuardState())
            tools=CapabilityAgentTools(
                GuardedToolGateway(guard,CanonContract("code","v1"),Port()),
                "compact-fixture","v1",
                ReadCapability(str(root)),WriteCapability(str(root)))
            specialist=CodingSpecialist(tools,Tests())
            raw=Raw([
                '{"search":"VALUE = 0","replace":"VALUE = 1"}',
                '{"search":"VALUE = 1","replace":"VALUE = 2"}',
            ])
            result=specialist.develop(
                agent=CompactEditProposalAgent(raw),
                instruction="Set VALUE to 2",target="value.py",
                acceptance_target=str(root/"accept.py"),max_repairs=1)
            self.assertEqual((result.status,result.attempts),
                             ("TESTED_CHANGE",2))
            self.assertEqual((root/"value.py").read_text(),"VALUE = 2\n")
            self.assertEqual(len(guard.state.effects),2)
            self.assertIn("AssertionError",raw.requests[1]["test_feedback"])



    def test_malformed_fast_proposal_deep_repairs_with_one_guarded_write(self):
        """Actual bounded development loop: failed compact text does not write."""
        with tempfile.TemporaryDirectory(prefix="compact-deep-fallback-") as tmp:
            root = Path(tmp)
            source = root / "value.py"
            source.write_text("VALUE = 0\n")
            (root / "accept.py").write_text(
                "from value import VALUE\nassert VALUE == 2\n")
            class Port:
                def observe(self, plan): return Path(plan.target).read_text()
                def execute(self, plan): Path(plan.target).write_text(plan.text)
            class Tests:
                def run_tests(self, target):
                    outcome = subprocess.run(
                        [sys.executable, "-B", target], cwd=root,
                        capture_output=True, text=True, timeout=5)
                    if outcome.returncode:
                        raise RuntimeError(outcome.stderr)
                    return "PASS"
            guard = GuardCore(GuardState())
            tools = CapabilityAgentTools(
                GuardedToolGateway(
                    guard, CanonContract("code", "v1"), Port()),
                "compact-fallback", "v1",
                ReadCapability(str(root)), WriteCapability(str(root)))
            specialist = CodingSpecialist(tools, Tests())
            first = Raw(["NOT_A_JSON_PATCH"])
            full = Raw(["VALUE = 2\n"])
            result = specialist.develop(
                agent=OneFastThenDeepAgent(CompactEditProposalAgent(first), full),
                repair_agent=full,
                instruction="Fix VALUE with the host-pinned test",
                target="value.py", acceptance_target=str(root / "accept.py"),
                max_repairs=1)
            self.assertEqual((result.status, result.attempts),
                             ("TESTED_CHANGE", 2))
            self.assertEqual(source.read_text(), "VALUE = 2\n")
            self.assertEqual(len(guard.state.effects), 1)
            self.assertEqual(len(first.requests), 1)
            self.assertEqual(len(full.requests), 1)

    def test_host_optin_reuses_same_pinned_harness_and_lease(self):
        from ai_foundation.development_host import (
            HarnessProposalAgent, run_local_development_task,
        )
        class Lease:
            def __init__(self): self.entries = 0
            def hold(self):
                self.entries += 1
                return nullcontext()
        with tempfile.TemporaryDirectory(prefix="compact-optin-") as tmp:
            root = Path(tmp)
            argv = ("/usr/bin/sandbox-exec", "-f", "pinned.sb", "dsh")
            env = {"OLLAMA_HOST":"127.0.0.1:11436", "NO_PROXY":"*"}
            bound = HarnessProposalAgent(argv, tmp, env, 20)
            lease = Lease()
            observed = []
            def record_execution(**kwargs):
                observed.append(kwargs)
                return kwargs["proposal_agent"]
            with patch("ai_foundation.development_host.execute_development_task",
                       side_effect=record_execution):
                result = run_local_development_task(
                    root=root, guard=GuardCore(GuardState()), tests=object(),
                    proposal_agent=bound, lease=lease,
                    instruction="Fix safe file", target="value.py",
                    acceptance_target="accept.py",
                    repository="fixed/owner", branch="feature",
                    compact_single_edit=True,
                )
                unchanged = run_local_development_task(
                    root=root, guard=GuardCore(GuardState()), tests=object(),
                    proposal_agent=bound, lease=lease,
                    instruction="Fix safe file", target="value.py",
                    acceptance_target="accept.py",
                    repository="fixed/owner", branch="feature",
                    compact_single_edit=False,
                )
            self.assertIsInstance(result, OneFastThenDeepAgent)
            self.assertIs(result.deep, bound)
            self.assertIsInstance(result.fast, CompactEditProposalAgent)
            self.assertEqual(result.fast.raw_agent.argv_prefix, argv)
            self.assertEqual(result.fast.raw_agent.cwd, tmp)
            self.assertEqual(result.fast.raw_agent.env, env)
            self.assertEqual(result.fast.raw_agent.timeout_s, 20)
            self.assertIs(unchanged, bound)
            # The default repair side keeps the original reasoning-capable
            # Harness, not a second potentially low-quality compact proposal.
            self.assertIs(observed[0]["repair_agent"], bound)
            self.assertIsNone(observed[1]["repair_agent"])
            self.assertEqual(lease.entries, 2)

    def test_host_rejects_invalid_or_unbound_compact_optin(self):
        from ai_foundation.development_host import run_local_development_task
        class NoLease:
            def hold(self): raise AssertionError("must fail before leasing")
        with tempfile.TemporaryDirectory(prefix="compact-unbound-") as tmp:
            base = dict(
                root=tmp, guard=GuardCore(GuardState()), tests=object(),
                proposal_agent=Raw([]), lease=NoLease(),
                instruction="Fix safe file", target="value.py",
                acceptance_target="accept.py",
                repository="fixed/owner", branch="feature",
            )
            with self.assertRaisesRegex(
                    ValueError, "COMPACT_EDIT_REQUIRES_BOUND_HARNESS"):
                run_local_development_task(**base, compact_single_edit=True)
            with self.assertRaisesRegex(
                    ValueError, "INVALID_COMPACT_EDIT_OPT_IN"):
                run_local_development_task(**base, compact_single_edit="true")


    def test_fast_compact_success_never_invokes_slow_full_source(self):
        fast = Raw(['{"search":"return x - 1","replace":"return x + 1"}'])
        deep = Raw([])
        agent = OneFastThenDeepAgent(CompactEditProposalAgent(fast), deep)
        request = AgentRequest(json.dumps({
            "instruction":"Fix example","current_source":SOURCE,
            "test_feedback":"Initial implementation; acceptance has not run."
        }))
        self.assertIn("return x + 1", agent.run(request).output)
        self.assertEqual(agent.calls, 1)
        self.assertEqual(len(deep.requests), 0)

    def test_malformed_fast_result_uses_existing_next_repair_turn(self):
        fast = Raw(["Not a JSON patch"])
        deep = Raw(["def example(x):\\n    return x + 1\\n"])
        agent = OneFastThenDeepAgent(CompactEditProposalAgent(fast), deep)
        request = AgentRequest(json.dumps({
            "instruction":"Fix example","current_source":SOURCE,
            "test_feedback":"Initial implementation; acceptance has not run."
        }))
        with self.assertRaisesRegex(SyntaxError,"COMPACT_FAST_OUTPUT_REJECTED"):
            agent.run(request)
        self.assertIn("return x + 1", agent.run(request).output)
        self.assertEqual(agent.calls, 2)

    def test_transport_errors_are_not_silenced_or_replayed(self):
        class TransportFail:
            def run(self, request):raise subprocess.TimeoutExpired(["dsh"],3)
        deep=Raw([])
        agent=OneFastThenDeepAgent(TransportFail(),deep)
        with self.assertRaises(subprocess.TimeoutExpired):
            agent.run(AgentRequest("host request"))
        self.assertEqual(len(deep.requests),0)


    def test_compact_mode_is_fixed_python_only_and_bounded(self):
        with tempfile.TemporaryDirectory(prefix="compact-selector-") as tmp:
            root = Path(tmp)
            source = root / "source.py"
            source.write_text(SOURCE, encoding="utf-8")
            assert compact_first_eligible({"recipe": "python-fixed-test"}, source)
            for task in ({}, {"recipe": "bounded-http-positive-limit"},
                         {"recipe": "arbitrary"}, "python-fixed-test"):
                with self.subTest(task=task):
                    self.assertFalse(compact_first_eligible(task, source))
            source.write_bytes(b"x" * (MAX_WORKER_COMPACT_SOURCE_BYTES + 1))
            self.assertFalse(compact_first_eligible({"recipe": "python-fixed-test"}, source))
            source.write_bytes(b"")
            self.assertFalse(compact_first_eligible({"recipe": "python-fixed-test"}, source))
            source.write_text(SOURCE)
            alias = root / "alias.py"
            alias.symlink_to(source)
            self.assertFalse(compact_first_eligible({"recipe": "python-fixed-test"}, alias))
            self.assertFalse(compact_first_eligible({"recipe": "python-fixed-test"},
                                                  root / "absent.py"))

    def test_module_level_control_flow_rejected_before_write(self):
        for fragment in ("return 1", "break", "yield 1"):
            with self.subTest(fragment=fragment):
                with self.assertRaises(SyntaxError):
                    compose_exact_python_edit(
                        "VALUE = 0\n", json.dumps({
                            "search": "VALUE = 0", "replace": fragment,
                        }))

    def test_compact_transport_does_not_expose_private_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            def failed(argv, *, stdout, stderr, **kwargs):
                stderr.write(b"SYNTHETIC_OWNER_SECRET_NEVER_IN_RECEIPT")
                return subprocess.CompletedProcess(argv, 17)
            with patch("ai_foundation.development_compact_edit.subprocess.run",
                       side_effect=failed):
                agent = OwnerBoundHarnessTextAgent(("/unused/dsh",), tmp, {}, 10)
                with self.assertRaisesRegex(RuntimeError, "HARNESS_EXIT_17") as raised:
                    agent.run(AgentRequest("synthetic task"))
            self.assertEqual(str(raised.exception), "HARNESS_EXIT_17")

    def test_existing_worker_enables_bounded_compact_once_with_deep_repair(self):
        worker=(Path(__file__).resolve().parents[1]/
                "scripts/local9b_autodev_worker.py").read_text()
        compile(worker, "worker.py", "exec")
        # The installed worker source intentionally opts in only when its
        # fixed-Python recipe and source bound qualify; never based on a
        # model, Issue prose, provider name or a changed resource lease.
        self.assertIn("compact_first_eligible(task, repo/target)", worker)
        self.assertIn("compact_single_edit=compact_first", worker)
        self.assertNotIn("compact_single_edit=True", worker)
        self.assertNotIn("OneFastThenDeepAgent(", worker)
        self.assertIn("HarnessRoleRuntime(", worker)
        self.assertIn("repair_agent=harness_roles.agent(\"repair\")", worker)
        self.assertIn("contextWindow: 32768", worker)
        self.assertIn("maxTokens: 16384", worker)
        self.assertIn('OLLAMA_CONTEXT_LENGTH="32768"', worker)
        self.assertIn("HostComputeLease()", worker)
        self.assertIn("V6_PATCH_SHA256", worker)
        self.assertNotIn("choose_9b_budget", worker)


if __name__ == "__main__":
    unittest.main()
