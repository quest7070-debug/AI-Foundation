#!/usr/bin/env python3
"""One foreground lease for the model-free external ledger workflow.

Checkout and interpreter startup precede admission. No runner hooks are installed.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.host_compute_job import run_job


def phases(python=sys.executable):
    source = ROOT / "experiments" / "human_model"
    # Compile in memory: do not create bytecode in the checkout or touch an SSD.
    check = (
        "import pathlib,sys; "
        "[compile(pathlib.Path(p).read_bytes(),p,'exec') for p in sys.argv[1:]]"
    )
    return [
        {"name": "validate-ledger-sources", "argv": [python, "-B", "-c", check,
            *[str(source / p) for p in (
                "storage_location.py", "human_model_ledger.py", "test_external_ledger.py")]]},
        {"name": "synthetic-ledger-contracts", "argv": [python, "-B", "-m", "unittest",
            "discover", "-s", str(source), "-p", "test_external_ledger.py", "-v"]},
    ]


if __name__ == "__main__":
    # No waiting on existing users; busy is non-success 75, never a skipped PASS.
    raise SystemExit(run_job(phases(), max_wait_s=0))
