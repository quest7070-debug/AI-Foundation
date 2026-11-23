#!/usr/bin/env python3
"""Place an existing LLMPerks digest note in one app-owned research folder.

Uses already-consented owner drive.file, without touching KLM's readonly scope.
Outputs bounded receipt codes only; neither credentials nor file/folder IDs.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_foundation.llmperks_klm_folder import place_owner_note


def main(argv=None):
    p = argparse.ArgumentParser(description="Owner LLMPerks research placement")
    p.add_argument("--sha256", required=True)
    args = p.parse_args(argv)
    try:
        result = place_owner_note(args.sha256)
    except Exception as exc:
        # No source or private path/ID in logs.
        print("LLMPERKS_KLM_FOLDER=UNVERIFIED:" + type(exc).__name__, file=sys.stderr)
        return 2
    print("LLMPERKS_KLM_FOLDER=" + result["status"])
    print("LLMPERKS_KLM_FOLDER_DIGEST=" + result["sha256"])
    print("KLM_INTAKE_STAGED=NO")
    print("MODEL_CALLS=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
