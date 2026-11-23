#!/usr/bin/env python3
"""One owner-Mac LLMPerks → existing Drive app-file research-only handoff.

No new OAuth, KLM token, service registration, 9B work or scheduler.
Run from an owner checkout that contains BOTH the LLMPerks discovery code
(PR #526) and the already-consented Drive app-file port (PR #481).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_foundation.harness_research_bootstrap import load_harness_research_ledger
from ai_foundation.llmperks_discovery import SourceInvalid
from ai_foundation.llmperks_ranking import fetch_full_dump
from ai_foundation.llmperks_service_routes import project_service_model_routes
from ai_foundation.llmperks_owner_drive import handoff_to_owner_drive


def run(*, write=False, fetch=fetch_full_dump, handoff=handoff_to_owner_drive):
    ledger = load_harness_research_ledger(ROOT)
    if ledger is None:
        raise SourceInvalid("NO_EXISTING_RESEARCH_LEDGER")
    catalog = fetch()
    projection = project_service_model_routes(ledger, catalog)
    return handoff(catalog, projection, write=write)


def main(argv=None):
    p = argparse.ArgumentParser(description="Owner Drive research-only LLMPerks handoff")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--inspect", action="store_true",
                      help="public feed GET + owner Drive metadata/media GET only")
    mode.add_argument("--write-note", action="store_true",
                      help="owner-selected create-once Drive text and independent GET")
    a = p.parse_args(argv)
    try:
        result = run(write=a.write_note)
        # Never print Drive IDs, access tokens, owner paths or model/vendor claims.
        print("LLMPERKS_OWNER_DRIVE=" + result["status"])
        print("RESEARCH_SHA256=" + result["sha256"])
        return 0
    except Exception as exc:
        print("LLMPERKS_OWNER_DRIVE=UNVERIFIED:" + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
