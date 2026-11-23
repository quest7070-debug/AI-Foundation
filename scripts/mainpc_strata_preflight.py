#!/usr/bin/env python3
"""On-demand M1→MainPC Strata verification; no daemon, portproxy or secret export.

Default is read-only and never wakes the PC. --wake runs only the existing
owner's ~/wake-desktop.py once if Strata is unreachable. --smoke sends a fixed
non-personal prompt to the host-configured Strata endpoint.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_foundation.local_endpoint_config import load_local_endpoints

_PREFIX = "local:mainpc-strata"
_ALIAS = "code-agent"
_SMOKE = "Reply with exactly STRATA_ROUTE_OK and nothing else."


def _wake_existing_owner_script(*, home, runner):
    """No arbitrary argv, paths, programs, model calls or remote command."""
    script = Path(home) / "wake-desktop.py"
    try:
        info = script.lstat()
        if (not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022
                or not 0 < info.st_size <= 65536):
            return False
        completed = runner([sys.executable, str(script)], timeout=12,
                           stdin=subprocess.DEVNULL, capture_output=True,
                           check=False)
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


def verify_strata(config_path, *, wake=False, smoke=False, home=None,
                  runner=subprocess.run, monotonic=time.monotonic,
                  sleep=time.sleep, diagnostics=None):
    """Bounded fixed endpoint/config check, without leaking token or response."""
    if type(wake) is not bool or type(smoke) is not bool:
        return {"status": "INVALID_REQUEST"}
    try:
        rows = [r for r in load_local_endpoints(config_path) if r[0] == _PREFIX]
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "CONFIG_UNAVAILABLE"}
    if len(rows) != 1:
        return {"status": "MAINPC_STRATA_NOT_CONFIGURED"}
    _prefix, discovery, execution = rows[0]
    if _ALIAS not in execution.models:
        return {"status": "MAINPC_MODEL_NOT_BOUND"}

    reason = "DISCOVERY_UNAVAILABLE"
    def ready():
        nonlocal reason
        candidates = discovery.candidates()
        codes = {c.reason for c in candidates}
        known = {"HTTP_401", "HTTP_403", "HTTP_429", "HTTP_500", "HTTP_502",
                 "HTTP_503", "HTTP_504", "NO_AUTHORIZED_MODEL", "URLError",
                 "TimeoutError", "JSONDecodeError", "ValueError"}
        reason = next(("DISCOVERY_" + c for c in sorted(known) if c in codes),
                      "DISCOVERY_UNAVAILABLE")
        return any(c.binding == _PREFIX + ":" + _ALIAS
                   and c.health == "ONLINE" and c.same_host is False
                   for c in candidates)

    reachable = ready()
    woke = False
    if not reachable and wake:
        # A bad credential, missing model or reachable HTTP server is not a
        # sleeping PC. Never turn those failures into a physical wake effect.
        if reason not in {"DISCOVERY_URLError", "DISCOVERY_TimeoutError",
                          "DISCOVERY_UNAVAILABLE"}:
            if diagnostics is not None:
                diagnostics["reason_code"] = reason
            return {"status": "MAINPC_UNAVAILABLE"}
        woke = _wake_existing_owner_script(
            home=Path.home() if home is None else home, runner=runner)
        if not woke:
            return {"status": "WAKE_UNAVAILABLE"}
        # The historical MainPC sometimes took roughly 40 seconds to load
        # Strata after WoL; do not turn discovery into automatic daily wake.
        deadline = monotonic() + 60.0
        while not reachable and monotonic() < deadline:
            sleep(min(5.0, max(0.0, deadline - monotonic())))
            reachable = ready()
    if not reachable:
        if diagnostics is not None:
            diagnostics["reason_code"] = reason
        return {"status": "WAKE_ISSUED_NOT_READY" if woke else "MAINPC_UNAVAILABLE"}
    if not smoke:
        return {"status": "MODEL_DISCOVERED"}
    try:
        answer = execution.chat(_SMOKE, model=_ALIAS)
    except (OSError, ValueError, RuntimeError, KeyError, IndexError, TypeError) as exc:
        if diagnostics is not None:
            diagnostics["reason_code"] = (
                "INFERENCE_HTTP_" + str(exc.code) if isinstance(exc, HTTPError)
                and exc.code in (401, 403, 429, 500, 502, 503, 504)
                else "INFERENCE_" + type(exc).__name__
                if type(exc).__name__ in {"TimeoutError", "URLError", "JSONDecodeError"}
                else "INFERENCE_RESPONSE_OR_CONNECTION_ERROR")
        return {"status": "INFERENCE_UNAVAILABLE"}
    verified = isinstance(answer, str) and answer.strip() == "STRATA_ROUTE_OK"
    if not verified and diagnostics is not None:
        diagnostics["reason_code"] = ("INFERENCE_EMPTY_CONTENT" if not answer
                                      else "INFERENCE_REPLY_MISMATCH")
    return {"status": "INFERENCE_VERIFIED" if verified else "INFERENCE_NOT_VERIFIED"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="M1 existing endpoints.json")
    parser.add_argument("--wake", action="store_true", help="explicit one-shot owner WoL")
    parser.add_argument("--smoke", action="store_true", help="fixed synthetic inference")
    args = parser.parse_args()
    result = verify_strata(args.config, wake=args.wake, smoke=args.smoke)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"MODEL_DISCOVERED", "INFERENCE_VERIFIED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

