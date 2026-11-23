"""Non-network host lease contracts (no model and no CI start)."""
import os
from pathlib import Path
import subprocess
import sys
import time
import pytest
from ai_foundation.host_compute_lease import HostComputeBusy, HostComputeLease, HostComputeLeaseError


def test_separate_fds_exclude_same_host_lock(tmp_path):
    path = tmp_path / "owner" / "compute.lock"
    with HostComputeLease(path).hold():
        with pytest.raises(HostComputeBusy):
            with HostComputeLease(path).hold():
                pass
    with HostComputeLease(path).hold():
        assert path.is_file()


def test_exception_releases(tmp_path):
    path = tmp_path / "owner" / "compute.lock"
    with pytest.raises(ValueError):
        with HostComputeLease(path).hold():
            raise ValueError("synthetic")
    with HostComputeLease(path).hold():
        pass


def test_symlink_refused_without_following(tmp_path):
    parent = tmp_path / "owner"
    parent.mkdir(mode=0o700)
    target = tmp_path / "safe"
    target.write_text("unchanged")
    (parent / "compute.lock").symlink_to(target)
    with pytest.raises(HostComputeLeaseError):
        with HostComputeLease(parent / "compute.lock").hold():
            pass
    assert target.read_text() == "unchanged"


def test_world_writable_dir_refused(tmp_path):
    parent = tmp_path / "unsafe"
    parent.mkdir(mode=0o777)
    parent.chmod(0o777)
    with pytest.raises(HostComputeLeaseError, match="DIRECTORY_NOT_PRIVATE"):
        with HostComputeLease(parent / "compute.lock").hold():
            pass


def test_invalid_wait_refused(tmp_path):
    with pytest.raises(ValueError):
        with HostComputeLease(tmp_path / "owner" / "compute.lock").hold(max_wait_s=901):
            pass


def test_bounded_contention(tmp_path):
    lock = HostComputeLease(tmp_path / "owner" / "compute.lock")
    with lock.hold():
        start = time.monotonic()
        with pytest.raises(HostComputeBusy):
            with lock.hold(max_wait_s=0.08):
                pass
        assert 0.05 <= time.monotonic() - start < 0.5


def test_cli_exec_keeps_fd_locked_across_process(tmp_path):
    lock_path = tmp_path / "owner" / "compute.lock"
    script = """from ai_foundation.host_compute_lease import HostComputeLease
import sys
HostComputeLease(sys.argv[1]).exec_under_lock([sys.executable,'-c','import time;print("LEASED",flush=True);time.sleep(0.7)'])
"""
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    proc = subprocess.Popen([sys.executable, "-c", script, str(lock_path)],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "LEASED"
        with pytest.raises(HostComputeBusy):
            with HostComputeLease(lock_path).hold():
                pass
        assert proc.wait(timeout=2) == 0, proc.stderr.read()
        with HostComputeLease(lock_path).hold():
            pass
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=2)


def test_exec_inherited_lock_allows_nested_use(tmp_path):
    path = tmp_path / "owner" / "compute.lock"
    child = ("from ai_foundation.host_compute_lease import HostComputeLease\n"
             "import sys\n"
             "with HostComputeLease(sys.argv[1]).hold(): print('NESTED',flush=True)\n")
    runner = ("from ai_foundation.host_compute_lease import HostComputeLease\n"
              "import sys\n"
              "lease = HostComputeLease(sys.argv[1])\n"
              f"lease.exec_under_lock([sys.executable, '-c', {child!r}, sys.argv[1]])\n")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    p = subprocess.run([sys.executable, "-c", runner, str(path)], env=env,
                       text=True, capture_output=True, timeout=4)
    assert p.returncode == 0, (p.stdout, p.stderr)
    assert "NESTED" in p.stdout


@pytest.mark.parametrize("value", [True, False])
def test_boolean_lease_wait_never_creates_lockfile(tmp_path, value):
    path = tmp_path / "owner" / "compute.lock"
    lease = HostComputeLease(path)
    with pytest.raises(ValueError, match="INVALID_LEASE_WAIT"):
        with lease.hold(max_wait_s=value):
            pytest.fail("boolean wait was accepted")
    assert not path.exists()
    assert not path.parent.exists()
    # Valid finite numeric durations remain admitted.
    with lease.hold(max_wait_s=0):
        assert path.is_file()
