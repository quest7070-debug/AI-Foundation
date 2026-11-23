"""No-model failure follow-up: the original GitHub authority is consumed once."""
import json
import os
from pathlib import Path
import stat
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from local9b_failed_run_intake import (
    CANDIDATE_SCHEMA, candidate_from_attempt, capture_failed_run_candidates,
)
import local9b_failure_candidates as publisher


ID = "issue-271-6d8fa7e30ac8af54"


def fixture(root: Path, *, status="REPAIR_BUDGET_EXHAUSTED", issue=271,
            attempts=2, feedback="three pinned tests still failing"):
    (root / "inbox").mkdir()
    (root / "results").mkdir()
    task = {
        "id": ID, "source_issue": issue, "source_digest": "a" * 64,
        "recipe": "python-fixed-test",
        "base": "local9b/notification-projection-boundary-20261107",
        "base_sha": "7ac60405b6aa3b07d927eb61aa40de6a033c9bc2",
        "target": "src/ai_foundation/notification_boundary.py",
        "test": "tests/test_local9b_notification_projection_boundary.py",
        "test_sha256": "e04d4ee1e28035997e1b8cf722f8012cfdf6d7d2de07d63ed3f4a8ca386f65d4",
        "instruction": "Fix duplicate notification projections and malformed rows",
    }
    result = {
        "status": status, "attempts": attempts,
        "unattended": True, "model": "qwen3.5:9b",
        "production_activated": False, "delivery_ref": "",
        "feedback": feedback,
    }
    (root / "inbox" / f"{ID}.json").write_text(json.dumps(task))
    (root / "results" / f"{ID}.started").write_text("start")
    (root / "results" / "issue-271.claimed").write_text(f"{ID}.json")
    result_path = root / "results" / f"{ID}.json"
    result_path.write_text(json.dumps(result))
    return result_path, task, result


def test_real_failed_result_generates_unapproved_fixed_test_candidate(tmp_path):
    f, task, result = fixture(tmp_path)
    out = candidate_from_attempt(tmp_path, f)
    assert out["base"] == task["base"]
    assert out["test"] == task["test"]
    assert out["target"] == task["target"]
    assert out["origin"]["issue"] == 271
    assert out["origin"]["schema"] == CANDIDATE_SCHEMA
    assert out["origin"]["result_status"] == result["status"]
    assert out["origin"]["attempts"] == 2
    assert out["origin"]["approval_reusable"] is False
    assert "feedback" not in out  # Do not persist private test/agent diagnostics.


def test_failure_candidate_is_private_before_publication_under_permissive_umask(tmp_path):
    fixture(tmp_path)
    old = os.umask(0)
    try:
        report = capture_failed_run_candidates(tmp_path)
    finally:
        os.umask(old)
    assert report[0]["status"] == "CAPTURED_FOR_DIAGNOSTIC_REVIEW"
    directory = tmp_path / "failures"
    published = directory / ("autodev-" + ID + ".json")
    assert stat.S_IMODE(published.stat().st_mode) == 0o600
    assert list(directory.iterdir()) == [published]
    assert capture_failed_run_candidates(tmp_path) == []


def test_persistent_candidate_is_deduplicated_without_replay(tmp_path):
    fixture(tmp_path)
    first = capture_failed_run_candidates(tmp_path)
    assert len(first) == 1
    assert first[0]["status"] == "CAPTURED_FOR_DIAGNOSTIC_REVIEW"
    assert capture_failed_run_candidates(tmp_path) == []
    files = list((tmp_path / "failures").glob("*.json"))
    assert len(files) == 1
    spec = json.loads(files[0].read_text())
    assert spec["origin"]["issue"] == 271
    assert "three pinned tests still failing" not in files[0].read_text()


@pytest.mark.parametrize("status", [
    "DRAFT_PR_PRESENTED", "WRITE_NOT_VERIFIED", "WRITE_READBACK_MISMATCH",
    "SOURCE_CHANGED_DURING_TEST", "DELIVERY_UNVERIFIED", "TESTED_CHANGE",
    "STOPPED", "UNKNOWN_STATE", None,
])
def test_no_followup_for_success_or_effect_uncertainty(tmp_path, status):
    f, _, _ = fixture(tmp_path, status=status)
    assert candidate_from_attempt(tmp_path, f) is None
    assert capture_failed_run_candidates(tmp_path) == []


@pytest.mark.parametrize("status,attempts", [
    ("NO_PROGRESS", 1), ("INVALID_PROPOSAL", 1),
    ("REPAIR_BUDGET_EXHAUSTED", 2),
])
def test_each_recognized_model_failure_is_repairable_not_authorized(tmp_path, status, attempts):
    f, _, _ = fixture(tmp_path, status=status, attempts=attempts)
    result = candidate_from_attempt(tmp_path, f)
    assert result["origin"]["result_status"] == status
    assert result["origin"]["approval_reusable"] is False


@pytest.mark.parametrize("key,value", [
    ("unattended", False), ("model", "qwen3.5:4b"),
    ("production_activated", True), ("attempts", 0), ("attempts", 99),
    ("attempts", True), ("delivery_ref", "http://unreviewed.pr"),
])
def test_forged_or_ambiguous_result_cannot_generate_followup(tmp_path, key, value):
    f, _, result = fixture(tmp_path)
    result[key] = value
    f.write_text(json.dumps(result))
    with pytest.raises(ValueError):
        candidate_from_attempt(tmp_path, f)


def test_unclaimed_result_is_not_treated_as_owned_attempt(tmp_path):
    f, _, _ = fixture(tmp_path)
    (tmp_path / "results" / "issue-271.claimed").unlink()
    with pytest.raises(ValueError, match="ORIGINAL_ATTEMPT_EVIDENCE_MISSING"):
        candidate_from_attempt(tmp_path, f)


def test_older_claim_revision_is_rejected(tmp_path):
    f, _, _ = fixture(tmp_path)
    (tmp_path / "results" / "issue-271.claimed").write_text("issue-271-other.json")
    with pytest.raises(ValueError, match="ORIGINAL_ISSUE_CLAIM_MISMATCH"):
        candidate_from_attempt(tmp_path, f)


def test_mismatched_issue_number_is_rejected(tmp_path):
    f, _, _ = fixture(tmp_path, issue=272)
    with pytest.raises(ValueError, match="ORIGINAL_ISSUE_IDENTITY_MISMATCH"):
        candidate_from_attempt(tmp_path, f)


def test_claimed_result_symlink_is_rejected(tmp_path):
    f, _, _ = fixture(tmp_path)
    p = tmp_path / "results" / f.name
    p.unlink()
    p.symlink_to(tmp_path / "inbox" / (ID + ".json"))
    with pytest.raises(ValueError, match="UNTRUSTED_AUTODEV_RECEIPT"):
        candidate_from_attempt(tmp_path, p)


def test_candidate_conflicting_rewrite_fails_closed(tmp_path):
    fixture(tmp_path)
    assert capture_failed_run_candidates(tmp_path)
    path = tmp_path / "failures" / ("autodev-" + ID + ".json")
    path.write_text("{}")
    with pytest.raises(ValueError, match="FAILURE_CANDIDATE_CHANGED_AFTER_CAPTURE"):
        capture_failed_run_candidates(tmp_path)


def test_inbox_directory_redirect_is_global_fail_closed(tmp_path):
    fixture(tmp_path)
    inbox = tmp_path / "inbox"
    moved = tmp_path / "inbox-real"
    inbox.rename(moved)
    inbox.symlink_to(moved, target_is_directory=True)
    with pytest.raises(ValueError, match="UNTRUSTED_AUTODEV_DIRECTORY"):
        capture_failed_run_candidates(tmp_path)
    assert not (tmp_path / "failures").exists()


def test_invalid_attempt_does_not_starve_later_good_receipt(tmp_path):
    # Eight malformed lower-numbered results must not consume the capture
    # budget or prevent a later, properly consumed approved Issue from being
    # proposed for *separate* review. Bad receipts are never rewritten.
    valid, task, _ = fixture(tmp_path)
    for issue in range(200, 209):
        path = tmp_path / "results" / f"issue-{issue}-0123456789abcdef.json"
        path.write_text("PRIVATE_BAD_JSON_DO_NOT_PUBLISH")
    before = valid.read_bytes()
    report = capture_failed_run_candidates(tmp_path)
    assert sum(x["status"] == "UNTRUSTED_ATTEMPT_SKIPPED"
               for x in report) == 8
    assert sum(x["status"] == "CAPTURED_FOR_DIAGNOSTIC_REVIEW"
               for x in report) == 1
    assert (tmp_path / "failures" / ("autodev-" + ID + ".json")).is_file()
    assert valid.read_bytes() == before
    assert "PRIVATE_BAD_JSON_DO_NOT_PUBLISH" not in json.dumps(report)
    assert "PRIVATE_BAD_JSON_DO_NOT_PUBLISH" not in (
        tmp_path / "failures" / ("autodev-" + ID + ".json")).read_text()
    # Existing candidate is not reopened or re-approved on a later tick.
    second = capture_failed_run_candidates(tmp_path)
    assert sum(x["status"] == "CAPTURED_FOR_DIAGNOSTIC_REVIEW"
               for x in second) == 0


def test_failure_inventory_limit_blocks_incomplete_capture(tmp_path, monkeypatch):
    from local9b_failed_run_intake import MAX_RESULT_RECEIPTS
    import local9b_failed_run_intake as intake
    fixture(tmp_path)
    monkeypatch.setattr(intake, "MAX_RESULT_RECEIPTS", 0)
    with pytest.raises(ValueError, match="AUTODEV_FAILURE_INVENTORY_INCOMPLETE"):
        capture_failed_run_candidates(tmp_path)


def test_capture_budget_leaves_later_event_for_next_tick(tmp_path, monkeypatch):
    import local9b_failed_run_intake as intake
    fixture(tmp_path)
    monkeypatch.setattr(intake, "MAX_CAPTURE_PER_TICK", 0)
    assert capture_failed_run_candidates(tmp_path) == []
    assert list((tmp_path / "failures").glob("*.json")) == []


def test_no_raw_failure_prose_in_published_candidate_issue(tmp_path, monkeypatch):
    from unittest.mock import patch
    f, task, _ = fixture(tmp_path, feedback="PRIVATE_SECRET_UNEXPECTED")
    proposal = candidate_from_attempt(tmp_path, f)
    checkout = tmp_path / "repo"
    test = checkout / task["test"]
    test.parent.mkdir(parents=True)
    test.write_text("def test_broken(): assert 1 == 2")
    proposal["origin"]["original_test_sha256"]=__import__("hashlib").sha256(test.read_bytes()).hexdigest()
    captured = []

    def fake_gh(*args):
        if args[0] == "api":
            return task["base_sha"]
        if args[:2] == ("issue", "list"):
            return "[]"
        if args[:2] == ("issue", "create"):
            captured.append((args, Path(args[args.index("--body-file") + 1]).read_text()))
            return "https://github.com/quest7070-dev/AI-Foundation/issues/999"
        raise AssertionError(args)

    with patch.object(publisher, "gh", side_effect=fake_gh), patch.object(
        publisher, "FixedPytest"
    ) as mock_fixed:
        mock_fixed.return_value.run_tests.side_effect = RuntimeError("fixed test failed")
        outcome = publisher.publish_candidate(proposal, checkout, tmp_path)

    assert outcome["status"] == "CREATED"
    args, body = captured[0]
    assert "--label" not in args
    assert "Original autonomous development Issue #271" in body
    assert "REPAIR_BUDGET_EXHAUSTED" in body
    assert "PRIVATE_SECRET_UNEXPECTED" not in body
    assert "requires a new explicit ready-label review" in body


def test_origin_metadata_cannot_declare_any_new_effect_authority(tmp_path, monkeypatch):
    from unittest.mock import patch
    f, task, _ = fixture(tmp_path)
    proposal = candidate_from_attempt(tmp_path, f)
    proposal["origin"]["result_status"] = "DRAFT_PR_PRESENTED"
    checkout = tmp_path / "repo"
    test = checkout / task["test"]
    test.parent.mkdir(parents=True)
    test.write_text("def test_broken(): assert False")
    proposal["origin"]["original_test_sha256"]=__import__("hashlib").sha256(test.read_bytes()).hexdigest()
    def fake_gh(*args):
        if args[0] == "api":
            return task["base_sha"]
        if args[:2] == ("issue", "list"):
            return "[]"
        raise AssertionError(args)
    with patch.object(publisher, "gh", side_effect=fake_gh), patch.object(
        publisher, "FixedPytest"
    ) as mock_fixed:
        mock_fixed.return_value.run_tests.side_effect = RuntimeError("fixed test failed")
        with pytest.raises(ValueError, match="INVALID_ORIGIN_ATTEMPT_RECEIPT"):
            publisher.publish_candidate(proposal, checkout, tmp_path)



@pytest.mark.parametrize("status,feedback,expected", [
    ("REPAIR_BUDGET_EXHAUSTED",
     "GENERATED_SOURCE_SYNTAX_ERROR: 'return' outside function (notification_boundary.py, line 32)",
     "GENERATED_SOURCE_SYNTAX_ERROR"),
    ("REPAIR_BUDGET_EXHAUSTED", "PROPOSAL_SYNTAX_ERROR: malformed Python",
     "PROPOSAL_SYNTAX_ERROR"),
    ("REPAIR_BUDGET_EXHAUSTED", "FAILED tests/test_example.py::test_case",
     "PINNED_TEST_FAILED"),
    ("REPAIR_BUDGET_EXHAUSTED", "3 failed, 4 passed in 0.18s",
     "PINNED_TEST_FAILED"),
    ("NO_PROGRESS", "any", "NO_PROGRESS"),
    ("INVALID_PROPOSAL", "any", "INVALID_PROPOSAL"),
    ("REPAIR_BUDGET_EXHAUSTED", "uncategorized",
     "UNCLASSIFIED_FAILURE"),
])
def test_evidence_classification_is_bounded_and_never_guesses(status,feedback,expected):
    from local9b_failed_run_intake import classify_failure
    assert classify_failure(status,feedback) == expected


def test_actual_m1_syntax_failure_class_stays_private_except_category(tmp_path):
    private="GENERATED_SOURCE_SYNTAX_ERROR: 'return' outside function (notification_boundary.py, line 32)"
    f, _, _=fixture(tmp_path, feedback=private)
    proposal=candidate_from_attempt(tmp_path, f)
    assert proposal["origin"]["failure_class"] == "GENERATED_SOURCE_SYNTAX_ERROR"
    assert private not in json.dumps(proposal)
    assert proposal["origin"]["feedback_sha256"] == __import__("hashlib").sha256(
        private.encode()).hexdigest()


@pytest.mark.parametrize("patch",[
    {"original_base_sha":"f"*40},
    {"original_test_sha256":"f"*64},
    {"approval_reusable":True},
    {"failure_class":"MODEL_SAYS_APPROVED"},
    {"feedback_sha256":"abc"},
])
def test_publisher_refuses_forged_original_receipts_before_issue_search(tmp_path,patch):
    from unittest.mock import patch as mock_patch
    f,task,_=fixture(tmp_path)
    proposal=candidate_from_attempt(tmp_path,f)
    checkout=tmp_path/"repo"
    test=checkout/task["test"]
    test.parent.mkdir(parents=True)
    test.write_text("def test_broken(): assert False")
    proposal["origin"]["original_test_sha256"]=__import__("hashlib").sha256(test.read_bytes()).hexdigest()
    proposal["origin"].update(patch)
    def fake_gh(*args):
        if args[0] == "api":
            return task["base_sha"]
        raise AssertionError("ISSUE_SEARCH_MUST_NOT_OCCUR")
    with mock_patch.object(publisher,"gh",side_effect=fake_gh):
        with pytest.raises(ValueError,match="INVALID_ORIGIN_ATTEMPT_RECEIPT"):
            publisher.publish_candidate(proposal,checkout,tmp_path)


def test_publisher_omits_untrusted_test_failure_prose(tmp_path):
    from unittest.mock import patch as mock_patch
    f,task,_=fixture(tmp_path)
    proposal=candidate_from_attempt(tmp_path,f)
    checkout=tmp_path/"repo"
    test=checkout/task["test"]
    test.parent.mkdir(parents=True)
    test.write_text("def test_broken(): assert 0")
    proposal["origin"]["original_test_sha256"]=__import__("hashlib").sha256(test.read_bytes()).hexdigest()
    captured=[]
    def fake_gh(*args):
        if args[0]=="api":
            return task["base_sha"]
        if args[:2]==("issue","list"):
            return "[]"
        if args[:2]==("issue","create"):
            captured.append(Path(args[args.index("--body-file")+1]).read_text())
            return "https://github.com/quest7070-dev/AI-Foundation/issues/998"
        raise AssertionError(args)
    with mock_patch.object(publisher,"gh",side_effect=fake_gh), mock_patch.object(
        publisher,"FixedPytest") as fixed:
        fixed.return_value.run_tests.side_effect=RuntimeError("SECRET_TEST_ASSERTION and path")
        output=publisher.publish_candidate(proposal,checkout,tmp_path)
    assert output["status"]=="CREATED"
    assert "SECRET_TEST_ASSERTION" not in captured[0]
    assert "Independent fixed-test failure digest" in captured[0]
    assert "GENERATED_SOURCE_SYNTAX_ERROR" not in captured[0]  # test fixture is generic
    assert "UNCLASSIFIED_FAILURE" in captured[0]


def test_existing_diagnostic_candidate_deduplicates_by_exact_contract_marker(tmp_path):
    from unittest.mock import patch as mock_patch
    f,task,_=fixture(tmp_path)
    proposal=candidate_from_attempt(tmp_path,f)
    checkout=tmp_path/"repo"
    test=checkout/task["test"];test.parent.mkdir(parents=True)
    test.write_text("def test_red(): assert False")
    proposal["origin"]["original_test_sha256"]=__import__("hashlib").sha256(test.read_bytes()).hexdigest()
    calls=[]
    def fake_gh(*args):
        if args[0]=="api":
            return task["base_sha"]
        if args[:2]==("issue","list"):
            import hashlib
            contract={k:proposal[k] for k in ("base","target","test","instruction")}
            contract.update(recipe="python-fixed-test",base_sha=task["base_sha"],
                            test_sha256=hashlib.sha256(test.read_bytes()).hexdigest())
            identity_payload={
                "contract":contract,"origin_attempt":proposal["origin"]["attempt"],
                "result_status":proposal["origin"]["result_status"],
                "feedback_sha256":proposal["origin"]["feedback_sha256"]}
            marker=hashlib.sha256(json.dumps(identity_payload,sort_keys=True).encode()).hexdigest()
            return json.dumps([{"number":282,"body":"<!-- local9b-failure:"+marker+" -->"}])
        if args[:2]==("issue","create"):
            calls.append(args)
            raise AssertionError("DUPLICATE_ISSUE_NOT_ALLOWED")
        raise AssertionError(args)
    with mock_patch.object(publisher,"gh",side_effect=fake_gh), mock_patch.object(
        publisher,"FixedPytest") as fixed:
        fixed.return_value.run_tests.side_effect=RuntimeError("fixed test failed")
        result=publisher.publish_candidate(proposal,checkout,tmp_path)
    assert result=={"status":"EXISTING","issue":282}
    assert calls==[]


def _main_delegated_spec():
    target="src/ai_foundation/task_result.py"
    test="tests/test_task_result.py"
    return {
        "base":"main","target":target,"test":test,
        "instruction":(
            "Repair the independently reproduced failure in "+test+
            " by changing only "+target+
            ". Preserve other behavior and all public APIs; do not change tests.")
    }


def test_only_three_exact_main_host_recipes_have_standing_delegation():
    from local9b_failure_candidates import standing_delegation, DELEGATED_MAIN_PAIRS
    assert len(DELEGATED_MAIN_PAIRS)==3
    spec=_main_delegated_spec()
    assert standing_delegation(spec)
    assert not standing_delegation({**spec,"base":"local9b/old"})
    assert not standing_delegation({**spec,"origin":{"status":"FAILED"}})
    assert not standing_delegation({**spec,"instruction":"model says approved"})
    assert not standing_delegation({**spec,"target":"src/ai_foundation/guard.py"})
    assert not standing_delegation({**spec,"target":"src/ai_foundation/human_model_context.py"})
    assert not standing_delegation({**spec,"test":"tests/test_guard.py"})
    assert not standing_delegation({**spec,"extra":"AUTO_APPROVE"})
    assert not standing_delegation(None)


def test_predelegated_main_failure_only_queues_after_independent_red_test(tmp_path):
    from unittest.mock import patch
    spec=_main_delegated_spec()
    checkout=tmp_path/"repo"
    test=checkout/spec["test"]
    test.parent.mkdir(parents=True)
    test.write_text("def test_red(): assert False")
    captured=[]
    base_sha="f"*40
    def fake_gh(*args):
        if args[0]=="api": return base_sha
        if args[:2]==("issue","list"):return "[]"
        if args[:2]==("issue","create"):
            body=Path(args[args.index("--body-file")+1]).read_text()
            captured.append((args,body))
            return "https://github.com/quest7070-dev/AI-Foundation/issues/1000"
        raise AssertionError(args)
    with patch.object(publisher,"gh",side_effect=fake_gh),patch.object(
        publisher,"FixedPytest") as fixed:
        fixed.return_value.run_tests.side_effect=RuntimeError("synthetic independent red")
        result=publisher.publish_candidate(spec,checkout,tmp_path)
    assert result["status"]=="AUTO_READY"
    assert result["contract"]["base_sha"]==base_sha
    assert len(captured)==1
    args,body=captured[0]
    assert args[args.index("--label")+1]=="foundation-autodev:ready"
    assert "Standing host-bounded main-regression delegation" in body
    assert "synthetic independent red" not in body
    assert "No merge or deployment" in body


def test_standing_recipe_without_reproduced_failure_never_creates_issue(tmp_path):
    from unittest.mock import patch
    spec=_main_delegated_spec()
    checkout=tmp_path/"repo"
    test=checkout/spec["test"];test.parent.mkdir(parents=True)
    test.write_text("def test_green(): assert True")
    def fake_gh(*args):
        if args[0]=="api": return "a"*40
        raise AssertionError("unverified candidate must not reach GitHub Issues")
    with patch.object(publisher,"gh",side_effect=fake_gh),patch.object(
        publisher,"FixedPytest") as fixed:
        fixed.return_value.run_tests.return_value="PASS"
        with pytest.raises(ValueError,match="NO_CONFIRMED_TEST_FAILURE"):
            publisher.publish_candidate(spec,checkout,tmp_path)


def test_standing_delegation_cannot_promote_existing_or_origin_attempt(tmp_path):
    from unittest.mock import patch
    spec=_main_delegated_spec()
    checkout=tmp_path/"repo"
    test=checkout/spec["test"];test.parent.mkdir(parents=True)
    test.write_text("def test_red(): assert False")
    from local9b_failure_candidates import standing_delegation
    assert not standing_delegation({**spec,"origin":{"approval_reusable":False}})
    calls=[]
    def fake_gh(*args):
        calls.append(args)
        if args[0]=="api": return "a"*40
        if args[:2]==("issue","list"):
            import hashlib
            contract={"recipe":"python-fixed-test","base":"main","base_sha":"a"*40,
                      "target":spec["target"],"test":spec["test"],
                      "test_sha256":hashlib.sha256(test.read_bytes()).hexdigest(),
                      "instruction":spec["instruction"]}
            identity=hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()
            return json.dumps([{"number":999,"body":"<!-- local9b-failure:"+identity+" -->"}])
        raise AssertionError("existing diagnostic must not be auto relabelled")
    with patch.object(publisher,"gh",side_effect=fake_gh),patch.object(
        publisher,"FixedPytest") as fixed:
        fixed.return_value.run_tests.side_effect=RuntimeError("RED")
        result=publisher.publish_candidate(spec,checkout,tmp_path)
    assert result=={"status":"EXISTING","issue":999}
    assert not any(args[:2]==("issue","create") for args in calls)


def test_failed_attempt_followup_not_deduped_against_consumed_original(tmp_path):
    from unittest.mock import patch
    f, task, _ = fixture(tmp_path)
    spec = candidate_from_attempt(tmp_path, f)
    checkout = tmp_path / "repo"
    test = checkout / task["test"]
    test.parent.mkdir(parents=True)
    test.write_text("def test_red(): assert False")
    import hashlib
    spec["origin"]["original_test_sha256"] = hashlib.sha256(test.read_bytes()).hexdigest()
    contract = {k:spec[k] for k in ("base","target","test","instruction")}
    contract.update(recipe="python-fixed-test",base_sha=task["base_sha"],
                    test_sha256=hashlib.sha256(test.read_bytes()).hexdigest())
    original_marker=hashlib.sha256(json.dumps(contract,sort_keys=True).encode()).hexdigest()
    published=[]
    def fake_gh(*args):
        if args[0]=="api":return task["base_sha"]
        if args[:2]==("issue","list"):
            return json.dumps([{"number":271,"body":"<!-- local9b-failure:"+original_marker+" -->"}])
        if args[:2]==("issue","create"):
            published.append((args,Path(args[args.index("--body-file")+1]).read_text()))
            return "https://github.com/quest7070-dev/AI-Foundation/issues/1001"
        raise AssertionError(args)
    with patch.object(publisher,"gh",side_effect=fake_gh),patch.object(
        publisher,"FixedPytest") as fixed:
        fixed.return_value.run_tests.side_effect=RuntimeError("red")
        result=publisher.publish_candidate(spec,checkout,tmp_path)
    assert result["status"]=="CREATED"
    assert len(published)==1 and "--label" not in published[0][0]
    assert ("<!-- local9b-failure:"+original_marker+" -->") not in published[0][1]
    assert "The original Issue was consumed" in published[0][1]


def test_stale_failure_candidate_does_not_starve_next_valid_candidate(tmp_path):
    from unittest.mock import patch
    import local9b_failed_run_intake as intake
    failures=tmp_path/"failures"
    results=tmp_path/"results"
    failures.mkdir();results.mkdir()
    (failures/"a-stale.json").write_text(json.dumps({"base":"main","test":"old"}))
    (failures/"b-valid.json").write_text(json.dumps({"base":"main","test":"new"}))
    published=[]
    def fake_publish(spec,checkout,work):
        if spec["test"]=="old":raise ValueError("NO_CONFIRMED_TEST_FAILURE")
        published.append(spec["test"])
        return {"status":"CREATED","url":"https://github.com/quest7070-dev/AI-Foundation/issues/1002"}
    with patch.object(intake,"capture_failed_run_candidates",return_value=[]),patch.object(
        publisher.subprocess,"run",return_value=None),patch.object(
        publisher,"publish_candidate",side_effect=fake_publish):
        report=publisher.collect_failure_candidates(tmp_path)
    assert report[0]=={"status":"BLOCKED","reason":"NO_CONFIRMED_TEST_FAILURE"}
    assert report[1]["status"]=="CREATED"
    assert published==["new"]
    assert json.loads((results/"candidate-a-stale.json").read_text())==report[0]
    assert json.loads((results/"candidate-b-valid.json").read_text())==report[1]


def test_transient_publication_retry_without_starving_later_candidates(tmp_path):
    from unittest.mock import patch
    import subprocess
    import local9b_failed_run_intake as intake

    failures=tmp_path/"failures"
    results=tmp_path/"results"
    failures.mkdir()
    results.mkdir()
    (failures/"a-temporary.json").write_text(json.dumps({"base":"main","test":"flaky"}))
    (failures/"b-valid.json").write_text(json.dumps({"base":"main","test":"valid"}))
    published=[]
    def fake_publish(spec,checkout,work):
        published.append(spec["test"])
        if spec["test"]=="flaky" and published.count("flaky")==1:
            raise subprocess.CalledProcessError(1,["gh","issue","create"])
        return {"status":"CREATED","url":"https://github.com/quest7070-dev/AI-Foundation/issues/1003"}
    with patch.object(intake,"capture_failed_run_candidates",side_effect=lambda _root: []),patch.object(
        publisher.subprocess,"run",return_value=None),patch.object(
        publisher,"publish_candidate",side_effect=fake_publish):
        first=publisher.collect_failure_candidates(tmp_path)
        assert first[0]=={"status":"RETRYABLE","reason":"CalledProcessError"}
        assert first[1]["status"]=="CREATED"
        assert not (results/"candidate-a-temporary.json").exists()
        assert (results/"candidate-b-valid.json").exists()
        second=publisher.collect_failure_candidates(tmp_path)
    assert len(second)==1 and second[0]["status"]=="CREATED"
    assert published==["flaky","valid","flaky"]
    assert json.loads((results/"candidate-a-temporary.json").read_text())==second[0]


def test_changed_main_between_clone_and_recheck_is_retryable(tmp_path):
    from unittest.mock import patch
    import local9b_failed_run_intake as intake
    failures=tmp_path/"failures"
    results=tmp_path/"results"
    failures.mkdir()
    results.mkdir()
    (failures/"a-race.json").write_text(json.dumps({"base":"main","test":"race"}))
    (failures/"b-valid.json").write_text(json.dumps({"base":"main","test":"valid"}))
    calls=[]
    def fake_publish(spec,checkout,work):
        calls.append(spec["test"])
        if spec["test"]=="race" and calls.count("race")==1:
            raise ValueError("TASK_BASE_MOVED")
        return {"status":"CREATED"}
    with patch.object(intake,"capture_failed_run_candidates",side_effect=lambda _root: []),patch.object(
        publisher.subprocess,"run",return_value=None),patch.object(
        publisher,"publish_candidate",side_effect=fake_publish):
        first=publisher.collect_failure_candidates(tmp_path)
        assert first==[{"status":"RETRYABLE","reason":"TASK_BASE_MOVED"},{"status":"CREATED"}]
        assert not (results/"candidate-a-race.json").exists()
        assert (results/"candidate-b-valid.json").exists()
        second=publisher.collect_failure_candidates(tmp_path)
    assert second==[{"status":"CREATED"}]
    assert calls==["race","valid","race"]
    assert (results/"candidate-a-race.json").exists()
