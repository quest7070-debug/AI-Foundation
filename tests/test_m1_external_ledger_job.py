"""New workflow adapter tests; existing lease contracts are not duplicated."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ledger_job", ROOT / "scripts/m1_external_ledger_job.py")
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)
from ai_foundation.host_compute_lease import HostComputeLease


class WorkflowAdapter(unittest.TestCase):
    def test_existing_ledger_suite_runs_inside_one_plan(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            lease = HostComputeLease(Path(tmp) / "private" / "compute.lock")
            result = job.run_job(job.phases(), lease=lease, max_wait_s=0, emit=events.append)
        self.assertEqual(result, 0)
        self.assertEqual([e['event'] for e in events], [
            'WAITING', 'ADMITTED', 'PHASE_STARTED', 'PHASE_EXITED',
            'PHASE_STARTED', 'PHASE_EXITED', 'COMPLETE'])

    def test_plan_reuses_existing_test_and_current_interpreter(self):
        phases = job.phases()
        self.assertEqual(len(phases), 2)
        for phase in phases:
            self.assertEqual(phase['argv'][0], sys.executable)
            self.assertIn('-B', phase['argv'])
        self.assertEqual(phases[-1]['argv'][-2:], ['test_external_ledger.py', '-v'])

    def test_workflow_requires_disposable_runner_and_exact_fixed_commands(self):
        source = (ROOT / '.github/workflows/human-model-external-ledger.yml').read_text()
        self.assertIn('cancel-in-progress: false', source)
        # Three mutually exclusive fixed jobs: ledger, holder, contender.
        # A count of one was stale after adding the explicit two-runner mode.
        self.assertEqual(source.count('runs-on: [foundation-lease-disposable]'), 3)
        commands = [line.strip() for line in source.splitlines()
                    if line.strip().startswith('run: ')]
        self.assertCountEqual(commands, [
            'run: /usr/bin/python3 -B scripts/m1_external_ledger_job.py',
            'run: /usr/bin/python3 -B scripts/issue222_disposable_pair.py holder',
            'run: /usr/bin/python3 -B scripts/issue222_disposable_pair.py contender',
        ])
        self.assertNotIn('runs-on: [self-hosted', source)
        self.assertNotIn('workflow_run:', source)


if __name__ == '__main__':
    unittest.main()
