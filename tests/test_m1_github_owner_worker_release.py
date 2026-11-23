"""Owner 9B release Issue cannot be replaced by model/CI/other user text."""
import pytest
from pathlib import Path
from scripts.m1_github_owner_worker_release import owner_event, worker_queue_contract, Denied

SHA = "a" * 40
ENV = {"GITHUB_REPOSITORY": "quest7070-dev/AI-Foundation",
       "GITHUB_WORKFLOW": "Foundation M1 owner main 9B worker release",
       "GITHUB_EVENT_NAME": "issues",
       "GITHUB_ACTOR": "quest7070-debug", "GITHUB_SHA": SHA}

def request():
    return {"action": "opened", "sender": {"login": "quest7070-debug"},
            "repository": {"full_name": "quest7070-dev/AI-Foundation"},
            "issue": {"number": 739, "state": "open",
                      "user": {"login": "quest7070-debug"},
                      "title": "Foundation M1 Worker Release: " + SHA,
                      "body": "<!-- foundation-m1-worker-release:v1:" + SHA + " -->"}}

def test_exact_owner_issue():
    row = request()
    assert owner_event(row, ENV) == (739, SHA)
    assert owner_event(row, ENV, live=row["issue"]) == (739, SHA)

@pytest.mark.parametrize("change", [
    lambda x: x["issue"].update(body="run"),
    lambda x: x["issue"].update(title="Foundation M1 Worker Release: " + SHA + " "),
    lambda x: x["issue"]["user"].update(login="other"),
    lambda x: x["repository"].update(full_name="other/repo"),
    lambda x: x["sender"].update(login="other"),
    lambda x: x.update(action="edited"),
])
def test_untrusted_issue_denied(change):
    row = request()
    change(row)
    with pytest.raises(Denied):
        owner_event(row, ENV)

def test_issue_changed_or_nonowner_does_not_release():
    row = request()
    with pytest.raises(Denied):
        owner_event(row, ENV, live={**row["issue"], "body": "other"})
    with pytest.raises(Denied):
        owner_event(row, {**ENV, "GITHUB_ACTOR": "github-actions[bot]"})

def test_current_main_queue_contract_is_preserved():
    raw = (Path(__file__).resolve().parents[1] /
           "scripts/local9b_autodev_worker.py").read_bytes()
    assert worker_queue_contract(raw) == "state-root"

def test_legacy_queue_contract_does_not_claim_state_root():
    assert worker_queue_contract(b"ROOT=Path(__file__).resolve().parent") == "legacy"
    with pytest.raises(Denied):
        worker_queue_contract(b"ROOT=/untrusted")
