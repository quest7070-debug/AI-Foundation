#!/usr/bin/env python3
"""Owner SSH completion after verified Strata inference; no model invocation.

Read credentials only from the encrypted SSH stdin stream. Verify the pinned
authenticated model, then unlock/save/read back in one Keychain process.
This is credential enrollment, not new inference or MCP E2E acceptance.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import sys
from urllib import request
from urllib.error import HTTPError

BASE = "http://10.0.1.1:18080"
MODEL = "qwen3.8-flash-next-coder-iq1_m"
BINDING = "local:mainpc-strata:api-key"


def _keychain():
    from ai_foundation.macos_keychain import MacOSKeychain
    return MacOSKeychain()


def finish_keychain(data_root, payload, *, opener=None, keychain_factory=_keychain):
    if (type(payload) is not dict or set(payload) != {"api_key", "keychain_password"}
            or type(payload["api_key"]) is not str
            or not 16 <= len(payload["api_key"]) <= 256
            or any(ord(c) < 33 or ord(c) > 126 for c in payload["api_key"])
            or type(payload["keychain_password"]) is not str
            or not 0 < len(payload["keychain_password"].encode()) <= 4096):
        return {"status": "INPUT_REJECTED", "model_calls": 0}
    if __package__:
        from .m1_strata_local_first_setup import _reviewed_retarget
    else:
        from m1_strata_local_first_setup import _reviewed_retarget
    try:
        doc = json.loads((Path(data_root) / "local-compute/endpoints.json").read_text())
        rows = [r for r in doc["endpoints"] if type(r) is dict and r.get("name") == "mainpc-strata"]
        if (len(rows) != 1 or rows[0].get("base_url") != BASE
                or not _reviewed_retarget(rows[0], {"base_url": BASE})):
            raise ValueError()
    except (OSError, ValueError, TypeError, KeyError):
        return {"status": "AUTH_ENDPOINT_REVIEW_REQUIRED", "model_calls": 0}
    open_url = opener or request.build_opener(request.ProxyHandler({})).open
    try:
        for route in ("/health", "/v1/models"):
            req = request.Request(BASE + route, headers={"Authorization": "Bearer " + payload["api_key"]})
            with open_url(req, timeout=10) as response:
                raw = response.read(262145)
                if response.status != 200 or len(raw) > 262144:
                    raise ValueError()
            data = json.loads(raw)
            if route == "/health":
                if type(data) is not dict or data.get("api_key") is not True:
                    raise ValueError()
            elif (type(data) is not dict or type(data.get("data")) is not list
                  or not any(type(r) is dict and r.get("id") == MODEL for r in data["data"])):
                raise ValueError()
    except HTTPError as exc:
        return {"status": "AUTH_HTTP_REJECTED", "http_status": exc.code if exc.code in (401, 403) else 0, "model_calls": 0}
    except (OSError, ValueError, TypeError):
        return {"status": "AUTHENTICATED_MODEL_UNVERIFIED", "model_calls": 0}
    stage = "UNLOCK"
    try:
        store = keychain_factory()
        store.unlock(payload["keychain_password"])
        stage = "SAVE"
        store.save(BINDING, payload["api_key"])
        stage = "READBACK"
        saved = store.load(BINDING)
        if type(saved) is not str or not hmac.compare_digest(saved, payload["api_key"]):
            raise ValueError()
    except (OSError, RuntimeError, ValueError, KeyError):
        return {"status": "KEYCHAIN_" + stage + "_FAILED", "model_calls": 0}
    return {"status": "KEYCHAIN_REGISTERED_AUTHENTICATED_MODEL_VERIFIED", "model_calls": 0}


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from m1_development_bridge import require_m1
    from ai_foundation.productization import load_config
    from ai_foundation.authority_manifest import verify
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise SystemExit("M1_OWNER_SESSION_REQUIRED")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = load_config(args.config)
    root = Path(cfg.data_dir).resolve(strict=True)
    verify(root, cfg)
    raw = sys.stdin.buffer.read(32769)
    try:
        if len(raw) > 32768:
            raise ValueError()
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        result = {"status": "INPUT_REJECTED", "model_calls": 0}
    else:
        result = finish_keychain(root, payload)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "KEYCHAIN_REGISTERED_AUTHENTICATED_MODEL_VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
