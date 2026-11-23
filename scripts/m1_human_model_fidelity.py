"""Read existing private owner review files and print fidelity aggregates only.

No source/answer reads, review provisioning, model calls, Guard decisions,
remote transport, deployment or database writes. Missing reviews stay unknown.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    try:
        from m1_development_bridge import require_m1
        from ai_foundation.authority_manifest import verify
        from ai_foundation.human_model_fidelity_host import evaluate_owner_private_fidelity
        from ai_foundation.productization import load_config

        require_m1()
        if os.getuid() != 501 or os.geteuid() != os.getuid():
            raise PermissionError("M1_OWNER_SESSION_REQUIRED")
        config = load_config(args.config)
        root = Path(config.data_dir)
        verify(root, config)
        result = evaluate_owner_private_fidelity(root)
    except Exception:
        result = {"status": "BLOCKED", "reason": "OWNER_HOST_UNAVAILABLE",
                  "evaluated_questions": 0, "review_binding_verified": False,
                  "representative_fidelity_verified": False,
                  "execution_authority": False, "private_content_exported": False,
                  "model_calls": 0, "native_effects": 0}
    print(json.dumps(result, sort_keys=True))
    return 1 if result["status"] == "BLOCKED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
