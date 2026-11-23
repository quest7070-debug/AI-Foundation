"""Derive admission receipts from existing bounded M1 observations and fixed tests.

This module does not invoke new arbitrary shell commands, change services,
discover credentials, select code/test targets, or treat LLM claims as facts.
Host must supply the trusted existing M1 Bridge read-only projections and a
fixed benchmark port. Stale/partial data fails closed; runtime lease ownership
is a *separate* prerequisite for actual execution.
"""
from __future__ import annotations

from hashlib import sha256
import json
import math
from statistics import median
import re
import time

from .development_admission import BenefitReceipt, HardwareReceipt

GIB = 1024 ** 3
M1 = re.compile(r"Apple M1(?: Pro| Max| Ultra)?\Z")
METRIC = re.compile(r"[a-z][a-z0-9_]{1,63}\Z")


def _valid_gib(value):
    return (type(value) in (int, float) and math.isfinite(value)
            and 0 <= value <= 1024)


def _digest_proof(kind, record):
    # The hash is a correlation reference, not a signature/authorization.
    blob = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    return "m1:" + kind + "-" + sha256(blob).hexdigest()


def hardware_from_bridge(*, snapshot, triage, runtime, storage, chip, observed_at,
                         max_age_s=30, now=None, owned_lease=False):
    """Translate trusted, same-host read-only probes to an M1 hardware receipt.

    Only available state is accepted, not an advertised/recommended spec.
    The conservative half of the reclaimable estimate is NOT a guarantee of
    future resources: caller must also acquire existing HostComputeLease and
    recheck immediately before a write or model turn.
    """
    now = time.time() if now is None else now
    if (any(type(x) is not dict for x in (snapshot, triage, runtime, storage))
            or type(observed_at) not in (int, float)
            or not math.isfinite(observed_at) or now - observed_at < 0
            or now - observed_at > max_age_s or
            snapshot.get("platform") != "macOS/arm64" or
            type(chip) is not str or not M1.fullmatch(chip)):
        return None
    memory = triage.get("memory")
    fs = storage.get("filesystems")
    lease = runtime.get("compute_lease")
    dev = runtime.get("autodev")
    if (type(memory) is not dict or type(fs) is not dict or
            type(lease) is not dict or type(dev) is not dict or
            type(fs.get("installed_worker")) is not dict or
            type(fs.get("system")) is not dict):
        return None
    physical, reclaimable = memory.get("physical_gib"), memory.get("reclaimable_estimate_gib")
    disk_worker = fs["installed_worker"].get("available_gib")
    disk_system = fs["system"].get("available_gib")
    if (not all(_valid_gib(x) for x in
                (physical, reclaimable, disk_worker, disk_system)) or
            physical <= 0 or reclaimable > physical or
            fs["installed_worker"].get("state") != "OBSERVED" or
            fs["system"].get("state") != "OBSERVED" or
            # macOS sealed system volume is intentionally read-only. Only
            # the actual owner worker target must be writable for a trial.
            fs["installed_worker"].get("read_only") is True or
            runtime.get("state") != "OBSERVED" and
            runtime.get("state") is not None):
        return None
    # A coordinator-owned runner is not admissible from another process.
    # If there is no definitive idle snapshot we set competing_work=True.
    # The caller may request the owner-held variant only from inside the
    # established HostComputeLease.hold() context (never model supplied).
    # A read-only probe sees EXCLUSIVE_HELD even for this very same owner.
    idle = (lease.get("state") == "AVAILABLE_AT_PROBE"
            and dev.get("state") == "SCHEDULED_IDLE"
            and dev.get("uncompleted_start_count") == 0
            and dev.get("claim_without_start_or_result_count") == 0)
    owner = (owned_lease is True and
             lease.get("state") == "EXCLUSIVE_HELD_AT_PROBE" and
             dev.get("state") in ("SCHEDULED_IDLE", "RUNNING"))
    free = idle or owner
    record = {
        "observed_at": observed_at, "chip": chip,
        "ram_reclaimable_gib": reclaimable, "ram_physical_gib": physical,
        "disk_worker_gib": disk_worker, "disk_system_gib": disk_system,
        "lease": lease.get("state"), "autodev": dev.get("state"),
        "uncompleted": dev.get("uncompleted_start_count"),
        "claimed": dev.get("claim_without_start_or_result_count"),
    }
    return HardwareReceipt(
        checked_at=observed_at,
        proof=_digest_proof("hardware", record),
        os_name="macOS", arch="arm64", device=chip,
        available_ram_bytes=int(min(reclaimable, physical) * GIB * 0.5),
        free_disk_bytes=int(min(disk_worker, disk_system) * GIB),
        competing_work=not free,
    )


def measured_benefit_from_fixed_port(candidate_id, *, port, clock=time.time):
    """Host-selected immutable benchmark. It may not accept model commands.

    port.observe_pair(candidate_id, index) returns independent baseline and
    candidate numeric observations for the same fixed test, plus port.metric,
    port.direction and host-pinned port.test_sha256.
    The caller must already have a verified free/isolated benchmark contract.
    """
    if (type(candidate_id) is not str or
            re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", candidate_id) is None or
            type(getattr(port, "metric", None)) is not str or
            METRIC.fullmatch(port.metric) is None or
            getattr(port, "direction", None) not in ("higher", "lower") or
            type(getattr(port, "test_sha256", None)) is not str or
            re.fullmatch(r"[a-f0-9]{64}", port.test_sha256) is None):
        return None
    pairs = []
    for i in range(5):
        pair = port.observe_pair(candidate_id, i)
        if (type(pair) not in (tuple, list) or len(pair) != 2 or
                any(type(v) not in (int, float) or not math.isfinite(v)
                    or not 0 < v < 1e12 for v in pair)):
            return None
        pairs.append((float(pair[0]), float(pair[1])))
    base = median(x[0] for x in pairs)
    trial = median(x[1] for x in pairs)
    # Reject very noisy timings/scores. Protect against a lucky single trial.
    for column, med in (([x[0] for x in pairs], base),
                        ([x[1] for x in pairs], trial)):
        if max(abs(v - med) / med for v in column) > 0.20:
            return None
    now = clock()
    record = {"candidate": candidate_id, "metric": port.metric,
              "direction": port.direction, "test": port.test_sha256,
              "samples": pairs, "observed_at": now}
    return BenefitReceipt(
        checked_at=now,
        proof=_digest_proof("fixed-benchmark", record),
        metric=port.metric, baseline=base, observed=trial,
        direction=port.direction, independently_measured=True,
    )


def submit_with_existing_lease(lease, candidate_id, *, contract, verifiers,
                               drive, guard, executor, now=None):
    """Retain an existing HostComputeLease across final plan/Guard/submit.

    This guards the pending model/isolated work from another cooperating
    Foundation worker; caller still owns durable effect/replay reconciliation.
    """
    from .development_admission import plan_and_submit
    from .host_compute_lease import HostComputeBusy
    try:
        with lease.hold(max_wait_s=0):
            return plan_and_submit(
                candidate_id, contract=contract, verifiers=verifiers, drive=drive,
                guard=guard, executor=executor, now=now)
    except HostComputeBusy:
        return {"status": "DEFERRED", "reason": "HOST_COMPUTE_LEASE_BUSY"}
