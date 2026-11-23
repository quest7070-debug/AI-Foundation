"""Exact M1 KLM read-only OAuth/Inbox/Drive transport diagnosis.

Invoked only by the established owner Issue bridge. Refreshes an existing
read-only owner token in memory; performs only fixed Google GET requests.
No Work claim, Drive write, scheduler/model operation or source disclosure.
"""
from __future__ import annotations

import re
import json
import sys

_ALLOWED_RUNTIME = frozenset({
    "DRIVE_AUTH_REQUIRED", "OAUTH_TRANSPORT_OR_REPLY_INVALID",
    "OAUTH_HTTP_400", "OAUTH_HTTP_401", "OAUTH_HTTP_403",
    "OAUTH_HTTP_429", "OAUTH_HTTP_500", "OAUTH_HTTP_502",
    "OAUTH_HTTP_503", "OAUTH_HTTP_504",
    "DRIVE_HTTP_400", "DRIVE_HTTP_401", "DRIVE_HTTP_403",
    "DRIVE_HTTP_404", "DRIVE_HTTP_408", "DRIVE_HTTP_409",
    "DRIVE_HTTP_410", "DRIVE_HTTP_429", "DRIVE_HTTP_500",
    "DRIVE_HTTP_502", "DRIVE_HTTP_503", "DRIVE_HTTP_504",
})
_PHASES = frozenset({"OWNER_CONFIG", "TOKEN_REFRESH", "KEYCHAIN_LOAD",
                     "OAUTH_REFRESH_HTTP", "INBOX_READ", "DRIVE_CHANGES_READ", "COMPLETE"})


def inspect_transport(token, inbox, drive, *, on_phase=None):
    """Three fixed external checks; stop on first error without raw payload."""
    phase = "TOKEN_REFRESH"
    calls = 0
    if on_phase is not None:
        on_phase(phase)
    try:
        token()
        phase = "INBOX_READ"
        if on_phase is not None:
            on_phase(phase)
        values, max_rows = inbox.values()
        calls += 2  # exact Inbox grid metadata + bounded values GET
        if type(values) is not list or type(max_rows) is not int:
            raise ValueError("INVALID_INBOX_VALUES")
        phase = "DRIVE_CHANGES_READ"
        if on_phase is not None:
            on_phase(phase)
        result = drive("/drive/v3/changes/startPageToken",
                       {"fields": "startPageToken"})
        calls += 1
        if (type(result) is not dict
                or type(result.get("startPageToken")) is not str
                or not 1 <= len(result["startPageToken"]) <= 4096):
            raise ValueError("DRIVE_CURSOR_UNVERIFIED")
        return {"status": "LIVE_READONLY_APIS_VERIFIED",
                "phase": "COMPLETE", "fixed_gets": calls,
                "model_calls": 0, "drive_mutations": 0}
    except Exception as exc:
        # The transport owns only predetermined exception codes; a raw
        # Keychain, HTTP or OAuth failure message is never safe to publish.
        code = str(exc) if type(exc) is RuntimeError else None
        return {"status": "BLOCKED", "phase": phase,
                "error_type": type(exc).__name__,
                "reason": code if code in _ALLOWED_RUNTIME else "UNCLASSIFIED",
                "fixed_gets": calls, "model_calls": 0, "drive_mutations": 0}


def live_readonly_probe(*, on_phase=None):
    from pathlib import Path
    if __package__:
        from .m1_development_bridge import require_m1
        from .m1_klm_status_probe import (
            _fixed_service_paths, _json_owner, MAX_CONFIG,
        )
    else:
        from m1_development_bridge import require_m1
        from m1_klm_status_probe import (
            _fixed_service_paths, _json_owner, MAX_CONFIG,
        )
    from ai_foundation.klm_drive_auth import ReadonlyGoogleToken
    from ai_foundation.macos_keychain import MacOSKeychain
    from ai_foundation.klm_drive_runtime import OwnerDriveHTTP, OwnerInboxHTTP
    from ai_foundation.klm_drive_cycle import NativeInboxReader

    require_m1()
    if on_phase is not None:
        on_phase("OWNER_CONFIG")
    try:
        _report, config = _fixed_service_paths(Path.home())
        row, _ = _json_owner(config, MAX_CONFIG)
        if type(row) is not dict or set(row) != {
                "foundation_root", "roots", "owner_scope"}:
            raise ValueError("KLM_HOST_CONFIG_SCHEMA_INVALID")
        token = ReadonlyGoogleToken(MacOSKeychain(), on_phase=on_phase)
        if not token.available():
            return {"status": "BLOCKED", "phase": "TOKEN_REFRESH",
                    "reason": "DRIVE_AUTH_REQUIRED", "model_calls": 0,
                    "drive_mutations": 0}
    except Exception as exc:
        return {"status": "BLOCKED", "phase": "OWNER_CONFIG",
                "reason": "OWNER_BINDING_UNVERIFIED",
                "error_type": type(exc).__name__, "model_calls": 0,
                "drive_mutations": 0}
    return inspect_transport(token, NativeInboxReader(OwnerInboxHTTP(token)),
                             OwnerDriveHTTP(token), on_phase=on_phase)


def main():
    # The parent M1 bridge receives only these fixed, immediately flushed
    # progress categories if the existing Keychain/HTTP call cannot return.
    def progress(phase):
        if phase in _PHASES:
            print("KLM_PHASE:" + phase, file=sys.stderr, flush=True)
    report = live_readonly_probe(on_phase=progress)
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
