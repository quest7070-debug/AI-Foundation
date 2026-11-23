import json
import unittest
from unittest import mock

from scripts import m1_operator_status_probe as probe
from scripts import m1_development_bridge as bridge


def document():
    return {"state": "WAITING_HUMAN", "severity_counts": [0, 0, 0, 1, 1],
        "notices": [{"status": "WAITING_HUMAN", "actionable": True, "input_required": False,
                     "updated_at": 100, "subject": "SECRET_ID", "detail_ja": "SECRET_DETAIL"},
                    {"status": "UNCERTAIN", "input_required": True, "updated_at": 110}],
        "tasks": [{"status": "RUNNING", "text": "SECRET_TASK", "result": "SECRET_RESULT"}],
        "activity": [{"function": "CODE", "started_at": 90, "binding": "SECRET_BINDING"}],
        "services": [{"name": "SECRET_SERVICE", "ok": True}, {"ok": False}, {"ok": "secret"}],
        "providers": [{"binding": "SECRET_CREDENTIAL"}], "routes": [{"primary": "SECRET_ROUTE"}]}


class OperatorProjectionTests(unittest.TestCase):
    def setUp(self):
        # This module also runs under the owner's stdlib-only unittest runner.
        # Both runners must isolate live owner files/stdio from synthetic tests.
        for name, value in (
                ("_host_fidelity_summary", {"status": "UNVERIFIED", "private_content_exported": False, "model_calls": 0}),
                ("_host_development_catalog", {"state": "UNVERIFIED", "remote_caller_verified": False, "model_calls": 0})):
            patcher = mock.patch.object(probe, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_klm_lifecycle_exports_only_typed_counts(self):
        data = document()
        self.assertEqual(probe.project_operator(data, 200)["klm_lifecycle"],
                         {"state": "UNVERIFIED"})
        data["development"] = {
            "klm_lifecycle_state": "OBSERVED", "klm_atoms": 45,
            "klm_missing_features": 8, "klm_unresolved_reviews": 86,
            "klm_relations": 0, "klm_failed_intake": 1, "private": "SECRET"}
        row = probe.project_operator(data, 200)["klm_lifecycle"]
        self.assertEqual(row, {"state": "OBSERVED", "atoms": 45,
            "missing_features": 8, "unresolved_reviews": 86,
            "relations": 0, "failed_intake": 1,
            "observed_at_epoch": None, "snapshot_age_seconds": None})
        self.assertNotIn("SECRET", json.dumps(row))
        data["development"]["klm_atoms"] = True
        self.assertEqual(probe.project_operator(data, 200)["klm_lifecycle"],
                         {"state": "UNVERIFIED"})

    def test_klm_lifecycle_reports_observation_time_and_only_bounded_cache_age(self):
        data = document()
        data["development"] = {
            "klm_lifecycle_state": "OBSERVED", "klm_atoms": 45,
            "klm_missing_features": 8, "klm_unresolved_reviews": 86,
            "klm_relations": 0, "klm_failed_intake": 1,
            "klm_lifecycle_observed_at": 185,
            "klm_lifecycle_snapshot_age_seconds": 15,
            "private": "SECRET"}
        row = probe.project_operator(data, 200)["klm_lifecycle"]
        self.assertEqual((row["observed_at_epoch"], row["snapshot_age_seconds"]), (185, 15))
        for timestamp, age in ((True, True), ("185", "15"), (250, 31), (-1, -1)):
            data["development"].update(klm_lifecycle_observed_at=timestamp,
                                       klm_lifecycle_snapshot_age_seconds=age)
            row = probe.project_operator(data, 200)["klm_lifecycle"]
            self.assertIsNone(row["observed_at_epoch"])
            self.assertIsNone(row["snapshot_age_seconds"])
            self.assertEqual(row["atoms"], 45)
            self.assertNotIn("SECRET", json.dumps(row))

    def test_only_allowed_state_counts_and_timestamps_leave_api(self):
        output = probe.project_operator(document(), 200)
        self.assertEqual(output["operator_state"], "WAITING_HUMAN")
        self.assertEqual(output["notices"]["status_counts"], {"WAITING_HUMAN": 1, "UNCERTAIN": 1})
        self.assertEqual(output["notices"]["actionable_count"], 1)
        self.assertEqual(output["tasks"]["status_counts"], {"RUNNING": 1})
        self.assertEqual(output["activity"]["function_counts"], {"CODE": 1})
        self.assertEqual(output["services"]["unknown"], 1)
        self.assertEqual(output["coverage"], "OPERATOR_API_WINDOW_ONLY")
        self.assertNotIn("SECRET", json.dumps(output))
        self.assertEqual(output["state_diagnostics"], {
            "failed_work_window": None, "failed_effect_window": None,
            "dismissed_failed_notices_window": None,
        })

    def test_failed_banner_diagnostics_are_bounded_counts_only(self):
        data = document()
        data["state"] = "FAILED"
        data["state_diagnostics"] = {
            "failed_work_window": 2,
            "failed_effect_window": 1,
            "dismissed_failed_notices_window": 2,
            "owner_private": "SECRET",
        }
        output = probe.project_operator(data, 200)
        self.assertEqual(output["state_diagnostics"], {
            "failed_work_window": 2, "failed_effect_window": 1,
            "dismissed_failed_notices_window": 2,
        })
        self.assertNotIn("SECRET", json.dumps(output))
        for value in ("2", 2.0, -1, 99999, True, {"secret": "SECRET"}):
            data["state_diagnostics"]["failed_work_window"] = value
            self.assertIsNone(probe.project_operator(data, 200)["state_diagnostics"]["failed_work_window"])

    def test_runtime_wiring_is_tristate_and_cannot_export_private_values(self):
        old = probe.project_operator(document(), 200)
        self.assertIsNone(old["runtime_wiring"]["humanmodel_factory_registered"])
        self.assertIsNone(old["runtime_wiring"]["legacy_question_resolver_enabled"])
        self.assertIsNone(old["runtime_wiring"]["host_question_resolver_registered"])
        data = document()
        data["development"] = {"humanmodel_factory_registered": True,
                               "legacy_question_resolver_enabled": False,
                               "host_question_resolver_registered": True,
                               "owner_id": "SECRET_OWNER", "view_id": "SECRET_VIEW"}
        value=probe.project_operator(data, 200)
        self.assertEqual(value["runtime_wiring"], {
            "humanmodel_factory_registered": True,
            "legacy_question_resolver_enabled": False,
            "host_question_resolver_registered": True,
        })
        self.assertNotIn("SECRET", json.dumps(value))
        data["development"]["humanmodel_factory_registered"]="SECRET_TRUE"
        data["development"]["legacy_question_resolver_enabled"]="SECRET_FALSE"
        data["development"]["host_question_resolver_registered"]=1
        redacted=probe.project_operator(data, 200)["runtime_wiring"]
        assert all(value is None for value in redacted.values())

    def test_operator_direct_mcp_receipt_parity_requires_real_bound_host_source(self):
        data = document()
        self.assertEqual(probe.project_operator(data, 200)["direct_mcp"],
                         {"status": "UNVERIFIED"})
        data["development"] = {
            "source": "CURRENT_GUARD_WORK_SNAPSHOT+M1_OWNER_RUNTIME",
            "direct_mcp_status": "WORK_RECEIPTS_ONLY",
            "direct_mcp_running": 0, "direct_mcp_verified_receipts": 1,
            "direct_mcp_failed": 1, "direct_mcp_last_route": "STRATA",
            "direct_mcp_updated_at": 180,
            "owner_source": "SECRET_PRIVATE_OWNER",
            "remote_client_session": "SECRET_REMOTE_CLIENT"}
        observed = probe.project_operator(data, 200)["direct_mcp"]
        self.assertEqual(observed, {
            "status": "WORK_RECEIPTS_ONLY", "running": 0, "verified_receipts": 1,
            "failed": 1, "last_route": "STRATA", "updated_at_epoch": 180,
            "claim": "LOCAL_WORK_RECEIPTS_ONLY"})
        self.assertNotIn("SECRET", json.dumps(probe.project_operator(data, 200)))
        for field, invalid in (
                ("source", "PRIVATE_SOURCE"),
                ("direct_mcp_running", True),
                ("direct_mcp_verified_receipts", -1),
                ("direct_mcp_failed", 33),
                ("direct_mcp_last_route", "PRIVATE_REMOTE"),
                ("direct_mcp_updated_at", float("nan"))):
            changed = dict(data["development"], **{field: invalid})
            self.assertEqual(probe.project_operator({**data, "development": changed}, 200)["direct_mcp"],
                             {"status": "UNVERIFIED"})
        data["development"]["direct_mcp_updated_at"] = None
        self.assertIsNone(probe.project_operator(data, 200)["direct_mcp"]["updated_at_epoch"])

    def test_failed_notices_report_only_whitelisted_kind_counts(self):
        data = document()
        data["notices"].extend([
            {"status": "FAILED", "kind": "effect", "subject": "SECRET_EFFECT"},
            {"status": "FAILED", "kind": "work", "subject": "SECRET_JOB"},
            {"status": "FAILED", "kind": "private-owner-token", "secret": "SECRET"},
        ])
        result = probe.project_operator(data, 200)
        self.assertEqual(result["notices"]["failed_kind_counts"],
                         {"effect": 1, "work": 1, "UNKNOWN": 1})
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("private-owner-token", json.dumps(result))

    def test_unknown_values_and_future_nonfinite_times_are_withheld(self):
        data = document()
        data["state"] = "PRIVATE_STATE"
        data["notices"][0].update(status="PRIVATE_STATUS", updated_at=float("nan"))
        data["notices"][1]["updated_at"] = 100000
        data["activity"][0].update(function="PRIVATE_FUNCTION", started_at=True)
        data["severity_counts"][0] = True
        output = probe.project_operator(data, 200)
        self.assertEqual(output["operator_state"], "UNKNOWN")
        self.assertIsNone(output["severity_counts"])
        self.assertIsNone(output["notices"]["latest_updated_at_epoch"])
        self.assertIsNone(output["activity"]["oldest_started_at_epoch"])
        self.assertNotIn("PRIVATE", json.dumps(output))

    def test_unbounded_or_incompatible_schema_cannot_become_empty_success(self):
        for change in ({"tasks": {}}, {"notices": [None]}, {"activity": [{}] * (probe.MAX_ROWS + 1)},
                       {"state": None}):
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                probe.project_operator({**document(), **change}, 200)

    def test_owner_work_failure_summary_is_bounded_and_secret_free(self):
        from pathlib import Path
        from types import ModuleType, SimpleNamespace
        import sqlite3
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db_file = root / "work.db"
            with sqlite3.connect(db_file) as conn:
                conn.execute("CREATE TABLE work_steps(status TEXT, result TEXT, updated_at REAL, position INTEGER, name TEXT)")
                conn.executemany(
                    "INSERT INTO work_steps VALUES(?,?,?,?,?)",
                    [("FAILED", "RuntimeError", probe.time.time() - 8 * 86400, 0, "intake"),
                     ("FAILED", "PRIVATE-SECRET-OWNER-TEXT", probe.time.time() - 8 * 86400, 0, "private-step"),
                     ("VERIFIED", "PermissionError", probe.time.time(), 0, "intake")])
            # The production release module requires Python 3.12. The
            # longstanding read-only acceptance also runs on macOS Python 3.9;
            # inject only its two trusted binding functions, with no import.
            fake = ModuleType("scripts.m1_operator_release_cli")
            fake._guard_path = lambda home: (root / "guard.db", None)
            fake._installed_config = lambda home: SimpleNamespace(
                data_dir=str(root), work_db="work.db")
            with mock.patch.dict(sys.modules, {"scripts.m1_operator_release_cli": fake}):
                observed = probe._host_work_failure_summary()
                self.assertEqual(observed, {
                    "state": "OBSERVED", "sample_count": 2,
                    "failure_types": {"OTHER": 1, "RuntimeError": 1},
                    "complete": True,
                    "stage_counts": {"INTAKE": 1, "OTHER_STAGE": 1},
                    "age_counts": {"OLDER_THAN_7_DAYS": 2},
                })
                self.assertNotIn("PRIVATE", json.dumps(observed))
                # A symlink must never be followed, even into an owned source.
                db_file.rename(root / "real-work.db")
                db_file.symlink_to(root / "real-work.db")
                self.assertEqual(probe._host_work_failure_summary(),
                                 {"state": "UNAVAILABLE"})

    def test_work_failure_stage_and_age_cannot_expose_raw_step_names(self):
        result = probe._failure_context(
            [("TimeoutError", 0, "intake", 99),
             ("TimeoutError", 0, "PRIVATE_JOB_NAME", 2),
             ("TimeoutError", 0, "klm-readonly", 1000)],
            observed_at=100)
        self.assertEqual(result, {
            "stage_counts": {"INTAKE": 1, "OTHER_STAGE": 1, "KLM_READONLY": 1},
            "age_counts": {"UNDER_1_DAY": 2, "AGE_UNKNOWN": 1},
        })
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_work_failure_classification_uses_only_fixed_codes(self):
        data = probe._classify_failure_results(
            ["TimeoutExpired", "PRIVATE_SOURCE", "FAILED_EFFECT"], complete=False)
        self.assertEqual(data, {
            "state": "BOUNDED_PARTIAL", "sample_count": 3, "complete": False,
            "failure_types": {"TimeoutExpired": 1, "OTHER": 1, "FAILED_EFFECT": 1},
        })
        self.assertNotIn("PRIVATE", json.dumps(data))

    def test_loopback_get_bounds_body_and_closes_connection(self):
        with mock.patch.object(probe, "require_m1"), \
             mock.patch.object(probe.http.client, "HTTPConnection") as http:
            conn = http.return_value
            conn.getresponse.return_value.status = 200
            conn.getresponse.return_value.read.return_value = json.dumps(document()).encode()
            result = probe.operator_status(now=200)
        self.assertEqual(result["state"], "OBSERVED")
        http.assert_called_once_with("127.0.0.1", 8766, timeout=3)
        conn.request.assert_called_once_with("GET", "/api/human",
            headers={"Host": "127.0.0.1", "Accept": "application/json"})
        conn.getresponse.return_value.read.assert_called_once_with(probe.MAX_BODY + 1)
        conn.close.assert_called_once()

    def test_redirect_error_size_duplicate_and_private_exception_do_not_leak(self):
        cases = [(302, b"SECRET_REDIRECT", "OPERATOR_API_NOT_OK"),
                 (200, b"X" * (probe.MAX_BODY + 1), "OPERATOR_RESPONSE_TOO_LARGE"),
                 (200, b'{"state":"READY","state":"SECRET"}', "OPERATOR_SCHEMA_INVALID"),
                 (200, b'{"secret":"SECRET"}', "OPERATOR_SCHEMA_INVALID")]
        for status, body, reason in cases:
            with self.subTest(reason=reason), mock.patch.object(probe, "require_m1"), \
                 mock.patch.object(probe.http.client, "HTTPConnection") as http:
                conn = http.return_value
                conn.getresponse.return_value.status = status
                conn.getresponse.return_value.read.return_value = body
                result = probe.operator_status()
                self.assertEqual(result["reason"], reason)
                self.assertNotIn("SECRET", json.dumps(result))
                conn.close.assert_called_once()
        with mock.patch.object(probe, "require_m1"), \
             mock.patch.object(probe.http.client, "HTTPConnection") as http:
            http.return_value.request.side_effect = OSError("SECRET /private")
            self.assertEqual(probe.operator_status(),
                {"state": "UNAVAILABLE", "reason": "OPERATOR_API_UNREACHABLE"})

    def test_exact_operation_dispatch_and_no_caller_endpoint(self):
        op = "operator-status"
        body = '<!-- foundation-m1-bridge: {"version":1,"operation":"' + op + '"} -->'
        issue = {"number": 123, "state": "open", "user": {"login": bridge.OWNER_LOGIN},
                 "title": "Foundation M1 Bridge: " + op, "body": body}
        event = {"action": "opened", "repository": {"full_name": bridge.REPOSITORY}, "issue": issue}
        with self.assertRaises(bridge.BridgeDenied):
            bridge.parse_request(issue["title"], body.replace('} -->', ',"url":"http://private"} -->'))
        with mock.patch.object(bridge, "_github_api", side_effect=[issue, [], {}]), \
             mock.patch.object(probe, "operator_status", return_value={"state": "OBSERVED"}) as read:
            self.assertEqual(bridge.execute(event, "token", "123"), "OBSERVED")
        read.assert_called_once_with()


    def test_approval_summary_is_count_only_and_never_auth_source(self):
        data = document()
        data["notices"].extend([
            {"kind": "approval", "status": "WAITING_HUMAN",
             "approval_ref": "a" * 64, "action": "production_deploy",
             "target": "SECRET_TARGET", "run_id": "SECRET_RUN"},
            {"kind": "primary_review", "status": "PRIMARY_REVIEW_STARTED",
             "level": 2, "detail_ja": "SECRET_HUMANMODEL_SOURCE"},
            {"kind": "primary_review", "status": "PRIMARY_REVIEW_RESOLVED",
             "level": 2, "detail_ja": "SECRET_DECISION"},
            {"kind": "primary_review_escalation", "status": "OWNER_REVIEW_REQUIRED",
             "level": 4, "detail_ja": "SECRET_OWNER"},
            # Unsupported levels and invalid approval refs never count.
            {"kind": "approval", "status": "WAITING_HUMAN",
             "approval_ref": "not-a-current-ref"},
            {"kind": "primary_review_escalation", "status": "OWNER_REVIEW_REQUIRED",
             "level": 2},
        ])
        result = probe.project_operator(data, 200)
        self.assertEqual(result["approval"], {
            "current_guard_requests": 1,
            "primary_review_started": 1,
            "primary_review_resolved": 1,
            "owner_escalation_waiting": 1,
        })
        self.assertNotIn("SECRET", json.dumps(result))
        self.assertNotIn("a" * 64, json.dumps(result))
        self.assertNotIn("production_deploy", json.dumps(result))
        # A count of pending requests never means any decision is authorized.
        self.assertNotIn("authorized", json.dumps(result).lower())



if __name__ == "__main__":
    unittest.main()


def test_service_breakdown_exposes_only_five_fixed_labels():
    data = document()
    data["services"] = [
        {"name": "LOCAL COMPUTE", "ok": True},
        {"name": "TOOLHIVE FILES", "ok": False,
         "detail": "SECRET_PRIVATE_PROCESS"},
        {"name": "PROVIDER REGISTRY", "ok": None},
        {"name": "SECRET_SERVICE_NAME", "ok": True},
    ]
    observed = probe.project_operator(data, 200)["services"]
    assert observed["by_service"] == {
        "LOCAL COMPUTE": "READY",
        "PROVIDER REGISTRY": "UNKNOWN",
        "TOOLHIVE FILES": "UNAVAILABLE",
        "TOOLHIVE CODE": "NOT_OBSERVED",
        "LONG-TERM HEALTH": "NOT_OBSERVED",
    }
    assert "SECRET" not in json.dumps(observed)
    data["services"].append({"name": "LOCAL COMPUTE", "ok": False})
    assert probe.project_operator(data, 200)["services"]["by_service"]["LOCAL COMPUTE"] == "UNKNOWN"


def test_live_readback_checks_fixed_overview_tile_without_exporting_html():
    data = document()
    data["development"] = {
        "klm_lifecycle_state": "OBSERVED", "klm_atoms": 45,
        "klm_missing_features": 8, "klm_unresolved_reviews": 86,
        "klm_relations": 0, "klm_failed_intake": 1,
        "klm_lifecycle_observed_at": 185,
        "klm_lifecycle_snapshot_age_seconds": 15}
    page = ('<p>SECRET_PRIVATE_PAGE</p><a class="overview-tile" href="#development">'
            '<small>KLM / PROCESSING</small><strong>REVIEW REQUIRED</strong>'
            '<span>INDEX READ 2026-11-16 21:00:00 JST · SNAPSHOT AGE 15s</span></a>')
    api, html = mock.Mock(status=200), mock.Mock(status=200)
    api.read.return_value = json.dumps(data).encode()
    html.read.return_value = page.encode()
    with mock.patch.object(probe, "require_m1"), \
         mock.patch.object(probe, "_host_fidelity_summary", return_value={"status": "UNVERIFIED"}), \
         mock.patch.object(probe, "_host_development_catalog", return_value={"state": "UNVERIFIED"}), \
         mock.patch.object(probe.http.client, "HTTPConnection") as http:
        connection = http.return_value
        connection.getresponse.side_effect = [api, html]
        result = probe.operator_status(now=200)
    assert result["klm_lifecycle"]["observed_at_epoch"] == 185
    assert result["klm_overview"] == {"state": "OBSERVED", "formatted_index_read": True,
                                      "snapshot_age_displayed": True}
    assert connection.request.call_args_list == [
        mock.call("GET", "/api/human", headers={"Host": "127.0.0.1", "Accept": "application/json"}),
        mock.call("GET", "/", headers={"Host": "127.0.0.1", "Accept": "text/html"})]
    assert "SECRET" not in json.dumps(result)


def test_overview_readback_does_not_accept_labels_outside_fixed_tile_or_duplicate_tiles():
    good = ('<a class="overview-tile"><small>KLM / PROCESSING</small><span>'
            'INDEX READ 2026-11-16 21:00:00 JST · SNAPSHOT AGE 15s</span></a>')
    for page in ('<p>KLM / PROCESSING INDEX READ 2026-11-16 21:00:00 JST SNAPSHOT AGE 15s</p>',
                 good + good):
        connection = mock.Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = page.encode()
        assert probe._klm_overview_readback(connection) == {
            "state": "UNVERIFIED",
            "reason": "OVERVIEW_TILE_AMBIGUOUS" if page == good + good else "OVERVIEW_TILE_NOT_FOUND",
        }



def test_overview_readback_reports_only_fixed_failure_reasons():
    cases = [
        (503, b"SECRET_HTTP_BODY", None, "OVERVIEW_HTTP_NOT_OK"),
        (200, b"X" * (probe.MAX_BODY + 1), None, "OVERVIEW_RESPONSE_TOO_LARGE"),
        (200, bytes([255]) + b"SECRET_PRIVATE_PAGE", None, "OVERVIEW_ENCODING_INVALID"),
        (200, b"", TimeoutError("SECRET_TIMEOUT"), "OVERVIEW_TIMEOUT"),
        (200, b"", OSError("SECRET_PATH"), "OVERVIEW_TRANSPORT_ERROR"),
        (200, b"", probe.http.client.RemoteDisconnected("SECRET_PEER"), "OVERVIEW_TRANSPORT_ERROR"),
        (200, b"", ValueError("SECRET_PARSE"), "OVERVIEW_PARSE_INVALID"),
    ]
    for status, body, error, reason in cases:
        connection = mock.Mock()
        connection.getresponse.return_value.status = status
        connection.getresponse.return_value.read.return_value = body
        if error is not None:
            connection.request.side_effect = error
        result = probe._klm_overview_readback(connection)
        assert result == {"state": "UNVERIFIED", "reason": reason}
        assert "SECRET" not in json.dumps(result)


def test_klm_review_triage_readback_requires_exact_fixed_counts_and_total():
    data = document()
    assert probe.project_operator(data, 200)["klm_review_triage"] == {"state": "UNVERIFIED"}
    counts = dict(conflict=1, revision=2, qualifier=3, dependency=4,
                  difference=5, duplicate=6, other=7)
    data["development"] = {
        "klm_lifecycle_state": "OBSERVED", "klm_unresolved_reviews": 28,
        "klm_review_triage": counts, "private_reason": "SECRET_PRIVATE_REASON",
    }
    result = probe.project_operator(data, 200)["klm_review_triage"]
    assert result == {"state": "OBSERVED", "counts": counts}
    assert "SECRET" not in json.dumps(result)
    result["counts"]["conflict"] = 99
    assert counts["conflict"] == 1
    for invalid in (
            {**counts, "conflict": True}, {**counts, "conflict": -1},
            {**counts, "conflict": 100001}, {**counts, "conflict": "1"},
            {**counts, "SECRET_PRIVATE_CATEGORY": 0},
            {key: value for key, value in counts.items() if key != "other"}):
        data["development"]["klm_review_triage"] = invalid
        assert probe.project_operator(data, 200)["klm_review_triage"] == {"state": "UNVERIFIED"}
    data["development"]["klm_review_triage"] = counts
    for total in (27, True, "28", -1, 100001):
        data["development"]["klm_unresolved_reviews"] = total
        assert probe.project_operator(data, 200)["klm_review_triage"] == {"state": "UNVERIFIED"}
    data["development"].update(klm_unresolved_reviews=28, klm_lifecycle_state="UNVERIFIED")
    assert probe.project_operator(data, 200)["klm_review_triage"] == {"state": "UNVERIFIED"}


def test_selfdev_local_catalog_never_claims_remote_acceptance():
    # A synthetic owner-side stdio inventory is not a verified remote ChatGPT
    # session. Missing either command is a release blocker, not partial PASS.
    import plistlib
    from types import SimpleNamespace
    from pathlib import Path
    from scripts import m1_guarded_tunnel_refresh as refresh
    from scripts import m1_guarded_tunnel_cutover as cutover

    staged = Path("/private/tmp/.ai-foundation-tunnel-sources") / ("a" * 40)
    plist = plistlib.dumps({"ProgramArguments": [
        "/bin/bash", "-B", str(staged / "scripts/m1_guarded_tunnel.py"), "run"]})
    for names in (
        ("foundation_status", "development_request", "development_admit"),
        ("foundation_status", "development_continue", "development_cycle"),
    ):
        wire = "\n".join(json.dumps(row) for row in [
            {"jsonrpc": "2.0", "id": 1, "result": {"name": "synthetic"}},
            {"jsonrpc": "2.0", "id": 2, "result": {
                "tools": [{"name": name} for name in names]}},
        ])
        with mock.patch.object(probe.os, "getuid", return_value=501), \
             mock.patch.object(probe.os, "geteuid", return_value=501), \
             mock.patch.object(refresh, "previous_agent", return_value=plist), \
             mock.patch.object(cutover, "_request",
                               side_effect=lambda i, method: {
                                   "jsonrpc": "2.0", "id": i, "method": method}), \
             mock.patch("subprocess.run", return_value=
                        SimpleNamespace(returncode=0, stdout=wire)):
            result = probe._host_development_catalog()
        assert result["state"] == "OBSERVED"
        assert result["development_continue_available"] == (
            "development_continue" in names)
        assert result["development_cycle_available"] == (
            "development_cycle" in names)
        assert result["selfdev_catalog_ready"] == (
            {"development_continue", "development_cycle"} <= set(names))
        assert result["remote_caller_verified"] is False
        assert result["model_calls"] == 0
        assert "SECRET" not in json.dumps(result)
