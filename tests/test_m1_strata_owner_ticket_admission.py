"""Minimal owner CODE admission: one public review document, exact local Git bytes."""
from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest
from scripts import m1_strata_owner_ticket_admission as admit


def _git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args],
                                   text=True, stderr=subprocess.DEVNULL).strip()


def _fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-q", "-b", "main", str(repo)])
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    src = repo / "src/ai_foundation/example.py"
    src.parent.mkdir(parents=True)
    src.write_text("VALUE = 1\n")
    test = repo / "tests/test_example.py"
    test.parent.mkdir(parents=True)
    test.write_text("def test_value():\n    assert True\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    root = tmp_path / "data"
    review_dir = root / "development/reviews"
    review_dir.mkdir(parents=True, mode=0o700)
    (root / "development").chmod(0o700)
    review_dir.chmod(0o700)
    instruction = "Change VALUE to 2 and return the full Python source."
    source_hash = sha256(src.read_bytes()).hexdigest()
    row = {
        "version": 1, "review": admit.REVIEWED, "ticket_id": "next-public",
        "model": "strata", "base_sha": _git(repo, "rev-parse", "HEAD"),
        "target": "src/ai_foundation/example.py",
        "test": "tests/test_example.py",
        "source_sha256": source_hash,
        "public_source_sha256": source_hash,
        "test_sha256": sha256(test.read_bytes()).hexdigest(),
        "instruction": instruction,
        "public_instruction_sha256": sha256(instruction.encode()).hexdigest(),
    }
    path = review_dir / "next-public.json"
    path.write_text(json.dumps(row))
    path.chmod(0o600)
    return repo, root, row, path


def test_reviewed_local_ticket_admits_exact_git_bytes_and_instruction(tmp_path):
    repo, root, row, path = _fixture(tmp_path)
    result = admit.reviewed_contract(root, repo, "next-public")
    assert result["ticket_id"] == "next-public"
    assert result["model"] == "strata"
    assert result["public_source_sha256"] == result["source_sha256"]
    assert "review" not in result


def test_host_admission_requires_exact_saved_request_instruction(tmp_path):
    repo, root, row, path = _fixture(tmp_path)
    expected = sha256(row["instruction"].encode()).hexdigest()
    assert admit.reviewed_contract(root, repo, "next-public",
                                   expected_instruction_sha256=expected)["instruction"] == row["instruction"]
    with pytest.raises(ValueError, match="OWNER_REQUEST_INSTRUCTION_CHANGED"):
        admit.reviewed_contract(root, repo, "next-public",
                                expected_instruction_sha256=sha256(b"another request").hexdigest())


@pytest.mark.parametrize("model", ["m1", "auto", "strata"])
def test_owner_local_review_preserves_selected_existing_compute_policy(tmp_path, model):
    repo, root, row, path = _fixture(tmp_path)
    row["model"] = model
    path.write_text(json.dumps(row))
    result = admit.reviewed_contract(root, repo, "next-public")
    assert result["model"] == model
    assert result["source_origin"] == "owner-local-review-v1"
    assert ("public_source_sha256" in result) is (model != "m1")
    assert _git(repo, "rev-parse", "HEAD") == row["base_sha"]


def test_review_denies_changed_source_and_secrets_without_model_or_work(tmp_path):
    repo, root, row, path = _fixture(tmp_path)
    changed = dict(row, source_sha256="0" * 64, public_source_sha256="0" * 64)
    path.write_text(json.dumps(changed))
    with pytest.raises(ValueError, match="OWNER_REVIEWED_SOURCE_CHANGED"):
        admit.reviewed_contract(root, repo, "next-public")
    row["instruction"] = "Use secret sk-proj-" + "a"*30
    row["public_instruction_sha256"] = sha256(row["instruction"].encode()).hexdigest()
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError, match="OWNER_PUBLIC_EGRESS_DENIED"):
        admit.reviewed_contract(root, repo, "next-public")
    path.chmod(0o644)
    with pytest.raises(PermissionError):
        admit.reviewed_contract(root, repo, "next-public")

