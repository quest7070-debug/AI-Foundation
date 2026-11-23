"""No-model, exact policy contract tests for autonomous task picking."""
from pathlib import Path
import ast
import json
import os
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import local9b_issue_bridge as bridge
import local9b_task_selection as selection


def issue(number, *labels, recipe="python-fixed-test"):
    if recipe == "python-fixed-test":
        task = ('{"recipe":"python-fixed-test","base":"main",'
                '"base_sha":"' + "a"*40 + '",'
                '"target":"src/ai_foundation/core.py",'
                '"test":"tests/test_core.py",'
                '"test_sha256":"' + "f"*64 + '",'
                '"instruction":"Repair a verified failing fixed test."}')
    else:
        task = ('{"recipe":"bounded-http-positive-limit",'
                '"base":"main","field":"request_queue_size"}')
    return {
        "number": number, "state": "OPEN",
        "updatedAt": "2026-11-07T10:00:00Z",
        "labels": [{"name": bridge.READY_LABEL}] +
                  [{"name": name} for name in labels],
        "body": "Approved task\n```foundation-autodev-task\n" + task + "\n```",
    }


class TaskPolicyTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.inbox = self.root / "inbox"
        self.inbox.mkdir()
        (self.root / "results").mkdir()

    def intake(self, issues):
        with patch.object(bridge, "_gh", return_value=issues):
            return bridge.collect_ready(self.inbox)

    def test_default_is_p2_without_model_or_issue_text_ranking(self):
        rows = self.intake([issue(300), issue(200)])
        self.assertEqual([r["issue"] for r in rows], [200, 300])
        self.assertEqual([r["priority"] for r in rows], ["P2", "P2"])
        self.assertEqual(rows[0]["policy_version"], selection.POLICY_VERSION)

    def test_explicit_priority_beats_issue_number_and_api_order(self):
        rows = self.intake([
            issue(99, "foundation-autodev:p3"),
            issue(500, "foundation-autodev:p0"),
            issue(200, "foundation-autodev:p1"),
        ])
        self.assertEqual([r["issue"] for r in rows], [500, 200, 99])
        self.assertEqual([r["priority"] for r in rows], ["P0","P1","P3"])

    def test_pinned_regression_outweighs_legacy_smoke_at_same_priority(self):
        rows = self.intake([issue(1, recipe="bounded-http-positive-limit"), issue(90)])
        self.assertEqual([r["issue"] for r in rows], [90, 1])
        self.assertEqual(rows[0]["evidence_gate"],
                         "PINNED_TEST_BASELINE_REPRO_REQUIRED")
        self.assertEqual(rows[1]["evidence_gate"],
                         "HOST_FIXED_SMOKE_BASELINE_REPRO_REQUIRED")

    def test_explicit_hold_refuses_to_enqueue(self):
        rows = self.intake([issue(300,"foundation-autodev:hold")])
        self.assertEqual(rows[0]["status"], "HELD")
        self.assertEqual(rows[0]["reason"], "EXPLICIT_HOLD_LABEL")
        self.assertEqual(list(self.inbox.iterdir()), [])

    def test_conflicting_priority_requires_review(self):
        rows = self.intake([issue(300,"foundation-autodev:p0","foundation-autodev:p2")])
        self.assertEqual(rows[0]["status"], "NEEDS_PRIORITY_REVIEW")
        self.assertEqual(list(self.inbox.iterdir()), [])

    def test_duplicate_prior_receipt_blocks_at_any_priority(self):
        first = issue(300)
        receipt = self.root / "results" / (bridge.issue_task(first)["id"] + ".json")
        receipt.write_text('{"status":"DRAFT_PR_PRESENTED"}')
        rows = self.intake([issue(300, "foundation-autodev:p0"), issue(301)])
        self.assertEqual(rows[0]["issue"], 301)
        self.assertEqual(rows[1]["status"], "ALREADY_ATTEMPTED")
        self.assertEqual(list(self.inbox.iterdir())[0].name.startswith("issue-301-"), True)

    def test_revoked_hold_rejected_even_after_task_was_queued(self):
        approved = issue(300)
        task = bridge.issue_task(approved)
        later = issue(300, "foundation-autodev:hold")
        with patch.object(bridge, "_gh", return_value=later):
            with self.assertRaisesRegex(ValueError,"ISSUE_SELECTION_POLICY_CHANGED"):
                bridge.resolve_task(task)

    def test_no_ready_label_never_grants_authority(self):
        raw = issue(300)
        raw["labels"] = [{"name":"foundation-autodev:p0"}]
        with self.assertRaisesRegex(ValueError,"ISSUE_NOT_READY"):
            bridge.issue_task(raw)

    def test_selection_only_yields_valid_currently_queued_ids(self):
        rows = self.intake([issue(300), issue(400,"foundation-autodev:hold")])
        self.assertEqual(list(selection.queued_tasks(rows)), [bridge.issue_task(issue(300))["id"]])
        with self.assertRaisesRegex(ValueError,"UNTRUSTED_EXECUTION_QUEUE"):
            list(selection.queued_tasks([{"status":"QUEUED","task":"issue-1-../../secrets"}]))

    def test_untrusted_labels_fail_closed(self):
        x=issue(300)
        x["labels"]=[{"name":bridge.READY_LABEL}, "not-a-structured-label"]
        self.assertEqual(self.intake([x])[0]["status"],"NEEDS_SCOPED_CONTRACT")
        self.assertEqual(list(self.inbox.iterdir()), [])

    def test_worker_receipt_write_is_private_atomic_and_symlink_safe(self):
        # Extract the real worker helper without importing Native/DSH model
        # modules; the test verifies actual source behavior, not a reimplementation.
        worker = (Path(__file__).resolve().parents[1] /
                  "scripts/local9b_autodev_worker.py").read_text()
        definition = next(n for n in ast.parse(worker).body
                          if isinstance(n, ast.FunctionDef) and n.name == "write_result")
        context = {"Path": Path, "os": os, "tempfile": tempfile, "json": json}
        exec(compile(ast.Module(body=[definition], type_ignores=[]),
                     "<worker-write-result>", "exec"), context)
        save = context["write_result"]
        root = self.root / "results"
        receipt = root / "intake.json"
        prior = os.umask(0)
        try:
            save(receipt, {"status": "SUCCESS", "diagnostic": "PRIVATE_SOURCE"})
        finally:
            os.umask(prior)
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        self.assertEqual(json.loads(receipt.read_text())["diagnostic"], "PRIVATE_SOURCE")
        self.assertEqual(set(root.iterdir()), {receipt})

        receipt.chmod(0o644)
        save(receipt, {"status": "PARTIAL_SUCCESS"})
        self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
        self.assertEqual(json.loads(receipt.read_text())["status"], "PARTIAL_SUCCESS")
        self.assertEqual(set(root.iterdir()), {receipt})

        private = self.root / "private-owner-file"
        private.write_text("UNCHANGED")
        receipt.unlink()
        receipt.symlink_to(private)
        with self.assertRaisesRegex(ValueError, "UNTRUSTED_RESULT_PATH"):
            save(receipt, {"status": "BLOCKED"})
        self.assertEqual(private.read_text(), "UNCHANGED")
        self.assertEqual(set(root.iterdir()), {receipt})

    def test_worker_stdout_is_safe_even_when_private_receipt_contains_error(self):
        import re
        worker = (Path(__file__).resolve().parents[1] /
                  "scripts/local9b_autodev_worker.py").read_text()
        definition = next(node for node in ast.parse(worker).body
                          if isinstance(node, ast.FunctionDef)
                          and node.name == "public_result_status")
        scope = {"re": re}
        exec(compile(ast.Module(body=[definition], type_ignores=[]),
                     "<worker-public-status>", "exec"), scope)
        public = scope["public_result_status"]
        detailed = {"status": "STOPPED", "work": "/PRIVATE/OWNER/PATH",
                    "detail": "SYNTHETIC_OWNER_SECRET",
                    "error_type": "RuntimeError"}
        result = public(detailed)
        self.assertEqual(result, {"status": "STOPPED", "private_receipt_saved": True})
        self.assertNotIn("PRIVATE", json.dumps(result))
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertEqual(public({"status": "BAD\\nOWNER_SECRET"})["status"], "UNVERIFIED")
        self.assertIn("print(json.dumps(public_result_status(result)", worker)
        self.assertNotIn("print(json.dumps(result),flush=True)", worker)

    def test_scheduled_worker_selects_verified_operator_not_remote_tunnel(self):
        worker = (Path(__file__).resolve().parents[1] /
                  "scripts/local9b_autodev_worker.py").read_text()
        scheduled = next(n for n in ast.parse(worker).body
                         if isinstance(n, ast.FunctionDef)
                         and n.name == "scheduled_owner_cycle")
        source = ast.unparse(scheduled)
        self.assertIn("_installed_live_source_repo(_owner_local_repo())", source)
        self.assertNotIn("active_client_pids", source)
        self.assertNotIn("previous_agent", source)
        self.assertIn("--scheduled-cycle", source)

    def test_worker_advances_local_work_before_any_github_intake(self):
        # Execute the actual main body without loading model dependencies.
        worker = (Path(__file__).resolve().parents[1] /
                  "scripts/local9b_autodev_worker.py").read_text()
        definition = next(node for node in ast.parse(worker).body
                          if isinstance(node, ast.FunctionDef)
                          and node.name == "main")
        for state in ("VERIFIED_LOCAL", "SCOPE_APPROVAL_REQUIRED",
                      "SCHEDULED_CYCLE_BLOCKED", "DISCOVERY_REQUEST_RECORDED"):
            calls = []
            context = {"STATE_ROOT": self.root, "json": json,
                       "scheduled_owner_cycle": lambda: (calls.append("local") or
                                                          {"state": state}),
                       "write_result": lambda path, row: calls.append((path.name, row)),
                       "print": lambda *args, **kwargs: None,
                       "__builtins__": {**__import__("builtins").__dict__,
                           "__import__": lambda *args, **kwargs: self.fail(
                               "remote intake must not be entered after local work")}}
            exec(compile(ast.Module(body=[definition], type_ignores=[]),
                         "<worker-main>", "exec"), context)
            context["main"]()
            self.assertEqual(calls, ["local", ("scheduled-code-cycle.json",
                                               {"state": state})])
        self.assertLess(worker.index("cycle=scheduled_owner_cycle()"),
                        worker.index("intake=collect_ready("))
        self.assertNotIn("scan_standing_main_regressions(STATE_ROOT)", worker)

    def test_worker_runs_ranked_queue_once_and_never_inbox_glob(self):
        worker = (Path(__file__).resolve().parents[1] /
                  "scripts/local9b_autodev_worker.py").read_text()
        compile(worker,"local9b_autodev_worker.py","exec")
        self.assertIn("for task_id in queued_tasks(intake):",worker)
        self.assertIn("break  # one consumed task per tick",worker)
        self.assertNotIn('for path in sorted((ROOT/"inbox").glob("*.json"))',worker)
        self.assertIn('candidate_status="BLOCKED:"+type(e).__name__',worker)


if __name__ == "__main__":
    unittest.main()
