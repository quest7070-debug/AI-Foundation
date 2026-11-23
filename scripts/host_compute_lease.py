#!/usr/bin/env python3
"""Run a CI command with the same per-user compute lease as Foundation inference.

Busy/invalid lease never exits 0. Does not stop or evict another process.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from ai_foundation.host_compute_lease import HostComputeLease, HostComputeBusy, HostComputeLeaseError


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    run = sub.add_parser("run")
    run.add_argument("--max-wait-seconds", type=float, default=120)
    run.add_argument("command", nargs=argparse.REMAINDER)
    job = sub.add_parser("job", help="Hold one lease across every foreground phase")
    job.add_argument("--plan", type=Path, required=True)
    job.add_argument("--max-wait-seconds", type=float, default=120)
    args = p.parse_args(argv)
    if args.mode == "job":
        from ai_foundation.host_compute_job import read_plan, run_job
        return run_job(read_plan(args.plan), max_wait_s=args.max_wait_seconds)
    if args.mode == "run":
        command = args.command[1:] if args.command and args.command[0] == "--" else args.command
        if not command:
            p.error("run needs a command after --")
        try:
            HostComputeLease().exec_under_lock(command, max_wait_s=args.max_wait_seconds)
        except HostComputeBusy:
            print("HOST_COMPUTE_BUSY: defer CI; resource lease is held", file=sys.stderr)
            return 75
        except HostComputeLeaseError as exc:
            print(f"HOST_COMPUTE_LEASE_INVALID: {exc}", file=sys.stderr)
            return 76
    return 0


if __name__ == "__main__":
    sys.exit(main())
