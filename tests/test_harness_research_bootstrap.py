"""Operator research bootstrap cannot ever authorize an external service."""
import json
from pathlib import Path

from ai_foundation.harness_research_bootstrap import (
    load_harness_research_ledger, MAX_RESEARCH_BYTES,
)

LEDGER = "docs/data/free_ai_route_candidates_20261109.json"


def write(root, data):
    path = root / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


def sample():
    return {
        "deployment_state": "RESEARCH_ONLY",
        "default_route_enabled": False,
        "services": [{
            "id": "new-free-service",
            "name": "Example Free",
            "route_kind": "INFERENCE_API",
            "enabled": False,
        }],
    }


def test_canonical_research_expands_without_changing_bootstrap_test():
    source = load_harness_research_ledger(Path(__file__).resolve().parents[1])
    assert source is not None
    assert source["deployment_state"] == "RESEARCH_ONLY"
    assert len(source["services"]) >= 3
    assert {"groq", "opencode-console-free", "jules"} <= {
        entry["id"] for entry in source["services"]}
    assert all(row["enabled"] is False for row in source["services"])
    assert source["default_route_enabled"] is False


def test_missing_malformed_and_executable_research_never_load(tmp_path):
    assert load_harness_research_ledger(tmp_path) is None
    path = write(tmp_path, sample())
    assert load_harness_research_ledger(tmp_path) == sample()
    candidates = [
        dict(sample(), deployment_state="ACTIVE"),
        dict(sample(), default_route_enabled=True),
        dict(sample(), services=[]),
        dict(sample(), services=[dict(sample()["services"][0], enabled=True)]),
        dict(sample(), services=[sample()["services"][0]] * 2),
        dict(sample(), services=[dict(sample()["services"][0], id="../../escape")]),
        dict(sample(), services=[dict(sample()["services"][0], name="<script>" * 100)]),
    ]
    for candidate in candidates:
        write(tmp_path, candidate)
        assert load_harness_research_ledger(tmp_path) is None
    path.write_text("{INVALID JSON")
    assert load_harness_research_ledger(tmp_path) is None
    path.write_text("x" * (MAX_RESEARCH_BYTES + 1))
    assert load_harness_research_ledger(tmp_path) is None


def test_symlinked_research_file_does_not_expand_native_trust(tmp_path):
    path = write(tmp_path, sample())
    canonical = tmp_path / "other.json"
    path.rename(canonical)
    path.symlink_to(canonical)
    assert load_harness_research_ledger(tmp_path) is None


def test_real_operator_startup_binds_readonly_ledger_without_activation():
    source = (Path(__file__).resolve().parents[1] /
              "scripts/operator_server.py").read_text()
    assert "load_harness_research_ledger(Path(__file__).resolve().parents[1])" in source
    assert "research_ledger=harness_research" in source
    assert "settings=settings" in source
    assert "host_question_resolver=host_question_resolver" in source
    assert "free_route.attest" not in source

def test_operator_startup_does_not_activate_legacy_kandev_question_route():
    # Default entrypoint must not wire the old loopback source of owner
    # questions into Operator. Authenticated host-question handling remains.
    source = (Path(__file__).resolve().parents[1] /
              "scripts/operator_server.py").read_text()
    assert "question_resolver=None,question_authority=question_authority" in source
    assert "host_question_resolver=host_question_resolver" in source
    assert "question_resolver=lambda bundle" not in source
    assert "from ai_foundation.question_ingress import resolve_ingress" not in source
