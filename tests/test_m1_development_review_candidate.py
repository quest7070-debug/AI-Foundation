"""Review preparation is no-effect and cannot forge owner-authorized admission."""
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess

import pytest
from scripts import m1_development_review_candidate as review


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args],
                                   text=True, stderr=subprocess.DEVNULL).strip()


def fixture(tmp_path, *, instruction=None):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-q", "-b", "main", str(repo)])
    git(repo, "config", "user.name", "Fixture")
    git(repo, "config", "user.email", "fixture@example.invalid")
    src = repo / "src/ai_foundation/sample.py"
    src.parent.mkdir(parents=True)
    src.write_text("VALUE = 1\n")
    test = repo / "tests/test_sample.py"
    test.parent.mkdir()
    test.write_text("def test_value():\n    assert True\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "reviewed local base")
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    ident = "fresh-sample-1"
    instruction = (instruction if instruction is not None
                   else "Modify src/ai_foundation/sample.py; independently use tests/test_sample.py.")
    prefix = "mcp-development-request:" + sha256(review._OWNER.encode()).hexdigest() + ":"
    path = root / "work.db"
    with sqlite3.connect(path) as db:
        db.execute("""CREATE TABLE work_steps(
            job_id TEXT,position INTEGER,name TEXT,status TEXT,result TEXT)""")
        db.execute("INSERT INTO work_steps VALUES (?,?,?,?,?)",
                   (prefix + ident, 0, "development-request", "WAITING_HUMAN",
                    json.dumps({"ticket_id": ident, "instruction": instruction})))
    path.chmod(0o600)
    return root, repo, ident, instruction


def test_candidate_from_saved_request_is_unsigned_private_and_idempotent(tmp_path):
    root, repo, ident, instruction = fixture(tmp_path)
    before = sha256((root / "work.db").read_bytes()).hexdigest()
    first = review.candidate(root, repo, ident)
    assert first["status"] == "CANDIDATE_PREPARED"
    assert first["model_calls"] == 0 and first["work_modified"] is False
    draft = root / "development/review_candidates" / (ident + ".json")
    assert draft.stat().st_mode & 0o077 == 0
    assert draft.parent.stat().st_mode & 0o077 == 0
    assert draft.parent.parent.stat().st_mode & 0o077 == 0
    document = json.loads(draft.read_text())
    assert document["review"] == "UNREVIEWED_CANDIDATE"
    assert document["execution_authority"] is False
    assert document["external_egress_authorized"] is False
    assert document["public_source_sha256"] is None
    assert document["instruction"] == instruction
    assert document["base_sha"] == git(repo, "rev-parse", "HEAD")
    assert document["source_sha256"] == sha256(
        (repo / document["target"]).read_bytes()).hexdigest()
    assert review.candidate(root, repo, ident)["status"] == "CANDIDATE_ALREADY_PREPARED"
    assert not (root / "development/reviews" / (ident + ".json")).exists()
    assert sha256((root / "work.db").read_bytes()).hexdigest() == before


def test_source_and_test_scope_must_be_exact_and_locally_tracked(tmp_path):
    root, repo, ident, _ = fixture(
        tmp_path, instruction=("Change src/ai_foundation/sample.py and "
                               "src/ai_foundation/other.py"))
    with pytest.raises(ValueError, match="REVIEW_SCOPE_SELECTION_REQUIRED"):
        review.candidate(root, repo, ident)
    assert not (root / "development/review_candidates").exists()


def test_missing_fixed_test_does_not_autogenerate_or_grant_one(tmp_path):
    root, repo, ident, _ = fixture(
        tmp_path, instruction="Change src/ai_foundation/sample.py; test in tests/test_missing.py")
    with pytest.raises(ValueError, match="CANDIDATE_SOURCE_OR_TEST_UNVERIFIED"):
        review.candidate(root, repo, ident)
    assert not (root / "development/review_candidates").exists()


def test_cancelled_request_does_not_appear_ready_to_review(tmp_path):
    root, repo, ident, _ = fixture(tmp_path)
    with sqlite3.connect(root / "work.db") as db:
        db.execute("UPDATE work_steps SET status='CANCELLED'")
    with pytest.raises(ValueError, match="REQUEST_NOT_WAITING_FOR_REVIEW"):
        review.candidate(root, repo, ident)


def test_changed_candidate_bytes_or_dirty_repo_fail_closed(tmp_path):
    root, repo, ident, _ = fixture(tmp_path)
    review.candidate(root, repo, ident)
    draft = root / "development/review_candidates" / (ident + ".json")
    draft.write_text('{"review":"FORGED"}')
    with pytest.raises(ValueError, match="CANDIDATE_DRIFT_REVIEW_REQUIRED"):
        review.candidate(root, repo, ident)
    (repo / "src/ai_foundation/sample.py").write_text("VALUE = 2\n")
    with pytest.raises(ValueError, match="OWNER_CHECKOUT_NOT_CLEAN"):
        review.candidate(root, repo, ident)


def test_no_saved_request_and_bad_id_never_create_candidate(tmp_path):
    root, repo, ident, _ = fixture(tmp_path)
    for bad in ("../outside", "A", "fake"):
        with pytest.raises((ValueError, OSError)):
            review.candidate(root, repo, bad)
    assert not (root / "development/review_candidates").exists()


def test_cancelled_while_reading_source_does_not_prepare_candidate(tmp_path, monkeypatch):
    root, repo, ident, _ = fixture(tmp_path)
    actual = review._tracked_file
    calls = [0]

    def cancelled(repo_path, relative):
        calls[0] += 1
        result = actual(repo_path, relative)
        if calls[0] == 2:
            with sqlite3.connect(root / "work.db") as db:
                db.execute("UPDATE work_steps SET status='CANCELLED'")
        return result

    monkeypatch.setattr(review, "_tracked_file", cancelled)
    with pytest.raises(ValueError, match="REQUEST_NOT_WAITING_FOR_REVIEW"):
        review.candidate(root, repo, ident)
    assert not (root / "development/review_candidates").exists()


def test_dirty_checkout_during_source_snapshot_does_not_prepare_candidate(tmp_path, monkeypatch):
    root, repo, ident, _ = fixture(tmp_path)
    actual = review._tracked_file

    def edit_during_read(repo_path, relative):
        result = actual(repo_path, relative)
        if relative.endswith("/sample.py"):
            (repo / relative).write_text("VALUE = 99\\n")
        return result

    monkeypatch.setattr(review, "_tracked_file", edit_during_read)
    with pytest.raises(ValueError, match="OWNER_CHECKOUT_CHANGED_DURING_REVIEW"):
        review.candidate(root, repo, ident)
    assert not (root / "development/review_candidates").exists()


def test_private_candidate_path_cannot_be_symlink(tmp_path):
    root, repo, ident, _ = fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "development").mkdir(mode=0o700)
    (root / "development/review_candidates").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PermissionError):
        review.candidate(root, repo, ident)
    assert not list(outside.iterdir())


@pytest.mark.parametrize(("relative", "flag"), [
    ("src/ai_foundation/sample.py", "--assume-unchanged"),
    ("tests/test_sample.py", "--skip-worktree"),
])
def test_index_flags_cannot_hide_changed_reviewed_bytes(tmp_path, relative, flag):
    root, repo, ident, _ = fixture(tmp_path)
    git(repo, "update-index", flag, "--", relative)
    # Flags alone do not invalidate an unchanged tracked file.
    assert review._tracked_file(repo, relative) == sha256(
        (repo / relative).read_bytes()).hexdigest()
    before = sha256((root / "work.db").read_bytes()).hexdigest()
    (repo / relative).write_text("# hidden working-tree edit\n")
    assert git(repo, "status", "--porcelain", "--untracked-files=no") == ""
    with pytest.raises(ValueError, match="CANDIDATE_SOURCE_OR_TEST_UNVERIFIED"):
        review.candidate(root, repo, ident)
    assert not (root / "development/review_candidates").exists()
    assert sha256((root / "work.db").read_bytes()).hexdigest() == before


def test_exact_individual_review_uses_only_physically_verified_source_fallback(tmp_path, monkeypatch):
    """A signed stage-only review must not be rebound to missing main files."""
    from scripts import m1_development_ticket_factory as factory
    root, repo, ident, _ = fixture(tmp_path)
    stage = tmp_path / "installed-stage"
    git(repo, "worktree", "add", "-b", "reviewed-stage", str(stage))
    source = "src/ai_foundation/sample.py"
    test = "tests/test_sample.py"
    record = {
        "source_origin": "owner-local-review-v1",
        "base_sha": git(stage, "rev-parse", "HEAD"),
        "target": source,
        "test": test,
        "source_sha256": sha256((stage / source).read_bytes()).hexdigest(),
        "test_sha256": sha256((stage / test).read_bytes()).hexdigest(),
    }
    # The normal owner checkout now lacks the reviewed source and fixed test.
    git(repo, "rm", "--", source, test)
    git(repo, "commit", "-qm", "owner main lacks reviewed stage-only files")
    assert not (repo / source).exists()
    assert (stage / source).is_file()
    before_owner = git(repo, "rev-parse", "HEAD")
    before_stage = git(stage, "rev-parse", "HEAD")
    from scripts import m1_development_review_candidate as candidate
    calls = []
    def trusted_stage(owner):
        calls.append(owner)
        assert owner == repo.resolve()
        return stage
    monkeypatch.setattr(candidate, "_installed_live_source_repo", trusted_stage)
    assert factory._explicit_review_source_repo(repo, record) == stage.resolve()
    assert calls == [repo.resolve()]
    assert git(repo, "rev-parse", "HEAD") == before_owner
    assert git(stage, "rev-parse", "HEAD") == before_stage
    assert not (root / "development").exists()
    # A changed reference never substitutes another source or re-arms Work.
    bad = {**record, "source_sha256": "f" * 64}
    assert factory._explicit_review_source_repo(repo, bad) == repo.resolve()
    # A standing delegation cannot use the explicitly reviewed release path.
    delegated = {**record, "source_origin": "owner-scope-delegation-v1"}
    assert factory._explicit_review_source_repo(repo, delegated) == repo.resolve()


def test_reviewed_source_binding_does_not_switch_dirty_or_present_owner_base(tmp_path, monkeypatch):
    from scripts import m1_development_ticket_factory as factory
    from scripts import m1_development_review_candidate as candidate
    _, repo, _, _ = fixture(tmp_path)
    source = "src/ai_foundation/sample.py"
    test = "tests/test_sample.py"
    record = {
        "source_origin": "owner-local-review-v1",
        "base_sha": git(repo, "rev-parse", "HEAD"),
        "target": source, "test": test,
        "source_sha256": sha256((repo / source).read_bytes()).hexdigest(),
        "test_sha256": sha256((repo / test).read_bytes()).hexdigest(),
    }
    def must_not_fallback(_owner):
        raise AssertionError("present or dirty owner source must not switch")
    monkeypatch.setattr(candidate, "_installed_live_source_repo", must_not_fallback)
    # Existing tracked paths, even at an unrelated commit, never authorize fallback.
    assert factory._explicit_review_source_repo(repo, record) == repo.resolve()
    git(repo, "commit", "--allow-empty", "-qm", "unrelated owner HEAD")
    assert factory._explicit_review_source_repo(repo, record) == repo.resolve()
    (repo / source).write_text("LOCAL_DIRTY = True\n")
    assert factory._explicit_review_source_repo(repo, record) == repo.resolve()
