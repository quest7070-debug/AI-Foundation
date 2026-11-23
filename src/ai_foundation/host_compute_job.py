"""Opt-in whole-command job admission using the existing host compute lease.

The supervisor and every foreground phase hold the same OS file description.
No detached guardian, PID-based unlocking, TTL-based stealing or process signals.
This does not install a GitHub runner hook or govern nonparticipating clients.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from .host_compute_lease import HostComputeLease, HostComputeBusy, HostComputeLeaseError


def read_plan(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or set(value) != {"version", "phases"} or value["version"] != 1:
        raise ValueError("INVALID_JOB_PLAN")
    phases = value["phases"]
    if not isinstance(phases, list) or not 1 <= len(phases) <= 64:
        raise ValueError("INVALID_JOB_PHASES")
    names = set()
    for phase in phases:
        if not isinstance(phase, dict) or set(phase) != {"name", "argv"}:
            raise ValueError("INVALID_JOB_PHASE")
        name, argv = phase["name"], phase["argv"]
        if not isinstance(name, str) or not name or name in names or len(name) > 100:
            raise ValueError("INVALID_JOB_PHASE_NAME")
        names.add(name)
        if not isinstance(argv, list) or not argv or any(not isinstance(a, str) or '\0' in a for a in argv) or not argv[0]:
            raise ValueError("INVALID_JOB_ARGV")
    return phases


def run_job(phases, *, lease=None, max_wait_s=0, emit=None):
    """Run trusted foreground commands; no command evaluation or model fallback.

    SIGINT/SIGTERM stop admission of subsequent phases. The current child is
    reaped without signalling it. If this supervisor dies, the child's inherited
    FD retains exclusivity until it exits. Detached/FD-closing descendants are
    outside this contract and must not be used as job phases.
    """
    lease = lease or HostComputeLease()
    emit = emit or (lambda row: print(json.dumps(row, sort_keys=True), flush=True))
    cancelled = []
    def cancel(signum, frame):
        cancelled.append(signum)
    previous = {sig: signal.signal(sig, cancel) for sig in (signal.SIGINT, signal.SIGTERM)}
    def event(kind, **fields):
        emit({"event": kind, "monotonic_s": time.monotonic(), **fields})
    try:
        event("WAITING", max_wait_s=max_wait_s, scope="cooperative_same_uid")
        with lease.hold(max_wait_s=max_wait_s) as fd:
            if cancelled:
                event("CANCELLED_BEFORE_START")
                return 128 + cancelled[0]
            event("ADMITTED", uid=os.getuid(), pid=os.getpid())
            env = dict(os.environ, FOUNDATION_HOST_COMPUTE_LEASE_FD=str(fd),
                       FOUNDATION_HOST_COMPUTE_LEASE_PATH=str(lease.path.absolute()))
            for phase in phases:
                if cancelled:
                    event("CANCELLED", signal=cancelled[0])
                    return 128 + cancelled[0]
                event("PHASE_STARTED", name=phase["name"])
                child = subprocess.Popen(phase["argv"], env=env, pass_fds=(fd,))
                # No automatic retry, no force kill, no detached lease holder.
                result = child.wait()
                event("PHASE_EXITED", name=phase["name"], returncode=result)
                if cancelled:
                    event("CANCELLED", signal=cancelled[0])
                    return 128 + cancelled[0]
                if result:
                    event("FAILED", name=phase["name"])
                    return result if result > 0 else 128 - result
            event("COMPLETE")
            return 0
    except HostComputeBusy:
        event("DEFERRED", reason="HOST_COMPUTE_BUSY")
        return 75
    except HostComputeLeaseError as exc:
        event("INVALID", reason=str(exc))
        return 76
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
