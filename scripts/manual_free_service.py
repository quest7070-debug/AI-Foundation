"""Owner-only Free service selection, no network or model calls.

The human chooses a provider/account that *cannot* automatically charge.
This command records that one selection. It never discovers, ranks, tests,
renews, purchases, upgrades or changes a provider subscription.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from ai_foundation.free_route_admission import SQLiteFreeRouteAdmission
from ai_foundation.provider_registry import SQLiteProviderRegistry


def main(argv=None):
    parser = argparse.ArgumentParser(description="Manual Free-service allowlist")
    parser.add_argument("--root", required=True, help="Existing Foundation data directory")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="Read registered credentials and selection status")
    select = sub.add_parser("select", help="Record a human-selected no-charge Free route")
    select.add_argument("--binding", required=True)
    select.add_argument("--confirm-no-auto-charge", action="store_true", required=True,
                        help="I checked my provider/account cannot automatically charge")
    select.add_argument("--account-alias", default="", help="Optional grouping label")
    select.add_argument("--project-alias", default="", help="Optional grouping label")
    revoke = sub.add_parser("revoke", help="Withdraw one manual selection")
    revoke.add_argument("--binding", required=True)
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser()
    if not (root / "providers.sqlite").is_file():
        parser.error("FOUNDATION_PROVIDER_REGISTRY_NOT_FOUND")
    registry = SQLiteProviderRegistry(root / "providers.sqlite")
    gate = SQLiteFreeRouteAdmission(root / "free-route-admission.sqlite")

    if args.action == "list":
        entries = [
            {
                "binding": m["binding"],
                "provider": m["provider"],
                "tier": m["tier"],
                "model": m.get("model"),
                "selected": gate.decide(m).allowed,
            }
            for m in registry.credentials()
        ]
        result = {"mode": "MANUAL_ONLY", "services": entries}
    else:
        meta = registry.credential(args.binding)
        if meta is None:
            parser.error("REGISTERED_BINDING_NOT_FOUND")
        if args.action == "select":
            # The operator confirmation is the entire financial selection
            # decision, not a recurring or model-generated attestation.
            if not args.confirm_no_auto_charge:
                parser.error("OWNER_HARD_STOP_CONFIRMATION_REQUIRED")
            gate.select(meta, account_alias=args.account_alias,
                        project_alias=args.project_alias)
            result = {"binding": args.binding, "selected": True}
        else:
            gate.revoke(args.binding)
            result = {"binding": args.binding, "selected": False}
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
