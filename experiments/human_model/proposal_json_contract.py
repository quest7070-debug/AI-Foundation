"""Strict boundary for untrusted OSS/LLM hypothesis JSON responses.

Parsing never performs network calls, writes evidence or creates model views.
"""
from __future__ import annotations
import json
from proposal_evaluation import Proposal, evaluate_approved_view

FIELDS = frozenset({
    "producer", "revision", "observed_at", "key", "statement", "scope",
    "supporting_ids", "contradicting_ids"
})
MAX_BYTES = 65536
MAX_PROPOSALS = 32

def parse_proposals(raw: str) -> list[Proposal]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_BYTES:
        raise ValueError("proposal payload must be a bounded JSON string")
    data = json.loads(raw)
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_PROPOSALS:
        raise ValueError("expected nonempty bounded proposal list")
    proposals = []
    for obj in data:
        if not isinstance(obj, dict) or set(obj) != FIELDS:
            raise ValueError("unexpected proposal fields")
        for name in ("producer", "revision", "observed_at", "key", "statement", "scope"):
            if not isinstance(obj[name], str) or not obj[name].strip():
                raise ValueError("missing or invalid proposal field: " + name)
            if len(obj[name]) > 4096:
                raise ValueError("oversized proposal field")
        for name in ("supporting_ids", "contradicting_ids"):
            ids = obj[name]
            if (not isinstance(ids, list) or len(ids) > 128
                    or any(not isinstance(i, str) or not i.strip() or len(i) > 256 for i in ids)):
                raise ValueError("invalid evidence references")
        proposals.append(Proposal(
            obj["producer"], obj["revision"], obj["observed_at"],
            obj["key"], obj["statement"], obj["scope"],
            tuple(obj["supporting_ids"]), tuple(obj["contradicting_ids"])))
    return proposals

def evaluate_json_approved_view(*, raw: str, root, view_id: str, scope: str,
                                max_privacy="private", **validation_options):
    proposals = parse_proposals(raw)
    return evaluate_approved_view(
        root=root, view_id=view_id, scope=scope, proposals=proposals,
        max_privacy=max_privacy, **validation_options)
