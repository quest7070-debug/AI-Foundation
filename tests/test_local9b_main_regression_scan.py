"""Model-free standing regression intake: immutable main + three predelegated pairs."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from local9b_failure_candidates import (
    DELEGATED_MAIN_PAIRS, scan_standing_main_regressions,
)

SHA = "a" * 40


def owner_root(tmp_path):
    (tmp_path / "inbox").mkdir(mode=0o700)
    (tmp_path / "results").mkdir(mode=0o700)
    return tmp_path


def test_only_predelegated_pairs_publish_and_exact_main_reused(tmp_path):
    root = owner_root(tmp_path)
    calls = []
    def publish(spec, checkout, work):
        calls.append(spec)
        assert spec["base"] == "main"
        assert (spec["target"], spec["test"]) in DELEGATED_MAIN_PAIRS
        if spec["target"].endswith("task_result.py"):
            return {"status": "AUTO_READY", "url": "https://github.com/quest7070-dev/AI-Foundation/issues/100"}
        raise ValueError("NO_CONFIRMED_TEST_FAILURE")
    result = scan_standing_main_regressions(
        root, main_head=SHA, clone=lambda checkout: None,
        checkout_head=lambda checkout: SHA, publisher=publish)
    assert result["status"] == "SCANNED"
    assert len(calls) == 3
    assert sum(x["status"] == "AUTO_READY" for x in result["checks"]) == 1
    assert result["model_calls"] == 0
    again = scan_standing_main_regressions(
        root, main_head=SHA, clone=lambda checkout: (_ for _ in ()).throw(AssertionError("replayed")),
        checkout_head=lambda checkout: SHA, publisher=publish)
    assert again["status"] == "ALREADY_SCANNED"
    assert len(calls) == 3
    record = json.loads((root / "results" / ("standing-main-" + SHA + ".json")).read_text())
    assert record["main_sha"] == SHA


def test_main_movement_refuses_issue_and_keeps_uncertain_claim(tmp_path):
    root = owner_root(tmp_path)
    calls = []
    result = scan_standing_main_regressions(
        root, main_head=SHA, clone=lambda checkout: None,
        checkout_head=lambda checkout: "b" * 40,
        publisher=lambda *args: calls.append(args))
    assert result["status"] == "DEFERRED"
    assert result["reason"] == "TASK_BASE_MOVED"
    assert calls == []
    assert not (root / "results" / ("standing-main-" + SHA + ".claimed")).exists()
    retry = scan_standing_main_regressions(
        root, main_head=SHA, clone=lambda checkout: None,
        checkout_head=lambda checkout: SHA,
        publisher=lambda *args: (_ for _ in ()).throw(ValueError("NO_CONFIRMED_TEST_FAILURE")))
    assert retry["status"] == "SCANNED"


def test_base_moves_after_green_test_releases_pre_issue_claim(tmp_path):
    root = owner_root(tmp_path)
    attempts = []
    def publish(spec, checkout, work):
        attempts.append(spec["target"])
        if len(attempts) == 1:
            raise ValueError("NO_CONFIRMED_TEST_FAILURE")
        raise ValueError("TASK_BASE_MOVED")  # verified before GitHub Issue create

    first = scan_standing_main_regressions(
        root, main_head=SHA, clone=lambda p: None,
        checkout_head=lambda p: SHA, publisher=publish)
    assert first["status"] == "DEFERRED"
    assert first["reason"] == "TASK_BASE_MOVED"
    assert len(attempts) == 2
    assert not (root / "results" / ("standing-main-" + SHA + ".claimed")).exists()

    # Next tick can scan a newly stable main without reusing model attempts.
    again = scan_standing_main_regressions(
        root, main_head=SHA, clone=lambda p: None,
        checkout_head=lambda p: SHA,
        publisher=lambda *args: (_ for _ in ()).throw(ValueError(
            "NO_CONFIRMED_TEST_FAILURE")))
    assert again["status"] == "SCANNED"
    assert len(again["checks"]) == len(DELEGATED_MAIN_PAIRS)


def test_base_moves_after_actual_issue_keeps_uncertain_claim(tmp_path):
    root = owner_root(tmp_path)
    attempts = []
    def publish(spec, checkout, work):
        attempts.append(spec["target"])
        if len(attempts) == 1:
            return {"status": "AUTO_READY", "url": "https://github.com/example"}
        raise ValueError("TASK_BASE_MOVED")

    result = scan_standing_main_regressions(
        root, main_head=SHA, clone=lambda p: None,
        checkout_head=lambda p: SHA, publisher=publish)
    assert result["status"] == "RECONCILE_REQUIRED"
    assert len(attempts) == 2
    claim = root / "results" / ("standing-main-" + SHA + ".claimed")
    assert claim.is_file()
    assert scan_standing_main_regressions(root, main_head=SHA)["status"] == "RECONCILE_REQUIRED"


def test_ambiguous_issue_acknowledgement_not_retried(tmp_path):
    root = owner_root(tmp_path)
    calls = []
    def uncertain(*args):
        calls.append(1)
        raise TimeoutError("network")
    result = scan_standing_main_regressions(
        root, main_head=SHA, clone=lambda checkout: None,
        checkout_head=lambda checkout: SHA, publisher=uncertain)
    assert result["status"] == "RECONCILE_REQUIRED"
    assert len(calls) == 1
    assert scan_standing_main_regressions(root, main_head=SHA)["status"] == "RECONCILE_REQUIRED"
    assert len(calls) == 1


def test_untrusted_main_and_symlink_receipt_fail_closed(tmp_path):
    root = owner_root(tmp_path)
    assert scan_standing_main_regressions(root, main_head="not-a-sha")["status"] == "BLOCKED"
    receipt = root / "results" / ("standing-main-" + SHA + ".json")
    receipt.symlink_to(root / "inbox")
    assert scan_standing_main_regressions(root, main_head=SHA)["reason"] == "UNTRUSTED_SCAN_RECEIPT"
