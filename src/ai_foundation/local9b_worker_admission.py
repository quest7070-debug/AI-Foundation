"""Capacity admission for the existing dedicated local9B development worker.

Call ONLY while holding HostComputeLease. A GitHub Runner.Worker or sleeping
llama process is not proof of resource contention. Unlike the KLM worker,
this worker starts a *second* Ollama backend at 11436: a loaded model on the
shared 11434 backend remains a genuine duplicate-residency risk on a 16GiB M1.
No model is started/evicted by this gate. Uncertain probes defer without
consuming the one-shot Issue claim.
"""
from __future__ import annotations

from .host_compute_lease import HostComputeBusy
from .klm_compute_admission import AVAILABLE, RESOURCE_UNKNOWN, admit_local_9b

ADMISSION_REASONS = frozenset({
    "CPU_PRESSURE", "MEMORY_PRESSURE", "RESOURCE_UNKNOWN",
})


def require_dedicated_9b_capacity(read_shared_ps, check_dedicated_port, *,
                                  capacity_check=None):
    """Reject actual capacity/duplicate-backend hazards, not process presence.

    The caller retains the single shared compute lease for the full model turn.
    read_shared_ps uses the already-running shared Ollama /api/ps, not a load.
    check_dedicated_port must refuse an occupied backend without killing it.
    """
    try:
        state = read_shared_ps()
    except Exception:
        raise HostComputeBusy("SHARED_MODEL_STATE_UNKNOWN") from None
    if type(state) is not dict or type(state.get("models")) is not list:
        raise HostComputeBusy("SHARED_MODEL_STATE_UNKNOWN")
    if state["models"]:
        raise HostComputeBusy("SHARED_MODEL_RESIDENT")
    try:
        allowed, reason = (capacity_check or admit_local_9b)()
    except Exception:
        raise HostComputeBusy(RESOURCE_UNKNOWN) from None
    if allowed is not True or reason != AVAILABLE:
        raise HostComputeBusy(reason if type(reason) is str and reason in ADMISSION_REASONS else RESOURCE_UNKNOWN)
    try:
        port_result = check_dedicated_port()
        # Existing probes signal an occupied port by raising HostComputeBusy.
        # Also fail closed if a future probe explicitly returns False.
        if port_result is False:
            raise HostComputeBusy("LOCAL_BACKEND_PORT_OCCUPIED")
    except HostComputeBusy:
        # A confirmed occupied port remains a deferral, not a consumed attempt.
        raise
    except Exception:
        # A probe failure does not prove the port is free. Avoid consuming
        # the once-only Issue claim before any model has started.
        raise HostComputeBusy(RESOURCE_UNKNOWN) from None
