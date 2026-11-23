"""No-model receipts guard: an Issue is at most one owned execution."""
import sys
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import local9b_issue_bridge as bridge


def approved(number, revision="2026-11-07T00:00:00Z"):
    return {
        "number": number, "state": "OPEN", "updatedAt": revision,
        "labels": [{"name": bridge.READY_LABEL}],
        "body": (
            "Approved fixed recipe\n```foundation-autodev-task\n"
            '{"recipe":"bounded-http-positive-limit","base":"main",'
            '"field":"request_queue_size"}'
            "\n```"
        ),
    }


class ConsumedIssueTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        self.results = self.root / "results"
        self.results.mkdir()

    def _collect(self, issues):
        with patch.object(bridge, "_gh", return_value=issues):
            return bridge.collect_ready(self.inbox)

    def test_completed_draft_not_requeued_after_timestamp_change(self):
        old = approved(252)
        self.assertEqual(self._collect([old])[0]["status"], "QUEUED")
        old_task = bridge.issue_task(old)["id"]
        (self.results / (old_task + ".json")).write_text(
            '{"status":"DRAFT_PR_PRESENTED","delivery_ref":"draft"}')
        refreshed = approved(252, "2026-11-07T01:00:00Z")
        result = self._collect([refreshed])
        self.assertEqual(result[0]["status"], "ALREADY_ATTEMPTED")
        self.assertEqual(len(list(self.inbox.glob("*.json"))), 1)

    def test_interrupted_model_task_never_replays(self):
        old = approved(252)
        self._collect([old])
        old_task = bridge.issue_task(old)["id"]
        (self.results / (old_task + ".started")).write_text("started")
        new_body = approved(252)
        new_body["body"] += "\nEdited task description"
        result = self._collect([new_body])
        self.assertEqual(result[0]["status"], "ALREADY_ATTEMPTED")
        self.assertEqual(len(list(self.inbox.glob("*.json"))), 1)

    def test_unconsumed_busy_task_can_retry_and_other_issue_can_queue(self):
        first = approved(252)
        self._collect([first])
        # HostComputeBusy removes the prior .started marker without effects.
        refreshed = approved(252, "2026-11-07T01:00:00Z")
        status = self._collect([refreshed, approved(253)])
        self.assertEqual([x["status"] for x in status], ["QUEUED", "QUEUED"])
        self.assertEqual(len(list(self.inbox.glob("*.json"))), 3)

    def test_untrusted_receipt_link_fails_closed(self):
        issue = approved(252)
        (self.results / (bridge.issue_task(issue)["id"] + ".started")).symlink_to(
            self.root / "outside")
        report = self._collect([issue])
        self.assertEqual(report[0]["status"], "NEEDS_SCOPED_CONTRACT")
        self.assertEqual(report[0]["reason"], "UNTRUSTED_PRIOR_ATTEMPT")
        self.assertFalse(list(self.inbox.glob("*.json")))

    def test_revision_queued_before_first_run_is_refused_at_claim(self):
        first = approved(252)
        next_revision = approved(252, "2026-11-07T01:00:00Z")
        self._collect([first])
        self._collect([next_revision])
        self.assertEqual(len(list(self.inbox.glob("*.json"))), 2)
        (self.results / (bridge.issue_task(first)["id"] + ".started")).write_text("started")
        # The worker makes this same check after queue collection and before
        # creating the next exclusive marker, not just at intake time.
        self.assertTrue(bridge.previous_issue_attempt(self.inbox, 252))
        worker = (Path(__file__).resolve().parents[1] /
                  "scripts/local9b_autodev_worker.py").read_text()
        compile(worker, "local9b_autodev_worker.py", "exec")
        self.assertIn('previous_issue_attempt(STATE_ROOT/"inbox",int(match.group(1)))',
                      worker)

    def test_per_issue_claim_is_exclusive_across_revisions(self):
        first = approved(252)
        second = approved(252, "2026-11-07T01:00:00Z")
        self._collect([first])
        self._collect([second])
        claim = self.results / "issue-252.claimed"
        with claim.open("x") as writer:
            writer.write(bridge.issue_task(first)["id"])
        with self.assertRaises(FileExistsError):
            claim.open("x")
        self.assertTrue(bridge.previous_issue_attempt(self.inbox, 252))
        self.assertEqual(self._collect([second])[0]["status"], "ALREADY_ATTEMPTED")
        self.assertEqual(len(list(self.inbox.glob("*.json"))), 2)

    def test_busy_release_of_owned_claim_allows_fresh_queue(self):
        claim = self.results / "issue-252.claimed"
        claim.write_text("owned-before-model")
        self.assertTrue(bridge.previous_issue_attempt(self.inbox, 252))
        # Only the owning worker may remove its claim after HostComputeBusy.
        claim.unlink()
        self.assertFalse(bridge.previous_issue_attempt(self.inbox, 252))
        self.assertEqual(self._collect([approved(252)])[0]["status"], "QUEUED")

    def test_preexisting_result_without_started_marker_also_blocks_replay(self):
        old = approved(252)
        self._collect([old])
        (self.results / (bridge.issue_task(old)["id"] + ".json")).write_text(
            '{"status":"STOPPED","detail":"UNKNOWN_AFTER_MODEL"}')
        new = approved(252, "2026-11-07T02:00:00Z")
        self.assertEqual(self._collect([new])[0]["status"], "ALREADY_ATTEMPTED")


    def test_backend_port_occupied_defers_before_model_attempt(self):
        # Evaluate the production function with exact globals, without loading
        # private Harness assets, invoking a model or mutating any Issue claim.
        import ast
        import errno
        import socket
        source=(Path(__file__).resolve().parents[1] /
                "scripts/local9b_autodev_worker.py").read_text()
        parsed=ast.parse(source)
        method=next(n for n in parsed.body
                    if isinstance(n,ast.FunctionDef) and
                    n.name=="ensure_backend_port_available")
        class Busy(Exception):
            pass
        scope={"socket":socket,"errno":errno,"HostComputeBusy":Busy}
        exec(compile(ast.Module(body=[method],type_ignores=[]),
                     "<worker-admission>","exec"),scope)
        probe=scope["ensure_backend_port_available"]
        with socket.socket() as holder:
            holder.bind(("127.0.0.1",0))
            port=holder.getsockname()[1]
            with self.assertRaisesRegex(Busy,"LOCAL_BACKEND_PORT_OCCUPIED"):
                probe(port)
        self.assertIsNone(probe(port))



class PublicStrataAdmissionTests(unittest.TestCase):
    def contract(self):
        import hashlib
        source=b"VALUE = 0\n"
        instruction="Update the public fixture."
        return {
            "recipe":"python-fixed-test", "base":"main",
            "base_sha":"1"*40, "target":"src/ai_foundation/fixture.py",
            "test":"tests/test_fixture.py", "test_sha256":"2"*64,
            "instruction":instruction, "model":"auto",
            "source_sha256":hashlib.sha256(source).hexdigest(),
            "public_source_sha256":hashlib.sha256(source).hexdigest(),
            "public_instruction_sha256":hashlib.sha256(
                instruction.encode()).hexdigest(),
        }

    def test_public_contract_needs_exact_digest_and_m1_keeps_old_schema(self):
        from local9b_task_recipe import validate_contract
        contract=self.contract()
        validate_contract(contract)
        damaged=dict(contract,public_instruction_sha256="0"*64)
        with self.assertRaisesRegex(ValueError,"PUBLIC_REVIEW_HASH_MISMATCH"):
            validate_contract(damaged)
        damaged=dict(contract)
        damaged.pop("public_source_sha256")
        with self.assertRaisesRegex(ValueError,"PYTHON_TASK_FIELDS_INVALID"):
            validate_contract(damaged)
        damaged=dict(contract,instruction=None)
        with self.assertRaisesRegex(ValueError,"PYTHON_TASK_INSTRUCTION_INVALID"):
            validate_contract(damaged)
        fixed={k:v for k,v in contract.items()
               if k not in {"model","source_sha256","public_source_sha256",
                            "public_instruction_sha256"}}
        validate_contract(fixed)
        validate_contract(dict(fixed,model="m1"))

    def test_remote_is_only_discovered_for_explicit_public_auto(self):
        import ast
        import os
        from types import SimpleNamespace
        from unittest.mock import patch
        from ai_foundation import local_endpoint_config
        from local9b_task_recipe import validate_contract
        worker=(Path(__file__).resolve().parents[1]/
                "scripts/local9b_autodev_worker.py").read_text()
        parsed=ast.parse(worker)
        method=next(x for x in parsed.body
                    if isinstance(x,ast.FunctionDef)
                    and x.name=="_public_strata_endpoint")
        scope={"Path":Path,"os":os}
        exec(compile(ast.Module(body=[method],type_ignores=[]),
                     "<strata-admission>","exec"),scope)
        discover=scope["_public_strata_endpoint"]
        row={**self.contract(),"id":"issue-1-0123456789abcdef",
             "field":"max_concurrent_requests","source_issue":1,
             "source_digest":"0"*64}
        remote=SimpleNamespace(models={
            "code-agent":"qwen3.8-flash-next-coder-iq1_m"},api_key="synthetic-secret")
        online=SimpleNamespace(binding="local:mainpc-strata:code-agent",
                               health="ONLINE",capabilities=("CODE",),
                               same_host=False)
        registry=SimpleNamespace(candidates=lambda:(online,))
        # /tmp is a symlink to /private/tmp on macOS. The production
        # endpoint requires a canonical real directory, so test that path.
        data_root=str(Path("/tmp").resolve(strict=True))
        with patch.dict(os.environ,{"FOUNDATION_DATA_ROOT":data_root}):
            with patch.object(local_endpoint_config,"load_local_endpoints",
                              return_value=(("local:mainpc-strata",
                                             registry,remote),)) as loader:
                self.assertIs(discover(row),remote)
                self.assertIsNone(discover(dict(row,model="m1")))
                self.assertEqual(loader.call_count,1)
            registry.candidates=lambda:()
            with patch.object(local_endpoint_config,"load_local_endpoints",
                              return_value=(("local:mainpc-strata",
                                             registry,remote),)):
                self.assertIsNone(discover(row))
            registry.candidates=lambda:(online,)
            wrong=SimpleNamespace(models={"code-agent":"unreviewed-model"})
            with patch.object(local_endpoint_config,"load_local_endpoints",
                              return_value=(("local:mainpc-strata",
                                             registry,wrong),)):
                self.assertIsNone(discover(row))
        # The incumbent 9B LaunchAgent may omit FOUNDATION_DATA_ROOT. Reuse
        # only the independently verified installed Operator data root.
        import m1_human_model_activation_readiness as installed_operator
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(installed_operator,"installed_paths",
                              return_value=(Path(data_root)/"operator.py",Path(data_root))):
                with patch.object(local_endpoint_config,"load_local_endpoints",
                                  return_value=(("local:mainpc-strata",
                                                 registry,remote),)) as loader:
                    self.assertIs(discover(row),remote)
                    self.assertEqual(loader.call_args.args[0],
                                     Path(data_root)/"local-compute/endpoints.json")
            with patch.object(installed_operator,"installed_paths",return_value=None):
                self.assertIsNone(discover(row))
        # A valid model name in text never supplies its own admission.
        self.assertIsNone(validate_contract(self.contract()))


    def test_reviewed_public_proposal_uses_remote_without_starting_9b(self):
        import ast
        import hashlib
        import json
        import os
        import subprocess
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        from ai_foundation.agent import AgentRequest
        from ai_foundation.core import GuardState
        from ai_foundation.guard import GuardCore
        import local9b_task_recipe

        source="VALUE = 0\n"
        row={**self.contract(),"id":"issue-1-0123456789abcdef"}
        seen=[]
        remote=SimpleNamespace(chat=lambda prompt,model: (
            seen.append((json.loads(prompt),model)) or "VALUE = 2\n"))
        class Tests:
            def __init__(self, task, repo, work):
                seen.append(("test_setup", task["test"]))
            def run_tests(self, target):
                raise RuntimeError("expected baseline RED")
        class Result:
            def __init__(self):
                self.status="TESTED_CHANGE"
                self.attempts=1
                self.source_sha256=hashlib.sha256(b"VALUE = 2\n").hexdigest()
                self.feedback="1 passed"
                self.delivery_ref=""
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/"tmp").mkdir()
            def clone(argv, **kwargs):
                checkout=Path(argv[4])
                target=checkout/row["target"]
                target.parent.mkdir(parents=True)
                target.write_text(source)
                return subprocess.CompletedProcess(argv,0)
            def git(repo,*args):
                if args==("rev-parse","HEAD"):
                    return row["base_sha"]
                if args==("checkout","-b","local9b/autonomous-"+row["id"]):
                    return ""
                raise AssertionError("unexpected git operation")
            def evaluate(**kwargs):
                self.assertEqual(kwargs["max_repairs"],0)
                self.assertEqual(kwargs["target"],row["target"])
                self.assertEqual(kwargs["acceptance_target"],"fixed-host-tests")
                instruction=kwargs["instruction"]
                prompt=json.dumps({
                    "instruction":instruction,"current_source":source,
                    "test_feedback":"Initial implementation; acceptance has not run.",
                    "response_format":"Return only the complete replacement file, without Markdown fences.",
                },ensure_ascii=False)
                self.assertEqual(
                    kwargs["proposal_agent"].run(AgentRequest(prompt)).output,
                    "VALUE = 2\n")
                with self.assertRaises(PermissionError):
                    kwargs["proposal_agent"].run(AgentRequest(prompt))
                return Result()
            source_text=(Path(__file__).resolve().parents[1]/
                         "scripts/local9b_autodev_worker.py").read_text()
            parsed=ast.parse(source_text)
            method=next(x for x in parsed.body
                        if isinstance(x,ast.FunctionDef)
                        and x.name=="_try_public_strata_task")
            scope={"_public_strata_endpoint":lambda _:remote,
                   "Path":Path,"PRIVATE":root,"tempfile":tempfile,
                   "subprocess":SimpleNamespace(run=clone),
                   "git":git,"hashlib":hashlib,"json":json,
                   "os":os,"GuardCore":GuardCore,"GuardState":GuardState,
                   "run_local_development_task":evaluate}
            exec(compile(ast.Module(body=[method],type_ignores=[]),
                         "<public-strata-proposal>","exec"),scope)
            with patch.object(local9b_task_recipe,"FixedPytest",Tests):
                result=scope["_try_public_strata_task"](row)
            self.assertEqual(result["status"],"TESTED_CHANGE")
            self.assertEqual(result["attempted_binding"],
                             "local:mainpc-strata:code-agent")
            self.assertEqual(len(seen),2)
            self.assertEqual(seen[0],("test_setup",row["test"]))
            self.assertEqual(seen[1][1],"code-agent")
            self.assertEqual(seen[1][0]["current_source"],source)
            self.assertNotIn("tests/test_fixture.py",
                             json.dumps(seen[1][0]))


if __name__ == "__main__":
    unittest.main()
