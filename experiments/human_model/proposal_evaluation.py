"""Validate independently produced hypothesis proposals against approved evidence.

Proposal generators (OSS or LLM) are untrusted; only evidence IDs present in an
approved Foundation view may contribute to a hypothesis. No automatic endorsement.
"""
from __future__ import annotations
from dataclasses import dataclass
from hypothesis_engine import evaluate_hypothesis
from temporal_comparison import ModelSnapshot, compare_snapshots

@dataclass(frozen=True)
class Proposal:
    producer: str
    revision: str
    observed_at: str
    key: str
    statement: str
    scope: str
    supporting_ids: tuple[str, ...]
    contradicting_ids: tuple[str, ...]

def evaluate_proposals(*, proposals: list[Proposal], evidence: list[dict]) -> dict:
    if not proposals:
        raise ValueError("at least one proposal required")
    snapshots = []
    for proposal in proposals:
        if not all(isinstance(v, str) and v.strip()
                   for v in (proposal.producer, proposal.revision, proposal.observed_at)):
            raise ValueError("producer, revision and observed_at required")
        hypothesis = evaluate_hypothesis(
            key=proposal.key, statement=proposal.statement, scope=proposal.scope,
            supporting_ids=proposal.supporting_ids,
            contradicting_ids=proposal.contradicting_ids,
            evidence=evidence)
        snapshots.append(ModelSnapshot(
            proposal.producer, proposal.revision, proposal.observed_at, hypothesis))
    return compare_snapshots(snapshots)

def evaluate_approved_view(*, root, view_id: str, scope: str,
                           proposals: list[Proposal], max_privacy="private",
                           **validation_options) -> dict:
    from foundation_readonly import read_view
    evidence = read_view(root, view_id=view_id, scope=scope,
                         max_privacy=max_privacy, **validation_options)
    if any(p.scope != scope for p in proposals):
        raise ValueError("proposal scope differs from approved view scope")
    return evaluate_proposals(proposals=proposals, evidence=evidence)
