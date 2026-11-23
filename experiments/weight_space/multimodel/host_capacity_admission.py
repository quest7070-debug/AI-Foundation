#!/usr/bin/env python3
"""Fail-closed macOS unified-memory admission for local Ollama experiments.

Source-only decision support. Never starts/evicts a model, kills a process,
changes Ollama settings, nor interprets macOS memory_pressure's free percentage
as physical free RAM. Inactive pages are a RECLAIMABLE UPPER BOUND, not promised
free memory; require all of them plus free/speculative to exceed model+reserve.
"""
from __future__ import annotations
from dataclasses import dataclass
import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib import request

GIB = 1024**3
MIB = 1024**2
WINDOW_S = 3
RESERVE_BYTES = 2 * GIB
CONTEXT_AND_RUNTIME_BYTES = 1 * GIB
MAX_IDLE_SWAPOUT_MIB = 2
MODEL_REGISTRY = Path(__file__).resolve().parent / "registered_models.json"


class SnapshotError(ValueError):
    pass


@dataclass(frozen=True)
class MemorySnapshot:
    physical_bytes: int
    page_bytes: int
    free_pages: int
    inactive_pages: int
    speculative_pages: int
    swapouts_pages: int

    @property
    def optimistic_reclaimable_upper_bytes(self) -> int:
        # All inactive pages are *optimistically* treated as reclaimable.
        # This is only an upper bound: nothing below it is guaranteed available.
        return self.page_bytes * (
            self.free_pages + self.inactive_pages + self.speculative_pages
        )


def parse_vm_stat(data: str, physical_bytes: int) -> MemorySnapshot:
    if type(physical_bytes) is not int or physical_bytes <= 0:
        raise SnapshotError("PHYSICAL_MEMORY_UNVERIFIED")
    m = re.search(r"page size of\s+(\d+)\s+bytes", data)
    if not m:
        raise SnapshotError("PAGE_SIZE_UNVERIFIED")
    page_bytes = int(m.group(1))
    if page_bytes not in (4096, 16384):
        raise SnapshotError("UNEXPECTED_PAGE_SIZE")
    fields = {}
    required = {
        "Pages free": "free_pages",
        "Pages inactive": "inactive_pages",
        "Pages speculative": "speculative_pages",
        "Swapouts": "swapouts_pages",
    }
    for line in data.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        if key not in required:
            continue
        if required[key] in fields:
            raise SnapshotError("DUPLICATE_VM_STAT_FIELD")
        token = value.strip().rstrip(".")
        if not token.isdigit():
            raise SnapshotError("INVALID_VM_STAT_INTEGER")
        fields[required[key]] = int(token)
    if set(fields) != set(required.values()):
        raise SnapshotError("MISSING_VM_STAT_FIELDS")
    if (fields["free_pages"] + fields["inactive_pages"] +
            fields["speculative_pages"]) * page_bytes > physical_bytes:
        raise SnapshotError("VM_STAT_EXCEEDS_PHYSICAL_MEMORY")
    return MemorySnapshot(physical_bytes, page_bytes, **fields)


def read_registered_model_bytes(name: str, path: Path = MODEL_REGISTRY) -> int:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != "weight-space-existing-model-registry/v1":
        raise SnapshotError("UNKNOWN_MODEL_REGISTRY")
    matches = [m for m in data.get("registered_models", [])
               if m.get("model") == name]
    if len(matches) != 1:
        raise SnapshotError("MODEL_NOT_PINNED_UNIQUELY")
    value = matches[0].get("bytes")
    digest = matches[0].get("digest")
    if type(value) is not int or value <= 0 or not isinstance(digest, str) or len(digest) != 64:
        raise SnapshotError("MODEL_SIZE_OR_DIGEST_NOT_PINNED")
    return value


def assess(before: MemorySnapshot, after: MemorySnapshot, model_bytes: int,
           *, ci_active: bool, other_inference_active: bool,
           endpoints_verified: bool = True,
           reserve_bytes: int = RESERVE_BYTES,
           runtime_overhead_bytes: int = CONTEXT_AND_RUNTIME_BYTES) -> dict:
    if (before.page_bytes != after.page_bytes or
            before.physical_bytes != after.physical_bytes):
        raise SnapshotError("MEMORY_SNAPSHOT_SOURCE_DRIFT")
    if type(model_bytes) is not int or model_bytes <= 0:
        raise SnapshotError("INVALID_MODEL_SIZE")
    if reserve_bytes < 0 or runtime_overhead_bytes < 0:
        raise SnapshotError("INVALID_RESERVE")
    delta = after.swapouts_pages - before.swapouts_pages
    need = model_bytes + reserve_bytes + runtime_overhead_bytes
    optimistic = after.optimistic_reclaimable_upper_bytes
    if not endpoints_verified:
        reason = "INFERENCE_ENDPOINT_STATE_UNVERIFIED"
    elif ci_active:
        reason = "OTHER_CI_RUNNING"
    elif other_inference_active:
        reason = "OTHER_LOCAL_MODEL_RESIDENT_OR_LOADING"
    elif delta < 0:
        reason = "SWAP_COUNTER_RESET"
    elif delta * after.page_bytes > MAX_IDLE_SWAPOUT_MIB * MIB:
        reason = "ACTIVE_SWAP_WRITES"
    elif optimistic < need:
        reason = "INSUFFICIENT_RECLAIMABLE_UPPER_BOUND"
    else:
        reason = None
    return {
        "status": "DEFER" if reason else "CONSERVATIVE_PRECHECK_PASS",
        "reason": reason,
        "physical_bytes": after.physical_bytes,
        "model_registered_bytes": model_bytes,
        "reserved_system_bytes": reserve_bytes,
        "runtime_overhead_bytes": runtime_overhead_bytes,
        "required_optimistic_available_bytes": need,
        "optimistic_reclaimable_upper_bytes": optimistic,
        "actual_unallocated_bytes": after.free_pages * after.page_bytes,
        "swapouts_delta_pages": delta,
        "swapouts_delta_bytes": delta * after.page_bytes,
        "other_ci_active": bool(ci_active),
        "other_model_active": bool(other_inference_active),
        "endpoints_verified": bool(endpoints_verified),
        "warning": "PASS does not reserve RAM or guarantee an inference. Reject unsafe coexistence; never evict other clients or silently downgrade required model roles.",
        "model_calls": 0,
    }


def _snapshot() -> MemorySnapshot:
    physical = int(subprocess.check_output(
        ["sysctl", "-n", "hw.memsize"], text=True, timeout=5).strip())
    raw = subprocess.check_output(["vm_stat"], text=True, timeout=5)
    return parse_vm_stat(raw, physical)


def _api(path: str):
    with request.urlopen("http://127.0.0.1:11434" + path, timeout=2) as resp:
        data = resp.read(262145)
    if len(data) > 262144:
        raise SnapshotError("OLLAMA_REPLY_TOO_LARGE")
    return json.loads(data)


def _swap_status():
    with request.urlopen("http://127.0.0.1:9292/v1/models", timeout=2) as resp:
        data = resp.read(262145)
    if len(data) > 262144:
        raise SnapshotError("SWAP_REPLY_TOO_LARGE")
    models = json.loads(data).get("data")
    if not isinstance(models, list):
        raise SnapshotError("SWAP_STATES_UNVERIFIED")
    states = []
    for item in models:
        if type(item) is not dict or type(item.get("status")) is not dict:
            raise SnapshotError("SWAP_MODEL_STATE_MISSING")
        state = item["status"].get("value")
        if not isinstance(state, str):
            raise SnapshotError("SWAP_MODEL_STATE_UNKNOWN")
        states.append(state.lower())
    return states


def classify_ci_processes(data: str, *, pid: int, ppid: int, uid: int) -> dict:
    """Exclude only the nearest same-UID worker in this probe's ancestry.

    A job's own Runner.Worker is not competing CI. All other workers remain
    blockers. Missing ancestry, cross-UID parents and cycles grant no exclusion;
    malformed snapshots fail closed. No environment variable grants ownership.
    This identifies an observer's parent, not a lease or global host authority.
    """
    rows = {}
    for line in data.splitlines():
        if not line.strip():
            continue
        fields = line.strip().split(None, 3)
        if len(fields) != 4 or any(not x.isdigit() for x in fields[:3]):
            raise SnapshotError("PROCESS_INVENTORY_INVALID")
        proc_pid, parent, owner = map(int, fields[:3])
        if proc_pid <= 0 or proc_pid in rows:
            raise SnapshotError("PROCESS_INVENTORY_INVALID")
        rows[proc_pid] = (parent, owner, Path(fields[3]).name)
    if (any(type(x) is not int or x < 0 for x in (pid, ppid, uid)) or
            pid not in rows or rows[pid][:2] != (ppid, uid)):
        raise SnapshotError("PROBE_PROCESS_IDENTITY_UNVERIFIED")
    workers = {p for p, (_, _, name) in rows.items() if name == "Runner.Worker"}
    own_worker = None
    seen = {pid}
    parent = ppid
    while parent and parent not in seen:
        seen.add(parent)
        row = rows.get(parent)
        if row is None or row[1] != uid:
            break
        if row[2] == "Runner.Worker":
            own_worker = parent
            break
        parent = row[0]
    competing = sorted(workers - ({own_worker} if own_worker is not None else set()))
    return {"other_ci_active": bool(competing),
            "owned_ancestor_worker_pid": own_worker,
            "competing_worker_pids": competing,
            "process_names": [row[2] for row in rows.values()]}


def probe(name: str, *, sample_window_s: int = WINDOW_S):
    """Read-only host probe; no HTTP POST, no change to model residency."""
    size = read_registered_model_bytes(name)
    first = _snapshot()
    time.sleep(sample_window_s)
    second = _snapshot()
    proc = subprocess.check_output(
        ["ps", "-axo", "pid=,ppid=,uid=,comm="], text=True, timeout=5)
    processes = classify_ci_processes(proc, pid=os.getpid(), ppid=os.getppid(),
                                     uid=os.getuid())
    parts = processes["process_names"]
    ci = processes["other_ci_active"]
    # All local model runtimes count, including any not attached to /api/ps.
    active_process = any(x in ("llama-server", "llama-cli") for x in parts)
    verified = True
    loaded = False
    try:
        ollama = _api("/api/ps")
        if not isinstance(ollama, dict) or not isinstance(ollama.get("models"), list):
            raise SnapshotError("OLLAMA_PS_INVALID")
        loaded = bool(ollama["models"])
        swap = _swap_status()
        swap_busy = any(x not in ("unloaded", "failed", "error", "disabled") for x in swap)
    except (OSError, ValueError, KeyError, TypeError):
        verified = False
        swap_busy = True
    result = assess(first, second, size, ci_active=ci,
                    other_inference_active=active_process or loaded or swap_busy,
                    endpoints_verified=verified)
    result["owned_ancestor_worker_pid"] = processes["owned_ancestor_worker_pid"]
    result["competing_worker_pids"] = processes["competing_worker_pids"]
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True, choices=("qwen3.5:2b", "qwen3.5:9b", "qwen3:4b"))
    args = p.parse_args()
    result = probe(args.model)
    print(json.dumps({"model": args.model, **result}, ensure_ascii=False, sort_keys=True))
    # A deferred model is not a test failure; automation may inspect status.
    # This executable only diagnoses and NEVER starts a model.


if __name__ == "__main__":
    main()

