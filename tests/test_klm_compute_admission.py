"""Synthetic KLM admission tests; no model, host process or private data."""
from types import SimpleNamespace
from unittest.mock import patch

from ai_foundation.klm_compute_admission import (
    AVAILABLE, CPU_PRESSURE, MEMORY_PRESSURE, RESOURCE_UNKNOWN,
    admit_local_9b, reclaimable_bytes,
)


VM_OK = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free: 290000.
Pages active: 250000.
Pages inactive: 100000.
Pages speculative: 10000.
Pages purgeable: 20000.
"""


def run_vm(raw=VM_OK, *, returncode=0):
    return SimpleNamespace(returncode=returncode, stdout=raw)


def test_mac_vm_reclaimable_pages_not_double_counting_purgeable():
    assert reclaimable_bytes(VM_OK) == 16384 * (290000 + 100000 + 10000)


def test_running_runner_or_loaded_model_does_not_block_idle_host():
    # The predicate never enumerates process identities, asks Ollama for
    # loaded models or guesses their activity from residency.
    with patch("ai_foundation.klm_compute_admission.os.cpu_count", return_value=8), \
         patch("ai_foundation.klm_compute_admission.os.getloadavg", return_value=(2., 5., 5.)), \
         patch("ai_foundation.klm_compute_admission.subprocess.run", return_value=run_vm()) as vm:
        assert admit_local_9b() == (True, AVAILABLE)
    vm.assert_called_once()
    assert vm.call_args.args[0] == ["/usr/bin/vm_stat"]
    assert vm.call_args.kwargs["timeout"] == 3


def test_sustained_cpu_pressure_defers_before_spawning_a_vm_probe():
    with patch("ai_foundation.klm_compute_admission.os.cpu_count", return_value=8), \
         patch("ai_foundation.klm_compute_admission.os.getloadavg", return_value=(7.1, 2., 2.)), \
         patch("ai_foundation.klm_compute_admission.subprocess.run") as vm:
        assert admit_local_9b() == (False, CPU_PRESSURE)
        vm.assert_not_called()


def test_insufficient_reclaimable_memory_defers():
    low = VM_OK.replace("290000", "1000").replace("100000", "1000").replace("10000", "1000")
    with patch("ai_foundation.klm_compute_admission.os.cpu_count", return_value=8), \
         patch("ai_foundation.klm_compute_admission.os.getloadavg", return_value=(1., 1., 1.)), \
         patch("ai_foundation.klm_compute_admission.subprocess.run", return_value=run_vm(low)):
        assert admit_local_9b() == (False, MEMORY_PRESSURE)


def test_unknown_vm_output_or_failed_probe_stays_closed():
    with patch("ai_foundation.klm_compute_admission.os.cpu_count", return_value=8), \
         patch("ai_foundation.klm_compute_admission.os.getloadavg", return_value=(1., 1., 1.)):
        for observed in (run_vm("invalid"), run_vm(VM_OK, returncode=1)):
            with patch("ai_foundation.klm_compute_admission.subprocess.run", return_value=observed):
                assert admit_local_9b() == (False, RESOURCE_UNKNOWN)


def test_invalid_cpu_observation_stays_closed():
    with patch("ai_foundation.klm_compute_admission.os.cpu_count", return_value=None), \
         patch("ai_foundation.klm_compute_admission.subprocess.run") as vm:
        assert admit_local_9b() == (False, RESOURCE_UNKNOWN)
        vm.assert_not_called()


def test_vm_missing_required_count_and_duplicate_are_unavailable():
    assert reclaimable_bytes(VM_OK.replace("Pages inactive:", "Other:")) is None
    assert reclaimable_bytes(VM_OK + "Pages free: 10.\n") is None
    assert reclaimable_bytes(VM_OK.replace("16384", "9000")) is None


def test_real_timeout_does_not_convert_failure_into_idle():
    import subprocess
    with patch("ai_foundation.klm_compute_admission.os.cpu_count", return_value=8), \
         patch("ai_foundation.klm_compute_admission.os.getloadavg", return_value=(1., 1., 1.)), \
         patch("ai_foundation.klm_compute_admission.subprocess.run", side_effect=subprocess.TimeoutExpired("vm_stat", 3)):
        assert admit_local_9b() == (False, RESOURCE_UNKNOWN)
