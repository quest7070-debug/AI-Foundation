"""Admission heuristic for KLM's *already leased* local 9B compute window.

The shared HostComputeLease and fresh development-priority observation remain
the authority for Foundation-owned work. Here we reject sustained CPU pressure
or insufficient reclaimable RAM, rather than treating a GitHub runner or an
Ollama-loaded model as proof of active inference.

This is deliberately not a GPU activity detector or permission grant. External
Ollama clients that do not honor HostComputeLease cannot be proven idle here.
"""
from __future__ import annotations

import os
import re
import subprocess

# Local M1 9B needs a practical memory headroom; not a promise of sufficient VRAM.
MIN_RECLAIMABLE_BYTES = 4 * 1024**3
MAX_LOAD_PER_LOGICAL_CPU = 0.85

# Expose reason CODES only, no process names, paths, private data or model names.
AVAILABLE = "AVAILABLE"
CPU_PRESSURE = "CPU_PRESSURE"
MEMORY_PRESSURE = "MEMORY_PRESSURE"
RESOURCE_UNKNOWN = "RESOURCE_UNKNOWN"


def reclaimable_bytes(raw: str) -> int | None:
    """macOS vm_stat's free/inactive/speculative pages, conservatively counted.

    Do not double-count purgeable pages, which can overlap with inactive pages.
    Invalid/unknown metrics must never be interpreted as zero *usage*.
    """
    if type(raw) is not str or len(raw) > 131072:
        return None
    size = re.search(r"page size of ([0-9]+) bytes", raw)
    if size is None:
        return None
    page_size = int(size.group(1))
    if page_size not in (4096, 16384):
        return None
    counts = {}
    for label, value in re.findall(
            r"^Pages (free|inactive|speculative):\s*([0-9]+)\.\s*$",
            raw, flags=re.M):
        if label in counts:
            return None
        counts[label] = int(value)
    if not {"free", "inactive", "speculative"} <= counts.keys():
        return None
    return page_size * sum(counts.values())


def admit_local_9b() -> tuple[bool, str]:
    """Bounded low-cost CPU/RAM admission; never claims another model is idle.

    Called only after the existing lease has been acquired, on real candidate
    work. One-minute load is a *pressure hint*, not proof of no active GPU work.
    """
    try:
        cpus = os.cpu_count()
        load = os.getloadavg()[0]
        if (type(cpus) is not int or cpus < 1
                or not isinstance(load, (int, float))
                or not (0 <= load < 100000)):
            return False, RESOURCE_UNKNOWN
        if load >= cpus * MAX_LOAD_PER_LOGICAL_CPU:
            return False, CPU_PRESSURE
        vm = subprocess.run(
            ["/usr/bin/vm_stat"], capture_output=True, text=True, timeout=3)
        if vm.returncode != 0:
            return False, RESOURCE_UNKNOWN
        available = reclaimable_bytes(vm.stdout)
        if available is None:
            return False, RESOURCE_UNKNOWN
        if available < MIN_RECLAIMABLE_BYTES:
            return False, MEMORY_PRESSURE
        return True, AVAILABLE
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired):
        return False, RESOURCE_UNKNOWN
