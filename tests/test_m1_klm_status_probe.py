"""KLM owner receipt inspection via existing exact GitHub->M1 read-only bridge."""
import json
import os
from pathlib import Path
import plistlib
import sqlite3
import tempfile
import time
import unittest
from unittest import mock

from scripts import m1_development_bridge as bridge
from scripts import m1_klm_status_probe as probe


def _source_fixture(home, root, reviewed):
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    (agents / (probe.LABEL + ".plist")).write_bytes(plistlib.dumps({
        "Label": probe.LABEL,
        "ProgramArguments": ["/usr/bin/python3", str(root / "scripts/klm_drive_host_tick.py")],
    }))
    for relative in ("scripts/klm_drive_host_tick.py", "src/ai_foundation/klm_drive_cycle.py",
                     "src/ai_foundation/klm_drive_auth.py", "src/ai_foundation/knowledge_lifecycle.py"):
        for base in (root, reviewed):
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic public source\n")


def test_installed_klm_source_identifies_legacy_generation_and_actual_file_drift(tmp_path):
    home, reviewed = tmp_path / "owner", tmp_path / "reviewed"
    root = home / "Library/Application Support/AI-Foundation/klm-drive/releases" / ("a" * 40)
    _source_fixture(home, root, reviewed)
    same = probe._installed_source(home, reviewed_root=reviewed)
    assert same["declared_revision"] == "a" * 40
    assert same["all_match_reviewed"] is True
    assert same["execution_authority"] is False
    (root / "src/ai_foundation/klm_drive_auth.py").write_text("# PRIVATE_SENTINEL\n")
    changed = probe._installed_source(home, reviewed_root=reviewed)
    assert changed["all_match_reviewed"] is False
    assert changed["files"]["auth"]["matches_reviewed"] is False
    assert "PRIVATE_SENTINEL" not in json.dumps(changed)
    assert str(home) not in json.dumps(changed)


def test_installed_klm_source_reports_staged_manifest_as_metadata_only(tmp_path):
    home, reviewed = tmp_path / "owner", tmp_path / "reviewed"
    root = home / "Library/Application Support/AI-Foundation/operator-release-staging" / ("b" * 64) / "candidate"
    _source_fixture(home, root, reviewed)
    (root.parent / "manifest.json").write_text(json.dumps({"candidate_commit": "c" * 40}))
    result = probe._installed_source(home, reviewed_root=reviewed)
    assert result["layout"] == "OPERATOR_STAGE"
    assert result["declared_revision"] == "c" * 40
    assert result["claim"] == "FILES_ONLY_NOT_LOADED_PROCESS_OR_GUARD_PROOF"
    assert result["execution_authority"] is False


def test_installed_klm_source_does_not_inspect_arbitrary_owner_paths(tmp_path):
    home, reviewed = tmp_path / "owner", tmp_path / "reviewed"
    _source_fixture(home, tmp_path / "private-other", reviewed)
    assert probe._installed_source(home, reviewed_root=reviewed) == {
        "state": "UNRECOGNIZED_SOURCE_LAYOUT"}


class KlmStatusProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.home = root / "owner"
        self.agents = self.home / "Library" / "LaunchAgents"
        self.agents.mkdir(parents=True)
        self.foundation = root / "private-foundation"
        self.foundation.mkdir()
        self.report = root / "klm-owner-report.json"
        self.host_config = root / "klm-host-config.json"
        self.work_db = self.foundation / "work.sqlite"
        self.plist = self.agents / (probe.LABEL + ".plist")
        self.now = time.time()
        self.report_data = {
            "observed_at": self.now, "status": "CURRENT",
            "drive_auth": "BOUND", "coverage": "COMPLETE", "changes": "COMPLETE",
            "inference": "READ_ONLY_VERIFIED",
            "pages": 33, "folders": 33, "objects": 113,
            "staged": 0, "duplicates": 6, "inbox_writes": 0,
            "development": {
                "approved_pending": 0, "active_or_uncertain": 0,
                "complete": True, "native_only_approved": 1,
                "untrusted_private_raw": "SECRET_FROM_DEVELOPMENT"
            },
            "owner_scope": "SECRET_FROM_OWNER",
            "oauth": "SECRET_FROM_OAUTH",
            "raw": "SECRET_FROM_RAW",
        }
        self._write_report()
        self._write_plist()
        self._private_json(self.host_config, {
            "foundation_root": str(self.foundation), "roots": ["abc"], "owner_scope": "owner-secret"
        })
        self._private_json(self.foundation / "config.json", {
            "data_dir": str(self.foundation), "work_db": "work.sqlite"
        })
        with sqlite3.connect(self.work_db) as conn:
            conn.execute(
                "CREATE TABLE work_steps(job_id TEXT, position INTEGER, name TEXT, status TEXT, "
                "result TEXT, updated_at REAL)"
            )
            conn.execute(
                "INSERT INTO work_steps VALUES(?,?,?,?,?,?)",
                ("klm-drive:test", 0, "klm-readonly", "VERIFIED", json.dumps({
                    "result_ref": "klm-atoms-sha256:" + "a" * 64,
                    "source_sha256": "b" * 64,
                    "source_revision": "row:xxxx",
                    "execution_authority": False,
                }), self.now)
            )
            conn.commit()
        self.work_db.chmod(0o600)

    @staticmethod
    def _private_json(path, value):
        path.write_text(json.dumps(value))
        path.chmod(0o600)

    def _write_report(self):
        self._private_json(self.report, self.report_data)

    def _write_plist(self):
        self.plist.write_bytes(plistlib.dumps({
            "Label": probe.LABEL,
            "ProgramArguments": [
                "/usr/bin/python3", "-B", "/owner/klm_drive_host_tick.py",
                "--config", str(self.host_config), "--report", str(self.report)
            ]
        }))
        self.plist.chmod(0o644)

    def observe(self):
        # This read-only bridge no longer calls Ollama or inventories model
        # processes; it only sanitizes the GUI's existing owner-private report.
        return probe.klm_status(home=self.home, now=self.now + 1)

    def test_known_real_report_shape_and_durable_work_validates_one_job(self):
        result = self.observe()
        self.assertEqual(result["state"], "OBSERVED")
        self.assertEqual((result["status"], result["coverage"], result["changes"]),
                         ("CURRENT", "COMPLETE", "COMPLETE"))
        self.assertEqual((result["folders"], result["objects"], result["pages"]),
                         (33, 113, 33))
        self.assertTrue(result["report_fresh"])
        self.assertEqual(result["inference"], "READ_ONLY_VERIFIED")
        self.assertEqual(result["development"]["native_only_approved"], 1)
        self.assertEqual(result["durable"]["validated_noeffect_receipts"], 1)
        self.assertEqual(result["durable"]["validated_recent_noeffect_receipts"], 1)
        self.assertTrue(result["one_noeffect_job_evidenced"])

    def test_private_source_credential_sqlite_content_and_paths_never_leave_owner(self):
        report = json.dumps(self.observe(), sort_keys=True)
        for secret in (
            "SECRET_FROM_OWNER", "SECRET_FROM_OAUTH",
            "SECRET_FROM_RAW", "SECRET_FROM_DEVELOPMENT",
            str(self.foundation), str(self.report), "owner-secret", "klm-drive:test"
        ):
            self.assertNotIn(secret, report)

    def test_poll_failure_exposes_only_fixed_exception_class_without_private_message(self):
        self.report_data.update(status="POLL_FAILED", error_type="HTTPError",
                                poll_error_code="DRIVE_HTTP_403",
                                error="PRIVATE_TOKEN https://private/source")
        self._write_report()
        result = self.observe()
        self.assertEqual(result["poll_error_type"], "HTTPError")
        self.assertEqual(result["poll_error_code"], "DRIVE_HTTP_403")
        self.assertFalse(result["one_noeffect_job_evidenced"])
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(result))
        self.report_data["error_type"] = "PRIVATE_CLASS_OR_PATH"
        self.report_data["poll_error_code"] = "PRIVATE_TOKEN https://private/source"
        self._write_report()
        self.assertEqual(self.observe()["poll_error_type"], "UNKNOWN")
        self.assertEqual(self.observe()["poll_error_code"], "UNKNOWN")
        self.report_data.update(status="CURRENT", error_type="HTTPError")
        self._write_report()
        self.assertIsNone(self.observe()["poll_error_type"])
        self.assertIsNone(self.observe()["poll_error_code"])



    def test_reported_compute_admission_only_whitelisted_reason_leaves_host(self):
        self.report_data["compute_admission"] = {
            "state": "DEFER", "reason": "MEMORY_PRESSURE",
            "private_model": "PRIVATE_MODEL_NAME",
            "owner_source": "SECRET_FROM_OWNER",
        }
        self._write_report()
        result = self.observe()
        self.assertEqual(result["compute_admission"],
                         {"state": "DEFER", "reason": "MEMORY_PRESSURE"})
        self.assertNotIn("PRIVATE_MODEL_NAME", json.dumps(result))
        self.assertNotIn("SECRET_FROM_OWNER", json.dumps(result))
        self.assertNotIn("compute_gate_predicates", result)

    def test_old_report_does_not_claim_runner_or_model_is_idle(self):
        self.assertEqual(self.observe()["compute_admission"],
                         {"state": "UNAVAILABLE"})
        for bad in ({"state": "AVAILABLE", "reason": "MEMORY_PRESSURE"},
                    {"state": "DEFER", "reason": "PRIVATE_REASON"},
                    {"state": "SUCCESS", "reason": "AVAILABLE"}):
            self.report_data["compute_admission"] = bad
            self._write_report()
            self.assertEqual(self.observe()["compute_admission"],
                             {"state": "UNAVAILABLE"})
        self.report_data["compute_admission"] = {"state": "NOT_EVALUATED"}
        self._write_report()
        self.assertEqual(self.observe()["compute_admission"],
                         {"state": "NOT_EVALUATED"})

    def test_active_rescan_reports_only_checkpoint_aggregates_and_fixed_reasons(self):
        scope = __import__("hashlib").sha256(json.dumps(
            ["owner-secret", ["abc"]], sort_keys=True,
            ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        with sqlite3.connect(self.work_db) as conn:
            conn.execute("CREATE TABLE klm_drive_native_cycle(scope TEXT, scan_id TEXT)")
            conn.execute("CREATE TABLE klm_drive_folders("
                         "scan TEXT,folder TEXT,status TEXT,pages INTEGER,reason TEXT)")
            conn.execute("CREATE TABLE klm_drive_seen(scan TEXT,id TEXT)")
            conn.execute("CREATE TABLE klm_drive_scans(id TEXT,created REAL)")
            conn.execute("INSERT INTO klm_drive_native_cycle VALUES(?,?)",
                         (scope, "private-scan-id"))
            conn.execute("INSERT INTO klm_drive_scans VALUES(?,?)",
                         ("private-scan-id", self.now - 600))
            conn.execute("INSERT INTO klm_drive_folders VALUES(?,?,?,?,?)",
                         ("private-scan-id", "PRIVATE_FOLDER_1", "COMPLETE", 18, None))
            conn.execute("INSERT INTO klm_drive_folders VALUES(?,?,?,?,?)",
                         ("private-scan-id", "PRIVATE_FOLDER_2", "RETRY", 2,
                          "REVISION_CHANGED_DURING_SCAN"))
            conn.execute("INSERT INTO klm_drive_folders VALUES(?,?,?,?,?)",
                         ("private-scan-id", "PRIVATE_FOLDER_3", "RETRY", 0,
                          "PRIVATE_PROVIDER_EXCEPTION"))
            conn.execute("INSERT INTO klm_drive_seen VALUES(?,?)",
                         ("private-scan-id", "PRIVATE_SOURCE_ID"))
        result = self.observe()["durable"]["scan"]
        self.assertEqual(result["state"], "OBSERVED")
        self.assertEqual(result["pages"], 20)
        self.assertEqual(result["status_counts"]["RETRY"], 2)
        self.assertEqual(result["status_counts"]["COMPLETE"], 1)
        self.assertEqual(result["reason_counts"], {
            "REVISION_CHANGED_DURING_SCAN": 1, "OTHER_REDACTED": 1})
        for secret in ("PRIVATE_", "owner-secret", "private-scan-id"):
            self.assertNotIn(secret, json.dumps(result))

    def test_scan_checkpoint_not_in_schema_is_unknown_not_empty(self):
        result = self.observe()["durable"]["scan"]
        self.assertEqual(result, {"state": "UNAVAILABLE"})


    def test_lifecycle_counts_are_readonly_and_no_source_identifiers_escape(self):
        with sqlite3.connect(self.work_db) as db:
            db.execute("CREATE TABLE klm_drive_intake(intake_id TEXT, job_id TEXT)")
            db.execute("INSERT INTO klm_drive_intake VALUES('PRIVATE_INTAKE_ID','klm-drive:private')")
            db.execute("INSERT INTO work_steps VALUES(?,?,?,?,?,?)",
                       ("klm-drive:private", 0, "klm-readonly", "FAILED",
                        "PRIVATE_ORIGINAL_SOURCE", self.now))
            db.execute("CREATE TABLE klm_atoms(atom_id TEXT)")
            db.execute("INSERT INTO klm_atoms VALUES('PRIVATE_ATOM')")
            db.execute("CREATE TABLE klm_atom_features(atom_id TEXT)")
            db.execute("CREATE TABLE klm_relation_reviews(status TEXT)")
            db.execute("INSERT INTO klm_relation_reviews VALUES('UNRESOLVED')")
            db.execute("CREATE TABLE klm_placement_candidates(atom_id TEXT)")
            db.execute("INSERT INTO klm_placement_candidates VALUES('PRIVATE_ATOM')")
            db.execute("CREATE TABLE klm_retry_history(attempt_id TEXT)")
            db.execute("INSERT INTO klm_retry_history VALUES('PRIVATE_RETRY')")
            db.execute("INSERT INTO work_steps VALUES(?,?,?,?,?,?)",
                       ("klm-audit:daily:2026-11-08", 0, "audit-derived-receipts",
                        "VERIFIED", "PRIVATE_AUDIT", self.now))
        result = self.observe()["durable"]["lifecycle"]
        self.assertEqual(result["state"], "OBSERVED")
        self.assertEqual(result["work_states"]["FAILED"], 1)
        self.assertEqual(result["work_states"]["PLANNED"], 0)
        self.assertEqual(result["atoms"], 1)
        self.assertEqual(result["relation_reviews"], 1)
        self.assertEqual(result["unresolved_reviews"], 1)
        self.assertEqual(result["placements"], 1)
        self.assertEqual(result["retry_history"], 1)
        self.assertEqual(result["missing_atom_features"], 1)
        self.assertEqual(result["audit_work_states"]["VERIFIED"], 1)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_lifecycle_counts_missing_schema_is_unknown_not_zero(self):
        self.assertEqual(
            self.observe()["durable"]["lifecycle"], {"state": "UNAVAILABLE"})


    def test_legacy_verified_step_has_separate_independent_noeffect_receipt(self):
        self.report_data["inference"] = "NO_INPUT"
        self.report_data["legacy_inference"] = "READ_ONLY_VERIFIED"
        self._write_report()
        with sqlite3.connect(self.work_db) as db:
            db.execute("INSERT INTO work_steps VALUES(?,?,?,?,?,?)",
                       ("klm-legacy-review:fixture",0,"klm-legacy-source-review",
                        "VERIFIED",json.dumps({
                            "result_ref":"klm-atoms-sha256:" + "c"*64,
                            "source_sha256":"b"*64,
                            "execution_authority":False,
                        }),self.now))
        result = self.observe()
        self.assertEqual(result["durable"]["verified_work_steps"], 1)
        self.assertEqual(result["durable"]["verified_legacy_work_steps"], 1)
        self.assertEqual(result["durable"]["validated_legacy_noeffect_receipts"], 1)
        self.assertTrue(result["one_noeffect_job_evidenced"])
        self.assertNotIn("klm-legacy-review:fixture", json.dumps(result))

    def test_unconfirmed_inference_is_not_success(self):
        for status in ("WAIT_DEV_IDLE", "FAILED", "DEFER_COMPUTE_BUSY", None):
            self.report_data["inference"] = status
            self._write_report()
            self.assertFalse(self.observe()["one_noeffect_job_evidenced"])

    def test_native_priority_field_is_optional_not_inferred(self):
        del self.report_data["development"]["native_only_approved"]
        self._write_report()
        self.assertIsNone(self.observe()["development"]["native_only_approved"])

    def test_stale_current_report_is_not_current_acceptance(self):
        old = self.now - probe.MAX_AGE_SECONDS - 1
        os.utime(self.report, (old, old))
        result = self.observe()
        self.assertFalse(result["report_fresh"])
        self.assertFalse(result["one_noeffect_job_evidenced"])

    def test_owner_file_symlink_and_world_readable_report_are_rejected(self):
        self.report.chmod(0o644)
        self.assertEqual(self.observe()["state"], "UNAVAILABLE")
        self.report.chmod(0o600)
        self.report.unlink()
        self.report.symlink_to(self.host_config)
        self.assertEqual(self.observe()["state"], "UNAVAILABLE")

    def test_untrusted_service_label_does_not_follow_alternate_report(self):
        row = plistlib.loads(self.plist.read_bytes())
        row["Label"] = "dev.evil.fake"
        self.plist.write_bytes(plistlib.dumps(row))
        self.assertEqual(self.observe()["reason"], "SERVICE_LABEL_MISMATCH")

    def test_unverified_durable_receipt_cannot_claim_a_job(self):
        with sqlite3.connect(self.work_db) as conn:
            conn.execute("UPDATE work_steps SET result=?", (
                json.dumps({"result_ref":"not-a-hash", "execution_authority":True}),))
            conn.commit()
        result = self.observe()
        self.assertEqual(result["durable"]["verified_work_steps"], 1)
        self.assertEqual(result["durable"]["validated_noeffect_receipts"], 0)
        self.assertFalse(result["one_noeffect_job_evidenced"])

    def test_historical_verified_job_does_not_prove_latest_model_tick(self):
        with sqlite3.connect(self.work_db) as conn:
            conn.execute("UPDATE work_steps SET updated_at=?", (self.now - 86400,))
            conn.commit()
        result = self.observe()
        self.assertEqual(result["durable"]["validated_noeffect_receipts"], 1)
        self.assertEqual(result["durable"]["validated_recent_noeffect_receipts"], 0)
        self.assertFalse(result["one_noeffect_job_evidenced"])

    def test_missing_work_db_cannot_invent_success(self):
        self.work_db.unlink()
        value = self.observe()
        self.assertEqual(value["state"], "OBSERVED")
        self.assertEqual(value["durable"], {
            "state": "UNAVAILABLE", "reason": "WORK_QUERY_UNAVAILABLE"})
        self.assertFalse(value["one_noeffect_job_evidenced"])

    def test_world_readable_durable_db_denied_with_constant_code(self):
        self.work_db.chmod(0o644)
        value = self.observe()
        self.assertEqual(value["durable"], {
            "state": "UNAVAILABLE", "reason": "WORK_DB_NOT_PRIVATE"})
        self.assertFalse(value["one_noeffect_job_evidenced"])
        self.assertNotIn(str(self.work_db), json.dumps(value))

    def test_private_sqlite_missing_table_is_not_misreported_as_empty(self):
        with sqlite3.connect(self.work_db) as conn:
            conn.execute("DROP TABLE work_steps")
            conn.commit()
        self.assertEqual(self.observe()["durable"]["state"], "UNAVAILABLE")

    def test_unknown_private_values_are_never_echoed(self):
        self.report_data["status"] = "PRIVATE_TOKEN_UNRECOGNIZED"
        self.report_data["inference"] = "PRIVATE_MODEL_LOG"
        self.report_data["folders"] = True
        self._write_report()
        value = self.observe()
        self.assertEqual(value["status"], "UNKNOWN")
        self.assertEqual(value["inference"], "UNKNOWN")
        self.assertIsNone(value["folders"])
        self.assertNotIn("PRIVATE_", json.dumps(value))


class BridgeKlmOperationTests(unittest.TestCase):
    def test_bridge_requires_exact_owner_title_and_schema(self):
        body = '<!-- foundation-m1-bridge: {"version":1,"operation":"klm-status"} -->'
        self.assertEqual(bridge.parse_request("Foundation M1 Bridge: klm-status", body),
                         "klm-status")
        for title, candidate in [
            ("Foundation M1 Bridge: klm-status", body.replace('"version":1', '"version":false')),
            ("Foundation M1 Bridge: klm-status", body.replace(' -->', ',"path":"/private"} -->')),
            ("Foundation M1 Bridge: snapshot", body),
        ]:
            with self.subTest(title=title, candidate=candidate), self.assertRaises(
                bridge.BridgeDenied
            ):
                bridge.parse_request(title, candidate)

    def test_bridge_live_validated_once_and_only_fixed_probe_runs(self):
        event = {
            "action": "opened", "repository": {"full_name": bridge.REPOSITORY},
            "issue": {
                "number": 777, "state": "open",
                "title": "Foundation M1 Bridge: klm-status",
                "body": '<!-- foundation-m1-bridge: {"version":1,"operation":"klm-status"} -->',
                "user": {"login": bridge.OWNER_LOGIN},
            },
        }
        calls = []
        def api(method, path, token, payload=None):
            calls.append(method)
            if method == "GET" and "comments?" not in path:
                return event["issue"]
            if method == "GET":
                return []
            self.assertIn('"operation": "klm-status"', payload["body"])
            return {"id": 11}
        with mock.patch.object(bridge, "_github_api", side_effect=api), \
             mock.patch.object(probe, "klm_status",
                               return_value={"state": "UNAVAILABLE", "reason": "NO_REPORT"}) as getter:
            self.assertEqual(bridge.execute(event, "test-token", "456"), "OBSERVED")
        getter.assert_called_once_with()
        self.assertEqual(calls, ["GET", "GET", "POST"])

    def test_launchctl_status_reads_only_fixed_owned_label(self):
        with mock.patch.object(probe.subprocess, "run") as command:
            command.return_value.returncode = 0
            command.return_value.stdout = (
                "state = active\n"
                "runs = 7\n"
                "last exit code = 0\n"
                "run interval = 900 seconds\n"
                "secret = NEVER_EXPORT\n")
            result = probe._launch_agent_status()
        self.assertEqual(result, {"state": "OBSERVED", "runs": 7,
                                  "interval_seconds": 900, "last_exit_code": 0})
        self.assertEqual(command.call_args.args[0],
                         ["/bin/launchctl", "print",
                          "gui/" + str(os.getuid()) + "/" + probe.LABEL])
        self.assertNotIn("NEVER_EXPORT", json.dumps(result))
        self.assertEqual(command.call_args.kwargs["timeout"], 3)

    def test_no_one_time_grant_or_host_change_in_probe(self):
        import inspect
        source = inspect.getsource(probe)
        self.assertNotIn("subprocess.Popen(", source)
        self.assertNotIn("subprocess.run(argv, shell=True", source)
        self.assertNotIn("request.urlopen(", source)
        self.assertNotIn(".execute('UPDATE", source)
        self.assertNotIn(".execute('DELETE", source)


if __name__ == "__main__":
    unittest.main()

