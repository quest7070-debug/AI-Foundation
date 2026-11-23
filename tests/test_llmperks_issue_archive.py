"""No-network GitHub Issue archive and delta baseline safety."""
import json

import pytest

from ai_foundation.llmperks_discovery import SOURCE_URL, SourceInvalid, fingerprint
from ai_foundation.llmperks_issue_archive import (
    decode_snapshot, encode_snapshot, make_issue_body, main,
)


def sample():
    snap = {
        "schema": "llmperks-curated-v1",
        "source_url": SOURCE_URL,
        "publisher_snapshot": "2026-09-29T03:21:53.662Z",
        "featured_model_pages": {"https://llmperks.com/x/model": {
            "name": "Test", "free_at_claimed": ["groq"],
        }},
        "provider_summaries": {"groq": {"name": "Groq"}},
    }
    snap["sha256"] = fingerprint(snap)
    report = {
        "schema": "llmperks-review-v1", "source_url": SOURCE_URL,
        "current_sha256": snap["sha256"], "new_featured": [],
        "no_longer_featured_NOT_RETIRED": [],
    }
    models = [{"rank": 1, "name": "Good | Test<script>!", "aa_intelligence": 40.1,
               "gpqa_diamond": 90.0}]
    ranked = {
        "schema": "llmperks-reasoning-rankings-v1",
        "source_snapshot": "2026-11-09T21:53:10.556Z",
        "aa_intelligence": {"ranked": models},
        "gpqa_diamond": {"ranked": models},
        "execution_authorized": False,
    }
    proj = {
        "schema": "foundation-service-model-research-projection-v1",
        "publisher_snapshot": ranked["source_snapshot"],
        "provider_model_records": 4, "direct_api_research_routes": 2,
        "existing_adapter_model_mentions": 1,
        "non_api_service_observations": 1, "unmatched_provider_records": 1,
        "unmatched_provider_slugs": {"together": [{}, {}]},
        "execution_authorized": False,
    }
    return snap, report, ranked, proj


def test_restore_is_exact_source_snapshot_and_old_issue_is_initial_baseline():
    snapshot, report, ranking, projection = sample()
    assert decode_snapshot("An existing newly created research issue") is None
    body = make_issue_body(snapshot, report, ranking, projection)
    assert decode_snapshot(body) == snapshot
    assert "Good ／ Test‹script›!" in body
    assert "https://llmperks.com/llms-full.txt" in body
    assert len(body.encode()) < 60000
    assert body.count("FOUNDATION_LLMPERKS_SNAPSHOT_V1") == 1


def test_marker_mutation_or_mismatched_digest_does_not_downgrade_to_baseline():
    snap, report, ranked, proj = sample()
    body = make_issue_body(snap, report, ranked, proj)
    assert "FOUNDATION_LLMPERKS_SNAPSHOT_V1" in body
    with pytest.raises(SourceInvalid):
        decode_snapshot(body.replace("FOUNDATION_LLMPERKS_SNAPSHOT_V1",
                                      "FOUNDATION_LLMPERKS_SNAPSHOT_BROKEN"))
    marker = encode_snapshot(snap)
    # Mutate ONLY the trailing SHA256 value, not the compressed base64 bytes.
    old_digest = marker.rsplit(":", 1)[-1].split(" -->")[0]
    assert len(old_digest) == 64
    altered_digest = "0" * 64 if old_digest != "0" * 64 else "f" * 64
    altered = marker.replace(":" + old_digest + " -->",
                             ":" + altered_digest + " -->")
    with pytest.raises(SourceInvalid, match="DIGEST_MISMATCH"):
        decode_snapshot(altered)


def test_rank_or_report_must_belong_to_same_verified_source_revision():
    snap, report, ranked, proj = sample()
    report["current_sha256"] = "0" * 64
    with pytest.raises(SourceInvalid, match="ISSUE_RESEARCH_OUTPUT_MISMATCH"):
        make_issue_body(snap, report, ranked, proj)
    snap, report, ranked, proj = sample()
    ranked["source_snapshot"] = "1970-01-01T00:00:00Z"
    with pytest.raises(SourceInvalid, match="ISSUE_RESEARCH_OUTPUT_MISMATCH"):
        make_issue_body(snap, report, ranked, proj)


def test_cli_restores_baseline_after_persisted_render(tmp_path):
    snap, report, ranked, proj = sample()
    files = {}
    for name, value in (("snap", snap), ("report", report),
                        ("ranking", ranked), ("projection", proj)):
        files[name] = tmp_path / (name + ".json")
        files[name].write_text(json.dumps(value))
    issue_body, payload = tmp_path / "issue.md", tmp_path / "request.json"
    args = [
        "render", "--snapshot", str(files["snap"]), "--report", str(files["report"]),
        "--ranked", str(files["ranking"]), "--service-routes", str(files["projection"]),
        "--body", str(issue_body), "--payload", str(payload),
    ]
    assert main(args) == 0
    assert json.loads(payload.read_text())["body"] == issue_body.read_text()
    restored = tmp_path / "restored.json"
    assert main(["restore", "--body", str(issue_body), "--snapshot", str(restored)]) == 0
    assert json.loads(restored.read_text()) == snap
