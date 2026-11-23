"""Fixed 9B sandbox may read only reviewed checkout, never owner-home data."""
from hashlib import sha256
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import local9b_task_recipe as recipe


def test_pinned_source_and_tests_are_readable_without_home_access(tmp_path, monkeypatch):
    repo = (tmp_path / "reviewed").resolve()
    source = repo / "src" / "ai_foundation" / "literal_code_search.py"
    fixed = repo / "tests" / "test_literal_code_search.py"
    source.parent.mkdir(parents=True)
    fixed.parent.mkdir(parents=True)
    source.write_text("def ok(): return True\n")
    fixed.write_text("def test_ok(): assert True\n")
    work = (tmp_path / "isolated").resolve()
    work.mkdir()
    sha = "a" * 40
    monkeypatch.setattr(recipe.subprocess, "check_output",
                        lambda *args, **kwargs: sha + "\n")
    task = {
        "recipe": "python-fixed-test", "base": "local9b/reviewed-test",
        "base_sha": sha,
        "target": "src/ai_foundation/literal_code_search.py",
        "test": "tests/test_literal_code_search.py",
        "test_sha256": sha256(fixed.read_bytes()).hexdigest(),
        "instruction": "Run only the reviewed fixed acceptance",
    }
    harness = recipe.FixedPytest(task, repo, work)
    policy = harness.policy.read_text()
    assert '(deny file-read* (subpath (param "OWNER_HOME")))' in policy
    assert '(allow file-read* (subpath (param "REVIEWED_SRC")))' in policy
    assert '(allow file-read* (subpath (param "REVIEWED_TESTS")))' in policy
    assert '(allow file-read-metadata (subpath (param "REVIEWED_REPO")))' in policy
    assert '(allow file-read* (literal (param "REVIEWED_REPO")))' in policy
    assert "(deny file-write*)" in policy
    assert "(deny network-outbound)" in policy
    assert '(allow file-read* (subpath (param "OWNER_HOME")))' not in policy
    assert '(allow file-read-data (subpath (param "REVIEWED_REPO")))' not in policy
    assert str(repo) not in policy  # no untrusted path interpolated into SBPL

    called = []
    def capture(argv, **kwargs):
        called.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "1 passed\n", "")
    monkeypatch.setattr(recipe.subprocess, "run", capture)
    assert "1 passed" in harness.run_tests("fixed")
    argv, kw = called[0]
    assert argv[:3] == ["/usr/bin/sandbox-exec", "-f", str(harness.policy)]
    assert "OWNER_HOME=" + str(Path.home().resolve(strict=True)) in argv
    assert "REVIEWED_SRC=" + str(repo / "src") in argv
    assert "REVIEWED_TESTS=" + str(repo / "tests") in argv
    assert "REVIEWED_REPO=" + str(repo) in argv
    assert kw["cwd"] == repo
    assert kw["env"]["HOME"] == "/nonexistent"
    assert "-B" in argv and "--override-ini" in argv


def test_fixed_runner_rejects_source_alias_before_any_model_or_test(tmp_path, monkeypatch):
    import pytest
    repo = (tmp_path / "reviewed").resolve()
    source = repo / "src" / "ai_foundation" / "literal_code_search.py"
    fixed = repo / "tests" / "test_literal_code_search.py"
    source.parent.mkdir(parents=True)
    fixed.parent.mkdir(parents=True)
    outside = tmp_path / "unreviewed.py"
    outside.write_text("SECRET = 1\n")
    source.symlink_to(outside)
    fixed.write_text("def test_ok(): assert True\n")
    work = tmp_path / "isolated"
    work.mkdir()
    sha = "a" * 40
    monkeypatch.setattr(recipe.subprocess, "check_output",
                        lambda *args, **kwargs: sha + "\n")
    task = {
        "recipe": "python-fixed-test", "base": "main", "base_sha": sha,
        "target": "src/ai_foundation/literal_code_search.py",
        "test": "tests/test_literal_code_search.py",
        "test_sha256": sha256(fixed.read_bytes()).hexdigest(),
        "instruction": "Only host-pinned acceptance",
    }
    with pytest.raises(ValueError, match="FIXED_SOURCE_OR_TEST_MISSING"):
        recipe.FixedPytest(task, repo, work)
    assert outside.read_text() == "SECRET = 1\n"

    source.unlink()
    source.write_text("def ok(): return True\n")
    runner = recipe.FixedPytest(task, repo, work)
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(ValueError, match="FIXED_SOURCE_OR_TEST_ALIAS_CHANGED"):
        runner.run_tests("fixed")


def test_fixed_runner_rejects_wrong_recipe_even_with_valid_pins():
    import pytest
    task = {
        "recipe": "unreviewed-python", "base": "main", "base_sha": "a" * 40,
        "target": "src/ai_foundation/literal_code_search.py",
        "test": "tests/test_literal_code_search.py",
        "test_sha256": "b" * 64,
        "instruction": "Only host-pinned acceptance",
    }
    with pytest.raises(ValueError, match="PYTHON_TASK_RECIPE_INVALID"):
        recipe.validate_contract(task)


def test_fixed_runner_rejects_alias_ancestor_in_source_and_test(tmp_path, monkeypatch):
    import pytest

    repo = (tmp_path / "reviewed").resolve()
    repo.mkdir()
    outside = tmp_path / "outside"
    (outside / "ai_foundation").mkdir(parents=True)
    (outside / "ai_foundation" / "literal_code_search.py").write_text(
        "def ok(): return True\n")
    (outside / "test_literal_code_search.py").write_text(
        "def test_ok(): assert True\n")
    (repo / "src").symlink_to(outside, target_is_directory=True)
    (repo / "tests").mkdir()
    test = repo / "tests" / "test_literal_code_search.py"
    test.write_text("def test_ok(): assert True\n")
    work = tmp_path / "isolated"
    work.mkdir()
    sha = "a" * 40
    monkeypatch.setattr(
        recipe.subprocess, "check_output", lambda *args, **kwargs: sha + "\n")
    contract = {
        "recipe": "python-fixed-test", "base": "main", "base_sha": sha,
        "target": "src/ai_foundation/literal_code_search.py",
        "test": "tests/test_literal_code_search.py",
        "test_sha256": sha256(test.read_bytes()).hexdigest(),
        "instruction": "Use only the host selected fixed test",
    }
    with pytest.raises(ValueError, match="FIXED_SOURCE_OR_TEST_MISSING"):
        recipe.FixedPytest(contract, repo, work)

    (repo / "src").unlink()
    (repo / "src" / "ai_foundation").mkdir(parents=True)
    source = repo / "src" / "ai_foundation" / "literal_code_search.py"
    source.write_text("def ok(): return True\n")
    runner = recipe.FixedPytest(contract, repo, work)
    (repo / "tests" / "test_literal_code_search.py").unlink()
    (repo / "tests").rmdir()
    (repo / "tests").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="FIXED_SOURCE_OR_TEST_ALIAS_CHANGED"):
        runner.run_tests("fixed")

    # Also reject an ancestor alias introduced into the source tree after admission.
    (repo / "tests").unlink()
    (repo / "tests").mkdir()
    (repo / "tests" / "test_literal_code_search.py").write_text(
        "def test_ok(): assert True\n")
    (repo / "src" / "ai_foundation" / "literal_code_search.py").unlink()
    (repo / "src" / "ai_foundation").rmdir()
    (repo / "src").rmdir()
    (repo / "src").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="FIXED_SOURCE_OR_TEST_ALIAS_CHANGED"):
        runner.run_tests("fixed")
