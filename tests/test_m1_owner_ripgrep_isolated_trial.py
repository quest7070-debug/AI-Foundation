"""Offline ripgrep M1 one-shot: side effects denied when provenance absent."""
from hashlib import sha256
from pathlib import Path
import os
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import m1_owner_ripgrep_isolated_trial as trial
from ai_foundation.development_search_benchmark import SearchBenchmarkUnavailable


def test_no_compiler_means_no_lease_no_benchmark(monkeypatch, tmp_path, capsys):
    called = []
    monkeypatch.setattr(trial, "_source_attestation",
                        lambda _: tmp_path)
    monkeypatch.setattr(trial, "_cargo", lambda: None)
    monkeypatch.setattr(trial, "HostComputeLease",
                        lambda: called.append("lease"))
    assert trial.one_shot(tmp_path) == 0
    assert "HOLD_CARGO_NOT_PRESENT" in capsys.readouterr().out
    assert called == []


def test_pin_mismatch_denies_source_before_build(monkeypatch, tmp_path):
    root = tmp_path.resolve()
    monkeypatch.setattr(trial.subprocess, "check_output",
                        lambda *a, **kw: "f" * 40 + "\n")
    with pytest.raises(SearchBenchmarkUnavailable, match="COMMIT_MISMATCH"):
        trial._source_attestation(root)


def test_private_synthetic_corpus_and_binary_are_digest_bound(tmp_path):
    root = tmp_path.resolve()
    binary = root / "fake-rg"
    binary.write_bytes(b"synthetic-test-nonexecuting-bytes")
    binary.chmod(0o700)
    fixture = root / "fixture"
    pin = trial._fixture(fixture, binary,
                          "4649aa9700619f94cf9c66876e9549d83420e16c")
    assert pin.candidate_id == "ripgrep-14.1.1"
    assert pin.valid()
    assert sha256((fixture / "rg").read_bytes()).hexdigest() == pin.binary_sha256
    assert sha256((fixture / "corpus.txt").read_bytes()).hexdigest() == pin.corpus_sha256
    assert 0 < (fixture / "corpus.txt").stat().st_size < 2 * 1024 * 1024
    assert (fixture.stat().st_mode & 0o077) == 0
    (fixture / "corpus.txt").write_bytes(b"changed")
    from ai_foundation.development_search_benchmark import PinnedRipgrepBenchmark
    with pytest.raises(SearchBenchmarkUnavailable):
        PinnedRipgrepBenchmark(fixture, pin).observe_pair("ripgrep-14.1.1", 0)


def test_invalid_cli_argument_cannot_run_synthetic_trial(monkeypatch, capsys):
    invoked = []
    monkeypatch.setattr(sys, "argv", ["trial", "../outside"])
    monkeypatch.setattr(trial, "one_shot",
                        lambda _: invoked.append(True))
    assert trial.main() == 2
    assert not invoked
    assert "HOLD_SOURCE_ARGUMENT_INVALID" in capsys.readouterr().out
