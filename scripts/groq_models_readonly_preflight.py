"""Groq API-key read-only preflight from native Keychain; no model inference.

The Groq Models endpoint does not report the customer's billing plan.
A successful response proves only credential acceptance and model listing.
This command never creates a free-route attestation or makes a model runnable.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import os
import sqlite3
from urllib import request, error

from ai_foundation.native_credentials import MacOSNativeCredentialStore
from ai_foundation.provider_catalog import spec

MODELS_URL = "https://api.groq.com/openai/v1/models"
STAGED_BINDING = "pending:groq:free"
MAX_BYTES = 256 * 1024


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_KNOWN_403_CODES = frozenset({
    "model_permission_blocked_org",
    "model_permission_blocked_project",
    "blocked_api_access",
})
_KNOWN_TYPES = frozenset({
    "permissions_error", "invalid_request_error", "authentication_error",
})


def safe_http_error(exc):
    """Classify provider 4xx without printing its body or arbitrary fields.

    Permission-denied bodies can echo user paths, prompts, personal identifiers,
    or secret fragments. Only fixed categorical labels leave the Mac.
    """
    raw = exc.read(8193)
    headers = exc.headers
    media = headers.get("Content-Type", "").split(";", 1)[0].strip().lower() if headers else ""
    result = {"status": "HTTP_ERROR", "http_status": exc.code,
              "billing_verified": False, "inference_calls": 0,
              "error_class": "UNCLASSIFIED"}
    if len(raw) > 8192:
        result["error_class"] = "BODY_TOO_LARGE"
        return result
    if media in ("application/json", "application/problem+json") or raw.lstrip().startswith(b"{"):
        try:
            parsed = json.loads(raw)
        except (ValueError, UnicodeError):
            result["error_class"] = "JSON_PARSE_FAILED"
            return result
        err = parsed.get("error") if type(parsed) is dict else None
        if type(err) is not dict:
            result["error_class"] = "JSON_WITHOUT_ERROR_OBJECT"
            return result
        kind = err.get("type")
        code = err.get("code")
        if kind in _KNOWN_TYPES:
            result["error_type"] = kind
        if type(code) is str and code in _KNOWN_403_CODES:
            result["error_code"] = code
        result["error_class"] = "PROVIDER_JSON"
        if err.get("message") == "Forbidden":
            result["error_class"] = "GENERIC_FORBIDDEN"
        return result
    if media == "text/html" or raw.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        result["error_class"] = "HTML_GATEWAY_DENIAL"
    elif raw.strip().lower() == b"forbidden":
        result["error_class"] = "PLAIN_FORBIDDEN"
    else:
        result["error_class"] = "NON_JSON_DENIAL"
    return result


def verify_models(secret, *, opener=None, model=None):
    """Perform exactly one bounded, authenticated GET to the fixed official host."""
    if type(secret) is not str or not secret.startswith("gsk_"):
        return {"status": "INVALID_KEY_FORMAT", "billing_verified": False}
    model = model or spec("GROQ").model
    if model != spec("GROQ").model:
        return {"status": "MODEL_NOT_PINNED", "billing_verified": False}
    get = opener or request.build_opener(NoRedirect()).open
    req = request.Request(
        MODELS_URL, method="GET",
        headers={"Authorization": "Bearer " + secret, "Accept": "application/json"},
    )
    try:
        with get(req, timeout=8) as response:
            if response.status != 200:
                return {"status": "HTTP_ERROR", "http_status": response.status,
                        "billing_verified": False}
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            return {"status": "RESPONSE_TOO_LARGE", "billing_verified": False}
        try:
            body = json.loads(raw)
        except (json.JSONDecodeError, UnicodeError):
            return {"status": "INVALID_MODEL_LIST", "billing_verified": False}
        rows = body.get("data") if type(body) is dict else None
        if type(rows) is not list:
            return {"status": "INVALID_MODEL_LIST", "billing_verified": False}
        available = any(
            type(item) is dict and item.get("id") == model for item in rows)
        return {
            "status": "KEY_ACCEPTED_MODEL_LISTED" if available else "MODEL_NOT_LISTED",
            "model": model,
            "billing_verified": False,
            "network_calls": 1,
            "inference_calls": 0,
        }
    except error.HTTPError as exc:
        return safe_http_error(exc)
    except (OSError, TimeoutError, ValueError):
        return {"status": "NETWORK_UNAVAILABLE", "billing_verified": False}


def resolve_staged_or_registered_binding(store, registry_path=None):
    """Read-only; do not infer keys belong to the same account/Free project."""
    if store.available(STAGED_BINDING):
        return STAGED_BINDING, "STAGED_KEY"
    if registry_path is None or not Path(registry_path).is_file():
        return None, "STAGED_KEY_MISSING_REGISTRY_UNLOCATED"
    try:
        # SQLite's ro URI avoids creating a new registry as a side effect.
        with sqlite3.connect(Path(registry_path).resolve().as_uri() + "?mode=ro",
                             uri=True) as db:
            bindings = tuple(row[0] for row in db.execute(
                "SELECT binding FROM provider_credentials "
                "WHERE provider='GROQ' AND tier='FREE' ORDER BY binding"))
    except (OSError, sqlite3.Error):
        return None, "PROVIDER_REGISTRY_UNREADABLE"
    present = [b for b in bindings if store.available(b)]
    if len(present) > 1:
        return None, "MULTIPLE_REGISTERED_GROQ_KEYS"
    if present:
        return present[0], "REGISTERED_KEY"
    return None, "NO_GROQ_KEY_IN_KEYCHAIN"


def _registry_path(config_path):
    if not config_path or not Path(config_path).is_file():
        return None
    try:
        from ai_foundation.productization import load_config
        root = Path(load_config(config_path).data_dir)
        path = root / "providers.sqlite"
        return path if path.is_file() else None
    except (OSError, ValueError, TypeError, KeyError):
        return None


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only Groq models preflight")
    parser.add_argument(
        "--config", default=os.getenv(
            "AI_FOUNDATION_CONFIG",
            str(Path.home() / ".config/ai-foundation/config.json")))
    args = parser.parse_args(argv)
    store = MacOSNativeCredentialStore()
    binding, source = resolve_staged_or_registered_binding(
        store, _registry_path(args.config))
    if binding is None:
        print(json.dumps({"status": source, "billing_verified": False}))
        return 2
    try:
        # Never pass the key on argv, into a URL, to GitHub, or into output JSON.
        secret = store.load(binding)
    except KeyError:
        print(json.dumps({"status": "KEYCHAIN_ITEM_NOT_FOUND",
                          "billing_verified": False}))
        return 2
    except RuntimeError:
        print(json.dumps({"status": "KEYCHAIN_ACCESS_DENIED_OR_LOCKED",
                          "billing_verified": False}))
        return 2
    result = verify_models(secret)
    result["key_source"] = source
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "KEY_ACCEPTED_MODEL_LISTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
