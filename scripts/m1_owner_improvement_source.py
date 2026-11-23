"""No-effect reviewed feature-branch source/test attestation for improvement.

A candidate with measured benefit is NOT a main regression. A true positive
improvement needs an already-reviewed isolated feature branch containing an
immutable acceptance test. Read-only tests must not create a branch, edit
existing tests, grant an approval or cause a model call.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import stat
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_foundation.development_improvement_contract import HostImprovementScope


def _git(path: Path, *args: str) -> str:
    return subprocess.check_output(
        ["/usr/bin/git", "-C", str(path), *args],
        text=True, timeout=10, stderr=subprocess.DEVNULL,
    ).strip()


def observed_feature_test(scope, checkout):
    """Independent owner checkout readback; return a digest, never authority.

    This only proves that target and acceptance bytes are committed on a
    particular checked-out branch. It does not prove candidate benchmark,
    billing, review approval, failing baseline or Guard ALLOW.
    """
    # pathlib.Path() returns a concrete PosixPath on macOS; strict type()
    # equality against the abstract Path class wrongly rejects every owner
    # checkout before any of the actual safety checks run.
    if type(scope) is not HostImprovementScope or not isinstance(checkout, (str, Path)):
        return None
    root = Path(checkout)
    if not root.is_absolute() or root.is_symlink():
        return None
    try:
        base = root.resolve(strict=True)
        info = base.lstat()
        if (base != root or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022):
            return None
        # Validate the limited relative paths independent of a contract:
        # no Git option injection, traversals or dynamic shell commands.
        if not (scope.base_branch.startswith("local9b/")
                and ".." not in scope.base_branch
                and scope.target.startswith("src/ai_foundation/")
                and scope.acceptance_test.startswith("tests/test_")):
            return None
        for name in (scope.target, scope.acceptance_test):
            path = base
            for part in Path(name).parts:
                if part in ("..", "."):
                    return None
                path = path / part
                if path.is_symlink():
                    return None
            check = path.lstat()
            if (not stat.S_ISREG(check.st_mode)
                    or check.st_uid != os.getuid()
                    or check.st_mode & 0o022
                    or check.st_nlink != 1
                    or check.st_size < 1 or check.st_size > 65536):
                return None
        if _git(base, "rev-parse", "HEAD") != scope.base_sha:
            return None
        if _git(base, "branch", "--show-current") != scope.base_branch:
            return None
        if subprocess.run(
                ["/usr/bin/git", "-C", str(base), "diff", "--quiet",
                 "HEAD", "--", scope.target, scope.acceptance_test],
                timeout=10, capture_output=True).returncode != 0:
            return None
        # A matching untracked file is not an immutable branch acceptance.
        for relative in (scope.target, scope.acceptance_test):
            if _git(base, "ls-files", "--error-unmatch", "--", relative) != relative:
                return None
        target = base / scope.target
        test = base / scope.acceptance_test
        if sha256(test.read_bytes()).hexdigest() != scope.acceptance_sha256:
            return None
        return scope.acceptance_sha256
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
