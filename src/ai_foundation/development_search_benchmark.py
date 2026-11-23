"""Fixed, no-install ripgrep-vs-system-grep benchmark for a reviewed M1 trial.

The host, not a candidate/LLM/Issue, supplies immutable binary/corpus SHA256
pins. This module measures equivalent *observed* output; it does not attest
how an executable was built, grant cost/Guard authority, install rg, or issue
an admission receipt on its own. No executable -> no measurement (HOLD).
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re
import stat
import subprocess
import time
from statistics import median

from .development_candidate_registry import reviewed_offline_catalogue

_CANDIDATE = "ripgrep-14.1.1"
_SHA256 = re.compile(r"[a-f0-9]{64}\Z")
_NEEDLE = "FOUNDATION_BENCHMARK_NEEDLE_9B"
_HEADER = b"# Foundation benchmark corpus v1\n"
_MAX_CORPUS = 2 * 1024 * 1024
_GREP = "/usr/bin/grep"


class SearchBenchmarkUnavailable(ValueError):
    """Missing/changed host-pinned corpus, binary or equivalent results."""


@dataclass(frozen=True)
class ReviewedSearchPin:
    """Trusted owner-host manifest only; never deserialize from an Issue."""
    candidate_id: str
    upstream_commit: str
    binary_sha256: str
    corpus_sha256: str
    acceptance_test_sha256: str

    def valid(self) -> bool:
        catalog = reviewed_offline_catalogue()
        return (type(self) is ReviewedSearchPin
                and self.candidate_id == _CANDIDATE
                and self.upstream_commit == catalog[_CANDIDATE].pinned_commit
                and all(type(s) is str and _SHA256.fullmatch(s)
                        for s in (self.binary_sha256,
                                  self.corpus_sha256,
                                  self.acceptance_test_sha256)))


class PinnedRipgrepBenchmark:
    """One host-owned private fixture directory: rg + corpus.txt.

    Fixed, literal single-file search. No shell, dynamic commands, network,
    package manager, service change, or owner-data scan. A pinned binary digest
    proves only bytes identity; an independent host source-to-binary review is
    required before using numbers as an authorized BenefitReceipt.
    """
    metric = "latency_ms"
    direction = "lower"

    def __init__(self, root, pin: ReviewedSearchPin, *, runner=None,
                 clock_ns=None):
        if not isinstance(root, (str, Path)) or not pin.valid():
            raise SearchBenchmarkUnavailable("BENCHMARK_MANIFEST_UNVERIFIED")
        self.root = Path(root)
        self.pin = pin
        self.test_sha256 = pin.acceptance_test_sha256
        self._runner = subprocess.run if runner is None else runner
        self._clock_ns = time.perf_counter_ns if clock_ns is None else clock_ns

    def _fixed_files(self):
        root = self.root
        try:
            if (not root.is_absolute() or root.is_symlink()
                    or root.resolve(strict=True) != root):
                raise ValueError("noncanonical fixture")
            info = root.lstat()
            if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077):
                raise ValueError("fixture ownership")
            rg, corpus = root / "rg", root / "corpus.txt"
            for name in (rg, corpus):
                info = name.lstat()
                if (name.is_symlink() or not stat.S_ISREG(info.st_mode)
                        or info.st_uid != os.getuid() or info.st_mode & 0o022
                        or info.st_nlink != 1):
                    raise ValueError("file identity")
            ri, ci = rg.stat(), corpus.stat()
            if (not ri.st_mode & stat.S_IXUSR or not 0 < ri.st_size <= 64 * 1024 * 1024
                    or not len(_HEADER) < ci.st_size <= _MAX_CORPUS):
                raise ValueError("file size/mode")
            rb, cb = rg.read_bytes(), corpus.read_bytes()
            if (sha256(rb).hexdigest() != self.pin.binary_sha256
                    or sha256(cb).hexdigest() != self.pin.corpus_sha256
                    or not cb.startswith(_HEADER)
                    or _NEEDLE.encode() not in cb or b"\x00" in cb):
                raise ValueError("fixture digest/content")
            return rg, corpus
        except (OSError, ValueError) as exc:
            raise SearchBenchmarkUnavailable("BENCHMARK_FIXTURE_UNVERIFIED") from exc

    def _one(self, cmd):
        begin = self._clock_ns()
        try:
            out = self._runner(
                cmd, cwd=str(self.root), env={"PATH": "/usr/bin:/bin",
                 "LC_ALL": "C", "RIPGREP_CONFIG_PATH": "/dev/null"},
                stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise SearchBenchmarkUnavailable("BENCHMARK_COMMAND_FAILED") from exc
        elapsed = (self._clock_ns() - begin) / 1_000_000.0
        if (type(out.returncode) is not int or out.returncode != 0
                or type(out.stdout) is not bytes or not out.stdout
                or len(out.stdout) > _MAX_CORPUS
                or type(out.stderr) is not bytes or out.stderr
                or not 0 < elapsed <= 5000):
            raise SearchBenchmarkUnavailable("BENCHMARK_RESULT_UNVERIFIED")
        return elapsed, out.stdout

    def observe_pair(self, candidate_id, index):
        if (candidate_id != _CANDIDATE or type(index) is not int
                or not 0 <= index < 5):
            raise SearchBenchmarkUnavailable("BENCHMARK_REQUEST_UNVERIFIED")
        rg, corpus = self._fixed_files()
        reference_cmd = [_GREP, "-nF", "-e", _NEEDLE, "--", str(corpus)]
        trial_cmd = [str(rg), "--no-config", "--no-ignore", "--no-heading",
                     "--color", "never", "-nF", "-e", _NEEDLE, "--",
                     str(corpus)]
        # A single very short process launch on the shared 16GB M1 can have
        # >20% scheduler jitter. Keep the admission noise limit unchanged.
        # Median of eight AB/BA alternating fixed-output samples per pair
        # provides a robust observation without inflating a lucky gain.
        refs, trials = [], []
        for repeat in range(8):
            if (index + repeat) % 2 == 0:
                reference, output = self._one(reference_cmd)
                trial, trial_output = self._one(trial_cmd)
            else:
                trial, trial_output = self._one(trial_cmd)
                reference, output = self._one(reference_cmd)
            if output != trial_output:
                raise SearchBenchmarkUnavailable("BENCHMARK_OUTPUT_MISMATCH")
            refs.append(reference)
            trials.append(trial)
        self._fixed_files()  # no silent binary/corpus replacement mid-pair
        return (median(refs), median(trials))
