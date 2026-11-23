"""One consumed owner request refreshes the existing guarded tunnel source.

Reuse the installed profile, ID, owner LaunchAgent and guarded host. No new
tunnel, ticket, permission store, model execution or Operator release.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

if __package__:
    from . import m1_guarded_tunnel_cutover as cutover
    from .m1_development_bridge import _github_api
else:
    import m1_guarded_tunnel_cutover as cutover
    from m1_development_bridge import _github_api

REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
PREFIX = "Foundation M1 Guarded MCP Refresh: "
WORKFLOW = "Foundation M1 existing guarded MCP source refresh"
SHA = re.compile(r"[a-f0-9]{40}\Z")
SELFDEV_WORKFLOW = "Foundation M1 existing guarded MCP source refresh"


def request_identity(event, env, live):
    sha = env.get("GITHUB_SHA", "")
    issue = event.get("issue", {})
    cutover.require(
        env.get("GITHUB_REPOSITORY") == REPO
        and env.get("GITHUB_WORKFLOW") == WORKFLOW
        and env.get("GITHUB_EVENT_NAME") == "issues"
        and env.get("GITHUB_ACTOR") == OWNER
        and event.get("action") == "opened"
        and event.get("sender", {}).get("login") == OWNER
        and event.get("repository", {}).get("full_name") == REPO
        and type(sha) is str and SHA.fullmatch(sha) is not None
        and type(issue) is dict and type(live) is dict
        and type(issue.get("number")) is int and issue["number"] > 0
        and issue.get("number") == live.get("number")
        and issue.get("user", {}).get("login") == live.get("user", {}).get("login") == OWNER
        and issue.get("state") == live.get("state") == "open"
        and issue.get("title") == live.get("title") == PREFIX + sha
        and issue.get("body") == live.get("body") ==
            "<!-- foundation-m1-guarded-refresh:v1:" + sha + " -->",
        "EXACT_OWNER_REFRESH_REQUIRED")
    return issue["number"], sha


def previous_agent():
    """Refuse foreign/custom agents; preserve exact original bytes for rollback."""
    path = cutover.plist_path()
    raw = cutover.tunnel._trusted_bytes(path)
    doc = plistlib.loads(raw)
    args = doc.get("ProgramArguments", [])
    cutover.require(type(args) is list and len(args) == 4,
                    "PREVIOUS_GUARDED_AGENT_UNVERIFIED")
    source = Path(args[2])
    stage = source.parent.parent
    cutover.require(
        stage.parent == Path.home() / ".ai-foundation-tunnel-sources"
        and SHA.fullmatch(stage.name) is not None
        and source.name == "m1_guarded_tunnel.py"
        and doc == plistlib.loads(cutover.installed_agent(stage, guarded=True)),
        "PREVIOUS_GUARDED_AGENT_UNVERIFIED")
    cutover.tunnel._trusted_bytes(source)
    cutover.require(cutover.owner_managed(), "PREVIOUS_GUARDED_AGENT_NOT_RUNNING")
    return raw


def inventory_smoke(stage):
    """Actual owner child: discover inventory and call it without running work."""
    requests = [cutover._request(1, "server/discover"),
                cutover._request(2, "tools/list"),
                cutover._request(3, "tools/call", name="development_list", arguments={}),
                cutover._request(4, "tools/call", name="foundation_status", arguments={})]
    env = {key: os.environ[key] for key in ("HOME", "USER", "PATH", "TMPDIR", "LANG")
           if type(os.environ.get(key)) is str and os.environ[key]}
    child = subprocess.run([cutover.tunnel.PYTHON, "-B",
                            str(stage / "scripts/m1_guarded_tunnel_stdio.py")],
                           input="\n".join(json.dumps(row) for row in requests)+"\n",
                           env=env, capture_output=True, text=True, timeout=40, check=False)
    rows = [json.loads(line) for line in child.stdout.splitlines()]
    cutover.require(child.returncode == 0 and len(rows) == 4
                    and all(type(row) is dict and row.get("jsonrpc") == "2.0"
                            and type(row.get("id")) is int for row in rows)
                    and [row["id"] for row in rows] == [1, 2, 3, 4],
                    "REFRESH_STDIO_UNVERIFIED")
    names = {row["name"] for row in rows[1].get("result", {}).get("tools", [])}
    # Self-development release is incomplete if the new tools did not make
    # it into the *actual launched owner stdio catalog*. Operator status or a
    # list-only tunnel cannot substitute for both exact development methods.
    cutover.require("development_list" in names, "REFRESH_INVENTORY_UNAVAILABLE")
    cutover.require({"development_continue", "development_cycle"} <= names,
                    "REFRESH_SELFDEV_TOOLS_UNAVAILABLE")
    for row in rows[2:]:
        cutover.require(row.get("result", {}).get("isError") is False,
                        "REFRESH_READBACK_UNVERIFIED")
    inventory = json.loads(rows[2]["result"]["content"][0]["text"])
    cutover.require(type(inventory) is dict
                    and type(inventory.get("tickets")) is list
                    and type(inventory.get("ticket_count")) is int
                    and inventory["ticket_count"] == len(inventory["tickets"]) <= 32,
                    "REFRESH_INVENTORY_UNVERIFIED")
    return inventory["ticket_count"]


def restore(profile, original_profile, original_agent):
    cutover.launchctl("bootout", "gui/" + str(os.getuid()) + "/" + cutover.LABEL)
    # Never alter a still-running uncertain client or start a second one.
    if cutover.active_client_pids():
        return "CURRENT_CLIENT_RECONCILE_REQUIRED"
    cutover.replace_file(profile, original_profile)
    cutover.replace_file(cutover.plist_path(), original_agent)
    result = cutover.launchctl("bootstrap", "gui/" + str(os.getuid()), str(cutover.plist_path()))
    return "PREVIOUS_AGENT_RESTORED" if result.returncode == 0 else "ROLLBACK_RECONCILE_REQUIRED"


def refresh(sha, *, candidate_checkout=None):
    cutover.require(cutover.platform.system() == "Darwin"
                    and cutover.platform.machine() in ("arm64", "aarch64")
                    and os.getuid() == os.geteuid() == 501, "OWNER_M1_ONLY")
    cutover.require("TUNNEL_CLIENT_PROFILE_DIR" not in os.environ
                    and "XDG_CONFIG_HOME" not in os.environ, "CUSTOM_PROFILE_DENIED")
    if candidate_checkout is None:
        staged = cutover.stage_source()
    else:
        stage = Path.home() / ".ai-foundation-tunnel-sources" / sha
        cutover.require(candidate_checkout == stage and stage.is_dir()
                        and not stage.is_symlink(), "OWNER_STAGED_PR_REQUIRED")
        staged = cutover.stage_source(checkout=stage)
    cutover.require(staged.get("revision") == sha, "REFRESH_SOURCE_REVISION_MISMATCH")
    stage = Path.home() / ".ai-foundation-tunnel-sources" / sha
    original_agent = previous_agent()
    profile = Path.home() / ".config/tunnel-client/foundation-readonly.yaml"
    original_profile = cutover.tunnel._trusted_bytes(profile)
    original_id = cutover.tunnel._existing_tunnel_id()
    cutover.require(original_id is not None and len(cutover.active_client_pids()) == 1,
                    "EXISTING_CLIENT_NOT_UNIQUE")
    count = inventory_smoke(stage)
    # An uncertain refresh must never be retried, even through another Issue.
    marker = stage.parent / ("refresh-consumed-" + sha + ".json")
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(json.dumps({"revision": sha, "state": "CLAIMED"}))
        out.flush()
        os.fsync(out.fileno())
    try:
        configured = cutover.tunnel.owner_action("configure", checkout=stage, owner_root=stage)
        cutover.require(configured.get("status") == "EXISTING_PROFILE_REPOINTED",
                        "REFRESH_CONFIGURE_UNVERIFIED")
        cutover.require(cutover.tunnel._existing_tunnel_id() == original_id,
                        "REFRESH_TUNNEL_ID_CHANGED")
        stopped = cutover.launchctl("bootout", "gui/" + str(os.getuid()) + "/" + cutover.LABEL)
        cutover.require(stopped.returncode == 0, "REFRESH_BOOTOUT_UNVERIFIED")
        for _ in range(12):
            if not cutover.active_client_pids():
                break
            time.sleep(1)
        cutover.require(not cutover.active_client_pids(), "REFRESH_OLD_CLIENT_STILL_RUNNING")
        cutover.plist_path().unlink()
        cutover.launch_agent(stage, guarded=True)
        inventory_smoke(stage)
        for _ in range(12):
            if len(cutover.active_client_pids()) == 1:
                break
            time.sleep(1)
        cutover.require(len(cutover.active_client_pids()) == 1,
                        "REFRESH_CLIENT_NOT_UNIQUE")
        return {"status": "VERIFIED", "revision": sha, "same_registered_tunnel": True,
                "local_inventory_verified": True, "ticket_count": count,
                "remote_inventory_verified": False, "model_calls": 0}
    except Exception:
        return {"status": "RECONCILE_REQUIRED", "model_calls": 0,
                "rollback": restore(profile, original_profile, original_agent)}


def _recent_owner_issues(token):
    """Fixed read-only GitHub lookup. The PR workflow cannot grant approval."""
    cutover.require(type(token) is str and bool(token.strip()),
                    "OWNER_ISSUE_TOKEN_REQUIRED")
    suffix = (f"/repos/{REPO}/issues?state=open&sort=created"
              "&direction=desc&per_page=20")
    request = urllib.request.Request(
        "https://api.github.com" + suffix,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "foundation-owner-mcp-refresh"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(262145)
        if len(raw) > 262144:
            raise ValueError("BOUNDED_OWNER_ISSUES_REQUIRED")
        rows = json.loads(raw)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        raise cutover.CutoverDenied("OWNER_ISSUE_READBACK_UNAVAILABLE") from None
    cutover.require(type(rows) is list and len(rows) <= 100,
                    "OWNER_ISSUE_READBACK_UNVERIFIED")
    return rows


def _current_owner_pr(sha, token):
    """Independently match the LIVE exact Draft head before any M1 effects."""
    cutover.require(type(token) is str and bool(token.strip()),
                    "OWNER_PR_TOKEN_REQUIRED")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/pulls/1514",
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "foundation-owner-mcp-refresh"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(131073)
        if len(raw) > 131072:
            raise ValueError("BOUNDED_OWNER_PR_REQUIRED")
        row = json.loads(raw)
    except (OSError, ValueError, urllib.error.URLError, TimeoutError):
        raise cutover.CutoverDenied("OWNER_PR_READBACK_UNAVAILABLE") from None
    head = row.get("head", {}) if type(row) is dict else {}
    base = row.get("base", {}) if type(row) is dict else {}
    cutover.require(
        row.get("number") == 1514
        and row.get("state") == "open"
        and row.get("draft") is True
        and type(row.get("user")) is dict
        and row["user"].get("login") == OWNER
        and type(head) is dict
        and head.get("sha") == sha
        and head.get("ref") == "fix/p0-selfdev-fastlane-single-acceptance-20261121"
        and type(head.get("repo")) is dict
        and head["repo"].get("full_name") == REPO
        and type(base) is dict
        and base.get("ref") == "fix/p0-operator-review-runtime-import-root-20261121"
        and base.get("sha") == "d4ef51c2dbbe957eb5ed55b6897bd4a43d29110f",
        "OWNER_PR_HEAD_CHANGED")


def _owner_issue(issue, sha):
    return (type(issue) is dict
            and type(sha) is str and SHA.fullmatch(sha) is not None
            and type(issue.get("number")) is int and issue["number"] > 0
            and issue.get("state") == "open"
            and type(issue.get("user")) is dict
            and issue["user"].get("login") == OWNER
            and issue.get("title") == PREFIX + sha
            and issue.get("body") ==
                "<!-- foundation-m1-guarded-refresh:v1:" + sha + " -->"
            and "pull_request" not in issue)


def owner_pr_refresh(event, token):
    """Issue-authorized exact PR source; no issue implies zero service effects.

    The existing one-shot rollback/guarded-tunnel implementation is reused.
    This is deliberately NOT automatic approval from an AI or CI success.
    """
    from m1_selfdev_release_preflight import scoped_event
    current = subprocess.run(
        ["/usr/bin/git", "-C", str(cutover.ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True, timeout=5).stdout.strip()
    env = os.environ
    cutover.require(env.get("GITHUB_WORKFLOW") == SELFDEV_WORKFLOW
                    and scoped_event(event, env=env, current_sha=current),
                    "EXACT_SELFDEV_OWNER_PR_REQUIRED")
    _current_owner_pr(current, token)
    candidates = [row for row in _recent_owner_issues(token)
                  if _owner_issue(row, current)]
    if not candidates:
        return {"status": "OWNER_EXACT_ISSUE_REQUIRED", "revision": current,
                "service_mutations": 0, "model_calls": 0}
    cutover.require(len(candidates) == 1, "DUPLICATE_OWNER_ISSUE_DENIED")
    issue_number = candidates[0]["number"]
    path = f"/repos/{REPO}/issues/{issue_number}"
    live = _github_api("GET", path, token)
    cutover.require(_owner_issue(live, current)
                    and live.get("number") == issue_number,
                    "OWNER_ISSUE_CHANGED")
    _current_owner_pr(current, token)
    # Separate owner-M1 CI already staged this PR SHA with byte readback.
    # Nothing is checked out or installed until refresh() validates it again.
    stage = Path.home() / ".ai-foundation-tunnel-sources" / current
    result = refresh(current, candidate_checkout=stage)
    marker = ("<!-- foundation-m1-guarded-refresh-receipt:v1:"
              + str(issue_number) + " -->")
    _github_api("POST", path + "/comments", token, {
        "body": marker + "\n" + json.dumps(result, sort_keys=True)})
    return result


def main():
    if sys.argv[1:] == ["--owner-pr"]:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        result = owner_pr_refresh(event, os.environ.get("GITHUB_TOKEN", ""))
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in {
            "VERIFIED", "OWNER_EXACT_ISSUE_REQUIRED"} else 2
    cutover.require(not sys.argv[1:], "REFRESH_ARGUMENTS_INVALID")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    number = event.get("issue", {}).get("number")
    if type(number) is not int or number <= 0:
        raise ValueError("EXACT_OWNER_REFRESH_REQUIRED")
    token = os.environ.get("GITHUB_TOKEN", "")
    path = f"/repos/{REPO}/issues/{number}"
    live = _github_api("GET", path, token)
    _, sha = request_identity(event, os.environ, live)
    # Re-read the same exact open request immediately before the consumed effect.
    request_identity(event, os.environ, _github_api("GET", path, token))
    result = refresh(sha)
    body = "<!-- foundation-m1-guarded-refresh-receipt:v1:" + str(number) + " -->\n```json\n" + json.dumps(result, sort_keys=True) + "\n```"
    _github_api("POST", path + "/comments", token, {"body": body})
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "VERIFIED" else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        # Only fixed, public-safe reason codes; no private paths, issue content,
        # API bodies, process arguments or exception tracebacks.
        allowed = {
            "EXACT_SELFDEV_OWNER_PR_REQUIRED",
            "OWNER_PR_READBACK_UNAVAILABLE",
            "OWNER_PR_HEAD_CHANGED",
            "OWNER_PR_TOKEN_REQUIRED",
            "OWNER_ISSUE_TOKEN_REQUIRED",
            "OWNER_ISSUE_READBACK_UNAVAILABLE",
            "OWNER_ISSUE_READBACK_UNVERIFIED",
            "DUPLICATE_OWNER_ISSUE_DENIED",
            "OWNER_ISSUE_CHANGED",
            "OWNER_STAGED_PR_REQUIRED",
            "REFRESH_SOURCE_REVISION_MISMATCH",
            "REFRESH_ARGUMENTS_INVALID",
        }
        reason = (str(exc) if type(exc) is cutover.CutoverDenied
                  and str(exc) in allowed else "REFRESH_UNVERIFIED")
        print(json.dumps({"status": "BLOCKED", "reason": reason,
                          "service_mutations": 0, "model_calls": 0}))
        raise SystemExit(2)
