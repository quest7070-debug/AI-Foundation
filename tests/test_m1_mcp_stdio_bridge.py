"""No-network contracts for the exact M1 external stdio MCP smoke bridge."""
import json
import os
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from scripts import m1_development_bridge as bridge


def observed():
    return {
        "status": "OBSERVED", "transport": "owner-local-stdio",
        "protocol": "2026-07-28",
        "operator_http_verified": True, "readonly_tool_verified": True,
        "write_authority_denied": True, "public_remote_mcp_verified": False,
        "service_mutations": 0, "model_calls": 0, "native_dispatches": 0,
    }


def child(row, code=0):
    return SimpleNamespace(stdout=json.dumps(row), returncode=code, stderr="")


class MCPBridgeTests(unittest.TestCase):
    def test_exact_request_is_readonly_and_no_extra_issue_fields(self):
        body = '<!-- foundation-m1-bridge: {"version":1,"operation":"mcp-stdio"} -->'
        self.assertEqual(bridge.parse_request("Foundation M1 Bridge: mcp-stdio", body), "mcp-stdio")
        with self.assertRaises(bridge.BridgeDenied):
            bridge.parse_request("Foundation M1 Bridge: mcp-stdio",
                                 body.replace('"} -->', '","command":"anything"} -->'))

    def test_fixed_child_argv_and_no_github_token_in_environment(self):
        seen = []
        def fake(argv, **kw):
            seen.append((argv, kw))
            return child(observed())
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "SYNTHETIC_ONLY",
                                          "PRIVATE_UNAPPROVED": "SYNTHETIC_ONLY"}):
            result = bridge.bounded_mcp_stdio_helper(run=fake)
        self.assertEqual(result["status"], "OBSERVED")
        self.assertTrue(result["readonly_tool_verified"])
        self.assertTrue(result["write_authority_denied"])
        argv, kwargs = seen[0]
        self.assertEqual(argv[0], sys.executable)
        self.assertEqual(argv[1], "-B")
        self.assertTrue(argv[2].endswith("/scripts/m1_p4_mcp_stdio_e2e.py"))
        self.assertEqual(kwargs["timeout"], 35)
        self.assertNotIn("GITHUB_TOKEN", kwargs["env"])
        self.assertNotIn("PRIVATE_UNAPPROVED", kwargs["env"])
        self.assertNotIn("SYNTHETIC_ONLY", json.dumps(result))
        self.assertEqual(result["model_calls"], 0)
        self.assertFalse(result["public_remote_mcp_verified"])

    def test_bad_child_frames_and_spoofed_receipts_fail_closed(self):
        bad = [
            (child({**observed(), "model_calls": True}), "MCP_PROBE_UNVERIFIED"),
            (child({**observed(), "native_dispatches": -1}), "MCP_PROBE_UNVERIFIED"),
            (child({**observed(), "public_remote_mcp_verified": True}), "MCP_PROBE_UNVERIFIED"),
            (child({**observed(), "write_authority_denied": False}), "MCP_PROBE_UNVERIFIED"),
            (child({**observed(), "secret": "NEVER_ECHO"}), "MCP_PROBE_UNVERIFIED"),
            (child({**observed(), "status": "OBSERVED"}, code=1), "MCP_PROBE_UNVERIFIED"),
            (SimpleNamespace(stdout='PRIVATE_DATA_NO_JSON', returncode=0), "MCP_PROBE_UNVERIFIED"),
            (SimpleNamespace(stdout=json.dumps(["not-object"]), returncode=0), "MCP_PROBE_UNVERIFIED"),
        ]
        for sample, reason in bad:
            with self.subTest(sample=sample):
                result = bridge.bounded_mcp_stdio_helper(run=lambda *a, **k: sample)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertEqual(result["reason"], reason)
                self.assertNotIn("NEVER_ECHO", json.dumps(result))
                self.assertNotIn("PRIVATE_DATA_NO_JSON", json.dumps(result))

    def test_only_known_failure_reasons_are_emitted(self):
        row = {**observed(), "status": "BLOCKED",
               "write_authority_denied": False, "reason": "MCP_WRITE_SCOPE_NOT_DENIED"}
        self.assertEqual(bridge.bounded_mcp_stdio_helper(
            run=lambda *a, **k: child(row, code=1))["reason"], "MCP_WRITE_SCOPE_NOT_DENIED")
        row["reason"] = "PRIVATE_CREDENTIAL_DATA"
        result = bridge.bounded_mcp_stdio_helper(run=lambda *a, **k: child(row, code=1))
        self.assertEqual(result["reason"], "MCP_PROBE_UNVERIFIED")
        self.assertNotIn("PRIVATE_CREDENTIAL_DATA", json.dumps(result))

    def test_child_timeout_preserves_existing_running_services(self):
        def timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired("fixed", 35, stderr="PRIVATE_TEXT")
        result = bridge.bounded_mcp_stdio_helper(run=timeout)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertNotIn("PRIVATE_TEXT", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
