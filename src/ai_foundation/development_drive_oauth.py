"""Separate, explicitly consented Google Drive *app-file-only* credential.

The existing KLM read-only grant is never read, replaced, or upgraded. The
caller supplies the existing Foundation native secret store and browser opener.
No account registration, payment setup or browser-profile credential access.
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib import parse

from .development_drive_plan import DRIVE_FILE_SCOPE
from .klm_drive_auth import load_desktop_client, token_request

BINDING = "development-drive-appfile-v1"
SCOPE_SET = frozenset({DRIVE_FILE_SCOPE})


class DriveFileToken:
    def __init__(self, store, *, exchange=token_request, clock=time.time):
        self.store, self.exchange, self.clock = store, exchange, clock
        self._cache = None
        self._expires = 0

    def available(self):
        return self.store.available(BINDING)

    def __call__(self):
        if self._cache and self.clock() < self._expires - 30:
            return self._cache, tuple(sorted(SCOPE_SET))
        if not self.available():
            raise RuntimeError("DRIVE_APPFILE_OWNER_CONSENT_REQUIRED")
        raw = json.loads(self.store.load(BINDING))
        if (type(raw) is not dict or
                type(raw.get("scopes")) is not list or
                set(raw["scopes"]) != SCOPE_SET or
                len(raw["scopes"]) != 1):
            raise PermissionError("EXACT_DRIVE_FILE_SCOPE_REQUIRED")
        fields = {key: raw[key] for key in ("client_id", "client_secret", "refresh_token")}
        answer = self.exchange({**fields, "grant_type": "refresh_token"})
        if (type(answer) is not dict or
                ("scope" in answer and set(str(answer["scope"]).split()) != SCOPE_SET)):
            raise PermissionError("DRIVE_FILE_REFRESH_SCOPE_MISMATCH")
        token, lifetime = answer.get("access_token"), answer.get("expires_in")
        if (type(token) is not str or not token or
                type(lifetime) is not int or not 60 <= lifetime <= 86400):
            raise ValueError("INVALID_DRIVE_FILE_TOKEN_RESPONSE")
        self._cache, self._expires = token, self.clock() + lifetime
        return token, tuple(sorted(SCOPE_SET))


def save_grant(store, client, result):
    if (type(result) is not dict or
            set(str(result.get("scope", "")).split()) != SCOPE_SET):
        raise PermissionError("EXACT_DRIVE_FILE_SCOPE_REQUIRED")
    refresh = result.get("refresh_token")
    if type(refresh) is not str or not refresh:
        raise ValueError("OFFLINE_DRIVE_FILE_GRANT_REQUIRED")
    config = {key: client[key] for key in ("client_id", "client_secret")}
    config.update(refresh_token=refresh, scopes=sorted(SCOPE_SET))
    encoded = json.dumps(config, sort_keys=True)
    # One separate native-keychain record, no key reuse.
    store.save(BINDING, encoded)
    if store.load(BINDING) != encoded:
        raise RuntimeError("DRIVE_FILE_GRANT_READBACK_FAILED")
    return {"status": "DRIVE_FILE_CONSENT_BOUND", "scopes": 1}


def authorize(client_path, store, *, open_browser, exchange=token_request,
              clock=time.monotonic, timeout=300, redirect_port=0):
    """User-initiated local browser consent; no unattended OAuth prompts.

    Called only from an explicit owner/UI action. M1 worker must check
    DriveFileToken.available(), not call authorize() itself.
    """
    if type(timeout) is not int or not 30 <= timeout <= 600:
        raise ValueError("INVALID_CONSENT_TIMEOUT")
    # Mac GUI-free authentication uses the same desktop OAuth client with an
    # exact loopback port forwarded through the owner's encrypted SSH tunnel.
    # We never bind a public interface or auto-open a browser in this mode.
    if (type(redirect_port) is not int or
            not (redirect_port == 0 or 1024 <= redirect_port <= 65535)):
        raise ValueError("INVALID_LOOPBACK_REDIRECT_PORT")
    client = load_desktop_client(client_path)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    captured = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            target = parse.urlsplit(self.path)
            args = parse.parse_qs(target.query)
            valid = (target.path == "/oauth2callback" and
                     args.get("state") == [state] and
                     len(args.get("code", [])) == 1)
            self.send_response(200 if valid else 400)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Authorization received." if valid else b"Invalid OAuth callback.")
            if valid:
                captured["code"] = args["code"][0]
            elif args.get("state") == [state] and "error" in args:
                captured["denied"] = True

    with HTTPServer(("127.0.0.1", redirect_port), Callback) as server:
        redirect = "http://127.0.0.1:" + str(server.server_port) + "/oauth2callback"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + parse.urlencode({
            "client_id": client["client_id"],
            "redirect_uri": redirect, "response_type": "code",
            "scope": DRIVE_FILE_SCOPE, "access_type": "offline",
            "prompt": "consent", "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256"})
        if open_browser(url) is False:
            raise RuntimeError("SYSTEM_BROWSER_UNAVAILABLE")
        deadline = clock() + timeout
        server.timeout = 1
        while not captured and clock() < deadline:
            server.handle_request()
        if "code" not in captured:
            raise RuntimeError("DRIVE_FILE_CONSENT_DENIED_OR_TIMED_OUT")
    result = exchange({
        "client_id": client["client_id"], "client_secret": client["client_secret"],
        "grant_type": "authorization_code", "code": captured["code"],
        "code_verifier": verifier, "redirect_uri": redirect})
    return save_grant(store, client, result)
