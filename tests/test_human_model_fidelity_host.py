import hashlib
import json

import pytest

from ai_foundation.human_model_fidelity_host import evaluate_owner_private_fidelity


def row():
    return {"case_id": "private-case", "review_ref": "a" * 64,
            "reference_sha256": "b" * 64,
            "expected_behavior": "ANSWER", "model_behavior": "ANSWER",
            "agreement": "MATCH", "reason_preserved": True,
            "exception_preserved": True, "uncertainty_appropriate": True,
            "citation_valid": True, "false_owner_approval_claim": False}


def provision(root, rows=None):
    directory = root / "human-model" / "fidelity"
    directory.mkdir(parents=True, mode=0o700)
    directory.parent.chmod(0o700)
    rows = [row()] if rows is None else rows
    pins = {r["review_ref"]: hashlib.sha256(json.dumps(
        r, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
        for r in rows}
    for name, content in (("reviews.json", {"version": 1, "reviews": rows}),
                          ("contracts.json", {"version": 1, "review_contracts": pins})):
        path = directory / name
        path.write_text(json.dumps(content))
        path.chmod(0o600)
    return directory


def test_missing_or_empty_owner_reviews_are_not_evaluated_without_writes(tmp_path):
    assert list(tmp_path.iterdir()) == []
    missing = evaluate_owner_private_fidelity(tmp_path)
    assert missing["status"] == "NOT_EVALUATED"
    assert missing["evaluated_questions"] == 0
    assert list(tmp_path.iterdir()) == []
    provision(tmp_path, [])
    empty = evaluate_owner_private_fidelity(tmp_path)
    assert empty["status"] == "NOT_EVALUATED"
    assert not empty["review_binding_verified"]


def test_persisted_independent_owner_pins_reach_evaluator_without_content_export(tmp_path):
    directory = provision(tmp_path)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}
    result = evaluate_owner_private_fidelity(tmp_path)
    assert result["status"] == "OWNER_REVIEWED_SAMPLE"
    assert result["review_binding_verified"] and result["evaluated_questions"] == 1
    assert result["answer_agreement"]["MATCH"] == 1
    assert result["representative_fidelity_verified"] is False
    assert result["execution_authority"] is False
    assert result["model_calls"] == result["native_effects"] == 0
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()} == before
    encoded = json.dumps(result)
    for private in ("private-case", "a" * 64, "b" * 64, str(tmp_path)):
        assert private not in encoded


def test_modified_labels_cannot_self_regenerate_trusted_review_pins(tmp_path):
    directory = provision(tmp_path)
    path = directory / "reviews.json"
    content = json.loads(path.read_text())
    content["reviews"][0]["agreement"] = "MISMATCH"
    path.write_text(json.dumps(content))
    result = evaluate_owner_private_fidelity(tmp_path)
    assert result["status"] == "BLOCKED" and result["evaluated_questions"] == 0


@pytest.mark.parametrize("invalid", ["symlink", "permissions", "duplicate", "raw-content"])
def test_untrusted_or_ambiguous_private_documents_fail_closed(tmp_path, invalid):
    directory = provision(tmp_path)
    target = directory / "reviews.json"
    if invalid == "symlink":
        original = directory / "original.json"
        target.rename(original)
        target.symlink_to(original)
    elif invalid == "permissions":
        target.chmod(0o644)
    elif invalid == "duplicate":
        target.write_text('{"version":1,"version":1,"reviews":[]}')
    else:
        content = json.loads(target.read_text())
        content["reviews"][0]["source_text"] = "SECRET_PRIVATE_SOURCE"
        target.write_text(json.dumps(content))
    result = evaluate_owner_private_fidelity(tmp_path)
    assert result["status"] == "BLOCKED" and result["evaluated_questions"] == 0
    assert "SECRET_PRIVATE_SOURCE" not in json.dumps(result)


def test_changed_owner_contract_document_during_evaluation_is_not_trusted(tmp_path, monkeypatch):
    from ai_foundation import human_model_fidelity_host as module
    directory = provision(tmp_path)
    original = module.evaluate_owner_answer_fidelity

    def replace_after_evaluation(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[0]:
            (directory / "contracts.json").write_text('{"version":1,"review_contracts":{}}')
        return result

    monkeypatch.setattr(module, "evaluate_owner_answer_fidelity", replace_after_evaluation)
    result = evaluate_owner_private_fidelity(tmp_path)
    assert result["status"] == "BLOCKED" and result["evaluated_questions"] == 0
