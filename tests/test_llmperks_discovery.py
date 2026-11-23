"""No-network admission boundaries for the public LLMPerks discovery feed."""
from pathlib import Path

import pytest
from ai_foundation.llmperks_discovery import (
    SOURCE_URL, SourceInvalid, parse_index, fetch_index, compare, review_note,
)

INDEX = """# LLM Perks

> A public model index.
Snapshot: 2026-11-09T17:53:02.057Z
Free models: 275 (370 endpoints) · Providers online: 15/16
## Best free models right now
- [GLM 5.3 Flash](https://llmperks.com/glm/glm-5-3-flash): AA index 41.8, 1000000 ctx, free at groq, nvidia
- [Kimi K2](https://llmperks.com/kimi/kimi-k2): AA index 20, 128000 ctx, free at openrouter
## Providers
- [Groq](https://llmperks.com/groq): Free plan limits. Base URL: https://api.groq.com/openai/v1
- [OpenRouter](https://llmperks.com/openrouter): Some free models. Base URL: https://openrouter.ai/api/v1
""".encode("utf-8")


def test_source_contract_is_featured_only_and_cannot_authorize_any_provider():
    data = parse_index(INDEX)
    assert data["coverage"] == "FEATURED_ONLY_NOT_FULL_CATALOG"
    assert data["authority"] == "RESEARCH_ONLY_NO_EXECUTION_OR_BILLING"
    assert len(data["featured_model_pages"]) == 2
    assert data["provider_summaries"]["groq"]["existing_service_id_hint"] == "groq"
    assert data["publisher_counts_unverified"]["published_models"] == 275


def test_baseline_is_not_fake_new_models_and_ranking_loss_is_not_retirement():
    old = parse_index(INDEX)
    assert compare(old)["baseline_only"]
    assert compare(old)["new_featured"] == []
    assert compare(old, old)["new_featured"] == []
    modified = INDEX.replace(
        b"- [Kimi K2](https://llmperks.com/kimi/kimi-k2): AA index 20, 128000 ctx, free at openrouter\n", b"")
    new = parse_index(modified)
    diff = compare(new, old)
    assert diff["no_longer_featured_NOT_RETIRED"] == ["https://llmperks.com/kimi/kimi-k2"]
    assert diff["execution_authorized"] is False
    assert "No longer featured (NOT retired)" in review_note(new, diff)


def test_new_model_and_provider_changes_are_review_only():
    old = parse_index(INDEX)
    modified = INDEX.replace(b"Free plan limits", b"Updated plan limits")
    modified = modified.replace(
        b"## Providers",
        b"- [DeepSeek](https://llmperks.com/deepseek/deepseek-r1): AA, 128000 ctx, free at groq\n## Providers")
    current = parse_index(modified)
    delta = compare(current, old)
    assert delta["new_featured"] == ["https://llmperks.com/deepseek/deepseek-r1"]
    assert delta["changed_provider_summaries"] == ["groq"]
    assert delta["official_terms_reverification_required"] is True
    assert delta["manual_provider_selection"] is True


def test_malformed_or_disguised_source_refused():
    bad = (
        b"", b"<html>403</html>", INDEX[:110],
        INDEX.replace(b"## Providers", b"## Unexpected"),
        INDEX.replace(b"https://llmperks.com/groq", b"http://llmperks.com/groq"),
        INDEX + b"X" * 131072,
    )
    for raw in bad:
        with pytest.raises(SourceInvalid):
            parse_index(raw)


def test_public_fixed_get_has_no_key_or_model_inference():
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, length):
            assert length == 131073
            return INDEX
    def transport(req, timeout):
        assert req.full_url == SOURCE_URL
        assert req.get_method() == "GET"
        assert "Authorization" not in req.headers
        assert timeout == 12
        return Reply()
    assert fetch_index(transport=transport)["provider_summaries"]["groq"]["name"] == "Groq"


def test_unrelated_old_snapshot_is_never_treated_as_a_delta():
    old = parse_index(INDEX)
    old["schema"] = "unrelated"
    with pytest.raises(SourceInvalid):
        compare(parse_index(INDEX), old)



def test_corrupted_persisted_snapshot_is_not_used_for_delta():
    current = parse_index(INDEX)
    previous = parse_index(INDEX)
    previous["provider_summaries"]["groq"]["source_terms_excerpt"] = "tampered"
    with pytest.raises(SourceInvalid, match="INVALID_PREVIOUS"):
        compare(current, previous)
    assert compare(current, parse_index(INDEX))["changed_provider_summaries"] == []


def test_corrupted_current_snapshot_is_not_accepted_as_source_evidence():
    current = parse_index(INDEX)
    current["featured_model_pages"].clear()
    with pytest.raises(SourceInvalid, match="INVALID_CURRENT"):
        compare(current)


def test_malformed_persisted_snapshot_fails_closed_without_key_error():
    current = parse_index(INDEX)
    for previous in (None, [], {"schema": "llmperks-curated-v1", "source_url": SOURCE_URL,
                                  "sha256": "bad"}):
        if previous is None:
            continue  # A missing snapshot is a legitimate baseline.
        with pytest.raises(SourceInvalid):
            compare(current, previous)


def test_script_never_reads_secrets_or_edits_canonical_ledger():
    source = (Path(__file__).resolve().parents[1] /
              "scripts/llmperks_discovery.py").read_text()
    assert "fetch_index()" in source
    assert "provider_registry" not in source
    assert "keychain" not in source.lower()
    assert "drive_file" not in source.lower()
