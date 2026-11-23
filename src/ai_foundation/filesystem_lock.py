"""Kernel-owned serialization for small host-owned filesystem transactions.

The lock inode is intentionally retained: unlinking it would let a new caller
lock a different inode while another caller still holds the old one. This is
not an effect lease, scheduler, or cross-host lock.
"""
from contextlib import contextmanager
import os
from pathlib import Path


@contextmanager
def exclusive_file_lock(path):
    # Darwin/arm64 is the supported production host. Do not silently run
    # unlocked on a platform without this kernel primitive.
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)
