"""Deterministic retrieval over one *already Guard-approved, complete* view.

HumanModelContext is the only host-authenticated reader. At its current
32-record / 32-KiB limit, a bounded literal scan is cheaper than creating a
new FTS5 index for every call. No model, persistent cache, tokenization,
semantic similarity, external data store or new background worker is used.
FTS5 may be re-evaluated when complete owner-paginated views are accepted.
"""
from __future__ import annotations

from collections.abc import Mapping


class SearchUnavailable(ValueError):
    """Fixed reason only; never include original source text."""


def exact_source_matches(snapshot: Mapping, query: str, *, max_results: int = 10):
    """Source-only candidates, not validated owner personal judgments.

    Every candidate retains original evidence ID/revision and flags contested
    or inferred items for review. This function never merges records or
    infers permission from their text.
    """
    if (type(query) is not str or not query.strip()
            or len(query) > 512 or type(max_results) is not int
            or not 1 <= max_results <= 10):
        raise SearchUnavailable("INVALID_SEARCH_QUERY")
    if (not isinstance(snapshot, dict)
            or snapshot.get("source") != "HumanModel"
            or snapshot.get("status") != "AVAILABLE"
            or snapshot.get("execution_authority") is not False
            or snapshot.get("truncated") is not False
            or snapshot.get("omitted_record_ids") != []
            or type(snapshot.get("view_revision")) is not int
            or snapshot["view_revision"] < 1
            or type(snapshot.get("scope")) is not str
            or not isinstance(snapshot.get("snapshot_sha256"), str)
            or len(snapshot["snapshot_sha256"]) != 64):
        raise SearchUnavailable("COMPLETE_CURRENT_VIEW_REQUIRED")
    rows = snapshot.get("records")
    if not isinstance(rows, list) or len(rows) > 32:
        raise SearchUnavailable("INVALID_SOURCE_ROWS")
    # Validate ID types before deduplication: malformed JSON arrays/objects
    # must fail closed, not raise TypeError from hashing untrusted values.
    if any(not isinstance(r, dict) or type(r.get("id")) is not str
           or not r["id"] for r in rows):
        raise SearchUnavailable("INVALID_SOURCE_ROWS")
    if len({r["id"] for r in rows}) != len(rows):
        raise SearchUnavailable("INVALID_SOURCE_ROWS")
    requested = query.casefold().strip()
    hits = []
    for row in rows:
        if (not isinstance(row, dict)
                or row.get("scope") != snapshot["scope"]
                or type(row.get("id")) is not str
                or type(row.get("content")) is not str
                or not row["id"]):
            raise SearchUnavailable("INVALID_SOURCE_ROWS")
        # Only exact ID or literal substring are supported; a tokenized
        # paraphrase or negation-conflation is NOT a factual match.
        ident = row["id"] == query.strip()
        literal = requested in row["content"].casefold()
        if ident or literal:
            hits.append((0 if ident else 1, row))
    hits.sort(key=lambda pair: (pair[0], pair[1]["id"]))
    selected = []
    for _, row in hits[:max_results]:
        selected.append(row)
    return {
        **snapshot,
        "records": selected,
        "status": "AVAILABLE" if selected else "NO_MATCH",
        "retrieval_engine": "literal-bounded-v1",
        "search_coverage": "COMPLETE_APPROVED_VIEW_ONLY",
        "interpretations_are_personal_facts": False,
        "requires_evidence_review": any(
            r.get("disputed") is True or r.get("kind") == "inference"
            for r in selected
        ),
    }
