"""Model-free tests for a single owner-bound KLM source release contract."""
import plistlib

import pytest

from scripts.m1_github_owner_klm_main_release import (
    Denied, OWNER, PREFIX, REPO, WORKFLOW, owner_event, proposed_plist,
)


SHA = "f" * 40


def fixed_event(commit=SHA):
    return {
        "action": "opened",
        "sender": {"login": OWNER},
        "repository": {"full_name": REPO},
        "issue": {
            "number": 101, "state": "open",
            "user": {"login": OWNER},
            "title": PREFIX + commit,
            "body": "<!-- foundation-m1-klm-main-release:v1:" + commit + " -->",
        },
    }


def fixed_env(commit=SHA):
    return {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_WORKFLOW": WORKFLOW,
        "GITHUB_EVENT_NAME": "issues",
        "GITHUB_ACTOR": OWNER,
        "GITHUB_SHA": commit,
    }


def test_owner_gate_accepts_only_exact_sha_and_live_issue():
    event, env = fixed_event(), fixed_env()
    assert owner_event(event, env, live=event["issue"]) == (101, SHA)
    with pytest.raises(Denied):
        owner_event(event, {**env, "GITHUB_ACTOR": "other"})
    with pytest.raises(Denied):
        owner_event(event, env, live={**event["issue"], "body": "changed"})
    with pytest.raises(Denied):
        owner_event(event, {**env, "GITHUB_SHA": "x" * 40})
    with pytest.raises(Denied):
        owner_event(event, env, live={**event["issue"], "state": "closed"})


def test_plist_transform_changes_only_klm_entry_and_pythonpath():
    from pathlib import Path
    old = Path("/private/klm/releases/prior")
    new = Path("/private/main/staging/candidate")
    row = {
        "Label": "dev.quest7070.ai-foundation.klm-drive",
        "StartInterval": 900,
        "ProgramArguments": [
            "/opt/homebrew/bin/python3", "-B", str(old / "scripts/klm_drive_host_tick.py"),
            "--config", "/private/owner/settings.json",
        ],
        "EnvironmentVariables": {
            "PYTHONPATH": str(old) + "/src", "SYNTHETIC_CONFIG": "unchanged",
        },
    }
    converted = plistlib.loads(proposed_plist(plistlib.dumps(row), old, new))
    assert converted["ProgramArguments"][2] == str(new / "scripts/klm_drive_host_tick.py")
    assert converted["EnvironmentVariables"]["PYTHONPATH"] == str(new) + "/src"
    assert converted["ProgramArguments"][:2] == row["ProgramArguments"][:2]
    assert converted["ProgramArguments"][3:] == row["ProgramArguments"][3:]
    assert converted["EnvironmentVariables"]["SYNTHETIC_CONFIG"] == "unchanged"
    assert converted["StartInterval"] == 900
    row["Label"] = "wrong-service"
    with pytest.raises(Denied):
        proposed_plist(plistlib.dumps(row), old, new)
