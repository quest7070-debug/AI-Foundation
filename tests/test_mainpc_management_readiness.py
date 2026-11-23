import json
import unittest
from unittest import mock

from scripts import mainpc_management_readiness as probe


class ManagementReadinessTests(unittest.TestCase):
    def observe(self, raw, *, status=200):
        connection = mock.MagicMock()
        connection.getresponse.return_value.status = status
        connection.getresponse.return_value.read.return_value = raw
        with mock.patch.object(probe.socket, "create_connection", side_effect=OSError("SECRET")), mock.patch.object(probe.http.client, "HTTPConnection", return_value=connection) as http:
            result = probe.management_readiness()
        http.assert_called_once_with("10.0.1.1", 18080, timeout=2)
        connection.request.assert_called_once_with("GET", "/health", headers={"Accept": "application/json"})
        connection.close.assert_called_once()
        return result

    def test_auth_state_and_private_body_are_separate(self):
        for enabled in (True, False):
            report = self.observe(json.dumps({"api_key": enabled, "secret": "SECRET", "model": "PRIVATE"}).encode())
            self.assertIs(report["strata_health"]["auth_enabled"], enabled)
            self.assertEqual(report["credential_attempts"], 0)
            self.assertNotIn("SECRET", json.dumps(report))
            self.assertNotIn("PRIVATE", json.dumps(report))

    def test_malformed_oversized_and_nonbool_are_unknown(self):
        for raw in (b"{", b"x" * 4097, b'{"api_key":"false"}', b"[]", b'{}'):
            self.assertEqual(self.observe(raw)["strata_health"], {"status": "UNAVAILABLE"})
        self.assertEqual(self.observe(b'{"api_key":true}', status=503)["strata_health"], {"status": "UNAVAILABLE"})

    def test_only_fixed_ports_and_no_login(self):
        with mock.patch.object(probe.socket, "create_connection", return_value=mock.MagicMock()) as tcp:
            with mock.patch.object(probe.http.client, "HTTPConnection") as http:
                http.return_value.getresponse.side_effect = OSError("SECRET")
                report = probe.management_readiness()
        self.assertEqual(tcp.call_args_list, [mock.call(("10.0.1.1", p), timeout=0.5) for p in (22, 5985, 5986)])
        self.assertEqual(set(report["management_ports"].values()), {"REACHABLE"})
        self.assertEqual(report["model_calls"], 0)
        self.assertNotIn("SECRET", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
