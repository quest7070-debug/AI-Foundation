"""Pure-stdlib regression suite for the GitHub-to-M1 bridge."""
import json
import unittest
from unittest import mock

from scripts import m1_development_bridge as bridge


def event(operation="snapshot", author="quest7070-debug", repo=None):
    issue = {
        "number": 321,
        "state": "open",
        "title": "Foundation M1 Bridge: " + operation,
        "body": '<!-- foundation-m1-bridge: {"version":1,"operation":"' + operation + '"} -->',
        "user": {"login": author},
    }
    return {
        "action": "opened",
        "repository": {"full_name": repo or bridge.REPOSITORY},
        "issue": issue,
    }


class RequestContractTests(unittest.TestCase):
    def test_exact_owner_request(self):
        e = event()
        self.assertEqual(bridge.validate_event(e), (321, "snapshot"))
        self.assertEqual(bridge.validate_live_issue(e, dict(e["issue"])), (321, "snapshot"))

    def test_authority_must_match_exact_owner_repo_and_opened_event(self):
        bad = [
            event(author="other"),
            event(repo="other/AI-Foundation"),
            {**event(), "action": "edited"},
            {**event(), "issue": {**event()["issue"], "state": "closed"}},
            {**event(), "issue": {**event()["issue"], "number": True}},
        ]
        for e in bad:
            with self.subTest(e=e), self.assertRaises(bridge.BridgeDenied):
                bridge.validate_event(e)

    def test_request_has_no_shell_paths_or_unknown_operations(self):
        invalid = [
            ("Foundation M1 Bridge: shell", '<!-- foundation-m1-bridge: {"version":1,"operation":"shell"} -->'),
            ("Foundation M1 Bridge: snapshot", '<!-- foundation-m1-bridge: {"version":1,"operation":"snapshot","command":"rm -rf /"} -->'),
            ("Foundation M1 Bridge: snapshot", '<!-- foundation-m1-bridge: {"version":1,"operation":"snapshot","version":1} -->'),
            ("Foundation M1 Bridge: snapshot", '<!-- foundation-m1-bridge: {"version":true,"operation":"snapshot"} -->'),
            ("Foundation M1 Bridge: snapshot", '<!-- foundation-m1-bridge: {"version":1,"operation":"snapshot"} --> anything'),
            ("Foundation M1 Bridge: snapshot", '<!-- foundation-m1-bridge: {"version":1,"operation":"snapshot"} -->\n<!-- foundation-m1-bridge: {"version":1,"operation":"selftest"} -->'),
            ("Foundation M1 Bridge: selftest", '<!-- foundation-m1-bridge: {"version":1,"operation":"snapshot"} -->'),
        ]
        for title, body in invalid:
            with self.subTest(body=body), self.assertRaises(bridge.BridgeDenied):
                bridge.parse_request(title, body)

    def test_event_and_live_edited_or_closed_issue_are_denied(self):
        e = event()
        for update in [
            {"body": "changed"},
            {"title": "other"},
            {"state": "closed"},
            {"user": {"login": "other"}},
            {"number": 322},
        ]:
            with self.subTest(update=update), self.assertRaises(bridge.BridgeDenied):
                bridge.validate_live_issue(e, {**e["issue"], **update})

    def test_comment_replay_and_incomplete_page_fail_closed(self):
        self.assertTrue(bridge.receipt_already_exists(
            [{"body": bridge._receipt_marker(321), "user": {"login": "github-actions[bot]"}}], 321))
        self.assertFalse(bridge.receipt_already_exists([{"body": "other"}], 321))
        self.assertFalse(bridge.receipt_already_exists(
            [{"body": bridge._receipt_marker(321), "user": {"login": "attacker"}}], 321))
        with self.assertRaises(bridge.BridgeDenied):
            bridge.receipt_already_exists([{"body": "x"}] * 100, 321)
        with self.assertRaises(bridge.BridgeDenied):
            bridge.receipt_already_exists([{"bad": "schema"}], 321)

    def test_receipt_excludes_untrusted_source_and_shell(self):
        body, status = bridge.result_body(
            321, "snapshot", {"loopback_ports_reachable": {"ollama": False}}, "1234")
        self.assertEqual(status, "OBSERVED")
        self.assertIn("foundation-m1-bridge-receipt:v1:321", body)
        self.assertNotIn("Authorization", body)
        self.assertNotIn("secret", body)
        with self.assertRaises(bridge.BridgeDenied):
            bridge.result_body(321, "snapshot", {}, "https://evil")

    def test_execution_checks_live_before_observation_and_posts_once(self):
        e = event()
        calls = []
        def api(method, path, token, payload=None):
            calls.append((method, path))
            if method == "GET" and "comments?" not in path:
                return dict(e["issue"])
            if method == "GET":
                return []
            self.assertEqual(method, "POST")
            self.assertIn("receipt", payload["body"])
            return {"id": 1}

        with mock.patch.object(bridge, "_github_api", side_effect=api), \
             mock.patch.object(bridge, "snapshot", return_value={"ok": True}):
            self.assertEqual(bridge.execute(e, "token", "999"), "OBSERVED")
        self.assertEqual([c[0] for c in calls], ["GET", "GET", "POST"])

    def test_replay_does_not_execute(self):
        e = event()
        with mock.patch.object(bridge, "_github_api", side_effect=[
            dict(e["issue"]), [{"body": bridge._receipt_marker(321), "user": {"login": "github-actions[bot]"}}]
        ]), mock.patch.object(bridge, "snapshot") as observe:
            self.assertEqual(bridge.execute(e, "token", "999"), "ALREADY_RECORDED")
            observe.assert_not_called()

    def test_selftest_only_fixed_command_and_no_stdout_exposure(self):
        with mock.patch.object(bridge, "require_m1"), \
             mock.patch.object(bridge.subprocess, "run") as run:
            run.return_value.returncode = 0
            result = bridge.bridge_selftest()
            self.assertTrue(result["passed"])
            argv = run.call_args.args[0]
            self.assertEqual(argv[-3:], ["-p", "test_m1_operator_status_probe.py", "-q"])
            self.assertEqual([call.args[0][-2] for call in run.call_args_list],
                             ["test_m1_development_bridge.py", "test_m1_runtime_status_probe.py",
                              "test_m1_operator_status_probe.py"])
            self.assertNotIn("stdout", result)

    def test_failure_is_published_as_failure_not_success(self):
        e = event("selftest")
        with mock.patch.object(bridge, "_github_api", side_effect=[
            dict(e["issue"]), [], {"id": 3}
        ]), mock.patch.object(bridge, "bridge_selftest", return_value={"passed": False}):
            self.assertEqual(bridge.execute(e, "token", "5"), "FAIL")

    def test_snapshot_never_opens_non_loopback_connection(self):
        with mock.patch.object(bridge, "require_m1"), \
             mock.patch.object(bridge.socket, "create_connection") as conn, \
             mock.patch.object(bridge.shutil, "disk_usage") as usage:
            conn.return_value.__enter__.return_value = None
            usage.return_value.free = 42 * 1024 ** 3
            result = bridge.snapshot()
            self.assertEqual(result["checkout_free_gib"], 42.0)
            for call in conn.call_args_list:
                self.assertEqual(call.args[0][0], "127.0.0.1")



class FixedTriageContractTests(unittest.TestCase):
    def test_owner_and_exact_payload(self):
        self.assertEqual(bridge.validate_event(event("triage")), (321, "triage"))
        with self.assertRaises(bridge.BridgeDenied):
            bridge.validate_event(event("triage", author="attacker"))
        with self.assertRaises(bridge.BridgeDenied):
            bridge.parse_request(
                "Foundation M1 Bridge: triage",
                '<!-- foundation-m1-bridge: {"version":1,"operation":"triage","cmd":"sh"} -->',
            )

    def test_loopback_http_only_aggregates_no_model_names(self):
        with mock.patch.object(bridge.http.client, "HTTPConnection") as http:
            conn = http.return_value
            response = conn.getresponse.return_value
            response.status = 200
            response.read.return_value = b'{"models":[{"name":"private-model","size_vram":2147483648}]}'
            outcome = bridge._read_only_http_probe(11434, "/api/ps", models=True)
            http.assert_called_once_with("127.0.0.1", 11434, timeout=1.0)
            conn.request.assert_called_once_with(
                "GET", "/api/ps",
                headers={"Host": "127.0.0.1", "Accept": "application/json"},
            )
            self.assertEqual(outcome["loaded_model_count"], 1)
            self.assertEqual(outcome["loaded_vram_gib"], 2.0)
            self.assertNotIn("private-model", str(outcome))
            conn.close.assert_called_once()

    def test_http_unavailable_never_echoes_exception(self):
        with mock.patch.object(bridge.http.client, "HTTPConnection") as http:
            http.return_value.request.side_effect = OSError("private /secret")
            self.assertEqual(bridge._read_only_http_probe(8766, "/health"),
                             {"status": "unreachable"})

    def test_fixed_triage_argv_and_redaction(self):
        commands = {
            ("/usr/sbin/sysctl", "-n", "hw.memsize"): "17179869184\n",
            ("/usr/bin/vm_stat",): (
                "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                "Pages free: 1000.\nPages inactive: 2000.\nPages speculative: 1000.\n"
            ),
            ("/usr/sbin/sysctl", "-n", "vm.swapusage"):
                "total = 1024.00M used = 512.00M free = 512.00M\n",
            ("/bin/ps", "-axo", "comm="):
                "/usr/local/bin/ollama\n/Users/private/bin/llama-swap\n/opt/curl TOKEN\n",
            ("/bin/ps", "-axo", "pcpu=,rss=,comm="):
                "234.2 2097152 /private/Users/sensitive/Python\n"
                "88.1 1048576 /Applications/Google Chrome Helper\n"
                "22.2 131072 /secret/custom-process\n",
            ("/bin/launchctl", "list"):
                "PID Status Label\n123 0 dev.quest7070.ai-foundation.operator\n"
                "- 1 dev.quest7070.ai-foundation.remote\n123 0 org.user.secret\n",
        }
        seen = []
        def fixed(argv):
            seen.append(tuple(argv))
            return commands.get(tuple(argv))
        with mock.patch.object(bridge, "require_m1"), \
             mock.patch.object(bridge, "_fixed_command", side_effect=fixed), \
             mock.patch.object(bridge, "_read_only_http_probe", return_value={"http_status": 200}), \
             mock.patch.object(bridge.os, "getloadavg", return_value=(3.5, 2.5, 1.5)):
            report = bridge.triage()
        self.assertEqual(set(seen), set(commands))
        self.assertEqual(report["memory"]["physical_gib"], 16.0)
        self.assertEqual(report["memory"]["swap_used_gib"], 0.5)
        self.assertEqual(report["process_counts"]["ollama"], 1)
        self.assertEqual(report["process_counts"]["llama_swap"], 1)
        self.assertEqual(len(report["launch_agents"]), 2)
        self.assertTrue(report["launch_agents"][0]["running_in_runner_context"])
        self.assertNotIn("TOKEN", str(report))
        self.assertNotIn("/Users/private", str(report))
        self.assertEqual(report["resource_groups"]["state"], "OBSERVED")
        self.assertEqual(report["resource_groups"]["groups"]["python"]["cpu_percent_sum"], 234.2)
        self.assertEqual(report["resource_groups"]["groups"]["browser"]["count"], 1)
        self.assertNotIn("custom-process", str(report))
        self.assertNotIn("/private/Users", str(report))

    def test_process_sample_never_exposes_raw_command_or_path(self):
        report = bridge._fixed_resource_groups(
            "345.2 1048576 /private/owner/project/my-secret-tool\n"
            "nan 10 /private/malformed\n"
            "-9 22 /private/malformed\\n")
        self.assertEqual(report["groups"]["other"]["count"], 1)
        self.assertNotIn("secret", str(report))
        self.assertNotIn("owner", str(report))
        self.assertEqual(bridge._fixed_resource_groups(None)["state"], "UNAVAILABLE")

    def test_unavailable_observation_is_not_success(self):
        with mock.patch.object(bridge, "require_m1"), \
             mock.patch.object(bridge, "_fixed_command", return_value=None), \
             mock.patch.object(bridge, "_read_only_http_probe", return_value={"status": "unreachable"}), \
             mock.patch.object(bridge.os, "getloadavg", return_value=(0, 0, 0)):
            report = bridge.triage()
        self.assertEqual(report["memory"], {})
        self.assertEqual(report["process_counts"], {})
        self.assertEqual(report["launch_agents"], [])
        self.assertEqual(report["http_checks"]["ollama_loaded"], {"status": "unreachable"})

    def test_dispatch_is_fixed(self):
        e = event("triage")
        with mock.patch.object(bridge, "_github_api", side_effect=[
            dict(e["issue"]), [], {"id": 3}
        ]), mock.patch.object(bridge, "triage", return_value={"ok": True}) as run:
            self.assertEqual(bridge.execute(e, "token", "12"), "OBSERVED")
            run.assert_called_once_with()


class ExistingCIVerificationTests(unittest.TestCase):
    sha = "a" * 40

    def test_exact_request_and_checkout_preflight(self):
        e = event("verify-main")
        with mock.patch.object(bridge, "_github_api", side_effect=[e["issue"], []]), \
             mock.patch.object(bridge, "_fixed_command", return_value=self.sha + "\n"):
            bridge.verification_preflight(e, "token", self.sha, workflow="Foundation CI", job="unit")

    def test_context_and_edited_request_denied_before_tests(self):
        e = event("verify-main")
        for workflow, job, sha in (("other", "unit", self.sha),
                ("Foundation CI", "bridge", self.sha), ("Foundation CI", "unit", "main")):
            with mock.patch.object(bridge, "_github_api") as api, self.assertRaises(bridge.BridgeDenied):
                bridge.verification_preflight(e, "token", sha, workflow=workflow, job=job)
            api.assert_not_called()
        with mock.patch.object(bridge, "_github_api", return_value={**e["issue"], "body": "edited"}), \
             mock.patch.object(bridge, "_fixed_command") as command, self.assertRaises(bridge.BridgeDenied):
            bridge.verification_preflight(e, "token", self.sha, workflow="Foundation CI", job="unit")
        command.assert_not_called()

    def test_checkout_mismatch_and_prior_receipt_cannot_repeat_tests(self):
        e = event("verify-main")
        with mock.patch.object(bridge, "_github_api", return_value=e["issue"]), \
             mock.patch.object(bridge, "_fixed_command", return_value="b" * 40), \
             self.assertRaisesRegex(bridge.BridgeDenied, "CHECKOUT_MISMATCH"):
            bridge.verification_preflight(e, "token", self.sha, workflow="Foundation CI", job="unit")
        comments = [{"user": {"login": "github-actions[bot]"}, "body": bridge._receipt_marker(321)}]
        with mock.patch.object(bridge, "_github_api", side_effect=[e["issue"], comments]), \
             mock.patch.object(bridge, "_fixed_command", return_value=self.sha), \
             self.assertRaisesRegex(bridge.BridgeDenied, "ALREADY_RECORDED"):
            bridge.verification_preflight(e, "token", self.sha, workflow="Foundation CI", job="unit")

    def test_only_actual_success_becomes_pass_and_receipt_is_bounded(self):
        e = event("verify-main")
        for outcome in ("success", "failure", "cancelled", "skipped"):
            with self.subTest(outcome=outcome), \
                 mock.patch.object(bridge, "_github_api", side_effect=[e["issue"], [], {}]) as api, \
                 mock.patch.object(bridge, "_fixed_command", return_value=self.sha):
                status = bridge.verification_receipt(e, "token", "999", self.sha, outcome,
                    workflow="Foundation CI", job="bridge-verification-receipt")
                self.assertEqual(status, "PASS" if outcome == "success" else "FAIL")
                body = api.call_args.args[3]["body"]
                self.assertIn(self.sha, body)
                self.assertNotIn("token", body)
                self.assertNotIn("stdout", body)
                self.assertIn("test/cache writes only", body)

    def test_receipt_replay_is_readonly_and_unknown_outcome_is_denied(self):
        e = event("verify-main")
        comments = [{"user": {"login": "github-actions[bot]"}, "body": bridge._receipt_marker(321)}]
        with mock.patch.object(bridge, "_github_api", side_effect=[e["issue"], comments]) as api, \
             mock.patch.object(bridge, "_fixed_command", return_value=self.sha):
            self.assertEqual(bridge.verification_receipt(e, "token", "999", self.sha, "success",
                workflow="Foundation CI", job="bridge-verification-receipt"), "ALREADY_RECORDED")
            self.assertEqual(api.call_count, 2)
        with mock.patch.object(bridge, "_github_api") as api, self.assertRaises(bridge.BridgeDenied):
            bridge.verification_receipt(e, "token", "999", self.sha, "SECRET_OUTCOME",
                workflow="Foundation CI", job="bridge-verification-receipt")
        api.assert_not_called()

    def test_verification_never_falls_through_to_host_triage(self):
        e = event("verify-main")
        with mock.patch.object(bridge, "_github_api", side_effect=[e["issue"], []]), \
             mock.patch.object(bridge, "triage") as triage, self.assertRaises(bridge.BridgeDenied):
            bridge.execute(e, "token", "1")
        triage.assert_not_called()


if __name__ == "__main__":
    unittest.main()


def test_m1_bridge_uses_existing_release_python_runtime():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/m1-development-bridge.yml").read_text()
    release = (root / ".github/workflows/m1-owner-local9b-main-release.yml").read_text()
    command = "/opt/homebrew/bin/python3.12 -B "
    assert command + "scripts/m1_development_bridge.py" in workflow
    assert "PYTHONPATH: src:." in workflow
    assert command + "scripts/m1_github_owner_local9b_release.py" in release
    assert "/usr/bin/python3 -B scripts/m1_development_bridge.py" not in workflow


def test_issue_bridge_isolated_checkout_has_exact_head_and_owned_cleanup():
    # A shared self-hosted runner previously lost this script between checkout
    # and the fixed read-only operation. Never execute from the shared root.
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/m1-development-bridge.yml").read_text()
    assert "path: .m1-bridge/${{ github.run_id }}-${{ github.run_attempt }}" in workflow
    assert "working-directory: .m1-bridge/${{ github.run_id }}-${{ github.run_attempt }}" in workflow
    assert 'if [[ "$PWD" != "$M1_BRIDGE_ROOT"' in workflow
    assert '"$(git rev-parse HEAD)" != "$GITHUB_SHA"' in workflow
    assert "BRIDGE_EVENT_SOURCE_DRIFT" in workflow
    assert "BRIDGE_CLEANUP_SCOPE_UNVERIFIED" in workflow
    assert 'expected="$GITHUB_WORKSPACE/.m1-bridge/${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}"' in workflow
    assert 'rm -rf -- "$expected"' in workflow
    assert "if: always()" in workflow
    # No caller-provided branch ref, script, command, token or host path.
    assert "ref: ${{ github.sha }}" in workflow
    assert "persist-credentials: false" in workflow
