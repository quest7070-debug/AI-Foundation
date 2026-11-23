"""M1 localhost Ollama smoke test using synthetic evidence only.

No personal data, no external SSD writes, no hypothesis endorsement.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "human_model"))
from ollama_proposal_runner import generate_local_proposals
from proposal_json_contract import parse_proposals
from proposal_evaluation import evaluate_proposals

def main():
    model = os.environ.get("HUMAN_MODEL_OLLAMA_MODEL", "").strip()
    if not model:
        raise SystemExit("BLOCKED: explicitly configure HUMAN_MODEL_OLLAMA_MODEL")
    evidence = [
        {"id": "synthetic-evidence-1", "scope": "synthetic",
         "content": "Synthetic user explicitly prefers option A."},
        {"id": "synthetic-evidence-2", "scope": "synthetic",
         "content": "Synthetic user sometimes chooses option B."},
    ]
    raw = generate_local_proposals(model=model, evidence=evidence, timeout=45)
    if raw == "[]":
        print(json.dumps({"model_reachable": True, "valid_proposals": 0,
                          "status": "NO_PROPOSALS"}))
        return
    proposals = parse_proposals(raw)
    comparison = evaluate_proposals(proposals=proposals, evidence=evidence)
    print(json.dumps({"model_reachable": True, "valid_proposals": len(proposals),
                      "status": "VALIDATED", "disagreement": comparison["producer_disagreement"]}))

if __name__ == "__main__":
    main()
