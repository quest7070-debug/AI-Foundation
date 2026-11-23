from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import dev_autonomy_intake as intake


class FakeAPI:
    def __init__(self):
        self.calls = []

    def repo_path(self, suffix):
        return "/repos/test/repo" + suffix

    def request(self, path, method="GET", payload=None):
        self.calls.append((path, method, payload))
        if path.startswith("/repos/test/repo/issues?"):
            return [
                {"number": 1, "title": "Approved task", "body": "bounded objective",
                 "html_url": "https://github.com/test/repo/issues/1",
                 "updated_at": "2026-10-30T00:00:00Z",
                 "created_at": "2026-10-29T23:00:00Z",
                 "labels": [{"name": "foundation-autodev:ready"}]},
                {"number": 2, "title": "PR masquerading as issue", "body": "",
                 "pull_request": {"url": "api"}, "labels": []},
                {"number": 3, "title": "Unapproved task", "body": "do not run",
                 "html_url": "https://github.com/test/repo/issues/3",
                 "updated_at": "2026-10-30T00:00:00Z", "labels": []},
            ]
        if path.startswith("/repos/test/repo/actions/runs?"):
            return {"workflow_runs": [
                {"id": 9, "name": "CI", "conclusion": "failure",
                 "updated_at": "2026-10-30T00:00:00Z", "head_branch": "feature",
                 "event": "pull_request", "html_url": "https://github.com/test/repo/actions/runs/9"},
                {"id": 8, "name": "old CI", "conclusion": "failure",
                 "updated_at": "2026-10-01T00:00:00Z"},
                {"id": 7, "name": "Successful CI", "conclusion": "success",
                 "updated_at": "2026-10-29T23:00:00Z", "head_branch": "fixed",
                 "html_url": "https://github.com/test/repo/actions/runs/7"},
            ]}
        if path.startswith("/repos/test/repo/actions/runs/9/jobs?"):
            return {"jobs": [{"name": "unit", "conclusion": "failure",
                              "steps": [{"name": "pytest", "conclusion": "failure"}]}]}
        if path.startswith("/repos/test/repo/pulls?state=open"):
            return [{"number": 4, "title": "Open PR", "html_url": "https://github.com/test/repo/pull/4",
                     "draft": True, "head": {"ref": "branch", "sha": "a" * 40},
                     "updated_at": "2026-10-30T00:00:00Z"}]
        if path.startswith("/repos/test/repo/pulls?state=closed"):
            return [
                {"number": 5, "title": "Merged PR", "html_url": "https://github.com/test/repo/pull/5",
                 "merged_at": "2026-10-29T23:00:00Z", "updated_at": "2026-10-29T23:00:00Z",
                 "head": {"ref": "feature", "sha": "b" * 40}},
                {"number": 6, "title": "Old merged PR", "html_url": "https://github.com/test/repo/pull/6",
                 "merged_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z",
                 "head": {"ref": "old", "sha": "c" * 40}},
            ]
        raise AssertionError(path)


def make_plan(*items):
    return {"status": "READY", "summary": "bounded plan", "items": list(items)}


def plan_item(source_key, depends_on=None, risk="low", group="lane-a"):
    return {
        "source_key": source_key,
        "priority": "P1",
        "rationale": "specific reason",
        "depends_on": depends_on or [],
        "parallel_group": group,
        "risk": risk,
    }


class DevAutonomyIntakeTests(unittest.TestCase):
    def test_existing_worker_does_not_require_legacy_paseo_gate(self):
        report = intake.build_report("quest7070-dev/AI-Foundation", [], [], None,
                                     "DETERMINISTIC_NO_READY_ISSUES", "none")
        self.assertTrue(report["execution_gate"].startswith("READY_ISSUE_WORKER_SEPARATE:"))
        self.assertFalse(report["safety"]["worker_execution"])
        self.assertNotIn("PASEO", report["execution_gate"])

    def test_github_repository_validation(self):
        with self.assertRaisesRegex(intake.IntakeError, "REPOSITORY_INVALID"):
            intake.GitHubAPI("token", "../wrong")
        with self.assertRaisesRegex(intake.IntakeError, "TOKEN_MISSING"):
            intake.GitHubAPI("", "owner/repo")
        with self.assertRaisesRegex(intake.IntakeError, "OFFICIAL_HTTPS"):
            intake.GitHubAPI("token", "owner/repo", "http://api.github.com")

    def test_collect_signals_filters_pull_requests_and_old_failures(self):
        api = FakeAPI()
        signals, pulls, completed_prs, successful_ci = intake.collect_signals(
            api, now=datetime(2026, 10, 30, tzinfo=timezone.utc),
        )
        self.assertEqual({s.source_key for s in signals}, {"issue:1", "issue:3", "ci:9"})
        self.assertTrue(next(s for s in signals if s.source_key == "issue:1").autodev_ready)
        self.assertFalse(next(s for s in signals if s.source_key == "issue:3").autodev_ready)
        self.assertEqual(pulls[0].number, 4)
        self.assertEqual([p.number for p in completed_prs], [5])
        self.assertEqual([row["run_id"] for row in successful_ci], [7])
        self.assertTrue(any("/actions/runs/9/jobs" in path for path, _, _ in api.calls))
        self.assertFalse(any("/actions/runs/8/jobs" in path for path, _, _ in api.calls))

    def test_ci_discovery_survives_more_than_thirty_unrelated_runs(self):
        class BusyCI(FakeAPI):
            def request(self, path, method="GET", payload=None):
                if path.startswith("/repos/test/repo/actions/runs?"):
                    self.calls.append((path, method, payload))
                    return {"workflow_runs": [
                        {"id": 1000 - i, "workflow_id": 500 + i,
                         "name": "unrelated CI", "head_branch": f"feature-{i}",
                         "conclusion": "success",
                         "updated_at": "2026-10-30T01:00:00Z"}
                        for i in range(40)
                    ] + [{
                        "id": 90, "workflow_id": 42, "name": "Foundation CI",
                        "head_branch": "useful-regression",
                        "head_sha": "a" * 40, "event": "push",
                        "conclusion": "failure",
                        "updated_at": "2026-10-30T00:59:00Z",
                        "html_url": "https://github.com/test/repo/actions/runs/90",
                    }]}
                if "/actions/runs/90/jobs?" in path:
                    self.calls.append((path, method, payload))
                    return {"jobs": [{
                        "name": "unit", "conclusion": "failure",
                        "steps": [{"name": "pytest", "conclusion": "failure"}],
                    }]}
                return super().request(path, method, payload)

        api = BusyCI()
        signals, _, _, _ = intake.collect_signals(
            api, now=datetime(2026, 10, 30, 2, tzinfo=timezone.utc))
        self.assertEqual([s.source_key for s in signals if s.kind == "ci_failure"],
                         ["ci:90"])
        self.assertTrue(any("/actions/runs?per_page=100" in path
                            for path, _, _ in api.calls))
        self.assertEqual(len([c for c in api.calls if
                              "/actions/runs?" in c[0]]), 1)

    def test_plan_rejects_unknown_source_and_duplicate(self):
        known = {"issue:1": intake.Signal("issue:1", "issue", "a", "", "", "", ("foundation-autodev:ready",), True)}
        with self.assertRaisesRegex(intake.IntakeError, "UNKNOWN_OR_DUPLICATE"):
            intake.validate_plan(make_plan(plan_item("issue:999")), known)
        with self.assertRaisesRegex(intake.IntakeError, "UNKNOWN_OR_DUPLICATE"):
            intake.validate_plan(make_plan(plan_item("issue:1"), plan_item("issue:1")), known)

    def test_plan_rejects_dependency_cycle(self):
        known = {
            "issue:1": intake.Signal("issue:1", "issue", "a", "", "", ""),
            "issue:2": intake.Signal("issue:2", "issue", "b", "", "", ""),
        }
        with self.assertRaisesRegex(intake.IntakeError, "DEPENDENCY_CYCLE"):
            intake.validate_plan(make_plan(
                plan_item("issue:1", ["issue:2"]),
                plan_item("issue:2", ["issue:1"]),
            ), known)

    def test_model_can_propose_but_never_authorize_execution(self):
        known = {
            "issue:1": intake.Signal("issue:1", "issue", "ready", "", "", "", ("foundation-autodev:ready",), True),
            "issue:2": intake.Signal("issue:2", "issue", "not ready", "", "", ""),
        }
        checked = intake.validate_plan(make_plan(
            plan_item("issue:1", risk="low"),
            plan_item("issue:2", risk="low"),
        ), known)
        self.assertTrue(checked["items"][0]["dispatch_candidate"])
        self.assertFalse(checked["items"][0]["execution_authorized"])
        self.assertFalse(checked["items"][1]["dispatch_candidate"])
        self.assertFalse(checked["items"][1]["execution_authorized"])

    def test_build_report_never_grants_execution(self):
        report = intake.build_report("test/repo", [], [], None, "HARNESS_ROLE_UNBOUND", "none")
        self.assertIn("READY_ISSUE_WORKER_SEPARATE", report["execution_gate"])
        self.assertIn("cannot grant Guard authority", report["execution_gate"])
        self.assertFalse(report["safety"]["task_submission"])
        self.assertFalse(report["safety"]["worker_execution"])
        self.assertFalse(report["safety"]["merge"])


    def test_report_artifacts_redact_issue_body_and_model_rationale(self):
        signal = intake.Signal(
            "issue:1", "issue", "@everyone <img src=x>",
            "private-body-secret", "https://github.com/test/repo/issues/1", "",
            ("foundation-autodev:ready",), True,
        )
        plan = intake.validate_plan(make_plan({
            "source_key": "issue:1", "priority": "P1",
            "rationale": "model-echoed-secret", "depends_on": [],
            "parallel_group": "lane", "risk": "low",
        }), {"issue:1": signal})
        report = intake.build_report("test/repo", [signal], [], plan, "HARNESS_TRIAGE_PLAN", "none")
        serialized = __import__("json").dumps(report, ensure_ascii=False)
        markdown = intake.render_markdown(report)
        self.assertNotIn("private-body-secret", serialized)
        self.assertNotIn("model-echoed-secret", serialized)
        self.assertNotIn("<img", markdown)
        self.assertNotIn("@everyone", markdown)
        self.assertFalse(report["plan"]["items"][0]["execution_authorized"])
        self.assertFalse(report["plan"]["items"][0]["dispatch_candidate"])


    def test_report_shows_completed_prs_successful_ci_and_open_work(self):
        signal = intake.Signal("issue:1", "issue", "Task", "", "https://github.com/test/repo/issues/1", "",
                               "2026-10-29T23:00:00Z")
        open_pr = intake.PullRequestSignal(4, "Open PR", "https://github.com/test/repo/pull/4",
                                           True, "feature", "a" * 40, "2026-10-30T00:00:00Z")
        merged_pr = intake.PullRequestSignal(5, "Merged PR", "https://github.com/test/repo/pull/5",
                                             False, "feature", "b" * 40, "2026-10-29T23:00:00Z",
                                             "2026-10-29T23:00:00Z")
        successful = [{"run_id": 7, "name": "Successful CI", "branch": "fixed",
                       "url": "https://github.com/test/repo/actions/runs/7",
                       "updated_at": "2026-10-29T23:00:00Z"}]
        report = intake.build_report("test/repo", [signal], [open_pr], None,
                                     "NO_CHANGE", "none", [merged_pr], successful)
        markdown = intake.render_markdown(report)
        self.assertIn("昨夜完了した開発", markdown)
        self.assertIn("Merged PR", markdown)
        self.assertIn("Successful CI", markdown)
        self.assertIn("進行中のPR", markdown)
        self.assertIn("Open PR", markdown)


    def test_ci_report_keeps_only_failed_job_and_step_names(self):
        ci = intake.Signal(
            "ci:9", "ci_failure", "Foundation CI",
            __import__("json").dumps({
                "branch": "feature",
                "failed_jobs": [{
                    "name": "unit",
                    "conclusion": "failure",
                    "failed_steps": ["pytest"],
                    "raw_log": "private raw log secret",
                }],
            }),
            "https://github.com/test/repo/actions/runs/9",
            "2026-10-30T00:00:00Z",
        )
        report = intake.build_report("test/repo", [ci], [], None,
                                     "NO_CHANGE", "none")
        markdown = intake.render_markdown(report)
        serialized = __import__("json").dumps(report, ensure_ascii=False)
        self.assertIn("Failed job", markdown)
        self.assertIn("pytest", markdown)
        self.assertNotIn("private raw log secret", serialized)
        self.assertNotIn("raw_log", serialized)

    def test_publish_refuses_to_overwrite_foreign_marker(self):
        class CommentAPI:
            def repo_path(self, suffix):
                return suffix
            def request(self, path, method="GET", payload=None):
                if method == "GET":
                    return [{"id": 12, "body": intake.REPORT_MARKER, "user": {"login": "human"}}]
                raise AssertionError("must not update a human-owned comment")
        with self.assertRaisesRegex(intake.IntakeError, "OWNERSHIP_MISMATCH"):
            intake.publish_report(CommentAPI(), 7, "report")

    def test_render_report_does_not_claim_execution(self):
        signal = intake.Signal("issue:1", "issue", "Task", "", "https://github.com/test/repo/issues/1", "")
        plan = intake.validate_plan(make_plan(plan_item("issue:1", risk="low")),
                                    {"issue:1": signal})
        report = intake.build_report("test/repo", [signal], [], plan, "HARNESS_TRIAGE_PLAN", "none")
        markdown = intake.render_markdown(report)
        self.assertIn("Paseoへのタスク送信: なし", markdown)
        self.assertIn("Worker起動: なし", markdown)



    def test_opt_in_label_matches_daily_workflow(self):
        workflow = (ROOT / ".github/workflows/dev-autonomy-intake.yml").read_text(encoding="utf-8")
        assert intake.READY_LABEL == "foundation-autodev:ready"
        assert f"github.event.label.name == '{intake.READY_LABEL}'" in workflow


    def test_artifact_quota_is_optional_but_intake_and_issue_publication_are_not(self):
        workflow = (ROOT / ".github/workflows/dev-autonomy-intake.yml").read_text(
            encoding="utf-8")
        collect, artifact = workflow.split(
            "      - name: Publish bounded report artifact\n", 1)
        self.assertIn("--publish-comment", collect)
        self.assertIn("--publish-ci-task-drafts", collect)
        self.assertNotIn("continue-on-error: true", collect)
        self.assertIn(
            "continue-on-error: true\n        uses: actions/upload-artifact@v6",
            artifact)
        self.assertIn("if-no-files-found: error", artifact)


    def test_ci_failure_draft_is_idempotent_and_never_auto_ready(self):
        class DraftAPI:
            def __init__(self):
                self.issues = []
                self.created = []
            def repo_path(self, suffix):
                return "/repos/test/repo" + suffix
            def request(self, path, method="GET", payload=None):
                if path.startswith("/repos/test/repo/issues?state=all"):
                    return list(self.issues)
                if path == "/repos/test/repo/issues" and method == "POST":
                    self.created.append(payload)
                    issue = {"number": len(self.created), "body": payload["body"]}
                    self.issues.append(issue)
                    return {"number": issue["number"], "html_url": "https://github.com/test/repo/issues/99"}
                raise AssertionError((path, method))
        api = DraftAPI()
        signal = intake.Signal(
            "ci:900", "ci_failure", "Foundation CI",
            __import__("json").dumps({
                "workflow_id": 123, "head_sha": "a" * 40, "branch": "feature",
                "failed_jobs": [{"name": "unit", "conclusion": "failure", "failed_steps": ["test step"]}],
            }),
            "https://github.com/test/repo/actions/runs/900", "2026-10-30T00:00:00Z",
        )
        first = intake.publish_ci_failure_task_drafts(api, [signal])
        second = intake.publish_ci_failure_task_drafts(api, [signal])
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(len(api.created), 1)
        self.assertNotIn("labels", api.created[0])
        self.assertIn("NOT labeled foundation-autodev:ready", api.created[0]["body"])
        self.assertIn("a" * 40, api.created[0]["body"])


    def test_newer_success_or_pending_ci_suppresses_old_failure(self):
        for newest_conclusion in ("success", None):
            class CurrentCI(FakeAPI):
                def request(self, path, method="GET", payload=None):
                    if path.startswith("/repos/test/repo/actions/runs?"):
                        return {"workflow_runs": [
                            {"id": 30, "workflow_id": 123,
                             "name": "Foundation CI", "head_branch": "feature",
                             "conclusion": newest_conclusion,
                             "updated_at": "2026-10-30T01:00:00Z"},
                            {"id": 20, "workflow_id": 123,
                             "name": "Foundation CI", "head_branch": "feature",
                             "head_sha": "a" * 40,
                             "conclusion": "failure",
                             "updated_at": "2026-10-30T00:00:00Z"},
                        ]}
                    if "/actions/runs/20/jobs" in path:
                        raise AssertionError("old CI must not be inspected after latest run")
                    return super().request(path, method, payload)
            signals, _, _, _ = intake.collect_signals(
                CurrentCI(), now=datetime(2026, 10, 30, 2, tzinfo=timezone.utc))
            self.assertFalse(any(signal.kind == "ci_failure" for signal in signals))

    def test_latest_persisted_ci_observation_does_not_revert_to_old_failure(self):
        import json
        current = intake.Signal(
            "ci:30", "ci_failure", "CI",
            json.dumps({"workflow_id": 123, "head_sha": "b" * 40,
                        "branch": "feature", "failed_jobs": [
                            {"name": "unit", "conclusion": "failure", "failed_steps": []}
                        ]}),
            "https://github.com/test/repo/actions/runs/30",
            "2026-11-10T02:00:00Z",
        )
        old = intake.Signal(
            "ci:20", "ci_failure", "CI",
            json.dumps({"workflow_id": 123, "head_sha": "a" * 40,
                        "branch": "feature", "failed_jobs": [
                            {"name": "unit", "conclusion": "failure", "failed_steps": []}
                        ]}),
            "https://github.com/test/repo/actions/runs/20",
            "2026-11-10T01:00:00Z",
        )
        class API:
            def __init__(self):
                self.issue = None
                self.posts = []
            def repo_path(self, suffix):
                return suffix
            def request(self, path, method="GET", payload=None):
                if path.startswith("/issues?state=all"):
                    return [self.issue] if self.issue else []
                if path == "/issues" and method == "POST":
                    self.posts.append(payload)
                    self.issue = {"number": 1, "state": "open",
                                  "labels": [], "body": payload["body"]}
                    return {"number": 1, "html_url": "https://github.com/test/repo/issues/1"}
                if path == "/issues/1" and method == "GET":
                    return dict(self.issue)
                if path == "/issues/1" and method == "PATCH":
                    raise AssertionError("never rewind latest observation")
                raise AssertionError((path, method))
        api = API()
        self.assertEqual(intake.publish_ci_failure_task_drafts(api, [old, current]),
                         {"created": 1, "updated": 0, "skipped": 1})
        self.assertEqual(intake.publish_ci_failure_task_drafts(api, [old, current]),
                         {"created": 0, "updated": 0, "skipped": 2})
        self.assertEqual(len(api.posts), 1)
        self.assertIn("/actions/runs/30", api.issue["body"])
        self.assertNotIn("/actions/runs/20", api.issue["body"])

    def test_ready_issue_not_starved_by_recent_diagnostic_backlog(self):
        class BackloggedAPI(FakeAPI):
            def request(self, path, method="GET", payload=None):
                if path.startswith("/repos/test/repo/issues?state=open&per_page=100&labels="):
                    return [{"number": 11, "title": "Approved", "body": "contract",
                             "html_url": "https://github.com/test/repo/issues/11",
                             "labels": [{"name": intake.READY_LABEL}]}]
                if path.startswith("/repos/test/repo/issues?state=open&per_page=100&sort="):
                    return [{"number": n, "title": "Diagnostic", "body": "not approved",
                             "html_url": f"https://github.com/test/repo/issues/{n}",
                             "labels": []} for n in range(100, 30, -1)]
                return super().request(path, method, payload)
        signals, _, _, _ = intake.collect_signals(
            BackloggedAPI(), now=datetime(2026, 10, 30, tzinfo=timezone.utc))
        self.assertEqual(len([s for s in signals if s.kind == "issue"]), intake.MAX_ISSUES)
        self.assertIn("issue:11", [s.source_key for s in signals])
        self.assertTrue(next(s for s in signals if s.source_key == "issue:11").autodev_ready)
        self.assertEqual(len({s.source_key for s in signals}), len(signals))

    def test_harness_triage_has_no_direct_model_or_authority(self):
        import json
        signal = intake.Signal(
            "issue:7", "issue", "Fix regression", "Bounded local task",
            "https://github.com/test/repo/issues/7", "",
            labels=(intake.READY_LABEL,), autodev_ready=True,
        )
        class Roles:
            def __init__(self, answer):
                self.answer, self.calls = answer, []
            def invoke(self, role, prompt):
                self.calls.append((role, prompt))
                return self.answer
        roles = Roles(json.dumps(make_plan(plan_item("issue:7"))))
        plan, status = intake.plan_with_harness([signal], [], roles)
        self.assertEqual(status, "HARNESS_TRIAGE_PLAN")
        self.assertEqual(roles.calls[0][0], "triage")
        self.assertIn("issue:7", roles.calls[0][1])
        self.assertFalse(plan["items"][0]["execution_authorized"])
        self.assertTrue(plan["items"][0]["dispatch_candidate"])

        roles.answer = json.dumps(make_plan(plan_item("issue:999")))
        self.assertEqual(intake.plan_with_harness([signal], [], roles)[1],
                         "HARNESS_TRIAGE_INVALID")
        roles.answer = '{"status":"READY","status":"READY","summary":"x","items":[]}'
        self.assertEqual(intake.plan_with_harness([signal], [], roles)[1],
                         "HARNESS_TRIAGE_INVALID")

    def test_harness_transport_failure_keeps_observation_alive(self):
        signal = intake.Signal(
            "issue:7", "issue", "Known Task", "untrusted body",
            "https://github.com/test/repo/issues/7", "",
            labels=(intake.READY_LABEL,), autodev_ready=True,
        )
        class OfflineHarness:
            def invoke(self, role, prompt):
                raise RuntimeError("model temporarily busy")
        plan, status = intake.plan_with_harness([signal], [], OfflineHarness())
        self.assertIsNone(plan)
        self.assertEqual(status, "HARNESS_TRIAGE_UNAVAILABLE")
        report = intake.build_report("test/repo", [signal], [], plan, status, "harness-managed")
        self.assertEqual(report["counts"]["issues"], 1)
        self.assertFalse(report["safety"]["task_submission"])

    def test_harness_role_requires_explicit_owner_binding(self):
        import os
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(intake._trusted_harness_roles_from_env())
        with patch.dict(os.environ, {"FOUNDATION_HARNESS_TRIAGE_CONFIG_JSON":
                                    '{"argv":["/bin/sh","-c","echo fake"],"cwd":"/tmp","timeout_s":5}'}, clear=True):
            with self.assertRaisesRegex(intake.IntakeError, "HARNESS_HOST_CONFIG_INVALID"):
                intake._trusted_harness_roles_from_env()

    def test_deterministic_triage_prioritizes_approved_without_inference(self):
        def issue(number, *labels):
            return intake.Signal(
                f"issue:{number}", "issue", f"Task {number}", "ignored",
                f"https://github.com/test/repo/issues/{number}", "",
                labels=tuple(labels), autodev_ready=intake.READY_LABEL in labels,
            )
        signals = [
            issue(91, intake.READY_LABEL),
            issue(7, intake.READY_LABEL, "foundation-autodev:p1"),
            issue(3, intake.READY_LABEL, "foundation-autodev:hold"),
            issue(4, intake.READY_LABEL, "foundation-autodev:p0", "foundation-autodev:p2"),
            issue(5),
        ]
        plan, status = intake.deterministic_plan(signals)
        self.assertEqual(status, "DETERMINISTIC_READY_TRIAGE")
        self.assertEqual([row["source_key"] for row in plan["items"]], ["issue:7", "issue:91"])
        self.assertEqual([row["priority"] for row in plan["items"]], ["P1", "P2"])
        report = intake.build_report("test/repo", signals, [], plan, status, "none")
        self.assertEqual(report["safety"]["planning_route"], "deterministic")
        self.assertTrue(all(not row["execution_authorized"] for row in report["plan"]["items"]))
        self.assertEqual(intake.deterministic_plan([issue(5)])[1],
                         "DETERMINISTIC_NO_READY_ISSUES")

    def test_ci_failure_coalesces_into_legacy_open_diagnostic_issue(self):
        import json
        old_body = (
            "<!-- foundation-autodev-ci-task:v1:" + "a" * 64 + " -->\n\n"
            "- Workflow run: https://github.com/test/repo/actions/runs/5\n"
            "- Branch: feature\n- Commit: " + "a" * 40 + "\n"
            "- Workflow ID: 123\n"
        )

        class DraftAPI:
            def __init__(self):
                self.issue = {"number": 48, "state": "open", "labels": [],
                              "body": old_body, "user": {"login": "github-actions[bot]"},
                              "created_at": "2026-11-09T00:00:00Z",
                              "updated_at": "2026-11-09T00:00:00Z"}
                self.patches = []
                self.creates = []
            def repo_path(self, suffix):
                return "/repos/test/repo" + suffix
            def request(self, path, method="GET", payload=None):
                if path.startswith("/repos/test/repo/issues?state=all"):
                    return [self.issue]
                if path == "/repos/test/repo/issues/48":
                    if method == "PATCH":
                        self.patches.append(payload)
                        self.issue.update(payload)
                    return dict(self.issue)
                if path == "/repos/test/repo/issues" and method == "POST":
                    self.creates.append(payload)
                    raise AssertionError("same workflow and branch must not create another Issue")
                raise AssertionError((path, method))
        api = DraftAPI()
        signal = intake.Signal(
            "ci:9", "ci_failure", "Foundation CI",
            json.dumps({"workflow_id": 123, "head_sha": "b" * 40,
                        "branch": "feature",
                        "failed_jobs": [{"name": "unit", "conclusion": "failure",
                                         "failed_steps": ["pytest"]}]}),
            "https://github.com/test/repo/actions/runs/9",
            "2026-11-10T00:00:00Z",
        )
        first = intake.publish_ci_failure_task_drafts(api, [signal])
        second = intake.publish_ci_failure_task_drafts(api, [signal])
        self.assertEqual(first, {"created": 0, "updated": 1, "skipped": 0})
        self.assertEqual(second, {"created": 0, "updated": 0, "skipped": 1})
        self.assertEqual(len(api.patches), 1)
        self.assertEqual(api.creates, [])
        self.assertIn("https://github.com/test/repo/actions/runs/5", api.issue["body"])
        self.assertIn("https://github.com/test/repo/actions/runs/9", api.issue["body"])
        self.assertIn("foundation-autodev-ci-thread:v1:", api.issue["body"])
        self.assertNotIn('"labels"', json.dumps(api.patches))

    def test_human_edited_legacy_ci_issue_is_not_replaced(self):
        import json
        edited = {
            "number": 19, "state": "open", "labels": [],
            "user": {"login": "github-actions[bot]"},
            "body": "<!-- foundation-autodev-ci-task:v1:" + "a" * 64 +
                    " -->\n- Workflow ID: 123\n- Branch: feature\nHuman note to keep",
            "created_at": "2026-11-09T00:00:00Z",
            "updated_at": "2026-11-09T01:00:00Z",
        }
        class API:
            def __init__(self):
                self.created = []
            def repo_path(self, suffix):
                return suffix
            def request(self, path, method="GET", payload=None):
                if path.startswith("/issues?state=all"):
                    return [edited]
                if path == "/issues" and method == "POST":
                    self.created.append(payload)
                    return {"number": 20, "html_url": "https://github.com/test/repo/issues/20"}
                raise AssertionError("human edited Issue must not be patched")
        signal = intake.Signal(
            "ci:99", "ci_failure", "CI",
            json.dumps({"workflow_id": 123, "head_sha": "b" * 40,
                        "branch": "feature", "failed_jobs": [
                            {"name": "unit", "conclusion": "failure", "failed_steps": []}
                        ]}),
            "https://github.com/test/repo/actions/runs/99", "",
        )
        api = API()
        self.assertEqual(intake.publish_ci_failure_task_drafts(api, [signal]),
                         {"created": 1, "updated": 0, "skipped": 0})
        self.assertEqual(len(api.created), 1)
        self.assertEqual(edited["body"].endswith("Human note to keep"), True)

    def test_ci_failure_never_overwrites_newly_approved_issue(self):
        import json
        old_body = (
            "<!-- foundation-autodev-ci-task:v1:" + "a" * 64 + " -->\n"
            "- Branch: feature\n- Workflow ID: 123\n"
        )
        class API:
            def repo_path(self, suffix):
                return suffix
            def request(self, path, method="GET", payload=None):
                if path.startswith("/issues?state=all"):
                    return [{"number": 12, "state": "open", "body": old_body, "labels": [],
                             "user": {"login": "github-actions[bot]"},
                             "created_at": "2026-11-09T00:00:00Z",
                             "updated_at": "2026-11-09T00:00:00Z"}]
                if path == "/issues/12" and method == "GET":
                    return {"number": 12, "state": "open", "body": old_body,
                            "labels": [{"name": intake.READY_LABEL}]}
                raise AssertionError("no update or new Issue allowed once a human approved")
        signal = intake.Signal(
            "ci:9", "ci_failure", "Foundation CI",
            json.dumps({"workflow_id": 123, "head_sha": "b" * 40,
                        "branch": "feature",
                        "failed_jobs": [{"name": "unit", "conclusion": "failure",
                                         "failed_steps": ["pytest"]}]}),
            "https://github.com/test/repo/actions/runs/9", "",
        )
        self.assertEqual(intake.publish_ci_failure_task_drafts(API(), [signal]),
                         {"created": 0, "updated": 0, "skipped": 1})

if __name__ == "__main__":
    unittest.main()
