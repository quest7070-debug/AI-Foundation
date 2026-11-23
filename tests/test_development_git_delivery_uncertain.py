"""No-network Draft delivery acceptance for ambiguous GitHub create outcomes."""
import hashlib
import json
import subprocess

import pytest

from ai_foundation.development_git_delivery import GitDraftPublisher


def publisher_fixture(tmp_path, mode):
    target = "src/ai_foundation/fixed.py"
    source = tmp_path / target
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 3\n", encoding="utf-8")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    pub = GitDraftPublisher(
        root=tmp_path, repository="quest7070-dev/AI-Foundation",
        branch="local9b/approved-once", base="main")
    head = "a" * 40
    state = {"created": mode == "existing", "creates": 0, "lists": 0,
             "pushes": 0, "pushed": False}

    def command(*argv):
        if argv == ("git", "branch", "--show-current"):
            return pub.branch
        if argv == ("git", "ls-files", "--error-unmatch", "--", target):
            return target
        if argv == ("git", "diff", "--name-only", "HEAD"):
            return target
        if argv == ("git", "ls-files", "--others", "--exclude-standard"):
            return ""
        if argv == ("git", "diff", "--cached", "--name-only"):
            return ""
        if argv[:2] in (("git", "add"), ("git", "commit")):
            return ""
        if argv == ("git", "rev-parse", "HEAD"):
            return head
        if argv == ("git", "push", "origin", "HEAD:refs/heads/" + pub.branch):
            state["pushes"] += 1
            if mode == "push_before_failure":
                raise subprocess.CalledProcessError(1, argv)
            state["pushed"] = True
            if mode == "push_timeout_after":
                raise subprocess.TimeoutExpired(argv, 2)
            return ""
        if argv == ("git", "ls-remote", "origin",
                    "refs/heads/" + pub.branch):
            if mode == "push_remote_unavailable":
                raise subprocess.TimeoutExpired(argv, 2)
            if not state["pushed"]:
                return ""
            remote_head = "b" * 40 if mode == "push_wrong_head" else head
            return remote_head + "\trefs/heads/" + pub.branch
        if argv[:3] == ("gh", "pr", "list"):
            state["lists"] += 1
            if mode == "unreadable_before":
                raise subprocess.TimeoutExpired(argv, 1)
            if mode in ("unreadable_after", "unreadable_success") and state["creates"] == 1:
                raise subprocess.TimeoutExpired(argv, 1)
            if mode == "bad_initial_json" and state["creates"] == 0:
                return '{"not":"a list"}'
            if not state["created"]:
                return "[]"
            return json.dumps([{
                "url": "https://github.com/quest7070-dev/AI-Foundation/pull/123",
                "headRefOid": ("b" * 40 if mode == "wrong_head" else head),
                "isDraft": mode != "not_draft",
                "baseRefName": "main",
            }])
        if argv[:3] == ("gh", "pr", "create"):
            state["creates"] += 1
            if mode != "before_failure":
                state["created"] = True
            if mode in ("timeout_after", "unreadable_after",
                        "wrong_head", "not_draft"):
                raise subprocess.TimeoutExpired(argv, 2)
            if mode == "before_failure":
                raise subprocess.CalledProcessError(1, argv)
            return "https://github.com/quest7070-dev/AI-Foundation/pull/123"
        raise AssertionError("unexpected command " + repr(argv))

    pub._run = command
    return pub, target, digest, state


@pytest.mark.parametrize("mode", ["success", "timeout_after", "existing"])
def test_verified_draft_delivery_after_success_or_uncertain_create(tmp_path, mode):
    pub, target, digest, state = publisher_fixture(tmp_path, mode)
    assert pub(target=target, source_sha256=digest) == (
        "https://github.com/quest7070-dev/AI-Foundation/pull/123")
    assert state["creates"] == (0 if mode == "existing" else 1)
    assert state["lists"] == (1 if mode == "existing" else 2)


@pytest.mark.parametrize("mode", ["before_failure", "wrong_head",
                                  "not_draft", "unreadable_after"])
def test_no_repeated_create_or_false_success_when_remote_is_uncertain(tmp_path, mode):
    pub, target, digest, state = publisher_fixture(tmp_path, mode)
    with pytest.raises(RuntimeError, match="DRAFT_CREATION_UNCERTAIN"):
        pub(target=target, source_sha256=digest)
    assert state["creates"] == 1
    assert state["lists"] == 2


def test_source_mismatch_never_creates_any_remote_effect(tmp_path):
    pub, target, _, state = publisher_fixture(tmp_path, "success")
    with pytest.raises(RuntimeError, match="DELIVERY_SOURCE_CHANGED"):
        pub(target=target, source_sha256="0" * 64)
    assert state["creates"] == 0
    assert state["lists"] == 0


def test_push_transport_timeout_after_commit_is_reconciled_once(tmp_path):
    pub, target, digest, state = publisher_fixture(tmp_path, "push_timeout_after")
    assert pub(target=target, source_sha256=digest).endswith("/pull/123")
    assert state["pushes"] == 1
    assert state["creates"] == 1


@pytest.mark.parametrize("mode,expected", [
    ("push_before_failure", "REMOTE_PUSH_UNCERTAIN"),
    ("push_remote_unavailable", "REMOTE_PUSH_UNCERTAIN"),
    ("push_wrong_head", "REMOTE_HEAD_MISMATCH"),
])
def test_push_not_repeated_and_no_pr_created_without_matching_remote_head(tmp_path, mode, expected):
    pub, target, digest, state = publisher_fixture(tmp_path, mode)
    with pytest.raises(RuntimeError, match=expected):
        pub(target=target, source_sha256=digest)
    assert state["pushes"] == 1
    assert state["creates"] == 0
    assert state["lists"] == 0


@pytest.mark.parametrize("mode", ["unreadable_before", "bad_initial_json"])
def test_unverifiable_initial_pr_list_prevents_duplicate_draft_creation(tmp_path, mode):
    pub, target, digest, state = publisher_fixture(tmp_path, mode)
    with pytest.raises(RuntimeError, match="DRAFT_CREATION_UNCERTAIN"):
        pub(target=target, source_sha256=digest)
    assert state["pushes"] == 1
    assert state["creates"] == 0
    assert state["lists"] == 1


def test_successful_pr_create_without_remote_readback_is_uncertain(tmp_path):
    pub, target, digest, state = publisher_fixture(tmp_path, "unreadable_success")
    with pytest.raises(RuntimeError, match="DRAFT_CREATION_UNCERTAIN"):
        pub(target=target, source_sha256=digest)
    assert state["pushes"] == 1
    assert state["creates"] == 1
    assert state["lists"] == 2


@pytest.mark.parametrize("mode,accepted", [
    ("committed_then_timeout", True),
    ("no_commit", False),
    ("wrong_parent", False),
    ("extra_file", False),
    ("dirty_index", False),
])
def test_ambiguous_local_commit_is_verified_without_second_commit(tmp_path, mode, accepted):
    pub, target, digest, state = publisher_fixture(tmp_path, "success")
    normal = pub._run
    old_head, new_head = "1" * 40, "2" * 40
    stage = {"committed": False, "commits": 0}

    def uncertain(*argv):
        if argv == ("git", "rev-parse", "HEAD"):
            return new_head if stage["committed"] else old_head
        if argv == ("git", "commit", "-m", "fix: bounded local development task"):
            stage["commits"] += 1
            stage["committed"] = mode != "no_commit"
            raise subprocess.TimeoutExpired(argv, 1)
        if argv == ("git", "rev-parse", "HEAD^"):
            return "0" * 40 if mode == "wrong_parent" else old_head
        if argv == ("git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"):
            return target + "\nREADME.md" if mode == "extra_file" else target
        if argv == ("git", "status", "--porcelain"):
            return "M  README.md" if mode == "dirty_index" else ""
        if argv == ("git", "ls-remote", "origin",
                    "refs/heads/" + pub.branch):
            return new_head + "\trefs/heads/" + pub.branch
        if argv[:3] == ("gh", "pr", "list"):
            rows = json.loads(normal(*argv))
            for row in rows:
                row["headRefOid"] = new_head
            return json.dumps(rows)
        return normal(*argv)

    pub._run = uncertain
    if accepted:
        assert pub(target=target, source_sha256=digest).endswith("/pull/123")
        assert state["pushes"] == 1
    else:
        with pytest.raises(RuntimeError, match="LOCAL_COMMIT_UNCERTAIN"):
            pub(target=target, source_sha256=digest)
        assert state["pushes"] == 0
        assert state["creates"] == 0
    assert stage["commits"] == 1
