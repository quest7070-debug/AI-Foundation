#!/usr/bin/env python3
"""One bounded two-runner model-free HostComputeLease/FD fixture.

A new temporary lease domain is private to a workflow_dispatch run ID. This
proves a real kernel lock can persist in an inherited child when the holder
parent leaves its context. It does NOT install runner hooks, govern any
uncoordinated workload, or authorize real 9B inference.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.host_compute_lease import HostComputeBusy, HostComputeLease

SLEEP_SECONDS = 12
READY_TIMEOUT_SECONDS = 24

def refuse(reason):
    raise RuntimeError(reason)

def private_dir(path):
    if path.is_symlink():
        refuse("FIXTURE_SYMLINK_REFUSED")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    s = path.lstat()
    if not stat.S_ISDIR(s.st_mode) or s.st_uid != os.getuid() or s.st_mode & 0o077:
        refuse("FIXTURE_PRIVATE_DIRECTORY_NOT_VERIFIED")

def get_root():
    run_id = os.getenv("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[0-9]{6,20}", run_id):
        refuse("EXACT_GITHUB_RUN_ID_REQUIRED")
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    base = home / "Library" / "Application Support" / "AI-Foundation"
    private_dir(base / "issue222-owned-pair")
    path = base / "issue222-owned-pair" / ("run-" + run_id)
    private_dir(path)
    return path

def marker(root, name, item):
    path = root / name
    if not re.fullmatch(r"[a-z-]{2,40}", name):
        refuse("INVALID_FIXTURE_MARKER")
    raw = (json.dumps(item,sort_keys=True) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    print(json.dumps({"stage":name,"runner":os.getenv("RUNNER_NAME"),
                      "uid":os.getuid()},sort_keys=True),flush=True)

def wait_marker(root, name, timeout):
    path = root / name
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        try:
            s = path.lstat()
        except FileNotFoundError:
            time.sleep(0.07)
            continue
        if (not stat.S_ISREG(s.st_mode) or s.st_uid != os.getuid()
                or s.st_mode & 0o077 or s.st_size > 1024):
            refuse("FIXTURE_MARKER_IDENTITY_DRIFT")
        return json.loads(path.read_text())
    refuse("FIXTURE_MARKER_TIMEOUT_" + name)

def check_runtime():
    runner = os.getenv("RUNNER_NAME", "")
    if runner not in ("p0-lease-20261106-a","p0-lease-20261106-b"):
        refuse("DEDICATED_RUNNER_IDENTITY_REQUIRED")
    if os.getuid() != 501:
        refuse("HOST_UID_DRIFT")
    return runner

def child(root):
    check_runtime()
    lease = HostComputeLease(root / "private" / "compute.lock")
    # Inherited FD must match same lock inode and owner. The real production
    # host_compute_lease.py validates this; never spoof an inherited fd.
    with lease.hold(max_wait_s=0) as fd:
        marker(root,"child-ready",{"child_pid":os.getpid(),"uid":os.getuid(),
                                   "fd_valid":os.fstat(fd).st_nlink == 1})
        time.sleep(SLEEP_SECONDS)
    return 0

def holder(root):
    name = check_runtime()
    lease = HostComputeLease(root / "private" / "compute.lock")
    proc = None
    with lease.hold(max_wait_s=0) as fd:
        env = dict(os.environ)
        env["FOUNDATION_HOST_COMPUTE_LEASE_FD"] = str(fd)
        env["FOUNDATION_HOST_COMPUTE_LEASE_PATH"] = str(lease.path.absolute())
        proc = subprocess.Popen([sys.executable,"-B",str(Path(__file__).resolve()),
                                 "child"],env=env,pass_fds=(fd,),close_fds=True)
        ready = wait_marker(root,"child-ready",7)
        if not ready.get("fd_valid"):
            refuse("DELEGATED_FD_NOT_VERIFIED")
    # Parent has now closed its lease FD; delegated child still holds it.
    marker(root,"parent-released",{"holder_runner":name,"uid":os.getuid(),
                                   "child_pid":proc.pid})
    try:
        child_exit = proc.wait(timeout=20)
        if child_exit != 0:
            refuse("DELEGATED_CHILD_FAILED")
        marker(root,"child-done",{"exit":child_exit,"runner":name})
        return 0
    finally:
        # Wait for task-owned child only. Never signal another user's process.
        if proc is not None and proc.poll() is None:
            proc.wait(timeout=20)

def contender(root):
    name = check_runtime()
    parent = wait_marker(root,"parent-released",READY_TIMEOUT_SECONDS)
    if parent.get("holder_runner") == name or parent.get("uid") != os.getuid():
        refuse("INDEPENDENT_RUNNER_OR_UID_NOT_PROVEN")
    lease = HostComputeLease(root / "private" / "compute.lock")
    try:
        with lease.hold(max_wait_s=0):
            refuse("LEASE_OVERLAP_ADMITTED_UNEXPECTEDLY")
    except HostComputeBusy:
        marker(root,"contender-deferred",{"runner":name,"reason":"HOST_COMPUTE_BUSY"})
    done = wait_marker(root,"child-done",READY_TIMEOUT_SECONDS)
    if done.get("exit") != 0:
        refuse("HOLDER_CHILD_NOT_CLEANLY_RELEASED")
    with lease.hold(max_wait_s=2):
        marker(root,"contender-recovered",{"runner":name,"uid":os.getuid()})
    return 0

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ("holder","contender","child"):
        refuse("EXPLICIT_PAIR_ROLE_REQUIRED")
    root = get_root()
    result = {"holder":holder,"contender":contender,"child":child}[sys.argv[1]](root)
    print(json.dumps({"decision":"ONE_PAIR_FIXTURE_ROLE_PASS","role":sys.argv[1],
                      "model_calls":0,"effect_authorized":False},sort_keys=True))
    return result

if __name__=="__main__":
    raise SystemExit(main())
