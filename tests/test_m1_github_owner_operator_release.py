"""An Issue from any other actor, ref or body never requests deployment."""
from scripts.m1_github_owner_operator_release import event_identity, ReleaseDenied
import pytest

SHA = "a" * 40
PREFIX = "Foundation M1 Operator Release: "
BODY = "<!-- foundation-m1-operator-release:v1:" + SHA + " -->"
ENV = {"GITHUB_REPOSITORY": "quest7070-dev/AI-Foundation",
       "GITHUB_WORKFLOW": "Foundation M1 owner main Operator release",
       "GITHUB_EVENT_NAME": "issues", "GITHUB_ACTOR": "quest7070-debug",
       "GITHUB_SHA": SHA}

def request():
    return {"action": "opened", "sender": {"login": "quest7070-debug"},
            "repository": {"full_name": "quest7070-dev/AI-Foundation"},
            "issue": {"number": 725, "state": "open",
                      "user": {"login": "quest7070-debug"},
                      "title": PREFIX + SHA, "body": BODY}}

def test_exact_owner_request_identity():
    event = request()
    assert event_identity(event, ENV) == (725, SHA)
    assert event_identity(event, ENV, live=event["issue"]) == (725, SHA)

@pytest.mark.parametrize("edit", [
    lambda e: e["issue"].update(body="release"),
    lambda e: e["issue"].update(title=PREFIX + SHA + " "),
    lambda e: e.update(action="edited"),
    lambda e: e["sender"].update(login="other"),
    lambda e: e["repository"].update(full_name="other/repo"),
    lambda e: e["issue"]["user"].update(login="other"),
    lambda e: e["issue"].update(state="closed"),
    lambda e: e["issue"].update(number="725"),
])
def test_invalid_request_denied(edit):
    event = request()
    edit(event)
    with pytest.raises(ReleaseDenied):
        event_identity(event, ENV)

def test_live_issue_drifts_are_denied():
    event = request()
    with pytest.raises(ReleaseDenied):
        event_identity(event, ENV, live={**event["issue"], "body": "changed"})

def test_non_owner_workflow_denied():
    with pytest.raises(ReleaseDenied):
        event_identity(request(), {**ENV, "GITHUB_ACTOR": "github-actions[bot]"})


def test_owner_release_receipt_redacts_errors_and_binds_only_commit():
    from scripts.m1_github_owner_operator_release import _receipt_body
    denied=_receipt_body(725,{"status":"BLOCKED",
        "reason":"PRIVATE_OWNER_TOKEN_IN_ERROR"})
    assert "PRIVATE" not in denied
    assert "RELEASE_UNVERIFIED" in denied
    assert "foundation-m1-operator-release-receipt:v1:725" in denied
    assert "\\n" not in denied
    accepted=_receipt_body(725,{"status":"VERIFIED","main":SHA,
        "secret":"PRIVATE_OWNER_CONTENT"})
    assert SHA in accepted and "PRIVATE_OWNER_CONTENT" not in accepted
    assert '"operator_only": true' in accepted
