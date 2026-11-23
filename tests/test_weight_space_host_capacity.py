"""Offline macOS admission regression. Uses synthetic vm_stat data only."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).parents[1]/"experiments"/"weight_space"/"multimodel"
sys.path.insert(0,str(ROOT))
from host_capacity_admission import (
    GIB,MemorySnapshot,SnapshotError,assess,parse_vm_stat,
    read_registered_model_bytes,probe,classify_ci_processes
)
PHYSICAL=16*GIB
SOURCE="""Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                                   7576.
Pages active:                                 397844.
Pages inactive:                               396793.
Pages speculative:                            451.
Pages wired down:                             109266.
Pages occupied by compressor:                 100965.
Swapins:                                      843474.
Swapouts:                                     1681731.
"""


class ParseTests(unittest.TestCase):
    def test_exact_16g_m1_parsed(self):
        snap=parse_vm_stat(SOURCE,PHYSICAL)
        self.assertEqual(snap.page_bytes,16384)
        self.assertEqual(snap.free_pages,7576)
        self.assertEqual(snap.swapouts_pages,1681731)
        self.assertLess(snap.optimistic_reclaimable_upper_bytes,7*GIB)
        self.assertLess(snap.free_pages*snap.page_bytes,150*1024**2)

    def test_missing_fields_fail_closed(self):
        with self.assertRaises(SnapshotError):
            parse_vm_stat(SOURCE.replace("Pages speculative:", "Pages unknown:"),PHYSICAL)

    def test_duplicate_fields_fail_closed(self):
        with self.assertRaises(SnapshotError):
            parse_vm_stat(SOURCE+"Pages free: 10.\n",PHYSICAL)

    def test_invalid_page_size(self):
        with self.assertRaises(SnapshotError):
            parse_vm_stat(SOURCE.replace("16384 bytes","7 bytes"),PHYSICAL)

    def test_impossible_free_inactive_sum(self):
        with self.assertRaises(SnapshotError):
            parse_vm_stat(SOURCE.replace("396793","99999999"),PHYSICAL)

    def test_registered_model_digest_size_pinned(self):
        self.assertEqual(read_registered_model_bytes("qwen3.5:9b"),6550825550)
        self.assertEqual(read_registered_model_bytes("qwen3.5:2b"),2741192820)

    def test_unknown_model_not_admitted(self):
        with self.assertRaises(SnapshotError):
            read_registered_model_bytes("qwen3.5:900b")


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        self.start=parse_vm_stat(SOURCE,PHYSICAL)
        self.end=self.start
        self.nine=read_registered_model_bytes("qwen3.5:9b")

    def test_9b_denied_with_79_percent_pressure_label(self):
        # memory_pressure once claimed 79%; it is not used by admission.
        result=assess(self.start,self.end,self.nine,
                      ci_active=False,other_inference_active=False)
        self.assertEqual(result["status"],"DEFER")
        self.assertEqual(result["reason"],"INSUFFICIENT_RECLAIMABLE_UPPER_BOUND")
        self.assertLess(result["actual_unallocated_bytes"],150*1024**2)
        self.assertGreater(result["required_optimistic_available_bytes"],9*GIB)
        self.assertEqual(result["model_calls"],0)

    def test_ample_host_passes_only_precheck(self):
        snap=MemorySnapshot(PHYSICAL,16384,free_pages=350000,
                            inactive_pages=350000,speculative_pages=8000,swapouts_pages=0)
        d=assess(snap,snap,self.nine,ci_active=False,other_inference_active=False)
        self.assertEqual(d["status"],"CONSERVATIVE_PRECHECK_PASS")
        self.assertIn("does not reserve RAM",d["warning"])

    def test_ci_has_priority(self):
        d=assess(self.start,self.end,self.nine,ci_active=True,other_inference_active=False)
        self.assertEqual(d["reason"],"OTHER_CI_RUNNING")

    def test_coexisting_local_model_denied(self):
        d=assess(self.start,self.end,self.nine,ci_active=False,other_inference_active=True)
        self.assertEqual(d["reason"],"OTHER_LOCAL_MODEL_RESIDENT_OR_LOADING")

    def test_unverified_endpoints_denied(self):
        d=assess(self.start,self.end,self.nine,ci_active=False,other_inference_active=False,
                 endpoints_verified=False)
        self.assertEqual(d["reason"],"INFERENCE_ENDPOINT_STATE_UNVERIFIED")

    def test_active_swap_denied(self):
        after=MemorySnapshot(PHYSICAL,16384,free_pages=350000,inactive_pages=350000,
                             speculative_pages=8000,swapouts_pages=2000)
        before=MemorySnapshot(PHYSICAL,16384,free_pages=350000,inactive_pages=350000,
                              speculative_pages=8000,swapouts_pages=0)
        d=assess(before,after,self.nine,ci_active=False,other_inference_active=False)
        self.assertEqual(d["reason"],"ACTIVE_SWAP_WRITES")

    def test_counter_reset_denied(self):
        after=MemorySnapshot(PHYSICAL,16384,free_pages=350000,inactive_pages=350000,
                             speculative_pages=8000,swapouts_pages=0)
        before=MemorySnapshot(PHYSICAL,16384,free_pages=350000,inactive_pages=350000,
                              speculative_pages=8000,swapouts_pages=2000)
        d=assess(before,after,self.nine,ci_active=False,other_inference_active=False)
        self.assertEqual(d["reason"],"SWAP_COUNTER_RESET")


class ProcessOwnershipTests(unittest.TestCase):
    OWN = "10 9 501 python3\n9 8 501 bash\n8 1 501 /runner/bin/Runner.Worker\n"

    def classify(self, text):
        return classify_ci_processes(text, pid=10, ppid=9, uid=501)

    def test_only_same_uid_ancestor_is_excluded(self):
        result = self.classify(self.OWN)
        self.assertFalse(result["other_ci_active"])
        self.assertEqual(result["owned_ancestor_worker_pid"], 8)
        self.assertEqual(result["competing_worker_pids"], [])

    def test_sibling_child_and_foreign_uid_workers_still_block(self):
        for extra in ("20 1 501 /other/Runner.Worker\n",
                      "20 10 501 /child/Runner.Worker\n",
                      "20 1 502 /other/Runner.Worker\n"):
            with self.subTest(extra=extra):
                result = self.classify(self.OWN + extra)
                self.assertTrue(result["other_ci_active"])
                self.assertEqual(result["competing_worker_pids"], [20])

    def test_cross_uid_ancestry_is_not_owned(self):
        result = self.classify(self.OWN.replace("9 8 501", "9 8 502"))
        self.assertIsNone(result["owned_ancestor_worker_pid"])
        self.assertEqual(result["competing_worker_pids"], [8])

    def test_missing_or_cyclic_ancestry_grants_no_exclusion(self):
        for text in (self.OWN.replace("9 8 501 bash\n", ""),
                     self.OWN.replace("9 8 501", "9 10 501")):
            with self.subTest(text=text):
                result = self.classify(text)
                self.assertIsNone(result["owned_ancestor_worker_pid"])
                self.assertEqual(result["competing_worker_pids"], [8])

    def test_only_nearest_worker_excluded(self):
        result = self.classify(self.OWN.replace("8 1 501", "8 7 501") +
                               "7 1 501 Runner.Worker\n")
        self.assertEqual(result["owned_ancestor_worker_pid"], 8)
        self.assertEqual(result["competing_worker_pids"], [7])

    def test_probe_pid_uid_and_parent_are_bound_to_os_identity(self):
        for text in ("", self.OWN.replace("10 9 501", "10 7 501"),
                     self.OWN.replace("10 9 501", "10 9 502")):
            with self.subTest(text=text), self.assertRaises(SnapshotError):
                self.classify(text)

    def test_malformed_or_duplicate_inventory_fails_closed(self):
        for suffix in ("oops\n", "8 1 501 duplicate\n", "0 1 501 bad\n"):
            with self.subTest(suffix=suffix), self.assertRaises(SnapshotError):
                self.classify(self.OWN + suffix)

    def test_environment_variables_cannot_exclude_other_worker(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true", "GITHUB_RUN_ID": "8"}):
            result = self.classify("10 9 501 python\n9 1 501 bash\n8 1 501 Runner.Worker\n")
        self.assertTrue(result["other_ci_active"])
        self.assertIsNone(result["owned_ancestor_worker_pid"])

    def test_paths_with_spaces_and_exact_worker_basename(self):
        result = self.classify(self.OWN.replace("/runner/bin/Runner.Worker",
                                               "/runner with spaces/bin/Runner.Worker"))
        self.assertEqual(result["owned_ancestor_worker_pid"], 8)
        result = self.classify(self.OWN.replace("Runner.Worker", "Runner.Worker-helper"))
        self.assertIsNone(result["owned_ancestor_worker_pid"])


class RuntimeProbeTests(unittest.TestCase):
    def process_snapshot(self):
        return f"{os.getpid()} {os.getppid()} {os.getuid()} python3\n"

    def test_no_daemon_or_model_calls_in_probe(self):
        snap=MemorySnapshot(PHYSICAL,16384,free_pages=350000,inactive_pages=350000,
                            speculative_pages=8000,swapouts_pages=0)
        with (patch("host_capacity_admission._snapshot",return_value=snap),
              patch("host_capacity_admission.time.sleep"),
              patch("host_capacity_admission.subprocess.check_output",return_value=self.process_snapshot()),
              patch("host_capacity_admission._api",return_value={"models":[]}),
              patch("host_capacity_admission._swap_status",return_value=["unloaded"])):
            out=probe("qwen3.5:9b")
        self.assertEqual(out["status"],"CONSERVATIVE_PRECHECK_PASS")
        self.assertEqual(out["model_calls"],0)

    def test_unreadable_swap_service_fails_closed(self):
        snap=MemorySnapshot(PHYSICAL,16384,free_pages=350000,inactive_pages=350000,
                            speculative_pages=8000,swapouts_pages=0)
        with (patch("host_capacity_admission._snapshot",return_value=snap),
              patch("host_capacity_admission.time.sleep"),
              patch("host_capacity_admission.subprocess.check_output",return_value=self.process_snapshot()),
              patch("host_capacity_admission._api",return_value={"models":[]}),
              patch("host_capacity_admission._swap_status",side_effect=OSError("offline"))):
            out=probe("qwen3.5:9b")
        self.assertEqual(out["reason"],"INFERENCE_ENDPOINT_STATE_UNVERIFIED")

    def test_own_worker_does_not_hide_real_capacity_or_other_ci_blockers(self):
        ample = MemorySnapshot(PHYSICAL,16384,free_pages=350000,inactive_pages=350000,
                               speculative_pages=8000,swapouts_pages=0)
        small = parse_vm_stat(SOURCE, PHYSICAL)
        for snapshot, extra, reason in (
                (ample, "", None),
                (small, "", "INSUFFICIENT_RECLAIMABLE_UPPER_BOUND"),
                (ample, "20 1 501 Runner.Worker\n", "OTHER_CI_RUNNING")):
            with self.subTest(reason=reason), \
                 patch("host_capacity_admission._snapshot", return_value=snapshot), \
                 patch("host_capacity_admission.time.sleep"), \
                 patch("host_capacity_admission.os.getpid", return_value=10), \
                 patch("host_capacity_admission.os.getppid", return_value=9), \
                 patch("host_capacity_admission.os.getuid", return_value=501), \
                 patch("host_capacity_admission.subprocess.check_output",
                       return_value=ProcessOwnershipTests.OWN + extra), \
                 patch("host_capacity_admission._api", return_value={"models": []}), \
                 patch("host_capacity_admission._swap_status", return_value=["unloaded"]):
                result = probe("qwen3.5:9b")
            self.assertEqual(result["reason"], reason)
            self.assertEqual(result["owned_ancestor_worker_pid"], 8)
            self.assertEqual(result["model_calls"], 0)


if __name__=="__main__":
    unittest.main()

