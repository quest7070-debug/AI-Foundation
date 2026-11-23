"""No-network full-data ranking: published scores never become route authority."""
import pytest

from ai_foundation.llmperks_discovery import SourceInvalid
from ai_foundation.llmperks_ranking import (
    FULL_URL, parse_full_dump, fetch_full_dump, ranked_reasoning, ranked_review_note,
)

FIXTURE = """# LLM Perks — full data dump
# Generated: 2026-11-09T21:54:44.501Z
# Snapshot: 2026-11-09T21:53:10.556Z
# Source: https://llmperks.com
# Sections: free models, free software

# ═══ Free models ═══

## Model A
URL: https://llmperks.com/test/model-a
Developer: Example
Type: text; size class: MID; capabilities: reasoning, coding, tools, long; open weights
AA Intelligence Index: 30.5; GPQA Diamond: 96.2%
- groq: id=example/model-a; context=131072; url=https://example.com/

## Model B
URL: https://llmperks.com/test/model-b
Developer: Example
Type: text; size class: TOP; capabilities: reasoning, coding, tools
AA Intelligence Index: 45.1; GPQA Diamond: 90.1%
- openrouter: id=example/model-b:free; context=262144; url=https://example.com

## No GPQA
URL: https://llmperks.com/test/no-gpqa
Developer: Example
Type: text; size class: MID; capabilities: reasoning, coding
AA Intelligence Index: 40.9
- nvidia: id=example/no-gpqa; context=n/a; url=https://example.com

## Not reasoning
URL: https://llmperks.com/test/not-reasoning
Developer: Example
Type: text; size class: TOP; capabilities: coding, tools
AA Intelligence Index: 99.9; GPQA Diamond: 99.9%
- together: id=example/not-reasoning; context=8192; url=https://example.com

# Total: 4 models, 4 free endpoints, 4 providers online

# ═══ Free AI software (1) ═══
- Example (trial) other
""".encode("utf-8")


def test_full_dump_scoped_to_free_models_and_exact_counts():
    catalog = parse_full_dump(FIXTURE)
    assert catalog["publisher_totals_not_verified"]["models"] == 4
    assert len(catalog["models"]) == 4
    assert all(m["endpoints_claimed"] for m in catalog["models"].values())
    assert catalog["authority"] == "RESEARCH_ONLY_NO_EXECUTION_OR_BILLING"


def test_reasoning_ranks_are_true_descending_not_publisher_presentation_order():
    catalog = parse_full_dump(FIXTURE)
    gpqa = ranked_reasoning(catalog, metric="gpqa_diamond", limit=25)
    aa = ranked_reasoning(catalog, metric="aa_intelligence", limit=25)
    assert [r["name"] for r in gpqa["ranked"]] == ["Model A", "Model B"]
    assert [r["name"] for r in aa["ranked"]] == ["Model B", "No GPQA", "Model A"]
    assert gpqa["missing_primary_score_excluded"] == 1
    assert aa["available_scored_reasoning_models"] == 3
    assert all(r["execution_authorized"] is False
               and r["account_no_auto_charge_verified"] is False
               for r in aa["ranked"] + gpqa["ranked"])
    assert gpqa["ranked"][1]["provider_model_ids_claimed"][0]["model_id"] == "example/model-b:free"


def test_nonsecret_drive_review_contains_both_metrics_and_boundaries():
    catalog = parse_full_dump(FIXTURE)
    note = ranked_review_note(catalog)
    assert "AA Index descending" in note
    assert "GPQA Diamond descending" in note
    assert "Manual provider selection" in note
    assert "model-b" in note
    assert len(note.encode("utf-8")) < 8192


def test_stale_or_wrong_feed_shape_does_not_make_ranking():
    corrupt = (
        b"", b"<html>sign in</html>", FIXTURE[:200],
        FIXTURE.replace(b"# Total: 4 models, 4 free endpoints, 4 providers online",
                        b"# Total: 4 models, 400 free endpoints, 4 providers online"),
        FIXTURE.replace(b"https://llmperks.com/test/model-b", b"https://llmperks.com/test/model-a"),
        FIXTURE.replace(b"GPQA Diamond: 96.2%", b"GPQA Diamond: 106.2%"),
        FIXTURE.replace(b"example/model-b:free", b"example/model-b:free; leaked=token"),
        FIXTURE + b"x" * 524288,
    )
    for raw in corrupt:
        with pytest.raises(SourceInvalid):
            parse_full_dump(raw)


def test_unknown_metric_is_not_assumed_or_combined_silently():
    catalog = parse_full_dump(FIXTURE)
    with pytest.raises(ValueError):
        ranked_reasoning(catalog, metric="hidden_composite")
    with pytest.raises(ValueError):
        ranked_reasoning(catalog, limit=0)


def test_public_single_fixed_get_never_sends_authorization():
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, length):
            assert length == 524289
            return FIXTURE

    def fake_http(req, timeout):
        assert req.full_url == FULL_URL
        assert req.get_method() == "GET"
        assert "Authorization" not in req.headers
        assert timeout == 12
        return Reply()

    assert fetch_full_dump(transport=fake_http)["publisher_snapshot"] == "2026-11-09T21:53:10.556Z"


def test_rankings_reject_modified_or_missing_cached_fingerprint():
    catalog = parse_full_dump(FIXTURE)
    model = next(iter(catalog["models"].values()))
    model["aa_intelligence"] = 99.9
    with pytest.raises(SourceInvalid, match="FULL_CATALOG_FINGERPRINT_MISMATCH"):
        ranked_reasoning(catalog)

    catalog = parse_full_dump(FIXTURE)
    del catalog["sha256"]
    with pytest.raises(SourceInvalid, match="FULL_CATALOG_FINGERPRINT_MISMATCH"):
        ranked_review_note(catalog)

def test_duplicate_publisher_metric_cannot_override_first_score():
    duplicated = FIXTURE.replace(
        b"AA Intelligence Index: 30.5; GPQA Diamond: 96.2%",
        b"AA Intelligence Index: 30.5; GPQA Diamond: 96.2%\n"
        b"AA Intelligence Index: 99.9; GPQA Diamond: 99.9%",
    )
    with pytest.raises(SourceInvalid, match="FULL_METRIC_DUPLICATE"):
        parse_full_dump(duplicated)


def test_duplicate_model_url_cannot_silently_replace_identity():
    duplicated = FIXTURE.replace(
        b"URL: https://llmperks.com/test/model-a",
        b"URL: https://llmperks.com/test/model-a\n"
        b"URL: https://llmperks.com/test/alternate-model",
    )
    with pytest.raises(SourceInvalid, match="FULL_MODEL_URL_DUPLICATE"):
        parse_full_dump(duplicated)


def test_duplicate_snapshot_cannot_silently_override_feed_metadata():
    duplicated = FIXTURE.replace(
        b"# Snapshot: 2026-11-09T21:53:10.556Z",
        b"# Snapshot: 2026-11-09T21:53:10.556Z\n"
        b"# Snapshot: 2026-11-09T21:53:11.556Z",
    )
    with pytest.raises(SourceInvalid, match="FULL_SNAPSHOT_DUPLICATE"):
        parse_full_dump(duplicated)


@pytest.mark.parametrize(
    ("original", "duplicate", "error"),
    [
        (b"Developer: Example", b"Developer: Other", "FULL_DEVELOPER_DUPLICATE"),
        (
            b"Type: text; size class: MID; capabilities: reasoning, coding, tools, long; open weights",
            b"Type: text; capabilities: coding",
            "FULL_TYPE_DUPLICATE",
        ),
    ],
)
def test_duplicate_model_metadata_is_rejected(original, duplicate, error):
    corrupt = FIXTURE.replace(original, original + b"\n" + duplicate, 1)
    with pytest.raises(SourceInvalid, match=error):
        parse_full_dump(corrupt)
