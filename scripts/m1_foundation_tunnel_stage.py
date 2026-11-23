"""Install one immutable, read-only Foundation MCP source worktree on owner M1.

This is NOT a tunnel activation or service release. It never changes the
owner's current branch, existing worktrees, Operator, Guard, 9B, KLM or Native.
Only one exact owner GitHub Issue can request this fixed source-only staging.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPO = "quest7070-dev/AI-Foundation"
OWNER = "quest7070-debug"
TITLE = "Foundation M1 Tunnel Stage: source-only"
BODY = '<!-- foundation-m1-tunnel-stage:v1:source-only -->'
SHA = re.compile(r"[0-9a-f]{40}\Z")
REQUIRED = (
    "scripts/foundation_mcp_stdio.py",
    "scripts/m1_foundation_tunnel_stdio.py",
    "scripts/m1_foundation_tunnel.py",
    "src/ai_foundation/mcp_host.py",
    "src/ai_foundation/operator_mcp_tools.py",
)


class StageDenied(RuntimeError):
    pass


def check(condition, code):
    if not condition:
        raise StageDenied(code)


def command(repo, *args, timeout=40):
    try:
        process = subprocess.run(
            ["/usr/bin/git", "-c", "core.hooksPath=/dev/null",
             "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout, check=False)
        check(process.returncode == 0 and len(process.stdout) <= 4096,
              "OWNER_SOURCE_GIT_UNAVAILABLE")
        return process.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        raise StageDenied("OWNER_SOURCE_GIT_UNAVAILABLE") from None


def private_dir(path):
    p = Path(path)
    if not p.exists() and not p.is_symlink():
        p.mkdir(mode=0o700)
    info = p.lstat()
    check(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
          and info.st_mode & 0o077 == 0 and not p.is_symlink(),
          "SOURCE_STAGE_PRIVATE_DIR_REQUIRED")
    return p


def fixed_request(event, live):
    check(type(event) is dict and event.get("action") == "opened"
          and type(event.get("repository")) is dict
          and event["repository"].get("full_name") == REPO,
          "SOURCE_STAGE_EVENT_INVALID")
    issue = event.get("issue")
    check(type(issue) is dict and type(live) is dict
          and type(issue.get("number")) is int and issue["number"] > 0
          and issue.get("title") == live.get("title") == TITLE
          and issue.get("body") == live.get("body") == BODY
          and live.get("state") == "open"
          and type(issue.get("user")) is dict
          and type(live.get("user")) is dict
          and issue["user"].get("login") == live["user"].get("login") == OWNER
          and issue["number"] == live.get("number"), "SOURCE_STAGE_OWNER_NOT_VERIFIED")
    return issue["number"]


def stage_source(*, checkout=ROOT, home=None, git=command):
    check(platform.system() == "Darwin" and
          platform.machine() in ("arm64", "aarch64") and
          os.getuid() == os.geteuid() == 501,
          "SOURCE_STAGE_M1_OWNER_REQUIRED")
    checkout = Path(checkout)
    home = Path.home() if home is None else Path(home)
    sha = git(checkout, "rev-parse", "HEAD")
    check(type(sha) is str and SHA.fullmatch(sha) is not None
          and not git(checkout, "status", "--porcelain", "--untracked-files=no"),
          "SOURCE_STAGE_PINNED_MAIN_REQUIRED")
    check(all((checkout / file).is_file() and not (checkout / file).is_symlink()
              for file in REQUIRED), "SOURCE_STAGE_REQUIRED_FILES_MISSING")

    owner_repo = home / "Develop" / "AI-Foundation"
    info = owner_repo.lstat()
    check(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
          and info.st_mode & 0o022 == 0 and not owner_repo.is_symlink(),
          "SOURCE_STAGE_OWNER_REPOSITORY_UNVERIFIED")
    check(Path(git(owner_repo, "rev-parse", "--show-toplevel")).resolve()
          == owner_repo.resolve(), "SOURCE_STAGE_OWNER_REPOSITORY_UNVERIFIED")
    # New private location. Never alter the owner's branch, checkout or service.
    base = private_dir(home / ".ai-foundation-tunnel-sources")
    target = base / sha
    if not target.exists() and not target.is_symlink():
        try:
            if git(owner_repo, "cat-file", "-t", sha) != "commit":
                raise StageDenied("SOURCE_STAGE_COMMIT_ABSENT")
        except StageDenied:
            # Import only exact main commit objects from the trusted runner.
            git(owner_repo, "fetch", "--no-tags", "--no-write-fetch-head",
                str(checkout), sha, timeout=60)
        check(git(owner_repo, "cat-file", "-t", sha) == "commit",
              "SOURCE_STAGE_COMMIT_ABSENT")
        git(owner_repo, "worktree", "add", "--detach", str(target), sha, timeout=90)
    check(target.exists() and target.is_dir() and not target.is_symlink()
          and git(target, "rev-parse", "HEAD") == sha
          and not git(target, "status", "--porcelain"),
          "SOURCE_STAGE_WORKTREE_UNVERIFIED")
    # Check only the fixed MCP entry and independent Host/Operator boundary.
    import hashlib
    for name in REQUIRED:
        a, b = checkout / name, target / name
        check(b.is_file() and not b.is_symlink()
              and hashlib.sha256(a.read_bytes()).digest()
              == hashlib.sha256(b.read_bytes()).digest(),
              "SOURCE_STAGE_PINNED_BYTES_MISMATCH")
    return {"status": "SOURCE_STAGED_VERIFIED", "revision": sha,
            "owner_branch_changed": False, "operator_changed": False,
            "local9b_changed": False, "klm_changed": False,
            "native_effects": 0, "model_calls": 0,
            "tunnel_started": False, "remote_client_verified": False}


def main():
    from m1_development_bridge import _github_api
    token = os.environ.get("GITHUB_TOKEN", "")
    number = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    issue = number.get("issue", {})
    no = issue.get("number")
    check(type(no) is int and no > 0 and
          os.environ.get("GITHUB_REPOSITORY") == REPO
          and os.environ.get("GITHUB_EVENT_NAME") == "issues",
          "SOURCE_STAGE_EVENT_INVALID")
    path = f"/repos/{REPO}/issues/{no}"
    live = _github_api("GET", path, token)
    fixed_request(number, live)
    replies = _github_api("GET", path + "/comments?per_page=100", token)
    marker = f"<!-- foundation-m1-tunnel-stage-receipt:v1:{no} -->"
    check(type(replies) is list and len(replies) <= 100
          and not any(type(row) is dict
                      and row.get("user", {}).get("login") == "github-actions[bot]"
                      and marker in row.get("body", "")
                      for row in replies), "SOURCE_STAGE_ALREADY_RECORDED")
    result = stage_source()
    report = marker + "\n" + "```json\n" + json.dumps(
        result, sort_keys=True, separators=(",", ":")) + "\n```"
    _github_api("POST", path + "/comments", token, {"body": report})
    print("SOURCE_STAGE_RECEIPT_WRITTEN")


if __name__ == "__main__":
    try:
        main()
    except (StageDenied, OSError, ValueError) as exc:
        # No paths, Git output, credentials or subprocess exception.
        print(exc.args[0] if isinstance(exc, StageDenied) else
              "SOURCE_STAGE_UNVERIFIED", file=sys.stderr)
        raise SystemExit(1)
