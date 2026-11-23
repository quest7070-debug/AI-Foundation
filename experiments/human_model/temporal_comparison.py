"""Versioned, non-convergent hypothesis comparisons.

Models are proposals with explicit evidence, not inferred personality facts.
Snapshots retain provenance and disagreements; no averaging or winner selection.
"""
from __future__ import annotations
from dataclasses import dataclass
from hypothesis_engine import Hypothesis

@dataclass(frozen=True)
class ModelSnapshot:
    producer: str
    revision: str
    observed_at: str
    hypothesis: Hypothesis

def compare_snapshots(snapshots: list[ModelSnapshot]) -> dict:
    if not snapshots:
        raise ValueError("at least one snapshot required")
    for item in snapshots:
        if not all((item.producer, item.revision, item.observed_at)):
            raise ValueError("producer, revision and observation time required")
    key = snapshots[0].hypothesis.key
    scope = snapshots[0].hypothesis.scope
    if any(s.hypothesis.key != key or s.hypothesis.scope != scope for s in snapshots):
        raise ValueError("cannot compare different hypothesis keys or scopes")
    identities = [(s.producer, s.revision) for s in snapshots]
    if len(set(identities)) != len(identities):
        raise ValueError("duplicate producer revision")
    # Preserve submission order; caller owns chronological ordering and timestamp validity.
    transitions = []
    for before, after in zip(snapshots, snapshots[1:]):
        transitions.append({
            "from": (before.producer, before.revision),
            "to": (after.producer, after.revision),
            "status_changed": before.hypothesis.status != after.hypothesis.status,
            "support_added": sorted(set(after.hypothesis.supporting_ids) - set(before.hypothesis.supporting_ids)),
            "support_removed": sorted(set(before.hypothesis.supporting_ids) - set(after.hypothesis.supporting_ids)),
            "contradiction_added": sorted(set(after.hypothesis.contradicting_ids) - set(before.hypothesis.contradicting_ids)),
            "contradiction_removed": sorted(set(before.hypothesis.contradicting_ids) - set(after.hypothesis.contradicting_ids)),
        })
    return {
        "key": key, "scope": scope, "snapshots": snapshots,
        "transitions": transitions,
        "producer_disagreement": len({s.hypothesis.status for s in snapshots}) > 1,
        "consensus": None,
    }
