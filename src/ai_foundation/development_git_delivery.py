"""Git-backed Draft delivery for CodingSpecialist.develop; caller owns checkout."""
from hashlib import sha256
from pathlib import Path
import json
import subprocess


class GitDraftPublisher:
    """Publish one verified tracked source file from an existing isolated branch.

    Requires a clean base except for the reviewed source. Does not merge or
    select a repository, branch, credential or command from model output.
    """
    def __init__(self, *, root, repository, branch, base="main"):
        self.root = Path(root).resolve(strict=True)
        self.repository = repository
        self.branch = branch
        self.base = base

    def _run(self, *args):
        return subprocess.run(args, cwd=self.root, check=True, capture_output=True,
                              text=True, timeout=60).stdout.strip()

    def __call__(self, *, target, source_sha256):
        path = (self.root / target).resolve(strict=True)
        relative = path.relative_to(self.root).as_posix()
        if sha256(path.read_bytes()).hexdigest() != source_sha256:
            raise RuntimeError("DELIVERY_SOURCE_CHANGED")
        if self.branch in ("main", "master", self.base):
            raise ValueError("ISOLATED_BRANCH_REQUIRED")
        if self._run("git", "branch", "--show-current") != self.branch:
            raise RuntimeError("DELIVERY_BRANCH_MISMATCH")
        self._run("git", "ls-files", "--error-unmatch", "--", relative)
        changed = self._run("git", "diff", "--name-only", "HEAD").splitlines()
        if changed != [relative] or self._run("git", "ls-files", "--others", "--exclude-standard"):
            raise RuntimeError("DELIVERY_CHECKOUT_NOT_ISOLATED")
        if self._run("git", "diff", "--cached", "--name-only"):
            raise RuntimeError("DELIVERY_INDEX_NOT_EMPTY")
        before_commit = self._run("git", "rev-parse", "HEAD")
        self._run("git", "add", "--", relative)
        commit_uncertain = False
        try:
            self._run("git", "commit", "-m", "fix: bounded local development task")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            commit_uncertain = True
        try:
            head = self._run("git", "rev-parse", "HEAD")
            if commit_uncertain:
                # A lost git-commit response can mean it committed successfully.
                # Prove one direct child, exactly one changed tracked source,
                # and a clean checkout before permitting any remote effects.
                if (head == before_commit
                        or self._run("git", "rev-parse", "HEAD^") != before_commit
                        or self._run("git", "diff-tree", "--no-commit-id",
                                     "--name-only", "-r", "HEAD").splitlines() != [relative]
                        or self._run("git", "status", "--porcelain")):
                    raise RuntimeError("LOCAL_COMMIT_UNCERTAIN")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            raise RuntimeError("LOCAL_COMMIT_UNCERTAIN") from None
        if sha256(path.read_bytes()).hexdigest() != source_sha256:
            raise RuntimeError("DELIVERY_SOURCE_CHANGED")
        # A transport failure after push may still have published the commit.
        # Never issue a second push merely because the response was lost.
        # The existing exact remote HEAD check is the sole acceptance proof.
        push_uncertain = False
        try:
            self._run("git", "push", "origin", "HEAD:refs/heads/" + self.branch)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            push_uncertain = True
        try:
            remote = self._run("git", "ls-remote", "origin",
                               "refs/heads/" + self.branch)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            raise RuntimeError("REMOTE_PUSH_UNCERTAIN") from None
        if not remote.split() or remote.split()[0] != head:
            raise RuntimeError(
                "REMOTE_PUSH_UNCERTAIN" if push_uncertain
                else "REMOTE_HEAD_MISMATCH")
        try:
            rows = json.loads(self._run("gh", "pr", "list", "--repo", self.repository,
                "--head", self.branch, "--state", "open", "--json", "url,headRefOid,isDraft,baseRefName"))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError,
                ValueError, TypeError):
            # Cannot prove that a Draft is absent. Creating another now would
            # risk a duplicate; this result is not a model timeout.
            raise RuntimeError("DRAFT_CREATION_UNCERTAIN") from None
        if type(rows) is not list:
            raise RuntimeError("DRAFT_CREATION_UNCERTAIN")
        # A create timeout/transport error is not proof of failure. GitHub
        # may already have committed the Draft, and this one-shot model task
        # must never blindly repeat a remote create. Re-read the exact branch
        # and accept only one Draft with matching remote HEAD and base.
        create_uncertain = False
        if not rows:
            try:
                self._run("gh", "pr", "create", "--repo", self.repository,
                    "--head", self.branch, "--base", self.base, "--draft",
                    "--title", "Local development: verified source change",
                    "--body", "Bounded local edit and fixed acceptance tests completed. Source SHA256: " + source_sha256)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
                create_uncertain = True
            try:
                rows = json.loads(self._run("gh", "pr", "list", "--repo", self.repository,
                    "--head", self.branch, "--state", "open", "--json", "url,headRefOid,isDraft,baseRefName"))
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError,
                    ValueError, TypeError):
                # A successful create acknowledgement without an exact remote
                # readback remains uncertain too. No duplicate create.
                raise RuntimeError("DRAFT_CREATION_UNCERTAIN") from None
        if (type(rows) is not list or len(rows) != 1
                or type(rows[0]) is not dict
                or rows[0].get("headRefOid") != head
                or rows[0].get("isDraft") is not True
                or rows[0].get("baseRefName") != self.base
                or type(rows[0].get("url")) is not str
                or not rows[0]["url"].startswith(
                    "https://github.com/" + self.repository + "/pull/")):
            raise RuntimeError(
                "DRAFT_CREATION_UNCERTAIN" if create_uncertain
                else "DRAFT_PR_READBACK_MISMATCH")
        return rows[0]["url"]
