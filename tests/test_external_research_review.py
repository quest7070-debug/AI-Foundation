"""Tests for non-authoritative finding reviews."""
from datetime import datetime, timezone
import json

import pytest

from ai_foundation.external_research_handoff import parse_external_research_handoff
from ai_foundation.external_research_review import build_review_record, persist_review_record


def _handoff():
    return parse_external_research_handoff(json.dumps({
        "schema_version": 1, "producer": "muse", "correlation_id": "scout:test",
        "query": "test", "generated_at": "2026-11-03T09:00:00+09:00",
        "uncertainty": "unverified", "findings": [
            {"source_url": "https://example.org/a", "claim": "claim A", "confidence": "low"},
            {"source_url": "https://example.org/b", "claim": "claim B", "confidence": "medium"},
        ],
    }))


def test_review_is_inert_and_idempotent(tmp_path):
    h = _handoff()
    decisions = [{"decision": "HOLD", "rationale": "independent verification pending"},
                 {"decision": "REJECT", "rationale": "outdated"}]
    record = build_review_record(h, decisions, reviewed_at="2026-11-03T10:00:00Z", reviewer="reviewer")
    assert record["candidate_sha256"] == h.content_sha256
    assert [x["decision"] for x in record["findings"]] == ["HOLD", "REJECT"]
    assert record["execution_authorized"] is False
    assert record["trusted_as_authority"] is False
    path = tmp_path / "review.json"
    assert persist_review_record(path, record) is True
    assert persist_review_record(path, record) is False
    assert json.loads(path.read_text()) == record
    with pytest.raises(ValueError, match="conflicting"):
        persist_review_record(path, {**record, "reviewer": "other"})


@pytest.mark.parametrize("decisions", [
    [],
    [{"decision": "CANDIDATE", "rationale": "ok"}],
    [{"decision": "EXECUTE", "rationale": "no"}, {"decision": "HOLD", "rationale": "ok"}],
    [{"decision": "HOLD", "rationale": ""}, {"decision": "HOLD", "rationale": "ok"}],
    [{"decision": "HOLD", "rationale": "ok", "execution_authorized": True},
     {"decision": "HOLD", "rationale": "ok"}],
])
def test_rejects_incomplete_or_privileged_decisions(decisions):
    with pytest.raises(ValueError):
        build_review_record(_handoff(), decisions, reviewed_at="2026-11-03T10:00:00Z", reviewer="reviewer")


def test_rejects_naive_time_and_authorized_record(tmp_path):
    decisions = [{"decision": "HOLD", "rationale": "pending"}] * 2
    with pytest.raises(ValueError, match="timezone"):
        build_review_record(_handoff(), decisions, reviewed_at="2026-11-03T10:00:00", reviewer="reviewer")
    record = build_review_record(_handoff(), decisions, reviewed_at="2026-11-03T10:00:00Z", reviewer="reviewer")
    with pytest.raises(ValueError, match="authority"):
        persist_review_record(tmp_path / "bad.json", {**record, "execution_authorized": True})


def test_reviews_are_owner_private_even_with_permissive_umask(tmp_path):
    import os
    import stat

    h = _handoff()
    record = build_review_record(h, [
        {"decision": "HOLD", "rationale": "private owner review"},
        {"decision": "REJECT", "rationale": "unverified"},
    ], reviewed_at="2026-11-03T10:00:00Z", reviewer="owner")
    path = tmp_path / "private-review.json"
    before = os.umask(0)
    try:
        assert persist_review_record(path, record) is True
    finally:
        os.umask(before)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert persist_review_record(path, record) is False

    # A pre-existing readable review is not an acceptable idempotent receipt.
    path.chmod(0o644)
    with pytest.raises(ValueError, match="untrusted existing review"):
        persist_review_record(path, record)

    path.chmod(0o600)
    alias = tmp_path / "alias.json"
    alias.symlink_to(path)
    with pytest.raises(ValueError, match="untrusted existing review"):
        persist_review_record(alias, record)
