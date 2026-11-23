"""No-model tests for the local9B worker preflight. Never start Ollama."""
import pytest

from ai_foundation.host_compute_lease import HostComputeBusy
from ai_foundation.local9b_worker_admission import require_dedicated_9b_capacity


def test_ci_process_presence_is_not_an_admission_input():
    # There is deliberately no process-list API: Runner.Worker alone cannot
    # veto a model turn. The existing lease protects cooperating CI workloads.
    calls = []
    require_dedicated_9b_capacity(
        lambda: {"models": []}, lambda: calls.append("port"),
        capacity_check=lambda: (True, "AVAILABLE"))
    assert calls == ["port"]


@pytest.mark.parametrize("state", [
    {"models": [{}]}, {"models": ["resident"]},
    {"models": None}, {}, None, {"models": "unknown"},
])
def test_second_backend_never_starts_for_resident_or_unknown_shared_model(state):
    with pytest.raises(HostComputeBusy):
        require_dedicated_9b_capacity(
            lambda: state, lambda: pytest.fail("port probe must not run"),
            capacity_check=lambda: pytest.fail("capacity probe must not run"))


def test_failed_shared_probe_defers_as_busy_not_consumed_issue_failure():
    def unavailable():
        raise TimeoutError("private server details")
    with pytest.raises(HostComputeBusy, match="SHARED_MODEL_STATE_UNKNOWN"):
        require_dedicated_9b_capacity(
            unavailable, lambda: pytest.fail("port probe must not run"))


@pytest.mark.parametrize("allowed,reason,expected", [
    (False, "CPU_PRESSURE", "CPU_PRESSURE"),
    (False, "MEMORY_PRESSURE", "MEMORY_PRESSURE"),
    (False, "RESOURCE_UNKNOWN", "RESOURCE_UNKNOWN"),
    (False, "UNRECOGNIZED", "RESOURCE_UNKNOWN"),
])
def test_capacity_pressure_defers_before_backend_reservation(allowed, reason, expected):
    with pytest.raises(HostComputeBusy, match=expected):
        require_dedicated_9b_capacity(
            lambda: {"models": []}, lambda: pytest.fail("port probe must not run"),
            capacity_check=lambda: (allowed, reason))


def test_explicit_false_port_probe_defers_without_starting_backend():
    with pytest.raises(HostComputeBusy, match="LOCAL_BACKEND_PORT_OCCUPIED"):
        require_dedicated_9b_capacity(
            lambda: {"models": []}, lambda: False,
            capacity_check=lambda: (True, "AVAILABLE"))


def test_admission_probe_error_stays_busy_and_port_busy_propagates():
    with pytest.raises(HostComputeBusy, match="RESOURCE_UNKNOWN"):
        require_dedicated_9b_capacity(
            lambda: {"models": []}, lambda: None,
            capacity_check=lambda: (_ for _ in ()).throw(RuntimeError("probe down")))
    with pytest.raises(HostComputeBusy, match="LOCAL_BACKEND_PORT_OCCUPIED"):
        require_dedicated_9b_capacity(
            lambda: {"models": []},
            lambda: (_ for _ in ()).throw(HostComputeBusy("LOCAL_BACKEND_PORT_OCCUPIED")),
            capacity_check=lambda: (True, "AVAILABLE"))


@pytest.mark.parametrize("probe_error", [
    OSError("unavailable"), TimeoutError("port probe timeout"),
    ValueError("unexpected response"),
])
def test_unknown_dedicated_port_probe_defers_without_consuming_issue(probe_error):
    with pytest.raises(HostComputeBusy, match="RESOURCE_UNKNOWN"):
        require_dedicated_9b_capacity(
            lambda: {"models": []},
            lambda: (_ for _ in ()).throw(probe_error),
            capacity_check=lambda: (True, "AVAILABLE"))
