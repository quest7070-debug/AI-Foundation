"""Bounded one-shot KLM retry: synthetic SQLite and exact owner intent only."""
import json
import os
from pathlib import Path
import sqlite3
import sys
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import m1_klm_failed_retry_once as r


def fixture_db(tmp_path):
    path = tmp_path / "work.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE klm_drive_intake (
            intake_id TEXT PRIMARY KEY, job_id TEXT, pointer TEXT, source_revision TEXT)""")
        db.execute("""CREATE TABLE work_steps (
            job_id TEXT, position INTEGER, name TEXT, status TEXT, result TEXT,
            updated_at REAL, PRIMARY KEY(job_id,position))""")
        for i, status, result in (
            (1, "FAILED", '{"error_type":"TimeoutError"}'),
            (2, "FAILED", '{"error_type":"ValueError"}'),
        ):
            key = str(i) * 64
            job = "klm-drive:" + key
            db.execute("INSERT INTO klm_drive_intake VALUES (?,?,?,?)",
                       (key, job, json.dumps({"record_id": key}), "row:revision"))
            db.execute("INSERT INTO work_steps VALUES (?,0,\'klm-readonly\',?,?,?)",
                       (job, status, result, float(i)))
    os.chmod(path, 0o600)
    return path


def test_selects_one_value_error_without_mutating_history(tmp_path):
    path = fixture_db(tmp_path)
    selected, count = r.inspect_oldest_failed(path)
    assert count == 2
    assert selected["intake_id"] == "2" * 64
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM work_steps WHERE status='FAILED'").fetchone()[0] == 2


def test_rejects_active_intake_and_untrusted_db(tmp_path):
    path = fixture_db(tmp_path)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE work_steps SET status='PLANNED' WHERE job_id=?", ("klm-drive:" + "1" * 64,))
    with pytest.raises(r.Denied, match="RETRY_ACTIVE_INTAKE_PRESENT"):
        r.inspect_oldest_failed(path)
    os.chmod(path, 0o644)
    with pytest.raises(r.Denied, match="RETRY_PRIVATE_WORK_DB_REQUIRED"):
        r.inspect_oldest_failed(path)


def test_only_current_verified_fairness_release_owner_request():
    from pathlib import Path
    assert r.release.NEW == "799a1ad8a0584da6e2a852a363e5edfd61454bf8"
    assert r.TITLE == "Foundation KLM retry one FAILED: 799a1ad8"
    assert r.release.NEW in r.BODY
    assert "2026-11-13-owner-continue" in r.BODY
    assert "cd12f042" not in r.BODY
    workflow = (Path(__file__).resolve().parents[1] /
                ".github/workflows/m1-klm-failed-retry-once.yml").read_text()
    assert "Foundation KLM retry one FAILED: 799a1ad8" in workflow
    assert "Foundation KLM retry one FAILED: cd12f042" not in workflow


def test_exact_owner_issue_and_live_receipt_replay_blocked():
    issue = {"number": 10, "user": {"login": r.release.OWNER}, "state": "open",
             "title": r.TITLE, "body": r.BODY}
    event = {"action": "opened", "repository": {"full_name": r.REPO}, "issue": issue}
    with mock.patch.object(r.bridge, "_github_api", side_effect=[issue, []]):
        assert r.check_issue(event, "synthetic-token")[0] == 10
    with mock.patch.object(r.bridge, "_github_api", side_effect=[
        issue, [{"body": r.MARKER + "10 -->", "user": {"login": "github-actions[bot]"}}]
    ]):
        with pytest.raises(r.Denied, match="RETRY_ALREADY_RECEIPTED"):
            r.check_issue(event, "synthetic-token")
    with mock.patch.object(r.bridge, "_github_api") as api:
        modified = {**issue, "body": issue["body"].replace("one-failed-no-effect", "all-failed")}
        with pytest.raises(r.Denied, match="RETRY_OWNER_INTENT_INVALID"):
            r.check_issue({**event, "issue": modified}, "synthetic-token")
        api.assert_not_called()
    with mock.patch.object(r.bridge, "_github_api") as api:
        old = {**issue, "title": "Foundation KLM retry one FAILED: cd12f042"}
        with pytest.raises(r.Denied, match="RETRY_OWNER_INTENT_INVALID"):
            r.check_issue({**event, "issue": old}, "synthetic-token")
        api.assert_not_called()

def test_reads_exact_pinned_script_not_default_branch_without_calling_main(tmp_path):
    entry = tmp_path / r.release.NEW / "scripts" / "klm_drive_host_tick.py"
    entry.parent.mkdir(parents=True)
    entry.write_text(
        "def existing_work_db(config, root):\n"
        "    return ('PINNED', config, root)\n"
        "if __name__ == '__main__':\n"
        "    raise AssertionError('MUST_NOT_EXECUTE_MAIN')\n"
    )
    # The fixture emulates a code-fingerprint validated release after
    # check_release; this helper never authenticates or changes source data.
    result = r.pinned_existing_work_db(tmp_path)({"work_db":"work.sqlite"}, "root")
    assert result == ("PINNED", {"work_db":"work.sqlite"}, "root")
    assert "klm_drive_host_tick" not in sys.modules


def test_rejects_missing_verified_entry_and_missing_helper(tmp_path):
    with pytest.raises(r.Denied, match="RETRY_PINNED_KLM_ENTRY_MISSING"):
        r.pinned_existing_work_db(tmp_path)
    entry = tmp_path / r.release.NEW / "scripts" / "klm_drive_host_tick.py"
    entry.parent.mkdir(parents=True)
    entry.write_text("VALUE = 1\n")
    with pytest.raises(r.Denied, match="RETRY_PINNED_DB_HELPER_MISSING"):
        r.pinned_existing_work_db(tmp_path)


def test_recovery_stage_log_is_fixed_and_no_dynamic_source_text(capsys):
    r.trace_stage("INTENT_STAGE_BEGIN")
    assert capsys.readouterr().out.strip() == "KLM_RETRY_STAGE:INTENT_STAGE_BEGIN"
    with pytest.raises(r.Denied, match="RETRY_STAGE_UNTRUSTED"):
        r.trace_stage("private-data")
    assert capsys.readouterr().out == ""


def test_runner_stages_intent_only_without_requeueing_original(tmp_path):
    path = fixture_db(tmp_path)
    selected, count = r.inspect_oldest_failed(path)
    assert count == 2
    assert r.stage_retry_intent(path, selected) == "STAGED_ONE_FOR_OWNER_VERIFY"
    with sqlite3.connect(path) as db:
        original = db.execute(
            "SELECT status FROM work_steps WHERE job_id=?",
            ("klm-drive:" + selected["intake_id"],)).fetchone()[0]
        staged = db.execute(
            "SELECT status,name FROM work_steps WHERE job_id=?",
            ("klm-retry-intent:" + selected["intake_id"],)).fetchone()
    assert original == "FAILED"
    assert staged == ("PLANNED", "klm-source-verified-retry")
    assert r.stage_retry_intent(path, selected) == "INTENT_ALREADY_PRESENT"
    with pytest.raises(r.Denied, match="RETRY_OTHER_INTENT_PENDING"):
        r.stage_retry_intent(path, {"intake_id":"1"*64})
    with pytest.raises(r.Denied, match="RETRY_EXACT_INTAKE_REQUIRED"):
        r.stage_retry_intent(path, {"intake_id":"PRIVATE_SOURCE_TEXT"})

