"""One-shot Groq IPv4 Keychain read-only diagnostic (zero inference calls).

Only the staged macOS Keychain key is read. A single curl GET to Groq's
official model listing uses IPv4 and does not
follow redirects. The secret crosses to curl via stdin config, never argv,
filesystem, logs or shell expansion. Output includes HTTP status only.

This can verify the API key on the same HTTP client that returned 401
without credentials, while prior Python urllib calls returned 403.
It cannot prove account billing safety or authorize any inference.
"""
from __future__ import annotations

import json
from ai_foundation.groq_ipv4_probe import check_ipv4, URL
from ai_foundation.native_credentials import MacOSNativeCredentialStore

STAGED_KEY = "pending:groq:free"


def main():
    store = MacOSNativeCredentialStore()
    try:
        key = store.load(STAGED_KEY)
    except KeyError:
        print(json.dumps({"status": "STAGED_KEY_NOT_FOUND"}))
        return 2
    except (OSError, RuntimeError):
        print(json.dumps({"status": "KEYCHAIN_READ_UNAVAILABLE"}))
        return 2
    result = check_ipv4(key)
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "GROQ_KEY_ACCEPTED_IPV4" else 2


if __name__ == "__main__":
    raise SystemExit(main())
