"""Explicit read-only Google desktop OAuth binding, using Foundation Keychain.

No browser-profile/Drive-app credentials are read. A desktop OAuth client must
be supplied by the operator; refresh secrets remain in the existing native store.
"""
import base64
import hashlib
import json
import secrets
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib import request, parse, error

BINDING = 'klm-drive-readonly-v1'
SCOPES = frozenset({'https://www.googleapis.com/auth/drive.readonly',
                    'https://www.googleapis.com/auth/spreadsheets.readonly'})
TOKEN_URL = 'https://oauth2.googleapis.com/token'


def token_request(fields):
    class NoRedirect(request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    req = request.Request(TOKEN_URL, data=parse.urlencode(fields).encode(),
                          headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with opener.open(req, timeout=10) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError('OAUTH_REPLY_TOO_LARGE')
        decoded = json.loads(raw)
        if type(decoded) is not dict:
            raise ValueError('OAUTH_REPLY_NOT_OBJECT')
        return decoded
    except error.HTTPError as exc:
        raise RuntimeError('OAUTH_HTTP_' + str(exc.code)) from None
    except (error.URLError, ValueError):
        raise RuntimeError('OAUTH_TRANSPORT_OR_REPLY_INVALID') from None


class ReadonlyGoogleToken:
    def __init__(self, store, *, exchange=token_request, clock=time.time, on_phase=None):
        self.store, self.exchange, self.clock = store, exchange, clock
        self.on_phase = on_phase
        self.cached = None
        self.expires = 0

    def available(self):
        return self.store.available(BINDING)

    def __call__(self):
        if self.cached and self.clock() < self.expires - 30:
            return self.cached
        if not self.available():
            raise RuntimeError('DRIVE_AUTH_REQUIRED')
        if self.on_phase is not None:
            self.on_phase('KEYCHAIN_LOAD')
        config = json.loads(self.store.load(BINDING))
        if set(config.get('scopes', [])) != SCOPES:
            raise PermissionError('EXACT_READONLY_SCOPES_REQUIRED')
        fields = {k: config[k] for k in ('client_id', 'client_secret', 'refresh_token')}
        if self.on_phase is not None:
            self.on_phase('OAUTH_REFRESH_HTTP')
        result = self.exchange({**fields, 'grant_type': 'refresh_token'})
        if 'scope' in result and set(result['scope'].split()) != SCOPES:
            raise PermissionError('REFRESH_SCOPE_MISMATCH')
        token, duration = result.get('access_token'), result.get('expires_in')
        if not isinstance(token, str) or not token or type(duration) is not int or not 60 <= duration <= 86400:
            raise ValueError('OAUTH_TOKEN_REPLY_INVALID')
        self.cached, self.expires = token, self.clock() + duration
        return token


def load_desktop_client(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError('EXPLICIT_DESKTOP_CLIENT_REQUIRED')
    row = json.loads(path.read_text()).get('installed', {})
    if (row.get('auth_uri') != 'https://accounts.google.com/o/oauth2/auth'
            or row.get('token_uri') != TOKEN_URL
            or not isinstance(row.get('client_id'), str)
            or not row['client_id'].endswith('.apps.googleusercontent.com')
            or not isinstance(row.get('client_secret'), str) or not row['client_secret']):
        raise ValueError('GOOGLE_DESKTOP_CLIENT_REQUIRED')
    return row


def save_grant(store, client, result):
    if set(str(result.get('scope', '')).split()) != SCOPES:
        raise PermissionError('EXACT_READONLY_SCOPES_REQUIRED')
    refresh = result.get('refresh_token')
    if not isinstance(refresh, str) or not refresh:
        raise ValueError('OFFLINE_REFRESH_GRANT_REQUIRED')
    grant = {k: client[k] for k in ('client_id', 'client_secret')}
    grant.update(refresh_token=refresh, scopes=sorted(SCOPES))
    encoded = json.dumps(grant)
    store.save(BINDING, encoded)
    if store.load(BINDING) != encoded:
        raise RuntimeError('NATIVE_GRANT_READBACK_FAILED')


def authorize(client_path, store, *, open_browser, exchange=token_request, timeout=300):
    """One local browser consent; code/state/verifier never logged or saved."""
    client = load_desktop_client(client_path)
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    captured = {}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            parsed = parse.urlsplit(self.path)
            values = parse.parse_qs(parsed.query)
            valid = (parsed.path == '/oauth2callback'
                     and values.get('state') == [state]
                     and len(values.get('code', [])) == 1)
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'Authorization received. Return to AI-Foundation.' if valid else b'Invalid OAuth callback.')
            if valid:
                captured['code'] = values['code'][0]
            elif values.get('state') == [state] and 'error' in values:
                captured['denied'] = True
    with HTTPServer(('127.0.0.1', 0), Callback) as server:
        redirect = 'http://127.0.0.1:' + str(server.server_port) + '/oauth2callback'
        url = 'https://accounts.google.com/o/oauth2/v2/auth?' + parse.urlencode({
            'client_id': client['client_id'], 'redirect_uri': redirect,
            'response_type': 'code', 'scope': ' '.join(sorted(SCOPES)),
            'access_type': 'offline', 'prompt': 'consent', 'state': state,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})
        if open_browser(url) is False:
            raise RuntimeError('SYSTEM_BROWSER_UNAVAILABLE')
        deadline = time.monotonic() + timeout
        server.timeout = 1
        while not captured and time.monotonic() < deadline:
            server.handle_request()
        if 'code' not in captured:
            raise RuntimeError('OAUTH_DENIED_OR_TIMED_OUT')
    result = exchange({'client_id': client['client_id'], 'client_secret': client['client_secret'],
                       'grant_type': 'authorization_code', 'code': captured['code'],
                       'code_verifier': verifier, 'redirect_uri': redirect})
    save_grant(store, client, result)
    return {'status': 'READONLY_GRANT_SAVED_AND_READ_BACK', 'scope_count': len(SCOPES)}
