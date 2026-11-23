"""Read-only M1 hardware admission from the existing owner M1 bridge.

No new background probe, model, service, shell arguments or hardware cache.
The only executable commands are the bridge's fixed diagnostics plus a fixed
system_profiler hardware identity read; caller must hold the existing compute
lease throughout planning and isolated execution. Model text is never a source.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import re
from pathlib import Path
import stat
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_foundation.development_host_evidence import hardware_from_bridge
from ai_foundation.host_compute_lease import canonical_lock_path

if __package__:
    from . import m1_development_bridge as bridge
    from . import m1_runtime_status_probe as runtime_probe
else:
    import m1_development_bridge as bridge
    import m1_runtime_status_probe as runtime_probe
CHIP_COMMAND = ("/usr/sbin/system_profiler", "SPHardwareDataType", "-json")


class HardwareEvidenceUnavailable(ValueError):
    pass


def _current_owned_lease(fd, lock_path):
    """Verify an exact current owner-compute lock, not an invented status flag."""
    if type(fd) is not int or fd < 0:
        raise HardwareEvidenceUnavailable("M1_OWNER_LEASE_REQUIRED")
    path = Path(lock_path)
    try:
        if path.is_symlink():
            raise ValueError("symlink")
        actual = path.stat(follow_symlinks=False)
        owned = os.fstat(fd)
        if (not stat.S_ISREG(actual.st_mode)
                or not stat.S_ISREG(owned.st_mode)
                or owned.st_uid != os.getuid()
                or actual.st_uid != os.getuid()
                or owned.st_dev != actual.st_dev
                or owned.st_ino != actual.st_ino
                or actual.st_nlink != 1
                or owned.st_mode & 0o077):
            raise ValueError("untrusted lock identity")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ValueError, BlockingIOError) as exc:
        raise HardwareEvidenceUnavailable("M1_OWNER_LEASE_UNVERIFIED") from exc


def _chip_from_fixed_command(host_bridge):
    raw = host_bridge._fixed_command(list(CHIP_COMMAND))
    if type(raw) is not str or not 0 < len(raw) <= 16384:
        raise HardwareEvidenceUnavailable("M1_CHIP_UNVERIFIED")
    try:
        doc = json.loads(raw)
        rows = doc["SPHardwareDataType"]
        if type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
            raise ValueError("invalid chip receipt")
        chip = rows[0]["chip_type"]
        if type(chip) is not str or re.fullmatch(r"Apple M1(?: Pro| Max| Ultra)?", chip) is None:
            raise ValueError("not Apple M1 family")
        return chip
    except (ValueError, TypeError, KeyError) as exc:
        raise HardwareEvidenceUnavailable("M1_CHIP_UNVERIFIED") from exc


def observe_m1_hardware(*, lease_fd, host_bridge=None,
                        host_runtime=None, lock_path=None, now=None):
    """Produce an independently observed HardwareReceipt under current lease.

    Use only from an installed trusted host producer, with the lease held across
    all rechecks, Drive plan I/O and eventual local executor submission.
    The receipt is not itself an installation or Guard approval.
    """
    host_bridge = bridge if host_bridge is None else host_bridge
    host_runtime = runtime_probe if host_runtime is None else host_runtime
    lock_path = canonical_lock_path() if lock_path is None else lock_path
    _current_owned_lease(lease_fd, lock_path)
    try:
        host_bridge.require_m1()
        stamp = time.time() if now is None else float(now)
        if not math.isfinite(stamp) or stamp <= 0:
            raise ValueError("bad observation time")
        # Reuse existing, finite read-only bridge projections and the single
        # canonical conversion rule, instead of a second memory/lease checker.
        snapshot = host_bridge.snapshot()
        triage = host_bridge.triage()
        chip = _chip_from_fixed_command(host_bridge)
        runtime = host_runtime.runtime_status(now=stamp)
        storage = host_runtime.storage_status(now=stamp)
        receipt = hardware_from_bridge(
            snapshot=snapshot, triage=triage, chip=chip, runtime=runtime,
            storage=storage, observed_at=stamp, now=stamp, owned_lease=True,
        )
        if receipt is None or receipt.competing_work:
            raise HardwareEvidenceUnavailable("M1_HOST_FACTS_UNAVAILABLE")
        return receipt
    except HardwareEvidenceUnavailable:
        raise
    except Exception as exc:
        raise HardwareEvidenceUnavailable("M1_HOST_FACTS_UNAVAILABLE") from exc
