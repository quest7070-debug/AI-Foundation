"""Actual committed test/target readback, without a model or network."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import os
import json
import time
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ai_foundation.development_improvement_contract import HostImprovementScope
from m1_owner_improvement_source import observed_feature_test
from m1_owner_candidate_admission import prepare_reviewed_improvement
from ai_foundation.development_admission import (
    CostReceipt, BenefitReceipt, HardwareReceipt, HostContract, _plan,
)


def git(root, *args):
    return subprocess.check_output(
        ["/usr/bin/git", "-C", str(root), *args],
        text=True, timeout=10,
    ).strip()


def checkout_fixture(tmp_path):
    # macOS /var is an OS-managed alias of /private/var; the production
    # auditor deliberately requires a canonical absolute owner checkout.
    repo = (tmp_path / "reviewed").resolve()
    repo.mkdir()
    git(repo, "init", "-q", "-b", "local9b/reviewed-positive-feature")
    target = repo / "src/ai_foundation/task_result.py"
    test = repo / "tests/test_task_result.py"
    target.parent.mkdir(parents=True)
    test.parent.mkdir()
    target.write_text("def feature():\n    return 1\n")
    test.write_text("from ai_foundation.task_result import feature\n"
                    "def test_feature(): assert feature()==2\n")
    git(repo, "add", "--", "src/ai_foundation/task_result.py",
        "tests/test_task_result.py")
    git(repo, "-c", "user.name=Host Fixed Test",
        "-c", "user.email=host@localhost", "commit", "-q", "-m",
        "reviewed fixed positive feature acceptance")
    scope = HostImprovementScope(
        "ripgrep-14.1.1", "local9b/reviewed-positive-feature",
        git(repo, "rev-parse", "HEAD"), "src/ai_foundation/task_result.py",
        "tests/test_task_result.py", sha256(test.read_bytes()).hexdigest(),
    )
    return repo, scope


def test_pinned_reviewed_positive_feature_branch_is_read_only(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    before = sorted((str(p.relative_to(repo)), p.read_bytes()) for p in
                    repo.rglob("*.py"))
    observed = observed_feature_test(scope, repo)
    assert observed == scope.acceptance_sha256, {
        "canonical": repo == repo.resolve(strict=True),
        "owner": repo.lstat().st_uid == os.getuid(),
        "root_mode_restricted": (repo.lstat().st_mode & 0o022) == 0,
        "target_regular": (repo / scope.target).is_file(),
        "test_regular": (repo / scope.acceptance_test).is_file(),
        "target_owner": (repo / scope.target).lstat().st_uid == os.getuid(),
        "test_owner": (repo / scope.acceptance_test).lstat().st_uid == os.getuid(),
        "target_size_ok": 0 < (repo / scope.target).lstat().st_size <= 65536,
        "test_size_ok": 0 < (repo / scope.acceptance_test).lstat().st_size <= 65536,
        "target_has_symlink_component": any(
            (repo.joinpath(*Path(scope.target).parts[:n])).is_symlink()
            for n in range(1, len(Path(scope.target).parts) + 1)),
        "test_has_symlink_component": any(
            (repo.joinpath(*Path(scope.acceptance_test).parts[:n])).is_symlink()
            for n in range(1, len(Path(scope.acceptance_test).parts) + 1)),
        "branch": git(repo, "branch", "--show-current") == scope.base_branch,
        "commit": git(repo, "rev-parse", "HEAD") == scope.base_sha,
        "tracked_target": git(repo, "ls-files", "--error-unmatch", "--",
                              scope.target) == scope.target,
        "tracked_test": git(repo, "ls-files", "--error-unmatch", "--",
                            scope.acceptance_test) == scope.acceptance_test,
        "clean": subprocess.run(
            ["/usr/bin/git", "-C", str(repo), "diff", "--quiet", "HEAD",
             "--", scope.target, scope.acceptance_test],
            timeout=10, capture_output=True).returncode == 0,
        "digest": sha256((repo / scope.acceptance_test).read_bytes()).hexdigest()
                  == scope.acceptance_sha256,
    }
    assert before == sorted((str(p.relative_to(repo)), p.read_bytes())
                            for p in repo.rglob("*.py"))


def test_modified_test_or_target_is_not_existing_reviewed_scope(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    (repo / scope.acceptance_test).write_text("assert True\n")
    assert observed_feature_test(scope, repo) is None
    git(repo, "checkout", "--", scope.acceptance_test)
    (repo / scope.target).write_text("def feature(): return 99\n")
    assert observed_feature_test(scope, repo) is None


def test_branch_or_commit_mismatch_cannot_borrow_test(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    assert observed_feature_test(replace(scope, base_sha="b" * 40), repo) is None
    assert observed_feature_test(
        replace(scope, base_branch="local9b/another-feature"), repo,
    ) is None
    assert observed_feature_test(
        replace(scope, base_branch="main"), repo,
    ) is None


def test_symlinked_test_and_untracked_target_are_denied(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    test = repo / scope.acceptance_test
    external = tmp_path / "outside.py"
    external.write_bytes(test.read_bytes())
    test.unlink()
    test.symlink_to(external)
    assert observed_feature_test(scope, repo) is None
    test.unlink()
    git(repo, "checkout", "--", scope.acceptance_test)
    git(repo, "rm", "--", scope.target)
    # git rm may prune an empty tracked source directory.
    (repo / scope.target).parent.mkdir(parents=True, exist_ok=True)
    (repo / scope.target).write_text("def feature(): return 1\n")
    assert observed_feature_test(scope, repo) is None


def test_no_missing_path_creates_an_acceptance(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    (repo / scope.acceptance_test).unlink()
    assert observed_feature_test(scope, repo) is None
    assert not (repo / scope.acceptance_test).exists()


def _review_candidate_setup(scope):
    moment = time.time()
    contract = HostContract("draft_code", scope.target,
                            scope.acceptance_sha256, 1024, 1024, 0.1,
                            "development:fixed-test")
    cost = CostReceipt(
        moment,
        "https://github.com/BurntSushi/ripgrep/commit/"
        "4649aa9700619f94cf9c66876e9549d83420e16c",
        True, 0, 0, "NOT_APPLICABLE_LOCAL")
    benefit = BenefitReceipt(
        moment, "m1:reviewed-independent-five-pairs", "latency_ms",
        10.0, 8.0, "lower", True)
    hardware = HardwareReceipt(
        moment, "m1:owner-read-only", "macOS", "arm64", "Apple M1",
        1024**3, 1024**3, False)
    plan = json.dumps(
        _plan(scope.candidate_id, contract, cost, benefit, hardware),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    class Readback:
        reads = 0
        def read(self, doc_id):
            self.reads += 1
            return plan
    return {
        "contract": contract, "cost": cost, "benefit": benefit,
        "hardware": hardware, "plan_id": "ownerplanreceipt123",
        "plan_digest": sha256(plan.encode("utf-8")).hexdigest(),
        "drive": Readback(), "now": moment,
    }


def test_positive_review_wrapper_requires_existing_pinned_feature_branch(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    proofs = _review_candidate_setup(scope)
    result = prepare_reviewed_improvement(
        scope.candidate_id, scope=scope, checkout=repo, **proofs)
    assert result["status"] == "REVIEW_REQUIRED", result
    assert result["queue_writes"] == result["issue_writes"] == 0
    assert result["ready_label"] is False
    assert "foundation-autodev-task" not in result["proposal"]
    assert proofs["drive"].reads == 1


def test_positive_review_wrapper_fails_before_drive_on_test_tamper(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    proofs = _review_candidate_setup(scope)
    (repo / scope.acceptance_test).write_text("assert True\n")
    result = prepare_reviewed_improvement(
        scope.candidate_id, scope=scope, checkout=repo, **proofs)
    assert result == {"status": "HOLD",
                      "reason": "FEATURE_BRANCH_SOURCE_UNVERIFIED"}
    assert proofs["drive"].reads == 0


def test_positive_review_wrapper_unknown_candidate_id_no_source_access(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    proofs = _review_candidate_setup(scope)
    result = prepare_reviewed_improvement(
        "other-ai-provider", scope=scope, checkout=repo, **proofs)
    assert result == {"status": "HOLD",
                      "reason": "IMPROVEMENT_SCOPE_NOT_REVIEWED"}
    assert proofs["drive"].reads == 0


def test_group_writable_and_hardlinked_reviewed_files_are_not_trusted(tmp_path):
    repo, scope = checkout_fixture(tmp_path)
    test = repo / scope.acceptance_test
    target = repo / scope.target
    test.chmod(0o664)
    assert observed_feature_test(scope, repo) is None
    test.chmod(0o644)
    target.chmod(0o666)
    assert observed_feature_test(scope, repo) is None
    target.chmod(0o644)
    alias = repo / "test-hardlink-alias.py"
    os.link(test, alias)
    try:
        assert observed_feature_test(scope, repo) is None
    finally:
        alias.unlink()
    assert observed_feature_test(scope, repo) == scope.acceptance_sha256
