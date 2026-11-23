"""No-model, no-host-state tests for Issue #555 one-shot staging."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
import m1_harness_parent555_stage as stage


class FakeAPI:
    def __init__(self, runs):
        self.runs = runs
        self.urls = []
    def repo_path(self, suffix):
        return "/repos/" + stage.REPO + suffix
    def request(self, path):
        self.urls.append(path)
        return {"workflow_runs": self.runs}


class Parent555StageTests(unittest.TestCase):
    def test_exact_base_and_independent_contracts_have_two_distinct_tests(self):
        contracts = stage.reviewed_contracts()
        self.assertEqual(set(contracts), {
            "src/ai_foundation/agent.py",
            "src/ai_foundation/development_loop.py",
        })
        self.assertEqual(len({v["test"] for v in contracts.values()}), 2)
        self.assertTrue(all(len(v["test_sha256"]) == 64 and v["instruction"]
                            for v in contracts.values()))

    def test_model_does_not_start_before_exact_current_ci_is_green(self):
        head = "a" * 40
        old = "b" * 40
        api = FakeAPI([
            {"id": 10, "name": "Foundation CI", "head_sha": old,
             "status": "completed", "conclusion": "success"},
            {"id": 11, "name": "Foundation CI", "head_sha": head,
             "status": "in_progress", "conclusion": None},
        ])
        with patch.dict(os.environ, {"PR_HEAD_SHA": head}):
            with self.assertRaises(stage.DeferredCiNotGreen):
                stage._require_current_head_green(api)
        self.assertEqual(len(api.urls), 1)
        api.runs[1].update(status="completed", conclusion="success")
        with patch.dict(os.environ, {"PR_HEAD_SHA": head}):
            stage._require_current_head_green(api)
        with patch.dict(os.environ, {"PR_HEAD_SHA": "../../other"}):
            with self.assertRaisesRegex(ValueError, "OWNER_GITHUB_HEAD_NOT_PINNED"):
                stage._require_current_head_green(api)

    def test_latest_same_head_ci_must_be_green_not_older_success(self):
        head = "c" * 40
        old_green = {"id": 100, "name": "Foundation CI",
                     "head_sha": head, "status": "completed",
                     "conclusion": "success"}
        new_run = {"id": 101, "name": "Foundation CI",
                   "head_sha": head, "status": "in_progress",
                   "conclusion": None}
        api = FakeAPI([old_green, new_run])
        with patch.dict(os.environ, {"PR_HEAD_SHA": head}):
            with self.assertRaises(stage.DeferredCiNotGreen):
                stage._require_current_head_green(api)
            new_run.update(status="completed", conclusion="failure")
            with self.assertRaises(stage.DeferredCiNotGreen):
                stage._require_current_head_green(api)
            new_run["conclusion"] = "success"
            stage._require_current_head_green(api)
            # Unordered API results cannot promote a stale green run.
            api.runs = [new_run, {**old_green, "id": 102,
                                 "status": "queued", "conclusion": None}]
            with self.assertRaises(stage.DeferredCiNotGreen):
                stage._require_current_head_green(api)

    def test_missing_ci_run_identity_fails_closed(self):
        head = "d" * 40
        api = FakeAPI([{"name": "Foundation CI", "head_sha": head,
                        "status": "completed", "conclusion": "success"}])
        with patch.dict(os.environ, {"PR_HEAD_SHA": head}):
            with self.assertRaisesRegex(ValueError, "CURRENT_FOUNDATION_CI_UNAVAILABLE"):
                stage._require_current_head_green(api)

    def test_automatic_wait_rechecks_only_pre_model_deferrals(self):
        from ai_foundation.host_compute_lease import HostComputeBusy
        with patch.object(stage, "_stage_one", side_effect=[
            HostComputeBusy("HOST_COMPUTE_LEASE_BUSY"),
            stage.DeferredCiNotGreen(),
            {"status": "PLAN_STAGED", "model_invoked": True},
        ]) as run, patch.object(stage.time, "sleep") as sleep:
            value = stage._stage_when_available(max_wait_s=600, poll_s=30)
        self.assertEqual(value["status"], "PLAN_STAGED")
        self.assertEqual(run.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(sleep.call_args_list[0].args, (30.0,))

    def test_long_busy_defers_without_repeating_or_ignoring_errors(self):
        from ai_foundation.host_compute_lease import HostComputeBusy
        with patch.object(stage, "_stage_one",
                          side_effect=HostComputeBusy("BUSY")) as run, \
             patch.object(stage.time, "sleep") as sleep:
            with self.assertRaises(HostComputeBusy):
                stage._stage_when_available(max_wait_s=0)
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()
        # Model errors and uncertain writes are NOT pre-model transient busy.
        with patch.object(stage, "_stage_one",
                          side_effect=RuntimeError("UNKNOWN_REMOTE_RESULT")) as run, \
             patch.object(stage.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError):
                stage._stage_when_available(max_wait_s=600)
        self.assertEqual(run.call_count, 1)
        sleep.assert_not_called()
        with self.assertRaisesRegex(ValueError, "INVALID_STAGE_RETRY_BOUNDS"):
            stage._stage_when_available(max_wait_s=1800)

    def test_failed_model_handoff_is_classified_and_never_auto_retried(self):
        import json
        stage.STAGE_PHASE = "MODEL_HANDOFF"
        stage.MODEL_HANDOFF_ATTEMPTED = True
        output = StringIO()
        with patch.object(stage, "_stage_when_available",
                          side_effect=RuntimeError("HARNESS_ROLE_EXIT_NONZERO")), \
             redirect_stdout(output):
            assert stage.main(["--stage-one"]) == 2
        data = json.loads(output.getvalue().split("HARNESS_PARENT555_STAGE=", 1)[1])
        assert data["status"] == "BLOCKED"
        assert data["reason"] == "HARNESS_ROLE_EXIT_NONZERO"
        assert data["phase"] == "MODEL_HANDOFF"
        assert data["model_handoff_attempted"] is True
        assert data["retry_authorized"] is False

    def test_untrusted_exception_text_never_leaks_to_public_receipt(self):
        output = StringIO()
        with patch.object(stage, "_stage_when_available",
                          side_effect=RuntimeError("private secret message")), \
             redirect_stdout(output):
            assert stage.main(["--stage-one"]) == 2
        assert "private secret" not in output.getvalue()
        assert '"reason": "RUNTIMEERROR"' in output.getvalue()

    def test_owner_config_is_single_create_exact_readback_not_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            cfg = home / "config.json"
            original = b'{"schema":"host"}\n'
            with patch.object(stage, "PRIVATE", home), \
                 patch.object(stage, "OWNER_CONFIG", cfg):
                sha = stage._store_exact_config(original)
                self.assertEqual(sha, stage._digest(original))
                self.assertEqual(cfg.read_bytes(), original)
                self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)
                self.assertEqual(stage._store_exact_config(original), sha)
                with self.assertRaisesRegex(
                        ValueError, "OWNER_CONFIG_PREVIOUS_VERSION_DRIFT"):
                    stage._store_exact_config(b'{"schema":"other"}\n')
                self.assertEqual(cfg.read_bytes(), original)
                cfg.unlink()
                cfg.symlink_to(home / "missing")
                with self.assertRaises(ValueError):
                    stage._store_exact_config(original)


    def test_owner_staged_plan_publishes_and_admits_one_without_model(self):
        from unittest.mock import call
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_file = home / "owner-config.json"
            plan_file = home / "owner-plan.json"
            config_file.write_text('{"source":"owner-pinned"}')
            plan_file.write_text('{"proposal":"immutable"}')
            config_file.chmod(0o600)
            plan_file.chmod(0o600)
            owner_config = {
                "parent_issue": 555, "base": stage.BASE,
                "base_sha": stage.BASE_SHA,
                "reviewed_contracts": stage.reviewed_contracts(),
            }
            proposal = {"proposal_sha256": "a" * 64}
            class OwnerAPI:
                def __init__(self, *_):
                    pass
                def repo_path(self, suffix):
                    return "/repos/" + stage.REPO + suffix
                def request(self, path):
                    assert path.endswith("/commits/main")
                    return {"sha": "c" * 40}
            with patch.object(stage, "OWNER_CONFIG", config_file), \
                 patch.object(stage, "OWNER_PLAN", plan_file), \
                 patch.object(stage, "GitHubAPI", OwnerAPI), \
                 patch.object(stage, "load_host_config", return_value=owner_config), \
                 patch.object(stage, "_load_plan_receipt", return_value=proposal), \
                 patch.object(stage, "_require_current_head_green") as require_ci, \
                 patch.object(stage, "verify_host_baseline", return_value=owner_config["reviewed_contracts"]), \
                 patch.object(stage, "verify_parent_scope"), \
                 patch.object(stage, "run_one", side_effect=[
                     {"status": "CHILD_ISSUE_CREATED_UNAPPROVED"},
                     {"status": "INDEPENDENT_CHILD_READY_FOR_EXISTING_WORKER"},
                 ]) as handoff, \
                 patch.dict(os.environ, {"GITHUB_TOKEN": "synthetic", "PR_HEAD_SHA": "c" * 40}):
                result = stage._publish_and_admit_one()
            assert result["publication"] == "CHILD_ISSUE_CREATED_UNAPPROVED"
            assert result["admission"] == "INDEPENDENT_CHILD_READY_FOR_EXISTING_WORKER"
            assert result["model_invoked"] is False
            assert result["worker_invoked"] is False
            assert handoff.call_count == 2
            assert handoff.call_args_list[0].kwargs["publish"] is True
            assert handoff.call_args_list[1].kwargs["admit"] is True
            assert handoff.call_args_list[0].kwargs["proposal_receipt"] is proposal
            assert handoff.call_args_list[1].kwargs["proposal_receipt"] is proposal
            assert (home / "owner-config.json.publish.lock").stat().st_mode & 0o777 == 0o600
            require_ci.assert_called_once()

    def test_missing_frozen_plan_never_creates_child_or_runs_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            config_file = home / "owner-config.json"
            config_file.write_text('{"schema":"synthetic"}')
            config_file.chmod(0o600)
            class OwnerAPI:
                def __init__(self, *_):
                    pass
                def repo_path(self, suffix):
                    return "/repos/" + stage.REPO + suffix
                def request(self, path):
                    return {"sha": "c" * 40}
            with patch.object(stage, "OWNER_CONFIG", config_file), \
                 patch.object(stage, "OWNER_PLAN", home / "missing-plan.json"), \
                 patch.object(stage, "GitHubAPI", OwnerAPI), \
                 patch.object(stage, "load_host_config", return_value={
                     "parent_issue": 555, "base": stage.BASE,
                     "base_sha": stage.BASE_SHA,
                     "reviewed_contracts": stage.reviewed_contracts()}), \
                 patch.object(stage, "_require_current_head_green"), \
                 patch.object(stage, "run_one") as handoff, \
                 patch.dict(os.environ, {"GITHUB_TOKEN": "synthetic", "PR_HEAD_SHA": "c" * 40}):
                with self.assertRaises(ValueError):
                    stage._publish_and_admit_one()
                handoff.assert_not_called()

    def test_live_workflow_routes_only_owner_labeled_parent_not_closed_pr524(self):
        workflow = (ROOT / ".github/workflows/dev-autonomy-intake.yml").read_text()
        start = workflow.index("  m1-harness-parent-profile-preflight:")
        end = workflow.index("  m1-worker-layout-diagnosis:")
        specific = workflow[start:end]
        assert "github.event.issue.number == 555" in specific
        assert specific.count("foundation-harness-parent555-stage-once:v1") == 3
        assert "github.event.issue.user.login == 'quest7070-debug'" in specific
        assert "github.event.comment.user.login == 'quest7070-debug'" in specific
        assert "github.event.comment.body == 'foundation-harness-parent555-stage-once:v1'" in specific
        assert "github.actor == 'quest7070-debug'" in specific
        assert "issue_comment:" in workflow
        assert "github.event.pull_request.number == 524" not in specific
        assert "needs.m1-harness-parent555-stage.outputs.plan_staged == 'true'" in specific
        assert "--publish-and-admit-one" in specific



    def test_failed_stage_prints_safe_receipt_and_does_not_admit_child(self):
        """Fail-closed one-shot must preserve sanitized cause, not suppress it."""
        import subprocess
        workflow = (ROOT / ".github/workflows/dev-autonomy-intake.yml").read_text()
        stage_job = workflow.split("  m1-harness-parent555-stage:\n", 1)[1].split(
            "  m1-harness-parent555-child-once:\n", 1)[0]
        assert 'receipt="$(python3 -B scripts/m1_harness_parent555_stage.py --stage-one)" || {' in stage_job
        assert 'stage_exit=$?' in stage_job
        assert 'exit "$stage_exit"' in stage_job
        assert 'printf \'%s\\n\' "$receipt"' in stage_job
        # Exercise bash -e behavior with an inert failing synthetic command.
        # No model or owner file is touched.
        script = (
            "set -euo pipefail\n"
            "receipt=\"$(printf 'HARNESS_PARENT555_STAGE=BLOCKED\\n'; exit 2)\" || {\n"
            "  stage_exit=$?\n"
            "  printf '%s\\n' \"$receipt\"\n"
            "  exit \"$stage_exit\"\n"
            "}\n"
            "echo SHOULD_NOT_ADMIT_CHILD\n"
        )
        result = subprocess.run(["bash", "-c", script], capture_output=True,
                                text=True, check=False)
        assert result.returncode == 2
        assert "HARNESS_PARENT555_STAGE=BLOCKED" in result.stdout
        assert "SHOULD_NOT_ADMIT_CHILD" not in result.stdout


if __name__ == "__main__":
    unittest.main()
