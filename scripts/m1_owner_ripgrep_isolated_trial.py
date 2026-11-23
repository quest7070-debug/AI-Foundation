"""Owner-M1 one-shot, offline, isolated ripgrep candidate benefit experiment.

No installation, paid provider, new token, source write, Drive plan, Guard
grant, issue/queue/model invocation, persistent process or service mutation.
If cargo dependencies are not already cached, fail closed, not network fetch.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_foundation.development_candidate_registry import reviewed_offline_catalogue
from ai_foundation.development_host_evidence import measured_benefit_from_fixed_port
from ai_foundation.development_search_benchmark import (
    PinnedRipgrepBenchmark, ReviewedSearchPin, SearchBenchmarkUnavailable,
)
from ai_foundation.host_compute_lease import (
    HostComputeBusy, HostComputeLease, HostComputeLeaseError,
)

CANDIDATE = "ripgrep-14.1.1"
PINNED_LICENSE_NAME = "LICENSE-MIT"


def _source_attestation(checkout):
    """Require exact owner-controlled immutable upstream checkout and MIT bytes."""
    source = Path(checkout)
    meta = reviewed_offline_catalogue()[CANDIDATE]
    if (not source.is_absolute() or source.is_symlink() or
            source.resolve(strict=True) != source):
        raise SearchBenchmarkUnavailable("PINNED_SOURCE_PATH_UNVERIFIED")
    head = subprocess.check_output(
        ["/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"],
        text=True, stderr=subprocess.DEVNULL, timeout=10).strip()
    if head != meta.pinned_commit:
        raise SearchBenchmarkUnavailable("PINNED_SOURCE_COMMIT_MISMATCH")
    license_path = source / PINNED_LICENSE_NAME
    if license_path.is_symlink():
        raise SearchBenchmarkUnavailable("PINNED_LICENSE_SYMLINK")
    license_bytes = license_path.read_bytes()
    if sha256(license_bytes).hexdigest() != meta.license_sha256:
        raise SearchBenchmarkUnavailable("PINNED_LICENSE_MISMATCH")
    return source


def _cargo():
    """Only already-installed compiler; never invoke installer or rustup."""
    home = Path.home()
    for path in (Path("/opt/homebrew/bin/cargo"), home / ".cargo/bin/cargo",
                 Path("/usr/local/bin/cargo")):
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def _fixture(root, binary, pinned_source_sha):
    """Private, synthetic, deterministic single-file corpus."""
    root.mkdir(mode=0o700)
    target = root / "rg"
    shutil.copyfile(binary, target)
    target.chmod(0o700)
    corpus = root / "corpus.txt"
    with corpus.open("wb") as fp:
        fp.write(b"# Foundation benchmark corpus v1\n")
        for index in range(28000):
            hit = (b"FOUNDATION_BENCHMARK_NEEDLE_9B" if index % 97 == 0
                   else b"nonmatching_generated_text")
            fp.write(b"synthetic-row-" + str(index).encode() + b" " +
                     hit + b" xxxxxxxxxxxxx\n")
    corpus.chmod(0o600)
    if corpus.stat().st_size >= 2 * 1024 * 1024:
        raise SearchBenchmarkUnavailable("SYNTHETIC_CORPUS_TOO_LARGE")
    # The source/test SHA is review identity only; this microbenchmark never
    # becomes a runnable positive-feature 9B test or an automatic Guard grant.
    return ReviewedSearchPin(
        CANDIDATE, pinned_source_sha,
        sha256(target.read_bytes()).hexdigest(),
        sha256(corpus.read_bytes()).hexdigest(),
        sha256((Path(__file__).parent.parent /
                "tests/test_development_search_benchmark.py").read_bytes()).hexdigest(),
    )


def one_shot(checkout):
    source = _source_attestation(checkout)
    cargo = _cargo()
    if cargo is None:
        print("CANDIDATE=HOLD_CARGO_NOT_PRESENT")
        return 0
    # Must hold one canonical lease through offline build and measurements;
    # do not delay or terminate the already-running local9B worker.
    try:
        with HostComputeLease().hold(max_wait_s=0):
            with tempfile.TemporaryDirectory(prefix="foundation-rg-one-shot-") as d:
                temp = Path(d).resolve()
                target = temp / "cargo-target"
                tools = str(cargo.parent)
                env = {
                    "HOME": str(Path.home()),
                    "PATH": tools + ":/opt/homebrew/bin:/usr/bin:/bin",
                    "CARGO_NET_OFFLINE": "true",
                    "CARGO_TARGET_DIR": str(target),
                    "RUST_BACKTRACE": "0",
                }
                # No download, Cargo install, global binary write or project
                # outside this immutable source checkout and temp target dir.
                result = subprocess.run(
                    [str(cargo), "build", "--locked", "--offline",
                     "--release", "--bin", "rg"],
                    cwd=str(source), env=env, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, timeout=180, check=False,
                )
                if result.returncode != 0:
                    print("CANDIDATE=HOLD_OFFLINE_BUILD_NOT_AVAILABLE")
                    return 0
                binary = target / "release/rg"
                if (binary.is_symlink() or not binary.is_file()
                        or not os.access(binary, os.X_OK)
                        or binary.stat().st_size > 64 * 1024 * 1024):
                    print("CANDIDATE=HOLD_BUILT_BINARY_UNVERIFIED")
                    return 0
                fixture = temp / "synthetic"
                pin = _fixture(fixture, binary,
                               reviewed_offline_catalogue()[CANDIDATE].pinned_commit)
                # The original fixed-host source checksum, exact Cargo.lock,
                # toolchain version and complete dependency tree still require
                # an independent supply-chain review before ADMISSION.
                port = PinnedRipgrepBenchmark(fixture, pin)
                receipt = measured_benefit_from_fixed_port(CANDIDATE, port=port)
                if receipt is None:
                    print("CANDIDATE=HOLD_NOISY_OR_UNVERIFIED_BENEFIT")
                    return 0
                improvement = (receipt.baseline - receipt.observed) / receipt.baseline
                print("BUILD=PINNED_SOURCE_OFFLINE_TEMPORARY")
                print("BINARY_SHA256=" + pin.binary_sha256)
                print("CORPUS_SHA256=" + pin.corpus_sha256)
                print("BENCHMARK=FIVE_PAIRS_EQUAL_OUTPUT")
                print("BASELINE_MEDIAN_MS=" + str(round(receipt.baseline, 3)))
                print("TRIAL_MEDIAN_MS=" + str(round(receipt.observed, 3)))
                print("RELATIVE_GAIN_PERCENT=" + str(round(improvement * 100, 2)))
                print("CANDIDATE=" + ("POSITIVE_MEASUREMENT_ONLY"
                      if improvement >= 0.10 else "HOLD_GAIN_BELOW_THRESHOLD"))
                return 0
    except HostComputeBusy:
        print("CANDIDATE=DEFERRED_EXISTING_WORKER_BUSY")
    except HostComputeLeaseError:
        print("CANDIDATE=HOLD_LEASE_NOT_VERIFIED")
    except (OSError, ValueError, subprocess.SubprocessError,
            SearchBenchmarkUnavailable):
        print("CANDIDATE=HOLD_ISOLATED_TRIAL_UNVERIFIED")
    return 0


def main():
    if len(sys.argv) != 2 or not sys.argv[1].startswith("/"):
        print("CANDIDATE=HOLD_SOURCE_ARGUMENT_INVALID")
        return 2
    result = one_shot(sys.argv[1])
    print("DRIVE_WRITE=NO GUARD_EFFECT=NO ISSUE=NO MODEL=NO INSTALL=NO")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
