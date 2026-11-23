"""One fixed existing-tunnel refresh; no real lifecycle or network calls."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import m1_guarded_tunnel_refresh as subject

SHA = "a" * 40


def test_request_requires_exact_current_issue_and_workflow():
    issue = {"number": 7, "state": "open", "user": {"login": subject.OWNER},
             "title": subject.PREFIX + SHA,
             "body": "<!-- foundation-m1-guarded-refresh:v1:" + SHA + " -->"}
    event = {"action": "opened", "sender": {"login": subject.OWNER},
             "repository": {"full_name": subject.REPO}, "issue": issue}
    env = {"GITHUB_SHA": SHA, "GITHUB_REPOSITORY": subject.REPO,
           "GITHUB_WORKFLOW": subject.WORKFLOW, "GITHUB_EVENT_NAME": "issues",
           "GITHUB_ACTOR": subject.OWNER}
    assert subject.request_identity(event, env, dict(issue)) == (7, SHA)
    for key, value in (("state", "closed"), ("body", "different"), ("number", 8)):
        with pytest.raises(subject.cutover.CutoverDenied):
            subject.request_identity(event, env, {**issue, key: value})
    with pytest.raises(subject.cutover.CutoverDenied):
        subject.request_identity(event, {**env, "GITHUB_SHA": "b" * 40}, issue)


def test_inventory_smoke_rejects_boolean_rpc_id(monkeypatch, tmp_path):
    rows = [{"jsonrpc": "2.0", "id": i, "result": {}} for i in (True, 2, 3, 4)]
    monkeypatch.setattr(subject.subprocess, "run", lambda *a, **k:
        SimpleNamespace(returncode=0, stdout="\n".join(map(json.dumps, rows))))
    with pytest.raises(subject.cutover.CutoverDenied, match="REFRESH_STDIO_UNVERIFIED"):
        subject.inventory_smoke(tmp_path)


@pytest.mark.parametrize("postcheck_fails", [False, True])
def test_refresh_claim_once_and_exact_previous_agent_rollback(monkeypatch, tmp_path, postcheck_fails):
    c = subject.cutover
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(c.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(c.platform, "machine", lambda: "arm64")
    monkeypatch.setattr(subject.os, "getuid", lambda: 501)
    monkeypatch.setattr(subject.os, "geteuid", lambda: 501)
    monkeypatch.delenv("TUNNEL_CLIENT_PROFILE_DIR", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    stage = tmp_path / ".ai-foundation-tunnel-sources" / SHA
    stage.mkdir(parents=True)
    plist = tmp_path / "agent.plist"
    plist.write_bytes(b"old-agent")
    monkeypatch.setattr(c, "plist_path", lambda: plist)
    monkeypatch.setattr(c, "stage_source", lambda: {"revision": SHA})
    monkeypatch.setattr(subject, "previous_agent", lambda: b"old-agent")
    monkeypatch.setattr(c.tunnel, "_trusted_bytes", lambda p: b"old-profile")
    monkeypatch.setattr(c.tunnel, "_existing_tunnel_id", lambda: "same-id")
    process = {"active": True, "configured": 0, "checks": 0}
    monkeypatch.setattr(c, "active_client_pids", lambda: [123] if process["active"] else [])
    def action(*args, **kwargs):
        process["configured"] += 1
        return {"status": "EXISTING_PROFILE_REPOINTED"}
    monkeypatch.setattr(c.tunnel, "owner_action", action)
    def launchctl(verb, *args):
        process["active"] = verb == "bootstrap"
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(c, "launchctl", launchctl)
    monkeypatch.setattr(c, "launch_agent", lambda *a, **k: process.update(active=True))
    def smoke(stage):
        process["checks"] += 1
        if postcheck_fails and process["checks"] == 2:
            raise ValueError("private-subprocess-error")
        return 2
    monkeypatch.setattr(subject, "inventory_smoke", smoke)
    restored = []
    monkeypatch.setattr(c, "replace_file", lambda path, raw: restored.append(raw))
    result = subject.refresh(SHA)
    assert result["status"] == ("RECONCILE_REQUIRED" if postcheck_fails else "VERIFIED")
    assert restored == ([b"old-profile", b"old-agent"] if postcheck_fails else [])
    assert "private-subprocess-error" not in str(result)
    with pytest.raises(FileExistsError):
        subject.refresh(SHA)
    assert process["configured"] == 1


@pytest.mark.parametrize("advertised", [
    set(),
    {"development_list"},
    {"development_list", "development_continue"},
    {"development_list", "development_cycle"},
    {"development_list", "development_continue", "development_cycle"},
])
def test_inventory_smoke_requires_actual_new_selfdev_tools(monkeypatch, tmp_path, advertised):
    # Only the exact live child tool catalog, not source declarations, counts.
    # This is an isolated, read-only MCP framing fixture: no CODE call or release.
    tools = [{"name": name} for name in sorted(advertised)]
    rows = [
        {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "synthetic"}}},
        {"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}},
        {"jsonrpc": "2.0", "id": 3, "result": {
            "isError": False, "content": [{"text": json.dumps({"tickets": [], "ticket_count": 0})}]}},
        {"jsonrpc": "2.0", "id": 4, "result": {"isError": False, "content": []}},
    ]
    observed = []
    def fake_child(*args, **kwargs):
        observed.append((args, kwargs))
        return SimpleNamespace(returncode=0, stdout="\n".join(map(json.dumps, rows)))
    monkeypatch.setattr(subject.subprocess, "run", fake_child)
    if {"development_list", "development_continue", "development_cycle"} <= advertised:
        assert subject.inventory_smoke(tmp_path) == 0
    else:
        reason = ("REFRESH_INVENTORY_UNAVAILABLE" if "development_list" not in advertised
                  else "REFRESH_SELFDEV_TOOLS_UNAVAILABLE")
        with pytest.raises(subject.cutover.CutoverDenied, match=reason):
            subject.inventory_smoke(tmp_path)
    assert len(observed) == 1
    assert "development_run" not in str(rows)


def _selfdev_event(head):
    from scripts import m1_selfdev_release_preflight as scoped
    return {
        "action": "synchronize",
        "pull_request": {
            "number": scoped.SELFDEV_WHOLE_PR_NUMBER,
            "user": {"login": subject.OWNER},
            "head": {
                "repo": {"full_name": subject.REPO},
                "ref": scoped.SELFDEV_WHOLE_BRANCH,
                "sha": head,
            },
            "base": {
                "ref": scoped.RUNTIME_IMPORT_BRANCH,
                "sha": scoped.SELFDEV_WHOLE_BASE_SHA,
            },
        },
    }


def test_owner_pr_refresh_without_exact_owner_issue_has_no_effect(monkeypatch):
    monkeypatch.setenv("GITHUB_WORKFLOW", subject.SELFDEV_WORKFLOW)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REPOSITORY", subject.REPO)
    monkeypatch.setattr(subject.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(stdout=SHA + "\n"))
    monkeypatch.setattr(subject, "_current_owner_pr", lambda sha, token: None)
    monkeypatch.setattr(subject, "_recent_owner_issues", lambda token: [])
    monkeypatch.setattr(subject, "refresh", lambda *a, **k:
                        pytest.fail("unapproved service mutation"))
    result = subject.owner_pr_refresh(_selfdev_event(SHA), "fixture-token")
    assert result == {"status": "OWNER_EXACT_ISSUE_REQUIRED",
                      "revision": SHA, "service_mutations": 0, "model_calls": 0}
    wrong = _selfdev_event(SHA)
    wrong["pull_request"]["base"]["sha"] = "b" * 40
    with pytest.raises(subject.cutover.CutoverDenied,
                       match="EXACT_SELFDEV_OWNER_PR_REQUIRED"):
        subject.owner_pr_refresh(wrong, "fixture-token")


def test_owner_pr_refresh_rechecks_live_issue_before_existing_cutover(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_WORKFLOW", subject.SELFDEV_WORKFLOW)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REPOSITORY", subject.REPO)
    monkeypatch.setattr(subject.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(stdout=SHA + "\n"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    issue = {"number": 42, "state": "open",
             "user": {"login": subject.OWNER},
             "title": subject.PREFIX + SHA,
             "body": "<!-- foundation-m1-guarded-refresh:v1:" + SHA + " -->"}
    monkeypatch.setattr(subject, "_current_owner_pr", lambda sha, token: None)
    monkeypatch.setattr(subject, "_recent_owner_issues", lambda token: [issue])
    calls = []
    def github(method, path, token, payload=None):
        calls.append((method, path))
        return issue if method == "GET" else {}
    monkeypatch.setattr(subject, "_github_api", github)
    def refresh(sha, *, candidate_checkout=None):
        calls.append(("REFRESH", sha))
        assert candidate_checkout == tmp_path / ".ai-foundation-tunnel-sources" / SHA
        return {"status": "VERIFIED"}
    monkeypatch.setattr(subject, "refresh", refresh)
    assert subject.owner_pr_refresh(_selfdev_event(SHA), "fixture-token") == {
        "status": "VERIFIED"}
    assert [x[0] for x in calls] == ["GET", "REFRESH", "POST"]
    wrong_user = dict(issue, user={"login": "untrusted"})
    monkeypatch.setattr(subject, "_recent_owner_issues", lambda token: [wrong_user])
    assert subject.owner_pr_refresh(_selfdev_event(SHA), "fixture-token")[
        "status"] == "OWNER_EXACT_ISSUE_REQUIRED"
    monkeypatch.setattr(subject, "_recent_owner_issues", lambda token: [issue])
    monkeypatch.setattr(subject, "_github_api", lambda *a, **k: wrong_user)
    with pytest.raises(subject.cutover.CutoverDenied, match="OWNER_ISSUE_CHANGED"):
        subject.owner_pr_refresh(_selfdev_event(SHA), "fixture-token")


def test_changed_live_pr_blocks_cutover_even_with_matching_owner_issue(monkeypatch):
    monkeypatch.setenv("GITHUB_WORKFLOW", subject.SELFDEV_WORKFLOW)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_REPOSITORY", subject.REPO)
    monkeypatch.setattr(subject.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(stdout=SHA + "\n"))
    def rejected(sha, token):
        raise subject.cutover.CutoverDenied("OWNER_PR_HEAD_CHANGED")
    monkeypatch.setattr(subject, "_current_owner_pr", rejected)
    monkeypatch.setattr(subject, "_recent_owner_issues", lambda token:
                        pytest.fail("must reject stale PR before Issue lookup"))
    monkeypatch.setattr(subject, "refresh", lambda *a, **k:
                        pytest.fail("stale PR cannot reach services"))
    with pytest.raises(subject.cutover.CutoverDenied, match="OWNER_PR_HEAD_CHANGED"):
        subject.owner_pr_refresh(_selfdev_event(SHA), "fixture-token")
