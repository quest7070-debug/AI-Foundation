"""No-model acceptance of the *existing* finite 9B Issue contract."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import local9b_real_issue_preflight as check


SOURCE = b"VALUE = 1\n"
TEST = b"def test_regression():\n    assert True\n"
BASE = "a" * 40
TARGET = "src/ai_foundation/task_result.py"
TEST_PATH = "tests/test_task_result.py"


def issue():
    contract = {
        "recipe": "python-fixed-test", "base": "local9b/example-test",
        "base_sha": BASE, "target": TARGET, "test": TEST_PATH,
        "test_sha256": hashlib.sha256(TEST).hexdigest(),
        "instruction": "Repair this independently verified failed test.",
    }
    return {
        "number": 277, "state": "open", "updated_at": "2026-11-10T01:00:00Z",
        "labels": [{"name": "foundation-autodev:ready"}],
        "body": "Approved\n" +
                "\x60\x60\x60foundation-autodev-task\n" +
                json.dumps(contract) + "\n\x60\x60\x60",
    }


class FakeAPI:
    def __init__(self):
        self.issued = issue()
        self.base_sha = BASE
        self.test_bytes = TEST
        self.log = []
        self.reads = 0
        self.on_second_issue_read = None

    def repo_path(self, path):
        return "/repos/" + check.REPOSITORY + path

    def request(self, path, method="GET", payload=None):
        assert method == "GET" and payload is None
        self.log.append(path)
        if path.endswith("/issues/277"):
            self.reads += 1
            if self.reads == 2 and self.on_second_issue_read:
                self.on_second_issue_read(self.issued)
            return copy.deepcopy(self.issued)
        if path.endswith("/commits/local9b%2Fexample-test"):
            return {"sha": self.base_sha}
        if "/contents/" in path:
            item = path.split("/contents/")[1].split("?", 1)[0]
            if item == TARGET:
                body = SOURCE
            elif item == TEST_PATH:
                body = self.test_bytes
            else:
                raise AssertionError(path)
            return {"type": "file", "path": item, "encoding": "base64",
                    "content": base64.b64encode(body).decode()}
        if path.endswith("/issues/276"):
            return {"number": 276, "state": "open"}
        raise AssertionError(path)


def test_ready_issue_uses_worker_contract_without_any_model_or_write():
    api = FakeAPI()
    receipt = check.verify_ready_issue(api, 277)
    assert receipt["status"] == check.NO_AUTH
    assert receipt["source"] == TARGET
    assert receipt["test"] == TEST_PATH
    assert receipt["test_sha256"] == hashlib.sha256(TEST).hexdigest()
    assert receipt["execution_authorized_by_preflight"] is False
    assert receipt["model_invoked"] is False
    assert receipt["baseline_reproduced"] is False
    assert api.reads == 2
    assert all(not path.endswith("/issues") for path in api.log)


def test_moved_base_and_changed_test_bytes_are_refused():
    api = FakeAPI()
    api.base_sha = "b" * 40
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_BASE_MOVED"):
        check.verify_ready_issue(api, 277)
    api = FakeAPI()
    api.test_bytes = TEST + b"# malicious edit\n"
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_TEST_SHA_DRIFT"):
        check.verify_ready_issue(api, 277)


def test_revoked_label_or_edited_body_during_read_is_refused():
    api = FakeAPI()
    api.on_second_issue_read = lambda row: row.update(
        {"labels": [{"name": "foundation-autodev:hold"}]})
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_REVISION_CHANGED"):
        check.verify_ready_issue(api, 277)
    api = FakeAPI()
    api.on_second_issue_read = lambda row: row.update(
        {"body": row["body"] + "\nChanged"})
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_REVISION_CHANGED"):
        check.verify_ready_issue(api, 277)


def test_unrelated_issue_metadata_drift_is_not_a_stable_approval():
    # A comment outside the pinned recipe can change without changing the
    # parsed task; the preflight must still reject a moving Issue snapshot.
    api = FakeAPI()
    api.on_second_issue_read = lambda row: row.update(
        {"body": row["body"] + "\\nUnreviewed appended note"})
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_REVISION_CHANGED"):
        check.verify_ready_issue(api, 277)

    api = FakeAPI()
    api.on_second_issue_read = lambda row: row.update(
        {"updated_at": "2026-11-10T01:00:01Z"})
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_REVISION_CHANGED"):
        check.verify_ready_issue(api, 277)

    api = FakeAPI()
    api.on_second_issue_read = lambda row: row.update(
        {"labels": row["labels"] + [{"name": "unreviewed-label"}]})
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_REVISION_CHANGED"):
        check.verify_ready_issue(api, 277)


def test_unclosed_dependency_cannot_pass_existing_worker_policy():
    api = FakeAPI()
    api.issued["body"] = (
        '<!-- foundation-autodev: {"paths":["' + TARGET +
        '"],"depends_on":[276]} -->\n' + api.issued["body"])
    with pytest.raises(ValueError, match="TASK_DEPENDENCY_NOT_CLOSED"):
        check.verify_ready_issue(api, 277)


def test_unsupported_or_held_task_cannot_pass():
    api = FakeAPI()
    api.issued["labels"] = [{"name": "foundation-autodev:hold"},
                            {"name": "foundation-autodev:ready"}]
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_HELD"):
        check.verify_ready_issue(api, 277)
    api = FakeAPI()
    api.issued["labels"] = []
    with pytest.raises(ValueError, match="ISSUE_PREFLIGHT_NOT_READY"):
        check.verify_ready_issue(api, 277)



def test_old_consumed_issue_requires_live_hold_and_two_stable_readbacks():
    api = FakeAPI()
    api.issued["labels"].append({"name": "foundation-autodev:hold"})
    result = check.verify_held_issue(api, 277)
    assert result["status"] == "EXPLICITLY_HELD_NOT_EXECUTABLE"
    assert result["execution_authorized_by_preflight"] is False
    assert api.reads == 2
    assert not any("/contents/" in path for path in api.log)

    api = FakeAPI()
    with pytest.raises(ValueError, match="ISSUE_EXPECTED_HOLD_MISSING"):
        check.verify_held_issue(api, 277)

    api = FakeAPI()
    api.issued["labels"].append({"name": "foundation-autodev:hold"})
    api.on_second_issue_read = lambda issue: issue.update({"body": issue["body"] + " changed"})
    with pytest.raises(ValueError, match="ISSUE_HOLD_SNAPSHOT_MOVED"):
        check.verify_held_issue(api, 277)
