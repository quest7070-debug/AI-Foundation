"""At-most-once public Groq inference only after true account Free attestation.

The pinned request is sent over curl IPv4, not urllib (which previously
returned HTTP 403 on the same host). A claim is durably committed before
dispatch, never retried even if delivery status cannot be determined.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_foundation.cloud_execution import ObservedCloudExecution
from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission
from ai_foundation.groq_ipv4_once_transport import (
    GroqIPv4OnceTransport, EXPECTED, fixture_payload)
from ai_foundation.groq_once_ledger import SQLiteGroqOnceLedger
from ai_foundation.native_credentials import MacOSNativeCredentialStore
from ai_foundation.provider_catalog import spec
from ai_foundation.provider_observer import ProviderResponseObserver
from ai_foundation.provider_registry import SQLiteProviderRegistry
from ai_foundation.productization import load_config


def free_groq_connections(registry):
    """Credential references under one Groq service; never assume same account."""
    return tuple(
        row["binding"] for row in registry.credentials()
        if row["provider"] == "GROQ" and row["tier"] == "FREE")


def run_one(registry, admission, secret_store, transport, *, binding, ledger):
    meta = registry.credential(binding)
    pinned = spec("GROQ")
    if (not meta or not pinned or meta["provider"] != "GROQ"
            or meta["tier"] != "FREE" or meta["model"] != pinned.model
            or meta["endpoint"] != pinned.endpoint):
        return {"status": "NOT_AN_ELIGIBLE_GROQ_FREE_BINDING", "sent": False}
    decision = admission.decide(meta)
    if not decision.allowed:
        return {"status": "FREE_ROUTE_DENIED", "reason": decision.reason, "sent": False}
    # An UNVERIFIED connection may try its first public call once the Free
    # account is admitted; skip only known outage/exhaustion signals.
    if meta.get("health") in (
            "RATE_LIMITED", "RETIRED", "CREDENTIAL_ERROR", "DOWN"):
        return {"status": "PROVIDER_NOT_READY", "sent": False}
    if not secret_store.available(binding):
        return {"status": "MISSING_NATIVE_KEY", "sent": False}

    payload = fixture_payload(meta["model"])
    try:
        # Exact-route guard before consuming a durable one-time claim.
        admission.require(meta, payload)
    except PermissionError:
        return {"status": "FREE_ROUTE_DENIED", "reason": "PAYLOAD_OR_COST_POLICY",
                "sent": False}
    try:
        claimed = ledger.claim(
            binding=binding, model=meta["model"], endpoint=meta["endpoint"])
    except Exception:
        return {"status": "ONE_SHOT_LEDGER_UNAVAILABLE", "sent": False}
    if not claimed:
        return {"status": "ONE_SHOT_ALREADY_CLAIMED", "sent": False}

    boundary = ObservedCloudExecution(
        registry, secret_store, ProviderResponseObserver(registry), transport,
        admission=admission)
    try:
        body = boundary.invoke(binding, payload)
        try:
            data = json.loads(body)
            text = data["choices"][0]["message"]["content"].strip()
            outcome = ("VERIFIED_PUBLIC_FIXTURE" if text == EXPECTED
                       else "NONMATCHING_PUBLIC_FIXTURE")
        except (ValueError, TypeError, KeyError, IndexError, AttributeError):
            outcome = "INVALID_PROVIDER_RESPONSE"
        result = {"status": outcome, "sent": True}
    except Exception as exc:
        # The request might have reached Groq even when the client times out.
        # Never retry. No exception text, prompt, raw response or key in output.
        result = {"status": "ONE_SHOT_FAILED",
                  "error": type(exc).__name__, "sent": "UNCERTAIN"}
        outcome = "ONE_SHOT_FAILED"
    try:
        ledger.finish(outcome)
    except Exception:
        # The existing CLAIMED record remains authoritative and blocks retries.
        return {"status": "ONE_SHOT_RECEIPT_WRITE_UNCERTAIN", "sent": "UNCERTAIN"}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--binding", help="Exact credential binding; inferred only for one Free Groq service")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--status", action="store_true",
                        help="Read readiness without sending any inference")
    args = parser.parse_args(argv)
    if args.once == args.status:
        print('{"status":"SELECT_EXACTLY_ONE_OF_STATUS_OR_ONCE"}')
        return 2
    root = Path(load_config(args.config).data_dir)
    registry = SQLiteProviderRegistry(root / "providers.sqlite")
    admission = SQLiteFreeRouteAdmission(root / "free-route-admission.sqlite")
    ledger = SQLiteGroqOnceLedger(root / "groq-one-shot.sqlite")
    binding = args.binding
    if binding is None:
        # One service can have multiple distinct billing projects. Never
        # silently pick a key when the Groq Free association is ambiguous.
        candidates = free_groq_connections(registry)
        if len(candidates) != 1:
            print(json.dumps({
                "status": "NO_UNIQUE_GROQ_FREE_SERVICE",
                "candidate_count": len(candidates)}, sort_keys=True))
            return 2
        binding = candidates[0]
    if args.status:
        meta = registry.credential(binding)
        pinned = spec("GROQ")
        route_pinned = bool(meta and pinned and
                            meta["provider"] == "GROQ" and
                            meta["tier"] == "FREE" and
                            meta["model"] == pinned.model and
                            meta["endpoint"] == pinned.endpoint)
        verdict = admission.decide(meta)
        health_permits = bool(meta and meta.get("health") not in (
            "RATE_LIMITED", "RETIRED", "CREDENTIAL_ERROR", "DOWN"))
        key_present = bool(route_pinned and
                           MacOSNativeCredentialStore().available(binding))
        one_shot = ledger.status()
        print(json.dumps({
            "status": ("READY_FOR_EXPLICIT_ONCE"
                       if route_pinned and verdict.allowed and health_permits and
                       key_present and one_shot == "NEVER_CLAIMED"
                       else "NOT_READY"),
            "health_permits": health_permits,
            "billing_attested": verdict.allowed,
            "billing_reason": verdict.reason,
            "key_present": key_present,
            "model_pinned": route_pinned,
            "one_shot_status": one_shot,
        }, sort_keys=True))
        return 0
    result = run_one(
        registry, admission, MacOSNativeCredentialStore(),
        GroqIPv4OnceTransport(), binding=binding, ledger=ledger)
    # Output is bounded structural status only, not response body or secrets.
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "VERIFIED_PUBLIC_FIXTURE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
