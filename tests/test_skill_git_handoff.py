"""Git-backed P3 acceptance: real local Guard write, Git commit/push/readback.

The original GitDraftPublisher handles every Git operation; only 'gh'
responses are replaced by a bounded fake. No credentials or network used.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess

import pytest

from ai_foundation.core import CanonContract
from ai_foundation.development_host import LocalDevelopmentGateway, LocalDevelopmentFilesystem
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.development_git_delivery import GitDraftPublisher
from ai_foundation.skill_git_handoff import NewSkillGitDraftHandoff


RAW = (
    "---\nname: public-fixture-workflow\n"
    "description: Create a verified public JSON fixture summary.\n---\n"
    "# Public fixture workflow\n\n"
    "Use an existing host-authorized DATA tool and independently verify output.\n"
)
PATH = "skills/public-fixture-workflow/SKILL.md"


def git(root, *args):
    return subprocess.run(["git", *args], cwd=root, text=True,
                          capture_output=True, check=True).stdout.strip()


class CountedCodePort:
    def __init__(self, root):
        self.host = LocalDevelopmentFilesystem(root)
        self.writes = 0
    def execute(self, plan):
        self.writes += 1
        return self.host.execute(plan)
    def observe(self, plan):
        return self.host.observe(plan)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "work"
    origin = tmp_path / "origin.git"
    root.mkdir()
    subprocess.run(["git", "init", "--bare", str(origin)],
                   capture_output=True, check=True)
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Fixture")
    (root / "README.md").write_text("Public fixture repo.\n")
    git(root, "add", "README.md")
    git(root, "commit", "-m", "fixture: base")
    git(root, "remote", "add", "origin", str(origin))
    git(root, "push", "origin", "main")
    git(root, "checkout", "-b", "test-skill-branch")
    (root / "skills" / "public-fixture-workflow").mkdir(parents=True)

    state = GuardState()
    guard = GuardCore(state)
    disk = CountedCodePort(root)
    gateway = LocalDevelopmentGateway(
        guard, CanonContract("foundation-code", "code-v1"), disk
    )
    staged = []
    def stage_verified(*, target, content):
        assert target == PATH
        status = gateway.write(
            run_id="host-fixed-skill-draft", target=str(root / target),
            content=content, canon_revision="code-v1", paid_cost=0,
            effect_id="fixed-public-skill-file",
        )
        staged.append(status)
        return status

    pr_created = {"value": False}
    original = GitDraftPublisher._run

    def dispatch(self, *args):
        if args and args[0] == "gh":
            assert args[:3] == ("gh", "pr", args[2])
            if args[2] == "create":
                assert "--draft" in args
                pr_created["value"] = True
                return "https://github.com/example/fixture/pull/17"
            if args[2] == "list":
                if not pr_created["value"]:
                    return "[]"
                return json.dumps([{
                    "url": "https://github.com/example/fixture/pull/17",
                    "headRefOid": original(self, "git", "rev-parse", "HEAD"),
                    "isDraft": True,
                    "baseRefName": "main",
                }])
            raise AssertionError("unexpected GitHub command")
        return original(self, *args)

    monkeypatch.setattr(GitDraftPublisher, "_run", dispatch)
    handoff = NewSkillGitDraftHandoff(
        root=root, repository="example/fixture",
        branch="test-skill-branch", base="main",
        stage_verified=stage_verified,
    )
    return root, disk, guard, staged, handoff


def _publish(handoff, *, target=PATH, content=RAW,
             fingerprint="a" * 64):
    return handoff(target=target, content=content,
                   source_sha256=sha256(content.encode()).hexdigest(),
                   fingerprint=fingerprint)


def test_new_skill_actual_guard_file_git_push_and_draft_readback(repo):
    root, disk, guard, staged, handoff = repo
    ref = _publish(handoff)
    assert ref == "https://github.com/example/fixture/pull/17"
    assert staged == ["VERIFIED_COMPLETE"]
    assert sha256((root / PATH).read_bytes()).hexdigest() == sha256(RAW.encode()).hexdigest()
    assert disk.writes == 1
    assert len(guard.state.effects) == 1
    sha = git(root, "rev-parse", "HEAD")
    assert git(root, "ls-remote", "origin",
               "refs/heads/test-skill-branch").split()[0] == sha
    assert git(root, "show", "HEAD:" + PATH) == RAW.strip()


def test_unrelated_modified_file_blocks_before_guard(repo):
    root, disk, _, _, handoff = repo
    (root / "README.md").write_text("tampered")
    with pytest.raises(RuntimeError, match="SKILL_DRAFT_CHECKOUT_NOT_CLEAN"):
        _publish(handoff)
    assert disk.writes == 0


def test_unrelated_untracked_file_blocks_before_guard(repo):
    root, disk, _, _, handoff = repo
    (root / "unrelated.txt").write_text("not in scope")
    with pytest.raises(RuntimeError, match="SKILL_DRAFT_CHECKOUT_NOT_CLEAN"):
        _publish(handoff)
    assert disk.writes == 0


@pytest.mark.parametrize("target", [
    "../escape.md", "scripts/evil.py", "skills/../unsafe/SKILL.md",
    "skills/UPPER/SKILL.md", "skills/foo/other.md"
])
def test_invalid_target_denied_before_guard(repo, target):
    _, disk, _, _, handoff = repo
    with pytest.raises(ValueError, match="HOST_SKILL_DRAFT_INVALID"):
        _publish(handoff, target=target)
    assert disk.writes == 0


def test_missing_guard_acceptance_cannot_index_or_publish(repo):
    root, _, _, _, handoff = repo
    handoff.stage_verified = lambda **kw: "UNCERTAIN_RECONCILE_REQUIRED"
    with pytest.raises(RuntimeError, match="GUARDED_SKILL_DRAFT_NOT_VERIFIED"):
        _publish(handoff)
    assert not (root / PATH).exists()
    assert not git(root, "ls-files", "--error-unmatch", "--", "README.md") == ""


def test_wrong_branch_denied_before_guard(repo):
    root, disk, _, _, handoff = repo
    git(root, "checkout", "main")
    with pytest.raises(PermissionError, match="ISOLATED_BRANCH_REQUIRED"):
        _publish(handoff)
    assert disk.writes == 0


def test_mismatched_skill_frontmatter_refused_before_guard(repo):
    _, port, _, _, handoff = repo
    invalid = RAW.replace("name: public-fixture-workflow", "name: other-workflow")
    with pytest.raises(ValueError, match="invalid Agent Skills metadata"):
        _publish(handoff, content=invalid)
    assert port.writes == 0


def test_symlinked_parent_rejected_before_guard_write(repo, tmp_path):
    root, port, _, _, handoff = repo
    folder = root / "skills" / "public-fixture-workflow"
    folder.rmdir()
    other = tmp_path / "external"
    other.mkdir()
    folder.symlink_to(other, target_is_directory=True)
    # An untracked symlink is first caught by the existing clean-checkout
    # safety gate; it must not reach the Guard writer.
    with pytest.raises(RuntimeError, match="SKILL_DRAFT_CHECKOUT_NOT_CLEAN"):
        _publish(handoff)
    assert port.writes == 0
    assert not (other / "SKILL.md").exists()



@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unavailable")
def test_guard_callback_fifo_is_rejected_without_blocking_or_git(repo):
    root, _, _, _, handoff = repo
    def stage_fifo(*, target, content):
        os.mkfifo(root / target)
        return "VERIFIED_COMPLETE"
    handoff.stage_verified = stage_fifo
    with pytest.raises(PermissionError, match="SKILL_DRAFT_UNSAFE_FILE"):
        _publish(handoff)
    assert git(root, "ls-files", "--cached", "--", PATH) == ""
    # Git does not list FIFOs as untracked files; verify the node directly.
    import stat
    assert stat.S_ISFIFO((root / PATH).lstat().st_mode)
    assert git(root, "ls-files", "--others", "--exclude-standard", "--", PATH) == ""


def test_guard_callback_group_writable_is_rejected_without_git(repo):
    root, _, _, _, handoff = repo
    def stage_unsafe_permissions(*, target, content):
        candidate = root / target
        candidate.write_text(content, encoding="utf-8")
        candidate.chmod(0o664)
        return "VERIFIED_COMPLETE"
    handoff.stage_verified = stage_unsafe_permissions
    with pytest.raises(PermissionError, match="SKILL_DRAFT_UNSAFE_FILE"):
        _publish(handoff)
    assert git(root, "ls-files", "--cached", "--", PATH) == ""
    assert (root / PATH).read_text(encoding="utf-8") == RAW


def test_guard_callback_hardlink_is_rejected_without_git(repo, tmp_path):
    root, _, _, _, handoff = repo
    outside = tmp_path / "outside-skill.md"
    outside.write_text(RAW, encoding="utf-8")
    def stage_hardlink(*, target, content):
        os.link(outside, root / target)
        return "VERIFIED_COMPLETE"
    handoff.stage_verified = stage_hardlink
    with pytest.raises(PermissionError, match="SKILL_DRAFT_UNSAFE_FILE"):
        _publish(handoff)
    assert outside.read_text(encoding="utf-8") == RAW
    assert git(root, "ls-files", "--cached", "--", PATH) == ""


def test_guard_callback_symlink_is_rejected_without_git(repo, tmp_path):
    root, _, _, _, handoff = repo
    outside = tmp_path / "external-skill.md"
    outside.write_text(RAW, encoding="utf-8")
    def stage_symlink(*, target, content):
        (root / target).symlink_to(outside)
        return "VERIFIED_COMPLETE"
    handoff.stage_verified = stage_symlink
    with pytest.raises(PermissionError, match="SKILL_DRAFT_UNSAFE_FILE"):
        _publish(handoff)
    assert outside.read_text(encoding="utf-8") == RAW
    assert git(root, "ls-files", "--cached", "--", PATH) == ""
    assert git(root, "ls-files", "--others", "--exclude-standard", "--", PATH) == PATH


def test_full_p3_host_callable_source_to_git_draft_pipeline(repo, tmp_path):
    from pydantic_ai import Agent
    from pydantic_ai.messages import ModelResponse, TextPart
    from pydantic_ai.models.function import FunctionModel
    from ai_foundation.agent import PydanticAgentPort
    from ai_foundation.artifact import TextArtifactResult
    from ai_foundation.agent_skills import _parse
    from ai_foundation.skill_git_handoff import (
        run_public_skill_draft_on_existing_development_branch,
    )

    root, disk, guard, staged, _ = repo
    public = tmp_path / "public-source.md"
    public.write_text("public [3,7,11] = count 3; mean 7\n", encoding="utf-8")
    raw = public.read_bytes()
    receipt = TextArtifactResult(
        target="public-source.md",
        status="VERIFIED_COMPLETE",
        utf8_sha256=sha256(raw).hexdigest(),
        utf8_bytes=len(raw),
    )
    def model(messages, info):
        assert not info.function_tools
        return ModelResponse(parts=[TextPart(
            "1. Use the existing public fixture only.\n"
            "2. Compute with already authorized DATA.\n"
            "3. Verify the resulting artifact against the original data."
        )])
    agent = PydanticAgentPort(Agent(FunctionModel(model)))
    accepted = []
    def verify_candidate(target, content, digest):
        assert target == PATH
        assert sha256(content.encode()).hexdigest() == digest
        summary, _ = _parse(content.encode(), "public-fixture-workflow")
        assert summary.name == "public-fixture-workflow"
        accepted.append(digest)
        return "VERIFIED"

    delivery = run_public_skill_draft_on_existing_development_branch(
        root=root, repository="example/fixture", branch="test-skill-branch",
        stage_verified=_.stage_verified,
        proposal_agent=agent,
        public_objective="Summarize public array [3,7,11] with independent proof.",
        name="public-fixture-workflow",
        description="Create a verified public JSON fixture summary.",
        artifact=receipt,
        readback=lambda target: (tmp_path / target).read_text(encoding="utf-8"),
        public_source_id="public-array-v1",
        source_revision="f" * 40,
        independently_test=verify_candidate,
        base="main",
    )
    assert delivery.status == "DRAFT_PR_PRESENTED"
    assert delivery.delivery_ref.endswith("/17")
    assert len(accepted) == 1
    assert len(staged) == 1 and staged[0] == "VERIFIED_COMPLETE"
    assert disk.writes == 1 and len(guard.state.effects) == 1
    assert sha256((root / PATH).read_bytes()).hexdigest() == accepted[0]
    sha = git(root, "rev-parse", "HEAD")
    assert git(root, "ls-remote", "origin",
               "refs/heads/test-skill-branch").split()[0] == sha
