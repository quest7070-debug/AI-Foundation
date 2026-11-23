"""Offline transport and enrollment regression; no secrets or live inference."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.error import HTTPError

from ai_foundation import openai_local_adapter as adapter
from ai_foundation.local_compute_registry import LocalComputeCandidate
from scripts import mainpc_strata_preflight as probe
from scripts import m1_strata_local_first_setup as setup


class ActivationDiagnosticsTests(unittest.TestCase):
    def test_ssh_pipe_key_is_bounded_and_never_echoed(self):
        from contextlib import redirect_stdout, redirect_stderr
        output = io.StringIO()
        for value, expected in (("SYNTHETIC_PRIVATE_KEY\r\n", "SYNTHETIC_PRIVATE_KEY"), ("", ""), ("x" * 10000, "x" * 258)):
            with mock.patch.object(sys, "stdin", io.StringIO(value)), redirect_stdout(output), redirect_stderr(output):
                self.assertEqual(setup.read_owner_key_stdin("ignored"), expected)
        self.assertEqual(output.getvalue(), "")

    def test_default_discovery_and_execution_ignore_ambient_proxy(self):
        with mock.patch.object(adapter.request, "build_opener") as build, mock.patch.object(adapter.request, "ProxyHandler", wraps=adapter.request.ProxyHandler) as proxy, mock.patch.dict(os.environ, {"http_proxy": "http://untrusted.invalid"}):
            discovery = adapter.OpenAILocalDiscovery("http://10.0.1.1:18080", binding_prefix="local:test", allowed_hosts=("10.0.1.1",), models=())
            execution = adapter.OpenAILocalExecution("http://10.0.1.1:18080", allowed_hosts=("10.0.1.1",), alias_to_model={})
        self.assertEqual(proxy.call_args_list, [mock.call({}), mock.call({})])
        self.assertIs(discovery.open, build.return_value.open)
        self.assertIs(execution.open, build.return_value.open)

    def test_auth_failure_is_bounded_without_exception_or_key_text(self):
        fail = mock.Mock(side_effect=HTTPError("http://private", 401, "SECRET", {}, None))
        discovery = adapter.OpenAILocalDiscovery("http://10.0.1.1:18080", binding_prefix="local:mainpc-strata", allowed_hosts=("10.0.1.1",), models=(), opener=fail)
        execution = SimpleNamespace(models={"code-agent": "fixed"}, chat=mock.Mock())
        details = {}
        with mock.patch.object(probe, "load_local_endpoints", return_value=(("local:mainpc-strata", SimpleNamespace(candidates=discovery), execution),)):
            self.assertEqual(probe.verify_strata("unused", smoke=True, diagnostics=details), {"status": "MAINPC_UNAVAILABLE"})
        self.assertEqual(details, {"reason_code": "DISCOVERY_HTTP_401"})
        execution.chat.assert_not_called()
        self.assertNotIn("SECRET", json.dumps(details))

    def test_unavailable_authorization_does_not_trigger_physical_wake(self):
        discovery = SimpleNamespace(candidates=lambda: (
            LocalComputeCandidate("local:mainpc-strata",
                                  health="UNAVAILABLE", reason="HTTP_401"),
        ))
        execution = SimpleNamespace(models={"code-agent": "code-fixture"})
        details = {}
        with mock.patch.object(probe, "load_local_endpoints", return_value=(
                ("local:mainpc-strata", discovery, execution),)):
            runner = mock.Mock(side_effect=AssertionError("must never wake on 401"))
            outcome = probe.verify_strata("unused", wake=True,
                                           runner=runner, diagnostics=details)
        self.assertEqual(outcome, {"status": "MAINPC_UNAVAILABLE"})
        self.assertEqual(details["reason_code"], "DISCOVERY_HTTP_401")
        runner.assert_not_called()

    def test_inference_failure_empty_reply_and_success_are_distinct(self):
        discovery = SimpleNamespace(candidates=lambda: (LocalComputeCandidate("local:mainpc-strata:code-agent", health="ONLINE", same_host=False),))
        cases = [(HTTPError("private", 403, "SECRET", {}, None), "INFERENCE_HTTP_403", "INFERENCE_UNAVAILABLE"), (None, "INFERENCE_EMPTY_CONTENT", "INFERENCE_NOT_VERIFIED"), ("WRONG_SECRET", "INFERENCE_REPLY_MISMATCH", "INFERENCE_NOT_VERIFIED"), ("STRATA_ROUTE_OK", None, "INFERENCE_VERIFIED")]
        for value, code, status in cases:
            with self.subTest(code=code):
                chat = mock.Mock(side_effect=value) if isinstance(value, Exception) else mock.Mock(return_value=value)
                execution = SimpleNamespace(models={"code-agent": "fixed"}, chat=chat)
                details = {}
                with mock.patch.object(probe, "load_local_endpoints", return_value=(("local:mainpc-strata", discovery, execution),)):
                    self.assertEqual(probe.verify_strata("unused", smoke=True, diagnostics=details), {"status": status})
                self.assertEqual(details, {} if code is None else {"reason_code": code})
                self.assertNotIn("SECRET", json.dumps(details))

    def test_failed_enrollment_restores_environment_and_never_saves_key(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            setup.configure_strata(root, port=18080, apply=True)
            response = mock.MagicMock()
            response.__enter__.return_value.status = 200
            response.__enter__.return_value.read.return_value = b'{"api_key":true}'
            preflight = SimpleNamespace(verify_strata=mock.Mock(return_value={"status": "INFERENCE_UNAVAILABLE"}))
            credentials = SimpleNamespace(MacOSNativeCredentialStore=mock.Mock())
            with mock.patch("urllib.request.build_opener") as opener, mock.patch.dict(sys.modules, {"mainpc_strata_preflight": preflight, "ai_foundation.native_credentials": credentials}), mock.patch.dict(os.environ, {"STRATA_API_KEY": "original"}):
                opener.return_value.open.return_value = response
                result = setup.register_owner_key(root, secret_prompt=lambda _: "SYNTHETIC_PRIVATE_KEY", diagnostics={})
                self.assertEqual(result, "AUTHENTICATED_INFERENCE_UNVERIFIED")
                self.assertEqual(os.environ["STRATA_API_KEY"], "original")
                credentials.MacOSNativeCredentialStore.assert_not_called()


if __name__ == "__main__":
    unittest.main()
