"""Official Groq model-list HTTPS IPv4 read-only Keychain probe.

Single GET, no redirects, no API POST, no inference or account billing
attestation. Only a bounded status code is returned; no secret, raw body or
error message escapes. Network failure leaves service UNVERIFIED.
"""
from __future__ import annotations

import re
import subprocess

URL = "https://api.groq.com/openai/v1/models"

def check_ipv4(key, *, runner=subprocess.run):
    if type(key) is not str or re.fullmatch(r"gsk_[A-Za-z0-9_-]{20,}", key) is None:
        return {"status": "INVALID_KEY_FORMAT", "http_status": None,
                "inference_calls": 0, "billing_verified": False}

    args = [
        "/usr/bin/curl", "-q", "--ipv4", "--silent", "--show-error",
        "--connect-timeout", "5", "--max-time", "12",
        "--proto", "=https",
        "--output", "/dev/null", "--write-out", "%{http_code}",
        "--config", "-", URL,
    ]
    # curl -K - reads the Authorization header from stdin rather than argv.
    # The key format is strictly validated so it cannot break config quoting.
    cfg = 'header = "Authorization: Bearer ' + key + '"\n'
    try:
        proc = runner(args, input=cfg, capture_output=True, text=True,
                      timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return {"status": "CURL_IPV4_UNAVAILABLE", "http_status": None,
                "inference_calls": 0, "billing_verified": False}
    code = proc.stdout.strip()
    if proc.returncode != 0 or not re.fullmatch(r"[0-9]{3}", code) or code == "000":
        return {"status": "IPV4_NETWORK_ERROR", "http_status": None,
                "inference_calls": 0, "billing_verified": False}
    http = int(code)
    status = {200: "GROQ_KEY_ACCEPTED_IPV4", 401: "GROQ_KEY_REJECTED_IPV4",
              403: "GROQ_KEY_FORBIDDEN_IPV4",
              429: "GROQ_RATE_LIMITED_IPV4"}.get(http, "GROQ_UNEXPECTED_HTTP_STATUS")
    return {"status": status, "http_status": http, "inference_calls": 0,
            "billing_verified": False}


