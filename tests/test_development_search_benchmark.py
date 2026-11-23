"""Host-pinned search benchmark never installs or manufactures an improvement."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import subprocess
import tempfile

import pytest

from ai_foundation.development_search_benchmark import (
    PinnedRipgrepBenchmark, ReviewedSearchPin, SearchBenchmarkUnavailable,
)
from ai_foundation.development_host_evidence import measured_benefit_from_fixed_port


def fixture():
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name).resolve()
    root.chmod(0o700)
    rg = root / "rg"
    corpus = root / "corpus.txt"
    rg.write_bytes(b"local fake executable for sandboxed benchmark\n")
    rg.chmod(0o700)
    corpus.write_bytes((b"# Foundation benchmark corpus v1\n"
                        b"example FOUNDATION_BENCHMARK_NEEDLE_9B\n") * 300)
    corpus.chmod(0o600)
    pin = ReviewedSearchPin(
        "ripgrep-14.1.1", "4649aa9700619f94cf9c66876e9549d83420e16c",
        sha256(rg.read_bytes()).hexdigest(),
        sha256(corpus.read_bytes()).hexdigest(), "a" * 64)
    return tmp, root, pin


def stub(*, changed=False, error=False):
    calls = []
    ticks = iter(i * 10_000_000 for i in range(250))
    def runner(cmd, **kw):
        calls.append((cmd, kw))
        data = b"2:example FOUNDATION_BENCHMARK_NEEDLE_9B\n"
        if changed and cmd[0].endswith("/rg"):
            data = b"WRONG\n"
        return subprocess.CompletedProcess(cmd, 1 if error else 0, data, b"")
    return runner, lambda: next(ticks), calls


def test_fixed_five_pairs_equal_outputs_without_shell_or_upload():
    tmp, root, pin = fixture()
    try:
        runner, ticks, calls = stub()
        port = PinnedRipgrepBenchmark(root, pin, runner=runner, clock_ns=ticks)
        receipt = measured_benefit_from_fixed_port(pin.candidate_id, port=port)
        assert receipt is not None
        assert receipt.metric == "latency_ms" and receipt.direction == "lower"
        assert receipt.baseline > 0 and receipt.observed > 0
        assert len(calls) == 80
        assert {x[1]["timeout"] for x in calls} == {5}
        assert all(x[1]["capture_output"] is True and x[1]["check"] is False
                   and x[1]["env"]["RIPGREP_CONFIG_PATH"] == "/dev/null"
                   for x in calls)
        assert all(isinstance(x[0], list) and "--" in x[0] for x in calls)
        assert sum(x[0][0] == "/usr/bin/grep" for x in calls) == 40
        assert sum(x[0][0].endswith("/rg") for x in calls) == 40
        # Index/repeat parity alternates caller order; no warm-cache bias.
        assert calls[0][0][0] == "/usr/bin/grep"
        assert calls[2][0][0].endswith("/rg")
    finally:
        tmp.cleanup()


def test_missing_rg_modified_binary_or_corpus_is_hold_before_any_execution():
    tmp, root, pin = fixture()
    try:
        runner, ticks, calls = stub()
        port = PinnedRipgrepBenchmark(root, pin, runner=runner, clock_ns=ticks)
        (root / "rg").unlink()
        with pytest.raises(SearchBenchmarkUnavailable):
            port.observe_pair(pin.candidate_id, 0)
        assert not calls
        (root / "rg").write_bytes(b"changed")
        (root / "rg").chmod(0o700)
        with pytest.raises(SearchBenchmarkUnavailable):
            port.observe_pair(pin.candidate_id, 0)
        assert not calls
    finally:
        tmp.cleanup()


def test_wrong_candidate_manifest_or_unpinned_test_never_runs():
    tmp, root, pin = fixture()
    try:
        for altered in (replace(pin, candidate_id="unknown"),
                        replace(pin, upstream_commit="b" * 40),
                        replace(pin, binary_sha256="not-a-sha")):
            with pytest.raises(SearchBenchmarkUnavailable):
                PinnedRipgrepBenchmark(root, altered)
        runner, ticks, calls = stub()
        port = PinnedRipgrepBenchmark(root, pin, runner=runner, clock_ns=ticks)
        with pytest.raises(SearchBenchmarkUnavailable):
            port.observe_pair("anything", 0)
        assert not calls
    finally:
        tmp.cleanup()


def test_different_search_results_never_produce_benefit_receipt():
    tmp, root, pin = fixture()
    try:
        runner, ticks, calls = stub(changed=True)
        port = PinnedRipgrepBenchmark(root, pin, runner=runner, clock_ns=ticks)
        with pytest.raises(SearchBenchmarkUnavailable):
            port.observe_pair(pin.candidate_id, 0)
        assert len(calls) == 2
    finally:
        tmp.cleanup()


def test_symlink_and_world_writable_fixture_rejected():
    tmp, root, pin = fixture()
    try:
        runner, ticks, calls = stub()
        port = PinnedRipgrepBenchmark(root, pin, runner=runner, clock_ns=ticks)
        (root / "rg").chmod(0o777)
        with pytest.raises(SearchBenchmarkUnavailable):
            port.observe_pair(pin.candidate_id, 0)
        (root / "rg").chmod(0o700)
        (root / "corpus.txt").rename(root / "real.txt")
        (root / "corpus.txt").symlink_to(root / "real.txt")
        with pytest.raises(SearchBenchmarkUnavailable):
            port.observe_pair(pin.candidate_id, 0)
        assert not calls
    finally:
        tmp.cleanup()
