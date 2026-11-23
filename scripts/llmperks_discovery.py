#!/usr/bin/env python3
"""Fetch LLMPerks research index; emit safe snapshot, delta and optional Drive note.

Paths are explicit; no credentials, inference, provider registration or Drive write.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.llmperks_discovery import SourceInvalid, fetch_index, compare, review_note
from ai_foundation.llmperks_ranking import fetch_full_dump, ranked_reasoning, ranked_review_note
from ai_foundation.harness_research_bootstrap import load_harness_research_ledger
from ai_foundation.llmperks_service_routes import project_service_model_routes, research_projection_note


def atomic_text(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                      prefix=".llmperks-", delete=False) as f:
        os.chmod(f.name, 0o600)
        f.write(content)
        temp = f.name
    try:
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--snapshot", required=True)
    p.add_argument("--report", required=True)
    p.add_argument("--review-note")
    p.add_argument("--ranked", help="Both published AA and GPQA ranking datasets")
    p.add_argument("--ranked-review-note", help="Short reasoning ranking for Drive/KLM")
    p.add_argument("--service-routes", help="Read-only nested model/API routes by existing service")
    p.add_argument("--service-routes-review-note", help="Short unresolved/matched service digest")
    a = p.parse_args(argv)
    if a.ranked_review_note and not a.ranked:
        p.error("--ranked-review-note requires --ranked")
    if a.service_routes and not a.ranked:
        p.error("--service-routes requires --ranked")
    if a.service_routes_review_note and not a.service_routes:
        p.error("--service-routes-review-note requires --service-routes")
    output_names = [a.snapshot, a.report, a.review_note, a.ranked, a.ranked_review_note,
                    a.service_routes, a.service_routes_review_note]
    paths = [Path(x).resolve() for x in output_names if x is not None]
    if len(set(paths)) != len(paths):
        p.error("All output paths must be different")
    try:
        old = json.loads(Path(a.snapshot).read_text(encoding="utf-8")) if Path(a.snapshot).exists() else None
        current = fetch_index()
        diff = compare(current, old)
        catalog = fetch_full_dump() if a.ranked else None
        model_route_projection = None
        if a.service_routes:
            ledger = load_harness_research_ledger(ROOT)
            if ledger is None:
                raise SourceInvalid("SERVICE_LEDGER_UNAVAILABLE")
            model_route_projection = project_service_model_routes(ledger, catalog)
        rankings = ({
            "schema": "llmperks-reasoning-rankings-v1",
            "source_snapshot": catalog["publisher_snapshot"],
            "aa_intelligence": ranked_reasoning(catalog, metric="aa_intelligence", limit=25),
            "gpqa_diamond": ranked_reasoning(catalog, metric="gpqa_diamond", limit=25),
            "publisher_claims_only": True,
            "execution_authorized": False,
        } if catalog is not None else None)
    except (OSError, SourceInvalid, ValueError, UnicodeError, KeyError, TypeError):
        print("LLMPERKS_SOURCE_INVALID_OR_UNAVAILABLE", file=sys.stderr)
        return 2
    # The previous snapshot is never changed on failed/invalid source responses.
    atomic_text(a.report, json.dumps(diff, ensure_ascii=False, indent=2) + "\n")
    if a.review_note:
        atomic_text(a.review_note, review_note(current, diff))
    if rankings is not None:
        atomic_text(a.ranked, json.dumps(rankings, ensure_ascii=False, indent=2) + "\n")
        if a.ranked_review_note:
            atomic_text(a.ranked_review_note, ranked_review_note(catalog))
    if model_route_projection is not None:
        atomic_text(a.service_routes, json.dumps(model_route_projection, ensure_ascii=False, indent=2) + "\n")
        if a.service_routes_review_note:
            atomic_text(a.service_routes_review_note, research_projection_note(model_route_projection))
    atomic_text(a.snapshot, json.dumps(current, ensure_ascii=False, indent=2) + "\n")
    print("LLMPERKS_RESEARCH_OK baseline=" + str(diff["baseline_only"]) +
          " new_featured=" + str(len(diff["new_featured"])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
