"""Consent handoff is owner-action-only and does not touch existing KLM grant."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_foundation.development_drive_consent_setup import (
    BINDING, existing_client, finish_consent, private_runtime,
    probe_app_file_scope, write_result, RESULT,
)


class Store:
    def __init__(self):
        self.data = {"klm-drive-readonly-v1": "original-readonly-keychain"}
    def available(self, key):
        return key in self.data
    def save(self, key, text):
        self.data[key] = text
    def load(self, key):
        return self.data[key]


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store()
        self.root = Path(self.tmp.name)
        self.runtime = self.root / "Library/Application Support/AI-Foundation/klm-drive"
        self.runtime.mkdir(mode=0o700, parents=True)
        self.client = self.runtime / "oauth-client.json"
        self.client.write_text(json.dumps({"installed": {
            "client_id": "test.apps.googleusercontent.com",
            "client_secret": "local-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"}}))
        self.client.chmod(0o600)

    def test_existing_private_client_reused_without_reimport(self):
        self.assertEqual(existing_client(self.runtime), self.client)
        self.assertEqual(private_runtime(self.root), self.runtime)

    def test_readonly_grant_does_not_count_as_write_grant(self):
        seen = []
        def consent(_client, store, **_):
            seen.append("owner-consent")
            store.save(BINDING, json.dumps({"scopes":
                ["https://www.googleapis.com/auth/drive.file"]}))
        def probe(token):
            seen.append("probe")
            self.assertTrue(token.available())
        result = finish_consent(self.client, self.store, consent=consent,
                                probe=probe, open_browser=lambda *_: True)
        self.assertEqual(seen, ["owner-consent", "probe"])
        self.assertEqual(result["status"], "DRIVE_FILE_CONSENT_AND_READ_PROBE_VERIFIED")
        self.assertEqual(self.store.load("klm-drive-readonly-v1"),
                         "original-readonly-keychain")
        self.assertFalse(result["writer_enabled"])

    def test_still_valid_grant_needs_no_new_google_consent(self):
        self.store.save(BINDING, "existing-private-grant")
        called = []
        result = finish_consent(
            self.client, self.store, consent=lambda *_a, **_k: self.fail("unwanted consent"),
            probe=lambda token: called.append("metadata GET"))
        self.assertEqual(result["status"], "DRIVE_FILE_CONSENT_ALREADY_VALID")
        self.assertEqual(called, ["metadata GET"])

    def test_expired_own_grant_renews_at_most_once(self):
        self.store.save(BINDING, "old-own-grant")
        events = []
        def probe(_):
            events.append("probe")
            if events == ["probe"]:
                raise RuntimeError("OAUTH_HTTP_401")
        def consent(_, store, **_kw):
            events.append("consent")
            store.save(BINDING, "new-own-grant")
        finish_consent(self.client, self.store, consent=consent, probe=probe)
        self.assertEqual(events, ["probe", "consent", "probe"])

    def test_transient_or_unknown_error_never_replays_consent(self):
        self.store.save(BINDING, "old-own-grant")
        with self.assertRaisesRegex(RuntimeError, "NETWORK_UNAVAILABLE"):
            finish_consent(
                self.client, self.store,
                consent=lambda *_a, **_k: self.fail("must not auto re-consent"),
                probe=lambda _: (_ for _ in ()).throw(RuntimeError("NETWORK_UNAVAILABLE")))

    def test_denied_consent_does_not_replace_readonly_grant(self):
        def denied(*_a, **_kw):
            raise RuntimeError("DRIVE_FILE_CONSENT_DENIED_OR_TIMED_OUT")
        with self.assertRaises(RuntimeError):
            finish_consent(self.client, self.store, consent=denied,
                           probe=lambda *_: self.fail("no probe"))
        self.assertEqual(self.store.load("klm-drive-readonly-v1"),
                         "original-readonly-keychain")
        self.assertFalse(self.store.available(BINDING))

    def test_client_symlink_rejected(self):
        link = self.runtime / "fake-client.json"
        link.symlink_to(self.client)
        self.client.unlink()
        link.rename(self.client)
        with self.assertRaises(PermissionError):
            existing_client(self.runtime)

    def test_client_world_readable_rejected(self):
        self.client.chmod(0o644)
        with self.assertRaisesRegex(PermissionError, "PRIVATE"):
            existing_client(self.runtime)

    def test_runtime_world_readable_rejected(self):
        self.runtime.chmod(0o755)
        with self.assertRaises(PermissionError):
            private_runtime(self.root)

    def test_probe_only_metadata_get_with_app_scope(self):
        calls = []
        class FakeHTTP:
            def __init__(self, token):
                calls.append(("token", token))
            def call(self, service, method, path, *, query):
                calls.append((service, method, path, query))
                return {"files": []}
        self.assertEqual(probe_app_file_scope(
            object(), http_factory=FakeHTTP),
            "DRIVE_FILE_METADATA_GET_VERIFIED")
        self.assertEqual(calls[1][:3], ("drive", "GET", "/files"))
        self.assertEqual(calls[1][3]["fields"], "files(id)")
        self.assertFalse(any("POST" in str(c) for c in calls))

    def test_invalid_google_probe_rejects_consent_success_claim(self):
        class FakeHTTP:
            def __init__(self, _): pass
            def call(self, *_a, **_kw): return {}
        with self.assertRaisesRegex(ValueError, "DRIVE_FILE_READ_PROBE_INVALID"):
            probe_app_file_scope(object(), http_factory=FakeHTTP)

    def test_private_report_has_no_secret_fields(self):
        result = {"status": "DRIVE_FILE_CONSENT_AND_READ_PROBE_VERIFIED",
                  "scope_count": 1, "writer_enabled": False}
        write_result(self.runtime, result)
        file = self.runtime / RESULT
        self.assertEqual(file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(file.read_text())["status"], result["status"])
        self.assertNotIn("client_secret", file.read_text())
        self.assertNotIn("refresh_token", file.read_text())

    def test_status_report_rejects_extra_fields(self):
        with self.assertRaises(ValueError):
            write_result(self.runtime, {
                "status": "ok", "scope_count": 1,
                "writer_enabled": False, "refresh_token": "secret"})
        self.assertFalse((self.runtime / RESULT).exists())


if __name__ == "__main__":
    unittest.main()
