"""Explicit no-inference adoption of one staged Groq Keychain credential.

A key known to work with macOS curl IPv4 must not pass back through the
Python urllib onboarding probe (which returned 403 on this host). This host-
only handoff writes a *disabled/unverified* provider registry entry with the
catalog's exact model and endpoint. Adoption never attests account billing,
enables a route, calls Groq, or deletes the original staging credential.
A separate explicit verification function does one read-only IPv4 GET.
"""
from __future__ import annotations

import re

from .provider_catalog import spec

STAGED = "pending:groq:free"
MANAGED = "llm:groq:staged-free-v1"


def adopt_staged_groq(registry, native, *, staging=STAGED, managed=MANAGED):
    """Trusted native operator only; no untrusted Issue/agent may invoke."""
    if staging != STAGED or managed != MANAGED:
        raise ValueError("GROQ_STAGING_BINDING_FIXED")
    pin = spec("GROQ")
    if (pin is None or not pin.endpoint.startswith("https://")
            or not pin.model or not pin.protocol):
        return {"state": "GROQ_CATALOG_NOT_PINNED", "wrote": False}
    current = registry.credential(managed)
    if current is not None:
        if (current.get("provider") != "GROQ"
                or current.get("tier") != "FREE"
                or current.get("active") is not False
                or current.get("model") != pin.model
                or current.get("endpoint") != pin.endpoint):
            return {"state": "EXISTING_ROUTE_IDENTITY_CONFLICT", "wrote": False}
        if not native.available(managed):
            return {"state": "MANAGED_KEYCHAIN_KEY_MISSING", "wrote": False}
        return {"state": "MANAGED_GROQ_ALREADY_REGISTERED", "wrote": False}
    if any(row["provider"] == "GROQ" and row["tier"] == "FREE"
           for row in registry.credentials()):
        return {"state": "GROQ_FREE_ALREADY_REGISTERED", "wrote": False}

    # Never display, print, log, serialize or send these bytes to the network.
    if not native.available(staging):
        return {"state": "STAGED_KEYCHAIN_KEY_MISSING", "wrote": False}
    secret = native.load(staging)
    if type(secret) is not str or re.fullmatch(
            r"gsk_[a-zA-Z0-9_-]{20,}", secret) is None:
        return {"state": "STAGED_KEY_FORMAT_INVALID", "wrote": False}

    newly_saved = False
    try:
        if native.available(managed):
            if native.load(managed) != secret:
                return {"state": "MANAGED_KEY_CONFLICT", "wrote": False}
        else:
            native.save(managed, secret)
            newly_saved = True
        if native.load(managed) != secret:
            raise RuntimeError("KEYCHAIN_COPY_READBACK_FAILED")
        registry.upsert(
            managed, "GROQ", tier="FREE", health="UNVERIFIED", active=False,
            reason="ACCOUNT_BILLING_NOT_ATTESTED_NO_INFERENCE",
            endpoint=pin.endpoint, model=pin.model, auth_style=pin.auth_style,
            protocol=pin.protocol, capabilities=pin.capabilities)
    except Exception:
        # An uncommitted registry entry cannot claim native acceptance.
        # Leave the original staging credential untouched for recovery.
        if newly_saved and registry.credential(managed) is None:
            try:
                native.delete(managed)
            except Exception:
                pass
        return {"state": "REGISTRATION_FAILED_NO_INFERENCE", "wrote": False}
    return {"state": "REGISTERED_UNVERIFIED_NO_INFERENCE", "wrote": True}


def verify_managed_groq_ipv4(registry, native, *, checker=None):
    """One explicit GET /models; mark ONLINE only for verified HTTP 200.

    Never infer billing approval from an authenticated API key. A failed or
    ambiguous GET makes this credential ineligible for Harness CODE routing,
    even if it was previously marked ONLINE.
    """
    row = registry.credential(MANAGED)
    pin = spec("GROQ")
    if (not row or not pin or row.get("provider") != "GROQ"
            or row.get("tier") != "FREE"
            or row.get("endpoint") != pin.endpoint
            or row.get("model") != pin.model):
        return {"status": "GROQ_MANAGED_ROUTE_NOT_PINNED",
                "http_status": None, "health_updated": False,
                "billing_verified": False, "inference_calls": 0}
    if not native.available(MANAGED):
        return {"status": "MANAGED_KEYCHAIN_KEY_MISSING",
                "http_status": None, "health_updated": False,
                "billing_verified": False, "inference_calls": 0}
    from .groq_ipv4_probe import check_ipv4
    probe = check_ipv4 if checker is None else checker
    try:
        result = probe(native.load(MANAGED))
    except Exception:
        result = {"status": "GROQ_IPV4_NETWORK_ERROR", "http_status": None}
    status = result.get("status")
    http_status = result.get("http_status")
    if status == "GROQ_KEY_ACCEPTED_IPV4" and http_status == 200:
        health, reason = "ONLINE", None
    elif status == "GROQ_RATE_LIMITED_IPV4" and http_status == 429:
        health, reason = "RATE_LIMITED", "GROQ_IPV4_RATE_LIMITED"
    else:
        health, reason = "UNVERIFIED", "GROQ_IPV4_AUTH_NOT_CONFIRMED"
    try:
        updated = registry.observe(MANAGED, health=health, reason=reason)
    except Exception:
        updated = False
    return {"status": status if updated else "GROQ_HEALTH_RECORD_UNAVAILABLE",
            "http_status": http_status if type(http_status) is int else None,
            "health_updated": updated,
            "billing_verified": False, "inference_calls": 0}
