"""Only exact owner-created current-main Issue may request 9B release."""
import pytest
from scripts.m1_github_owner_local9b_release import owner_event, Denied

SHA = "b" * 40
ENV = {"GITHUB_REPOSITORY": "quest7070-dev/AI-Foundation",
       "GITHUB_WORKFLOW": "Foundation M1 owner main local9B release",
       "GITHUB_EVENT_NAME": "issues",
       "GITHUB_ACTOR": "quest7070-debug", "GITHUB_SHA": SHA}

def sample():
    return {"action": "opened",
            "sender": {"login": "quest7070-debug"},
            "repository": {"full_name": "quest7070-dev/AI-Foundation"},
            "issue": {"number": 730, "state": "open",
                      "user": {"login": "quest7070-debug"},
                      "title": "Foundation M1 9B Release: " + SHA,
                      "body": "<!-- foundation-m1-local9b-release:v1:" + SHA + " -->"}}

def test_exact_owner_issue():
    e = sample()
    assert owner_event(e, ENV) == (730, SHA)
    assert owner_event(e, ENV, e["issue"]) == (730, SHA)

@pytest.mark.parametrize("edit", [
    lambda x: x["issue"].update(body="run this"),
    lambda x: x["issue"].update(title="Foundation M1 9B Release: " + "a"*40),
    lambda x: x.update(action="edited"),
    lambda x: x["sender"].update(login="other"),
    lambda x: x["issue"]["user"].update(login="other"),
    lambda x: x["issue"].update(state="closed"),
    lambda x: x["issue"].update(number="730"),
    lambda x: x["repository"].update(full_name="other/repo"),
])
def test_unbound_release_denied(edit):
    e = sample()
    edit(e)
    with pytest.raises(Denied):
        owner_event(e, ENV)

def test_live_mutation_denied():
    e = sample()
    with pytest.raises(Denied):
        owner_event(e, ENV, {**e["issue"], "body": "changed"})

def test_nonowner_actor_denied():
    with pytest.raises(Denied):
        owner_event(sample(), {**ENV, "GITHUB_ACTOR": "github-actions[bot]"})


def test_local_release_requires_verified_installed_source(monkeypatch, tmp_path):
    from scripts import m1_github_owner_local9b_release as worker
    from scripts import m1_operator_release_cli as cli
    from scripts import m1_development_ticket_factory as tickets
    from scripts import m1_development_review_candidate as review
    from unittest.mock import Mock
    stage = tmp_path / SHA
    stage.mkdir()
    monkeypatch.setattr(cli, "_owner_session", lambda: None)
    monkeypatch.setattr(tickets, "_owner_local_repo", lambda: tmp_path)
    monkeypatch.setattr(review, "_installed_live_source_repo", lambda _: stage)
    monkeypatch.setattr(worker, "ROOT", stage)
    monkeypatch.setattr(worker, "observe_installed_canon", lambda _: {
        "source_main": SHA, "canon_revision": "installed-fixture"})
    transaction = Mock(return_value={"status": "WAITING_HUMAN"})
    monkeypatch.setattr(worker, "release_transaction", transaction)
    monkeypatch.setattr(worker, "live_issue", lambda *_: pytest.fail("GitHub approval not permitted"))
    assert worker.local_reconcile() == {"status": "WAITING_HUMAN"}
    assert transaction.call_args.args[0] == SHA
    assert "legacy_owner" not in transaction.call_args.kwargs
    monkeypatch.setattr(worker, "ROOT", tmp_path)
    with pytest.raises(Denied, match="INSTALLED_LOCAL_RELEASE_SOURCE_REQUIRED"):
        worker.local_reconcile()
    assert transaction.call_count == 1
