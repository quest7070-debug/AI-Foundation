"""Cross-process per-user compute lease for cooperating M1 CI and llama-swap calls.

Advisory lock only: does not control unrelated Ollama clients, reserve RAM,
change model placement, kill a process, or override Host resource admission.
"""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import pwd
import stat
import time
import math


class HostComputeBusy(RuntimeError):
    """The host is occupied; defer without marking model or route as broken."""


class HostComputeLeaseError(RuntimeError):
    """The private coordination lock is unverifiable."""


def canonical_lock_path() -> Path:
    # Use the real account home, not a potentially isolated or injected HOME.
    home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    return home / "Library" / "Application Support" / "AI-Foundation" / "host-compute" / "compute.lock"


class HostComputeLease:
    def __init__(self, lock_path: Path | None = None):
        self.path = Path(lock_path) if lock_path is not None else canonical_lock_path()

    def _open(self):
        parent = self.path.parent
        for directory in (parent.parent, parent):
            if directory.is_symlink():
                raise HostComputeLeaseError("LEASE_DIRECTORY_SYMLINK")
        try:
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = parent.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise HostComputeLeaseError("LEASE_DIRECTORY_NOT_PRIVATE")
            flags = os.O_RDWR | os.O_CREAT | os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(self.path, flags, 0o600)
            try:
                file_info = os.fstat(fd)
                if (not stat.S_ISREG(file_info.st_mode) or file_info.st_uid != os.getuid()
                        or file_info.st_mode & 0o077 or file_info.st_nlink != 1):
                    raise HostComputeLeaseError("LEASE_FILE_NOT_PRIVATE")
            except BaseException:
                os.close(fd)
                raise
            return fd
        except OSError as exc:
            raise HostComputeLeaseError("LEASE_PATH_UNAVAILABLE") from exc

    @contextmanager
    def hold(self, *, max_wait_s: float = 0):
        if (isinstance(max_wait_s, bool) or not isinstance(max_wait_s, (int, float))
                or not math.isfinite(max_wait_s)
                or not 0 <= max_wait_s <= 600):
            raise ValueError("INVALID_LEASE_WAIT")
        # A CI command inherits the original locked FD across exec. Its
        # nested Foundation inference calls must not conflict with themselves.
        inherited = os.environ.get("FOUNDATION_HOST_COMPUTE_LEASE_FD", "")
        inherited_path = os.environ.get("FOUNDATION_HOST_COMPUTE_LEASE_PATH")
        if inherited_path is not None and os.path.abspath(inherited_path) != os.path.abspath(self.path):
            inherited = ""  # A different explicitly selected coordination domain.
        if inherited:
            # Validate the SAME path protections for borrowed and newly opened FDs.
            # A malformed/stale advertised FD is an error, never a silent reentry.
            check_fd = self._open()
            try:
                if not inherited.isdecimal():
                    raise HostComputeLeaseError("INVALID_INHERITED_LEASE_FD")
                fd_existing = int(inherited)
                owned = os.fstat(fd_existing)
                target = os.fstat(check_fd)
                if ((owned.st_ino, owned.st_dev) != (target.st_ino, target.st_dev)
                        or not stat.S_ISREG(owned.st_mode) or owned.st_uid != os.getuid()
                        or owned.st_mode & 0o077 or owned.st_nlink != 1):
                    raise HostComputeLeaseError("INHERITED_LEASE_IDENTITY_MISMATCH")
                try:
                    fcntl.flock(fd_existing, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise HostComputeBusy("INHERITED_LEASE_NOT_OWNED") from exc
            except OSError as exc:
                raise HostComputeLeaseError("INHERITED_LEASE_UNAVAILABLE") from exc
            finally:
                os.close(check_fd)
            # Keep consumer exceptions outside validation. Never catch an OSError
            # from the protected operation and accidentally execute it again.
            yield fd_existing
            return
        fd = self._open()
        deadline = time.monotonic() + max_wait_s
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError as exc:
                    if time.monotonic() >= deadline:
                        raise HostComputeBusy("HOST_COMPUTE_LEASE_BUSY") from exc
                    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
            yield fd
        finally:
            # Close, never LOCK_UN: a surviving explicitly delegated child may
            # still own this open-file description after its parent exits.
            os.close(fd)

    def exec_under_lock(self, argv: list[str], *, max_wait_s: float = 0) -> None:
        """Exec a CI command holding the same FD; no orphan guardian process."""
        if not argv or not isinstance(argv[0], str) or not argv[0]:
            raise ValueError("EMPTY_COMPUTE_COMMAND")
        with self.hold(max_wait_s=max_wait_s) as fd:
            os.set_inheritable(fd, True)
            old = os.environ.get("FOUNDATION_HOST_COMPUTE_LEASE_FD")
            old_path = os.environ.get("FOUNDATION_HOST_COMPUTE_LEASE_PATH")
            os.environ["FOUNDATION_HOST_COMPUTE_LEASE_FD"] = str(fd)
            os.environ["FOUNDATION_HOST_COMPUTE_LEASE_PATH"] = str(self.path.absolute())
            try:
                os.execvp(argv[0], argv)
            finally:
                if old is None:
                    os.environ.pop("FOUNDATION_HOST_COMPUTE_LEASE_FD", None)
                else:
                    os.environ["FOUNDATION_HOST_COMPUTE_LEASE_FD"] = old
                if old_path is None:
                    os.environ.pop("FOUNDATION_HOST_COMPUTE_LEASE_PATH", None)
                else:
                    os.environ["FOUNDATION_HOST_COMPUTE_LEASE_PATH"] = old_path
