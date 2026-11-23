"""Real OS/process contracts, synthetic commands only, no model/network/host kill."""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ai_foundation.host_compute_lease import HostComputeLease, HostComputeBusy, HostComputeLeaseError
from ai_foundation.host_compute_job import run_job, read_plan


class JobContracts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'private' / 'compute.lock'
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('FOUNDATION_HOST_COMPUTE_LEASE_')}
        self.env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
        self.env['PYTHONDONTWRITEBYTECODE'] = '1'
        self.patch = patch.dict(os.environ, self.env, clear=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def process(self, source, *args, pass_fds=()):
        p = subprocess.Popen([sys.executable, '-c', source, str(self.path), *map(str, args)],
                             env=self.env, text=True, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, pass_fds=pass_fds)
        def clean():
            if p.poll() is None:
                # All fixtures are bounded and may be released via their own stdin.
                try: p.stdin.write('exit\n'); p.stdin.flush()
                except (BrokenPipeError, ValueError): pass
            p.wait(timeout=8)
            for f in (p.stdin, p.stdout, p.stderr): f.close()
        self.addCleanup(clean)
        return p

    def line(self, p):
        with selectors.DefaultSelector() as s:
            s.register(p.stdout, selectors.EVENT_READ)
            self.assertTrue(s.select(5), 'fixture did not report readiness')
        return p.stdout.readline().strip()

    def job_source(self, phases):
        return ('import sys\nfrom ai_foundation.host_compute_job import run_job\n'
                'from ai_foundation.host_compute_lease import HostComputeLease\n'
                f'sys.exit(run_job({phases!r}, lease=HostComputeLease(sys.argv[1])))\n')

    def test_two_independent_jobs_exclude_and_release(self):
        source = '''import sys,select
from ai_foundation.host_compute_lease import HostComputeLease
with HostComputeLease(sys.argv[1]).hold():
 print('HELD',flush=True)
 if select.select([sys.stdin],[],[],5)[0]: sys.stdin.readline()
'''
        holder = self.process(source)
        self.assertEqual(self.line(holder), 'HELD')
        marker = Path(self.tmp.name) / 'must-not-exist'
        phases = [{'name': 'install', 'argv': [sys.executable, '-c', f'open({str(marker)!r},"w").close()']}]
        other = self.process(self.job_source(phases))
        self.assertEqual(other.wait(timeout=4), 75)
        self.assertIn('DEFERRED', other.stdout.read())
        self.assertFalse(marker.exists())
        holder.stdin.write('exit\n'); holder.stdin.flush()
        self.assertEqual(holder.wait(timeout=4), 0)
        with HostComputeLease(self.path).hold(): pass

    def test_whole_plan_covers_install_compile_test_and_nested_calls(self):
        child = '''import sys
from ai_foundation.host_compute_lease import HostComputeLease, HostComputeBusy
with HostComputeLease(sys.argv[1]).hold(): print('NESTED',flush=True)
'''
        phases = [{'name': n, 'argv': [sys.executable, '-c', child, str(self.path)]}
                  for n in ['install', 'compile', 'test', 'post']]
        # Separate independent process checks exclusion at each phase transition.
        events = []
        def emit(row):
            events.append(row['event'])
            if row['event'] in ('PHASE_STARTED', 'PHASE_EXITED'):
                p = self.process('from ai_foundation.host_compute_lease import HostComputeLease,HostComputeBusy\nimport sys\ntry:\n with HostComputeLease(sys.argv[1]).hold(): sys.exit(8)\nexcept HostComputeBusy: sys.exit(0)')
                self.assertEqual(p.wait(timeout=3), 0)
        self.assertEqual(run_job(phases, lease=HostComputeLease(self.path), emit=emit), 0)
        self.assertEqual(events.count('PHASE_EXITED'), 4)

    def test_failed_phase_skips_later_phases(self):
        marker = Path(self.tmp.name) / 'later'
        phases = [{'name':'bad','argv':[sys.executable,'-c','raise SystemExit(9)']},
                  {'name':'later','argv':[sys.executable,'-c',f'open({str(marker)!r},"w").close()']}]
        self.assertEqual(run_job(phases, lease=HostComputeLease(self.path), emit=lambda r:None),9)
        self.assertFalse(marker.exists())
        with HostComputeLease(self.path).hold(): pass

    def test_cancel_current_job_waits_for_owned_phase_without_sending_signals(self):
        # Synthetic phase requests SIGTERM on its own parent. No host PID discovery.
        phase = 'import os,signal;os.kill(os.getppid(),signal.SIGTERM)'
        marker = Path(self.tmp.name) / 'later'
        phases = [{'name':'cancel','argv':[sys.executable,'-c',phase]},
                  {'name':'later','argv':[sys.executable,'-c',f'open({str(marker)!r},"w").close()']}]
        p = self.process(self.job_source(phases))
        self.assertEqual(p.wait(timeout=4), 128+signal.SIGTERM)
        self.assertFalse(marker.exists())
        self.assertIn('CANCELLED',p.stdout.read())
        with HostComputeLease(self.path).hold(): pass

    def test_abrupt_exit_and_timeout_self_termination_release(self):
        for ending in ['os._exit(21)', 'signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(1);signal.pause()']:
            p=self.process('import os,signal,sys\nfrom ai_foundation.host_compute_lease import HostComputeLease\nwith HostComputeLease(sys.argv[1]).hold():\n print("HELD",flush=True)\n '+ending)
            self.assertEqual(self.line(p),'HELD')
            self.assertNotEqual(p.wait(timeout=4),0)
            with HostComputeLease(self.path).hold(): pass

    def test_parent_exit_does_not_unlock_surviving_delegated_child(self):
        release=Path(self.tmp.name)/'release'
        child='''import pathlib,sys,time
p=pathlib.Path(sys.argv[1]);print('CHILD_READY',flush=True)
until=time.monotonic()+5
while not p.exists() and time.monotonic()<until:time.sleep(.02)
'''
        source=('import subprocess,sys,os\nfrom ai_foundation.host_compute_lease import HostComputeLease\n'
                'with HostComputeLease(sys.argv[1]).hold() as fd:\n'
                f' p=subprocess.Popen([sys.executable,"-c",{child!r},sys.argv[2]],pass_fds=(fd,))\n'
                ' print("PARENT_DONE",flush=True)\n')
        p=self.process(source,release)
        first=self.line(p)
        self.assertEqual(p.wait(timeout=3),0)
        self.assertEqual({first,p.stdout.readline().strip()},{'PARENT_DONE','CHILD_READY'})
        with self.assertRaises(HostComputeBusy):
            with HostComputeLease(self.path).hold():pass
        release.touch()
        # EOF means child has exited and closed its descriptors; no arbitrary sleep.
        p.stdout.read()
        with HostComputeLease(self.path).hold():pass

    def test_borrowed_consumer_oserror_is_not_reentered(self):
        with HostComputeLease(self.path).hold() as fd:
            with patch.dict(os.environ,{'FOUNDATION_HOST_COMPUTE_LEASE_FD':str(fd)}):
                with self.assertRaisesRegex(OSError,'consumer'):
                    with HostComputeLease(self.path).hold():raise OSError('consumer')
            with self.assertRaises(HostComputeBusy):
                with HostComputeLease(self.path).hold():pass

    def test_inherited_fd_substitution_and_hardlink_refused(self):
        with HostComputeLease(self.path).hold() as fd:
            other=os.open(Path(self.tmp.name)/'other',os.O_CREAT|os.O_RDWR,0o600)
            try:
                with patch.dict(os.environ,{'FOUNDATION_HOST_COMPUTE_LEASE_FD':str(other)}):
                    with self.assertRaises(HostComputeLeaseError):
                        with HostComputeLease(self.path).hold():pass
            finally:os.close(other)
            os.link(self.path,self.path.parent/'alias')
            with patch.dict(os.environ,{'FOUNDATION_HOST_COMPUTE_LEASE_FD':str(fd)}):
                with self.assertRaises(HostComputeLeaseError):
                    with HostComputeLease(self.path).hold():pass

    def test_borrowed_symlink_refused(self):
        with HostComputeLease(self.path).hold() as fd:
            alias=self.path.parent/'alias';alias.symlink_to(self.path)
            with patch.dict(os.environ,{'FOUNDATION_HOST_COMPUTE_LEASE_FD':str(fd)}):
                with self.assertRaises(HostComputeLeaseError):
                    with HostComputeLease(alias).hold():pass

    def test_wrong_uid_refused(self):
        with HostComputeLease(self.path).hold():pass
        with patch('ai_foundation.host_compute_lease.os.getuid',return_value=os.getuid()+1):
            with self.assertRaises(HostComputeLeaseError):
                with HostComputeLease(self.path).hold():pass

    def test_unrelated_open_description_cannot_reenter(self):
        with HostComputeLease(self.path).hold():
            other=os.open(self.path,os.O_RDWR)
            try:
                with patch.dict(os.environ,{'FOUNDATION_HOST_COMPUTE_LEASE_FD':str(other)}):
                    with self.assertRaises(HostComputeBusy):
                        with HostComputeLease(self.path).hold():pass
            finally:os.close(other)

    def test_unrelated_fork_must_drop_capability_before_independent_admission(self):
        # The pytest host can have unrelated threads. Fork only in a fresh,
        # single-threaded synthetic process, never in the suite/runner itself.
        source='''import os,sys
from ai_foundation.host_compute_lease import HostComputeLease,HostComputeBusy
with HostComputeLease(sys.argv[1]).hold() as fd:
 pid=os.fork()
 if pid==0:
  os.close(fd)
  try:
   with HostComputeLease(sys.argv[1]).hold():os._exit(9)
  except HostComputeBusy:os._exit(0)
 status=os.waitpid(pid,0)[1]
 sys.exit(0 if status==0 else 1)
'''
        p=self.process(source)
        self.assertEqual(p.wait(timeout=4),0)

    def test_replaced_path_rejects_old_inherited_descriptor(self):
        with HostComputeLease(self.path).hold() as fd:
            self.path.rename(self.path.parent/'old')
            with patch.dict(os.environ,{'FOUNDATION_HOST_COMPUTE_LEASE_FD':str(fd)}):
                with self.assertRaises(HostComputeLeaseError):
                    with HostComputeLease(self.path).hold():pass

    def test_stale_fd_and_invalid_wait_refused(self):
        with patch.dict(os.environ,{'FOUNDATION_HOST_COMPUTE_LEASE_FD':'999999'}):
            with self.assertRaises(HostComputeLeaseError):
                with HostComputeLease(self.path).hold():pass
        for v in [float('nan'),float('inf'),-1,601]:
            with self.assertRaises(ValueError):
                with HostComputeLease(self.path).hold(max_wait_s=v):pass

    def test_nonparticipant_is_not_mistaken_for_cooperating(self):
        with HostComputeLease(self.path).hold():
            p=self.process('print("OUTSIDE_COVERAGE")')
            self.assertEqual(p.wait(timeout=3),0)
            self.assertEqual(p.stdout.read().strip(),'OUTSIDE_COVERAGE')

    def test_plan_validation_precedes_execution(self):
        f=Path(self.tmp.name)/'plan.json'
        for obj in [{}, {'version':1,'phases':[]}, {'version':1,'phases':[{'name':'bad','argv':[]}]}]:
            f.write_text(json.dumps(obj))
            with self.assertRaises(ValueError):read_plan(f)

if __name__=='__main__':unittest.main()
