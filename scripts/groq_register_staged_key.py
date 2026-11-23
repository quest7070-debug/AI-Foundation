"""Register staged Groq credential as an UNVERIFIED managed Harness service.

No inference or manual selection; optional --verify-ipv4 sends one models GET. Host operator
must explicitly pass --adopt-staged; --status is the default. Uses the
already available macOS Keychain, never asks for or prints the API key.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission
from ai_foundation.groq_staged_adoption import (
    MANAGED, STAGED, adopt_staged_groq, verify_managed_groq_ipv4,
)
from ai_foundation.native_credentials import MacOSNativeCredentialStore
from ai_foundation.productization import load_config
from ai_foundation.provider_registry import SQLiteProviderRegistry


def report(registry, native, admission=None):
    row = registry.credential(MANAGED)
    status = admission.decide(row) if admission is not None else None
    return {
        "service": "GROQ", "manager": "FOUNDATION_HARNESS",
        "staged_key_present": native.available(STAGED),
        "managed_key_present": native.available(MANAGED),
        "registered": row is not None and row.get("provider") == "GROQ",
        "health": row.get("health") if row else None,
        "manually_selected": bool(status and status.allowed),
        "account_and_health_eligible": bool(
            row and row.get("health") == "ONLINE"
            and native.available(MANAGED) and status and status.allowed),
        "selection_reason": status.reason if status else "NO_MANUAL_SELECTION_STORE",
        "live_code_route_enabled": False,
        "inference_calls": 0,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True,
                        help="Trusted Foundation native config path")
    parser.add_argument("--adopt-staged", action="store_true",
                        help="Copy staged Keychain key into inactive managed registry")
    parser.add_argument("--verify-ipv4", action="store_true",
                        help="One official read-only GET /models, no inference")
    args = parser.parse_args(argv)
    root = Path(load_config(args.config).data_dir)
    registry_path = root / "providers.sqlite"
    # Read-only status does not initialize an absent provider registry.
    if not (args.adopt_staged or args.verify_ipv4) and not registry_path.exists():
        print(json.dumps({"service": "GROQ", "registered": False,
                          "status": "REGISTRY_NOT_INITIALIZED",
                          "inference_calls": 0}, sort_keys=True))
        return 0
    registry = SQLiteProviderRegistry(registry_path)
    native = MacOSNativeCredentialStore()
    receipt_path = root / "free-route-admission.sqlite"
    admission = (SQLiteFreeRouteAdmission(receipt_path)
                 if receipt_path.exists() else None)
    if args.adopt_staged:
        result = adopt_staged_groq(registry, native)
    else:
        result = {"state": "READ_ONLY_STATUS", "wrote": False}
    success = not args.adopt_staged or result["state"] in (
        "REGISTERED_UNVERIFIED_NO_INFERENCE",
        "MANAGED_GROQ_ALREADY_REGISTERED")
    if args.verify_ipv4 and success:
        verification = verify_managed_groq_ipv4(registry, native)
        result["ipv4_check"] = verification
        success = verification["status"] == "GROQ_KEY_ACCEPTED_IPV4"
    result.update(report(registry, native, admission))
    print(json.dumps(result, sort_keys=True))
    return 0 if success else 2


if __name__ == "__main__":
    raise SystemExit(main())
