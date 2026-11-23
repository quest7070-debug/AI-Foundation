import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import tempfile
import time
import unittest
from unittest import mock

from scripts import m1_runtime_status_probe as probe
from scripts import m1_development_bridge as bridge


class RuntimeStatusTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name).resolve()
        self.root = self.home / "private-worker"
        self.root.mkdir()
        self.results = self.root / "results"
        self.results.mkdir()
        worker = self.root / "local9b_autodev_worker.py"
        worker.write_text("SECRET_WORKER_SOURCE")
        agents = self.home / "Library/LaunchAgents"
        agents.mkdir(parents=True)
        self.plist = agents / (probe.AUTODEV + ".plist")
        self.plist.write_bytes(plistlib.dumps({"Label": probe.AUTODEV,
            "ProgramArguments": ["/usr/bin/python3", "-B", str(worker)]}))
        self.now = time.time()
        self.idle = {"gui": {"observation": "REGISTERED", "last_exit_code": 0,
                             "process_present": False}}

    def result(self, name, row):
        path = self.results / (name + ".json")
        path.write_text(json.dumps(row))
        return path

    def observe(self):
        return probe.autodev_status(self.home, self.now + 1, self.idle)

    def test_worker_plist_rejects_control_bytes_in_any_argument(self):
        original = plistlib.loads(self.plist.read_bytes())
        for bad in ("\n", "\t", "\x7f"):
            with self.subTest(control=repr(bad)):
                row = dict(original)
                row["ProgramArguments"] = list(original["ProgramArguments"]) + ["--label=" + bad]
                self.plist.write_bytes(plistlib.dumps(row))
                report = self.observe()
                self.assertEqual(report["state"], "UNAVAILABLE")
                self.assertEqual(report["code"], "INVALID_ARGS")
        self.plist.write_bytes(plistlib.dumps(original))
        self.assertEqual(self.observe()["state"], "SCHEDULED_IDLE")

    def test_cycle_blocked_surfaces_in_queue_state(self):
        (self.root / "scheduled-code-cycle.json").write_text(
            json.dumps({"state": "SCHEDULED_CYCLE_BLOCKED"}))
        self.assertEqual(self.observe()["queue_state"], "SCHEDULED_CYCLE_BLOCKED")

    def test_cycle_healthy_stays_cycle_observed(self):
        (self.root / "scheduled-code-cycle.json").write_text(
            json.dumps({"state": "NO_ELIGIBLE_TICKET"}))
        self.assertEqual(self.observe()["queue_state"], "LOCAL_WORK_CYCLE_OBSERVED")

    def test_recipes_eligible_when_recipe_module_installed(self):
        recipe = self.root / "local9b_task_recipe.py"
        recipe.write_text('RECIPE = "python-fixed-test"\n')
        self.assertEqual(self.observe()["recipes"], {"eligible": 1})

    def test_recipes_unknown_without_recipe_module(self):
        self.assertEqual(self.observe()["recipes"], {"eligible": None})

    def test_recipes_unknown_when_marker_absent(self):
        recipe = self.root / "local9b_task_recipe.py"
        recipe.write_text('RECIPE = "something-else"\n')
        self.assertEqual(self.observe()["recipes"], {"eligible": None})

    def test_result_timestamps_timeout_and_private_data_excluded(self):
        success = self.result("success", {"status": "DRAFT_PR_PRESENTED",
            "feedback": "SECRET_FEEDBACK", "work": "/private/source", "delivery_ref": "SECRET_REF"})
        os.utime(success, (self.now - 20, self.now - 20))
        self.result("failed", {"status": "STOPPED", "error_type": "TimeoutExpired",
                               "detail": "MODEL_TURN_TIMEOUT"})
        report = self.observe()
        self.assertEqual(report["state"], "SCHEDULED_IDLE")
        self.assertEqual(report["latest_result"]["error_code"], "MODEL_TURN_TIMEOUT")
        self.assertEqual(report["latest_result"]["location"], "MODEL_TURN")
        self.assertGreater(report["last_failure_at_epoch"], report["last_success_at_epoch"])
        for secret in ("SECRET", str(self.home), "delivery_ref", "feedback"):
            self.assertNotIn(secret, json.dumps(report))

    def test_unfinished_start_requires_reconciliation_unless_live_process(self):
        (self.results / "unfinished.started").write_text(str(self.now))
        self.assertEqual(self.observe()["state"], "RECONCILE_REQUIRED")
        self.idle["gui"]["process_present"] = True
        self.assertEqual(self.observe()["state"], "RUNNING")
        self.result("unfinished", {"status": "NO_PROGRESS"})
        self.assertEqual(self.observe()["uncompleted_start_count"], 0)

    def test_latest_failure_survives_a_newer_success(self):
        failure = self.result("failed", {"status": "STOPPED", "detail": "MODEL_TURN_TIMEOUT"})
        os.utime(failure, (self.now - 20, self.now - 20))
        self.result("success", {"status": "DRAFT_PR_PRESENTED"})
        report = self.observe()
        self.assertEqual(report["latest_result"]["status"], "DRAFT_PR_PRESENTED")
        self.assertEqual(report["last_failure"]["error_code"], "MODEL_TURN_TIMEOUT")
        self.assertEqual(report["error_code_counts"], {"MODEL_TURN_TIMEOUT": 1})

    def test_existing_failure_receipt_supplies_only_fixed_class_and_location(self):
        attempt = "issue-271-" + "a" * 16
        self.result(attempt, {"status": "REPAIR_BUDGET_EXHAUSTED", "feedback": "SECRET_FEEDBACK"})
        failures = self.root / "failures"
        failures.mkdir()
        path = failures / ("autodev-" + attempt + ".json")
        origin = {"schema": "local9b-failed-attempt-candidate/v1", "issue": 271,
            "attempt": attempt, "result_status": "REPAIR_BUDGET_EXHAUSTED",
            "feedback_sha256": sha256(b"SECRET_FEEDBACK").hexdigest(),
            "approval_reusable": False, "failure_class": "GENERATED_SOURCE_SYNTAX_ERROR"}
        path.write_text(json.dumps({"origin": origin, "instruction": "SECRET_INSTRUCTION"}))
        report = self.observe()
        self.assertEqual(report["last_failure"]["error_code"], "GENERATED_SOURCE_SYNTAX_ERROR")
        self.assertEqual(report["last_failure"]["location"], "GENERATED_SOURCE_COMPILE")
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertNotIn(attempt, json.dumps(report))
        for key, wrong in (("issue", 272), ("approval_reusable", True),
                           ("failure_class", "SECRET_CLASS"), ("result_status", "NO_PROGRESS"),
                           ("feedback_sha256", "0" * 64)):
            changed = dict(origin, **{key: wrong})
            path.write_text(json.dumps({"origin": changed}))
            result = self.observe()["last_failure"]
            self.assertEqual(result["error_code"], "REPAIR_BUDGET_EXHAUSTED")
            self.assertNotIn("failure_class", result)
        path.unlink()
        path.symlink_to(self.results / (attempt + ".json"))
        self.assertEqual(self.observe()["last_failure"]["error_code"], "REPAIR_BUDGET_EXHAUSTED")

    def test_older_host_result_code_prefix_projects_without_feedback_leak(self):
        self.result("failed", {"status": "REPAIR_BUDGET_EXHAUSTED",
            "feedback": "GENERATED_SOURCE_SYNTAX_ERROR: SECRET_SOURCE /private/file.py line 32"})
        result = self.observe()
        self.assertEqual(result["last_failure"]["error_code"], "GENERATED_SOURCE_SYNTAX_ERROR")
        self.assertEqual(result["last_failure"]["location"], "GENERATED_SOURCE_COMPILE")
        self.assertEqual(result["last_failure"]["diagnostic_source"], "HOST_RESULT_CODE_PREFIX")
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("/private", json.dumps(result))
        self.result("failed", {"status": "REPAIR_BUDGET_EXHAUSTED",
            "feedback": "private source contains GENERATED_SOURCE_SYNTAX_ERROR: SECRET"})
        self.assertEqual(self.observe()["last_failure"]["error_code"], "REPAIR_BUDGET_EXHAUSTED")

    def test_claim_before_start_requires_reconciliation_without_replaying(self):
        attempt = "issue-271-" + "b" * 16
        claim = self.results / "issue-271.claimed"
        claim.write_text(attempt + ".json")
        report = self.observe()
        self.assertEqual(report["state"], "RECONCILE_REQUIRED")
        self.assertEqual(report["claim_without_start_or_result_count"], 1)
        self.assertNotIn(attempt, json.dumps(report))
        self.result(attempt, {"status": "DRAFT_PR_PRESENTED"})
        self.assertEqual(self.observe()["claim_without_start_or_result_count"], 0)
        claim.write_text("issue-999-" + "b" * 16 + ".json")
        self.assertEqual(self.observe()["invalid_records"], 1)

    def test_candidate_publication_receipt_is_not_a_development_attempt(self):
        self.result("candidate-autodev-issue-271-" + "a" * 16,
                    {"status": "CREATED", "url": "SECRET_URL"})
        result = self.observe()
        self.assertEqual(result["result_counts"], {})
        self.assertEqual(result["diagnostic_publication_records"], 1)
        self.assertIsNone(result["last_result_at_epoch"])

    def test_bad_json_and_unknown_values_are_not_empty_success(self):
        self.result("unknown", {"status": "SECRET_STATUS", "error_type": "SECRET_ERROR",
                                "detail": "SECRET_ERROR /private"})
        (self.results / "broken.json").write_text("{")
        report = self.observe()
        self.assertEqual(report["invalid_records"], 1)
        self.assertIsNone(report["last_success_at_epoch"])
        self.assertNotIn("SECRET", json.dumps(report))

    def test_queue_status_distinguishes_recent_waiting_from_active_and_stale(self):
        intake = self.root / "intake.json"
        intake.write_text(json.dumps({"status": "SUCCESS", "issues": [
            {"status": "QUEUED", "private": "SECRET_SOURCE"}]}))
        result = self.observe()
        self.assertEqual(result["state"], "SCHEDULED_IDLE")
        self.assertEqual(result["queue_state"], "QUEUED_NOT_RUNNING")
        self.assertEqual(result["intake"]["queued_count"], 1)
        self.assertNotIn("SECRET_SOURCE", json.dumps(result))
        self.idle["gui"]["process_present"] = True
        self.assertEqual(self.observe()["queue_state"], "RUNNING")
        self.idle["gui"]["process_present"] = False
        intake.write_text(json.dumps({"status": "SUCCESS", "issues": []}))
        self.assertEqual(self.observe()["queue_state"], "NO_QUEUED_TASK")
        intake.write_text(json.dumps({"status": "SUCCESS", "issues": [{"status": "QUEUED"}]}))
        os.utime(intake, (self.now - 3600, self.now - 3600))
        self.assertEqual(self.observe()["queue_state"], "UNAVAILABLE")
        intake.write_text(json.dumps({"status": "SUCCESS", "issues": "untrusted"}))
        self.assertEqual(self.observe()["queue_state"], "UNAVAILABLE")
        # An invalid member mixed with valid rows cannot be rounded down to
        # a confident zero-queue observation.
        intake.write_text(json.dumps({"status": "SUCCESS", "issues": [None]}))
        self.assertEqual(self.observe()["queue_state"], "UNAVAILABLE")
        intake.write_text(json.dumps({"status": "SUCCESS", "issues": [
            {"status": "OTHER"}, {"bad": "untrusted"}]}))
        self.assertEqual(self.observe()["queue_state"], "UNAVAILABLE")
        intake.write_text(json.dumps({"status": "SUCCESS", "issues": [
            {"status": "UNKNOWN_FUTURE_STATUS"}]}))
        self.assertEqual(self.observe()["queue_state"], "UNAVAILABLE")
        (self.results / "unfinished.started").write_text(str(self.now))
        self.assertEqual(self.observe()["queue_state"], "RECONCILE_REQUIRED")

    def test_current_9b_resource_deferral_codes_are_bounded_and_private(self):
        for code in ("CPU_PRESSURE", "MEMORY_PRESSURE", "RESOURCE_UNKNOWN",
                     "SHARED_MODEL_RESIDENT", "SHARED_MODEL_STATE_UNKNOWN",
                     "LOCAL_BACKEND_PORT_OCCUPIED"):
            row = probe._diagnostic({"detail": code, "feedback": "SECRET"}, "STOPPED")
            self.assertEqual(row["error_code"], code)
            self.assertNotIn("SECRET", json.dumps(row))
        self.assertEqual(probe._diagnostic(
            {"detail": "CPU_PRESSURE: SECRET_HOST_PATH"}, "STOPPED"
        )["error_code"], "UNKNOWN")

    def test_uncertain_draft_delivery_requires_reconciliation_without_details(self):
        for name, code in (("delivery-uncertain", "DRAFT_CREATION_UNCERTAIN"),
                           ("push-uncertain", "REMOTE_PUSH_UNCERTAIN")):
            with self.subTest(code=code):
                receipt = self.result(name, {
                    "status": "STOPPED", "error_type": "RuntimeError",
                    "detail": code, "feedback": "SECRET_SOURCE_TEXT"})
                report = self.observe()
                assert report["last_failure"]["error_code"] == code
                assert report["last_failure"]["location"] == "UNKNOWN"
                assert "SECRET_SOURCE_TEXT" not in json.dumps(report)
                receipt.unlink()

    def test_only_numeric_harness_exit_extracted(self):
        self.result("exit", {"status": "STOPPED", "error_type": "RuntimeError",
            "detail": "HARNESS_EXIT_7: SECRET RAW LOG /private"})
        report = self.observe()
        self.assertEqual(report["latest_result"]["harness_exit_code"], 7)
        self.assertNotIn("SECRET", json.dumps(report))

    def test_host_installed_parent_aliases_resolve_but_leaf_links_stay_denied(self):
        self.result("success", {"status": "DRAFT_PR_PRESENTED"})
        alias = self.home / "owner-alias"
        alias.symlink_to(self.home, target_is_directory=True)
        result = probe.autodev_status(alias, self.now + 1, self.idle)
        self.assertEqual(result["result_counts"], {"DRAFT_PR_PRESENTED": 1})
        self.assertNotIn(str(alias), json.dumps(result))

    def test_renamed_owner_installed_python_worker_is_bound_by_exact_label(self):
        installed = self.root / "worker.py"
        (self.root / "local9b_autodev_worker.py").rename(installed)
        self.plist.write_bytes(plistlib.dumps({"Label": probe.AUTODEV,
            "ProgramArguments": ["/usr/bin/python3", "-B", str(installed)]}))
        self.result("success", {"status": "DRAFT_PR_PRESENTED"})
        self.assertEqual(self.observe()["result_counts"], {"DRAFT_PR_PRESENTED": 1})
        row = plistlib.loads(self.plist.read_bytes())
        row["ProgramArguments"].append(str(self.root / "second.py"))
        self.plist.write_bytes(plistlib.dumps(row))
        self.assertEqual(self.observe()["code"], "WORKER_BINDING_UNKNOWN")

    def test_pinned_release_keeps_queue_outside_immutable_worker_bundle(self):
        durable = self.home / "preserved-queue"
        durable.mkdir()
        (durable / "results").mkdir()
        (durable / "results" / "success.json").write_text(
            json.dumps({"status": "DRAFT_PR_PRESENTED"}))
        (durable / "intake.json").write_text(
            json.dumps({"status": "SUCCESS", "issues": []}))
        row = plistlib.loads(self.plist.read_bytes())
        row["EnvironmentVariables"] = {
            "AI_FOUNDATION_LOCAL9B_STATE_ROOT": str(durable)}
        self.plist.write_bytes(plistlib.dumps(row))
        report = self.observe()
        self.assertEqual(report["result_counts"], {"DRAFT_PR_PRESENTED": 1})
        self.assertEqual(report["intake"]["state"], "SUCCESS")
        self.assertNotIn(str(durable), json.dumps(report))

    def test_untrusted_release_state_root_cannot_fall_back_to_bundle(self):
        self.result("old", {"status": "DRAFT_PR_PRESENTED"})
        row = plistlib.loads(self.plist.read_bytes())
        link = self.home / "linked-queue"
        link.symlink_to(self.root, target_is_directory=True)
        for value in ("relative", str(self.home / "missing"), str(link), 7):
            with self.subTest(value=value):
                row["EnvironmentVariables"] = {
                    "AI_FOUNDATION_LOCAL9B_STATE_ROOT": value}
                self.plist.write_bytes(plistlib.dumps(row))
                report = self.observe()
                self.assertEqual(report["state"], "UNAVAILABLE")
                self.assertNotIn("result_counts", report)
                self.assertNotIn(str(self.home), json.dumps(report))

    def test_state_root_rejects_control_characters_and_oversized_values(self):
        # A trusted plist can still contain a malformed path. Never treat
        # such values as authoritative or fall back to old worker results.
        self.result("old", {"status": "DRAFT_PR_PRESENTED"})
        row = plistlib.loads(self.plist.read_bytes())
        for value in (str(self.root) + "\n", str(self.root) + "\t",
                      str(self.root) + "\x7f", "/" + "x" * 4096):
            with self.subTest(kind=repr(value[-8:])):
                row["EnvironmentVariables"] = {
                    "AI_FOUNDATION_LOCAL9B_STATE_ROOT": value}
                self.plist.write_bytes(plistlib.dumps(row))
                report = self.observe()
                self.assertEqual(report["state"], "UNAVAILABLE")
                self.assertEqual(report["code"], "UNTRUSTED_STATE_ROOT")
                self.assertNotIn("result_counts", report)

    def test_untrusted_bindings_and_result_symlinks_rejected(self):
        self.plist.chmod(0o666)
        self.assertEqual(self.observe()["state"], "UNAVAILABLE")
        self.plist.chmod(0o644)
        outside = self.home / "secret.json"
        outside.write_text('{"status":"DRAFT_PR_PRESENTED"}')
        (self.results / "fake.json").symlink_to(outside)
        report = self.observe()
        self.assertEqual(report["invalid_records"], 1)
        self.assertIsNone(report["last_success_at_epoch"])

    def test_fixed_domain_commands_no_raw_launchctl_output(self):
        raw = "state = waiting\nruns = 3\nlast exit code = 0\nrun interval = 900 seconds\nsecret = SECRET\n"
        with mock.patch.object(probe, "_fixed_command", return_value=raw) as command:
            result = probe._domain_status(probe.AUTODEV, "gui/123")
        command.assert_called_once_with(["/bin/launchctl", "print", "gui/123/" + probe.AUTODEV])
        self.assertFalse(result["process_present"])
        self.assertEqual(result["interval_seconds"], 900)
        self.assertNotIn("SECRET", json.dumps(result))
        with mock.patch.object(probe, "_fixed_command", return_value=None):
            self.assertEqual(probe._domain_status(probe.AUTODEV, "system"),
                             {"observation": "UNAVAILABLE_OR_NOT_REGISTERED"})

    def test_existing_lease_observation_and_release_without_creation(self):
        self.assertEqual(probe.lease_status(self.home)["state"], "UNAVAILABLE")
        path = self.home / "Library/Application Support/AI-Foundation/host-compute/compute.lock"
        self.assertFalse(path.exists())
        path.parent.mkdir(parents=True, mode=0o700)
        path.parent.parent.chmod(0o755)  # canonical lease permits this app directory
        path.write_text("SECRET_LOCK")
        path.chmod(0o600)
        before = path.stat().st_mtime_ns
        with path.open("r") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(probe.lease_status(self.home)["state"], "EXCLUSIVE_HELD_AT_PROBE")
        self.assertEqual(probe.lease_status(self.home)["state"], "AVAILABLE_AT_PROBE")
        with path.open("r") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(before, path.stat().st_mtime_ns)
        self.assertEqual(path.read_text(), "SECRET_LOCK")

    def test_runtime_uses_contract_routes_and_three_domains(self):
        with mock.patch.object(probe, "require_m1"), \
             mock.patch.object(probe, "_fixed_command", return_value=None) as commands, \
             mock.patch.object(probe, "_read_only_http_probe", return_value={"http_status": 404}) as http, \
             mock.patch.object(probe, "_shared9b_admission_status", return_value={"state": "UNVERIFIED"}):
            report = probe.runtime_status(home=self.home, now=self.now)
        self.assertEqual(len(report["services"][probe.AUTODEV]), 3)
        self.assertEqual(len(commands.call_args_list), 13)
        self.assertEqual(http.call_args_list[0].args, (8766, "/v1/models"))
        self.assertFalse(report["harness"]["http_port_required"])
        self.assertNotIn("FAILED", json.dumps(report))

    def test_exact_bridge_request_and_dispatch(self):
        body = '<!-- foundation-m1-bridge: {"version":1,"operation":"runtime-status"} -->'
        issue = {"number": 123, "state": "open", "user": {"login": bridge.OWNER_LOGIN},
                 "title": "Foundation M1 Bridge: runtime-status", "body": body}
        event = {"action": "opened", "repository": {"full_name": bridge.REPOSITORY}, "issue": issue}
        self.assertEqual(bridge.validate_event(event), (123, "runtime-status"))
        with self.assertRaises(bridge.BridgeDenied):
            bridge.parse_request(issue["title"], body.replace('} -->', ',"path":"/secret"} -->'))
        with mock.patch.object(bridge, "_github_api", side_effect=[issue, [], {}]), \
             mock.patch.object(probe, "runtime_status", return_value={"autodev": {"state": "UNKNOWN"}}) as observe:
            self.assertEqual(bridge.execute(event, "token", "123"), "OBSERVED")
        observe.assert_called_once_with()

    def test_source_inventory_fingerprints_fixed_files_without_exporting_contents(self):
        module = self.root / "modules/ai_foundation/development_host.py"
        module.parent.mkdir(parents=True)
        module.write_text("PRIVATE_SOURCE_TEXT")
        with mock.patch.object(probe, "require_m1"):
            report = probe.source_status(home=self.home, now=self.now + 1)
        self.assertEqual(report["files"]["development_host"]["sha256"],
                         sha256(b"PRIVATE_SOURCE_TEXT").hexdigest())
        self.assertEqual(report["files"]["worker"]["state"], "OBSERVED")
        self.assertEqual(report["files"]["task_selection"]["state"], "UNAVAILABLE")
        self.assertNotIn("PRIVATE_SOURCE_TEXT", json.dumps(report))
        self.assertNotIn(str(self.home), json.dumps(report))
        module.unlink()
        module.symlink_to(self.root / "local9b_autodev_worker.py")
        with mock.patch.object(probe, "require_m1"):
            self.assertEqual(probe.source_status(home=self.home)["files"]["development_host"],
                             {"state": "UNAVAILABLE"})

    def test_release_module_fingerprints_use_immutable_source_not_legacy_queue(self):
        release = self.home / "p4" / "repo"
        code = release / "scripts"
        code.mkdir(parents=True)
        worker = code / "local9b_autodev_worker.py"
        worker.write_text("IMMUTABLE_P4_WORKER")
        package = release / "src" / "ai_foundation"
        package.mkdir(parents=True)
        (package / "development_host.py").write_text("RELEASE_DEVELOPMENT_HOST")
        self.plist.write_bytes(plistlib.dumps({
            "Label": probe.AUTODEV,
            "ProgramArguments": ["/usr/bin/python3", "-B", str(worker)],
            "EnvironmentVariables": {"AI_FOUNDATION_LOCAL9B_STATE_ROOT": str(self.root)},
        }))
        self.result("existing-at-old-root", {"status": "DRAFT_PR_PRESENTED"})
        self.assertEqual(probe._worker_root(self.home), self.root)
        with mock.patch.object(probe, "require_m1"):
            status = probe.source_status(home=self.home, now=self.now + 1)
        self.assertEqual(status["files"]["development_host"]["sha256"],
                         sha256(b"RELEASE_DEVELOPMENT_HOST").hexdigest())
        self.assertNotIn(str(self.home), json.dumps(status))
        self.assertEqual(self.observe()["result_counts"], {"DRAFT_PR_PRESENTED": 1})

    def test_source_operation_has_exact_schema_and_fixed_dispatch(self):
        body = '<!-- foundation-m1-bridge: {"version":1,"operation":"source-status"} -->'
        issue = {"number": 123, "state": "open", "user": {"login": bridge.OWNER_LOGIN},
                 "title": "Foundation M1 Bridge: source-status", "body": body}
        event = {"action": "opened", "repository": {"full_name": bridge.REPOSITORY}, "issue": issue}
        self.assertEqual(bridge.validate_event(event), (123, "source-status"))
        with mock.patch.object(bridge, "_github_api", side_effect=[issue, [], {}]), \
             mock.patch.object(probe, "source_status", return_value={"state": "OBSERVED"}) as observe:
            self.assertEqual(bridge.execute(event, "token", "123"), "OBSERVED")
        observe.assert_called_once_with()

    def test_fixed_log_metadata_never_reads_log_contents_and_rejects_links(self):
        stdout = self.root / "private-out.log"
        stderr = self.root / "private-err.log"
        stdout.write_text("SECRET_RAW_LOG")
        stderr.symlink_to(stdout)
        self.plist.write_bytes(plistlib.dumps({"Label": probe.AUTODEV,
            "StandardOutPath": str(stdout), "StandardErrorPath": str(stderr)}))
        with mock.patch.object(probe, "_owned_bytes", wraps=probe._owned_bytes) as read:
            result = probe._log_metadata(self.home, probe.AUTODEV, self.now + 1)
        self.assertEqual(result["stdout"]["size_bytes"], len("SECRET_RAW_LOG"))
        self.assertEqual(result["stderr"], {"state": "UNAVAILABLE"})
        self.assertEqual(read.call_count, 1)
        self.assertEqual(read.call_args.args[0], self.plist)
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn(str(self.home), json.dumps(result))

    def test_storage_groups_filesystems_without_exporting_paths_or_device_ids(self):
        observed = lambda: {"state": "OBSERVED", "available_gib": 42, "read_only": False}
        with mock.patch.object(probe, "require_m1"), \
             mock.patch.object(probe, "_space_status", side_effect=[(observed(), 112233),
                 (observed(), 445566), (observed(), 445566)]):
            result = probe.storage_status(home=self.home, now=self.now)
        self.assertEqual(result["filesystems"]["system"]["filesystem_group"], 0)
        self.assertEqual(result["filesystems"]["installed_worker"]["filesystem_group"], 1)
        self.assertEqual(result["filesystems"]["owner_home"]["filesystem_group"], 1)
        self.assertNotIn("445566", json.dumps(result))
        self.assertNotIn(str(self.home), json.dumps(result))
        with mock.patch.object(probe.os, "statvfs", side_effect=PermissionError("SECRET")):
            self.assertEqual(probe._space_status(self.home), ({"state": "UNAVAILABLE"}, None))

    def test_storage_operation_dispatch_is_fixed(self):
        op = "storage-status"
        issue = {"number": 123, "state": "open", "user": {"login": bridge.OWNER_LOGIN},
                 "title": "Foundation M1 Bridge: " + op,
                 "body": '<!-- foundation-m1-bridge: {"version":1,"operation":"' + op + '"} -->'}
        event = {"action": "opened", "repository": {"full_name": bridge.REPOSITORY}, "issue": issue}
        with mock.patch.object(bridge, "_github_api", side_effect=[issue, [], {}]), \
             mock.patch.object(probe, "storage_status", return_value={"state": "OBSERVED"}) as read:
            self.assertEqual(bridge.execute(event, "token", "123"), "OBSERVED")
        read.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()



def test_llama_swap_local_catalog_is_bounded_counts_only_without_model_calls():
    raw=json.dumps({"data": [
        {"id": "PRIVATE_MODEL_ALIAS", "status": {"value": "loaded"},
         "prompt": "SECRET_OWNER_PROMPT"},
        {"id": "PRIVATE_SECOND_ALIAS", "status": {"value": "unloaded"}},
        {"id": "PRIVATE_OTHER_ALIAS", "status": {"value": "unrecognized"}},
    ]}).encode()
    with mock.patch.object(probe.http.client, "HTTPConnection") as http:
        conn=http.return_value
        conn.getresponse.return_value.status=200
        conn.getresponse.return_value.read.return_value=raw
        result=probe._local_model_catalog_status()
    assert result["state"]=="OBSERVED"
    assert result["configured_alias_count"]==3
    assert result["runtime_state_counts"]=={
        "loaded":1,"unloaded":1,"loading":0,"failed":0,"other":1}
    assert "PRIVATE" not in json.dumps(result)
    assert "SECRET" not in json.dumps(result)
    conn.request.assert_called_once_with("GET", "/v1/models", headers={
        "Host": "127.0.0.1", "Accept": "application/json"})
    conn.close.assert_called_once()
    for bad in (b'{"data":"SECRET"}', b'{"data":[{"id":5}]}',
                b'{"data":[]}' + b"X" * 65537):
        with mock.patch.object(probe.http.client, "HTTPConnection") as http:
            http.return_value.getresponse.return_value.status=200
            http.return_value.getresponse.return_value.read.return_value=bad
            output=probe._local_model_catalog_status()
        assert output["state"]=="UNAVAILABLE"
        assert "SECRET" not in json.dumps(output)


def test_local_admission_reuses_owner_manifest_and_exports_only_fixed_counts(tmp_path):
    from types import SimpleNamespace
    from scripts import m1_operator_release_cli
    from ai_foundation import llama_swap_adapter
    root = tmp_path / "owner"
    manifest = root / "local-compute" / "llama-swap.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("PRIVATE_ARTIFACT_PATH")
    rows = (
        SimpleNamespace(health="UNAVAILABLE", reason="MODEL_ARTIFACT_MISSING",
                        capabilities=()),
        SimpleNamespace(health="ONLINE", reason=None, capabilities=("CODE",)),
        SimpleNamespace(health="UNAVAILABLE", reason="SECRET_FAILURE",
                        capabilities=()),
    )
    with mock.patch.object(m1_operator_release_cli, "_guard_path",
                           return_value=(root / "stores" / "guard.sqlite", root / "operator-registry.json")), \
         mock.patch.object(llama_swap_adapter, "LlamaSwapDiscovery") as discovery:
        discovery.return_value.return_value = rows
        result = probe._local_compute_admission_status(tmp_path)
    discovery.assert_called_once_with(manifest_path=manifest)
    assert result["routable_count"] == 1
    assert result["reason_counts"] == {"MODEL_ARTIFACT_MISSING": 1, "OTHER": 1}
    assert result["health_counts"] == {"UNAVAILABLE": 2, "ONLINE": 1}
    assert result["model_calls"] == 0 and result["manifest_present"] is True
    assert "PRIVATE" not in json.dumps(result) and "SECRET" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)


def test_local_admission_schema_error_does_not_abort_other_runtime_probes(tmp_path):
    from scripts import m1_operator_release_cli
    from ai_foundation import llama_swap_adapter
    with mock.patch.object(m1_operator_release_cli, "_guard_path",
                           return_value=(tmp_path / "guard.db", tmp_path / "registry.json")), \
         mock.patch.object(llama_swap_adapter, "LlamaSwapDiscovery") as discovery:
        discovery.return_value.side_effect = AttributeError("SECRET_CATALOG")
        result = probe._local_compute_admission_status(tmp_path)
    assert result == {"state": "UNAVAILABLE", "model_calls": 0}


def test_shared9b_admission_projects_current_identity_and_fixed_reason_only():
    from types import SimpleNamespace
    def row(health="ONLINE", reason=None):
        return SimpleNamespace(binding="local:ollama-shared9b:general", same_host=True,
                               health=health, reason=reason, model="PRIVATE_MODEL", path="SECRET")
    observed = probe._shared9b_admission_status(lambda: (row(),))
    assert observed == {"state": "OBSERVED", "health": "ONLINE", "reason": None, "model_calls": 0}
    for reason in ("CPU_PRESSURE", "MEMORY_PRESSURE", "PINNED_9B_NOT_VERIFIED"):
        assert probe._shared9b_admission_status(lambda: (row("UNAVAILABLE", reason),))["reason"] == reason
    hidden = probe._shared9b_admission_status(lambda: (row("UNAVAILABLE", "SECRET"),))
    assert hidden["reason"] == "UNCLASSIFIED"
    assert "PRIVATE" not in json.dumps(hidden) and "SECRET" not in json.dumps(hidden)


def test_shared9b_admission_does_not_accept_legacy_or_remote_identity():
    from types import SimpleNamespace
    for binding, same_host in (("local:llama-swap:general", True),
                               ("local:ollama-shared9b:general", False)):
        result = probe._shared9b_admission_status(lambda: [SimpleNamespace(
            binding=binding, same_host=same_host, health="ONLINE", reason=None)])
        assert result["state"] == "UNVERIFIED" and result["model_calls"] == 0
    def failing():
        raise OSError("SECRET_TRANSPORT")
    assert "SECRET" not in json.dumps(probe._shared9b_admission_status(failing))


def test_intake_failure_type_exports_only_exact_worker_exception_class():
    assert probe._intake_failure_type({"status": "BLOCKED", "reason": "CalledProcessError"}) == "CalledProcessError"
    assert probe._intake_failure_type({"status": "BLOCKED", "reason": "SECRET_COMMAND /private/file"}) == "UNKNOWN"
    assert probe._intake_failure_type({"status": "BLOCKED", "reason": True}) == "UNKNOWN"
    assert probe._intake_failure_type({"status": "SUCCESS", "reason": "RuntimeError"}) is None
