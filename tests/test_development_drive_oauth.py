"""Test separate app-file-only OAuth without a real Google account or browser."""
import json
import socket
import threading
import unittest
from urllib import parse, request
from unittest.mock import patch

from ai_foundation.development_drive_oauth import (
    BINDING, DRIVE_FILE_SCOPE, DriveFileToken, save_grant, authorize,
)


class Store:
    def __init__(self):
        self.entries = {"klm-drive-readonly-v1": "unmodified-old-grant"}

    def save(self, name, value):
        self.entries[name] = value

    def load(self, name):
        return self.entries[name]

    def available(self, name):
        return name in self.entries


class TestDriveFileOAuth(unittest.TestCase):
    def setUp(self):
        self.store = Store()
        self.client = {"client_id": "app.apps.googleusercontent.com",
                       "client_secret": "local-secret"}

    def grant(self):
        return save_grant(self.store, self.client, {
            "scope": DRIVE_FILE_SCOPE, "refresh_token": "new-grant"})

    def test_missing_consent_never_refreshes(self):
        calls = []
        port = DriveFileToken(self.store, exchange=lambda *_: calls.append("refresh"))
        self.assertFalse(port.available())
        with self.assertRaisesRegex(RuntimeError, "CONSENT_REQUIRED"):
            port()
        self.assertEqual(calls, [])
        self.assertEqual(self.store.load("klm-drive-readonly-v1"), "unmodified-old-grant")

    def test_separate_binding_and_exact_scope(self):
        self.assertEqual(self.grant()["status"], "DRIVE_FILE_CONSENT_BOUND")
        self.assertEqual(self.store.load("klm-drive-readonly-v1"), "unmodified-old-grant")
        self.assertEqual(set(json.loads(self.store.load(BINDING))["scopes"]),
                         {DRIVE_FILE_SCOPE})

    def test_refresh_returns_one_scoped_token_and_caches(self):
        self.grant()
        clock = [20.0]
        calls = []
        def exchange(payload):
            calls.append(payload)
            return {"access_token": "token", "expires_in": 3600,
                    "scope": DRIVE_FILE_SCOPE}
        token = DriveFileToken(self.store, exchange=exchange, clock=lambda: clock[0])
        self.assertEqual(token(), ("token", (DRIVE_FILE_SCOPE,)))
        self.assertEqual(token(), ("token", (DRIVE_FILE_SCOPE,)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["grant_type"], "refresh_token")
        self.assertEqual(calls[0]["refresh_token"], "new-grant")

    def test_old_readonly_grant_cannot_be_used(self):
        self.store.save(BINDING, self.store.load("klm-drive-readonly-v1"))
        token = DriveFileToken(self.store, exchange=lambda *_: self.fail("refresh"))
        with self.assertRaises((ValueError, TypeError, PermissionError)):
            token()

    def test_extra_scope_rejected_in_consent(self):
        with self.assertRaisesRegex(PermissionError, "EXACT_DRIVE_FILE_SCOPE"):
            save_grant(self.store, self.client, {
                "scope": DRIVE_FILE_SCOPE + " https://www.googleapis.com/auth/drive",
                "refresh_token": "x"})
        self.assertNotIn(BINDING, self.store.entries)

    def test_empty_offline_refresh_rejected(self):
        with self.assertRaisesRegex(ValueError, "OFFLINE_DRIVE_FILE"):
            save_grant(self.store, self.client, {"scope": DRIVE_FILE_SCOPE})

    def test_extra_scope_rejected_on_refresh(self):
        self.grant()
        token = DriveFileToken(self.store, exchange=lambda *_: {
            "access_token": "unsafe", "expires_in": 3600,
            "scope": DRIVE_FILE_SCOPE + " https://www.googleapis.com/auth/drive"})
        with self.assertRaisesRegex(PermissionError, "REFRESH_SCOPE"):
            token()

    def test_bad_token_or_lifetime_rejected(self):
        self.grant()
        for value in ({"access_token": "", "expires_in": 3600},
                      {"access_token": "ok", "expires_in": -1},
                      {"access_token": "ok", "expires_in": True}):
            with self.subTest(value=value):
                token = DriveFileToken(self.store, exchange=lambda _f: value)
                with self.assertRaises(ValueError):
                    token()

    def test_bad_stored_scope_never_refreshed(self):
        self.grant()
        record = json.loads(self.store.load(BINDING))
        record["scopes"] = ["https://www.googleapis.com/auth/drive.readonly"]
        self.store.save(BINDING, json.dumps(record))
        port = DriveFileToken(self.store, exchange=lambda *_: self.fail("refresh"))
        with self.assertRaisesRegex(PermissionError, "EXACT_DRIVE_FILE_SCOPE"):
            port()

    def test_consent_requires_explicit_client_and_browser(self):
        with self.assertRaises(ValueError):
            authorize("nonexistent-secret.json", self.store,
                      open_browser=lambda *_: self.fail("browser must not open"))

    def test_consent_rejects_unbounded_timeout(self):
        with self.assertRaisesRegex(ValueError, "INVALID_CONSENT_TIMEOUT"):
            authorize("irrelevant", self.store, open_browser=lambda *_: True, timeout=9999)

    def test_invalid_headless_redirect_ports_fail_before_client_or_browser(self):
        for port in (-1, 80, 65536, True, "8765"):
            with self.subTest(port=port):
                with self.assertRaisesRegex(ValueError, "INVALID_LOOPBACK"):
                    authorize("private", self.store, open_browser=lambda _:
                              self.fail("must not open"), redirect_port=port)

    def test_headless_phone_redirect_completes_on_fixed_localhost_port(self):
        # Simulates Android SSH -L local forwarding. No Google/network/GUI.
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        client = dict(self.client)
        client["token_uri"] = "https://oauth2.googleapis.com/token"
        client["auth_uri"] = "https://accounts.google.com/o/oauth2/auth"
        done = []
        seen = []
        def phone_browser(link):
            url = parse.urlsplit(link)
            self.assertEqual(url.hostname, "accounts.google.com")
            params = parse.parse_qs(url.query)
            self.assertEqual(params["scope"], [DRIVE_FILE_SCOPE])
            self.assertEqual(params["code_challenge_method"], ["S256"])
            redirect = params["redirect_uri"][0]
            self.assertEqual(redirect, f"http://127.0.0.1:{port}/oauth2callback")
            def phone_callback():
                req = redirect + "?" + parse.urlencode({
                    "state": params["state"][0], "code": "phone-granted"})
                with request.urlopen(req, timeout=3) as r:
                    done.append(r.status)
            worker = threading.Thread(target=phone_callback, daemon=True)
            worker.start()
            seen.append(worker)
            return True
        def exchange(payload):
            self.assertEqual(payload["code"], "phone-granted")
            self.assertEqual(payload["redirect_uri"],
                             f"http://127.0.0.1:{port}/oauth2callback")
            self.assertIn("code_verifier", payload)
            return {"scope": DRIVE_FILE_SCOPE, "refresh_token": "from-phone"}
        with patch("ai_foundation.development_drive_oauth.load_desktop_client",
                   return_value=client):
            result = authorize("private", self.store, open_browser=phone_browser,
                               exchange=exchange, redirect_port=port, timeout=30)
        for worker in seen:
            worker.join(timeout=3)
        self.assertEqual(done, [200])
        self.assertEqual(result["status"], "DRIVE_FILE_CONSENT_BOUND")
        self.assertEqual(self.store.load("klm-drive-readonly-v1"),
                         "unmodified-old-grant")

    def test_headless_cannot_accept_browser_refusal(self):
        with patch("ai_foundation.development_drive_oauth.load_desktop_client",
                   return_value=self.client):
            with self.assertRaisesRegex(RuntimeError, "SYSTEM_BROWSER_UNAVAILABLE"):
                authorize("private", self.store, open_browser=lambda _url: False,
                          timeout=30)
        self.assertFalse(self.store.available(BINDING))


if __name__ == "__main__":
    unittest.main()
