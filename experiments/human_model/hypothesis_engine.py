"""Evidence-grounded hypothesis snapshots; not a psychological classifier.

The engine never converts raw prose into asserted personality traits. A hypothesis
must be explicitly supplied with supporting and contradicting evidence IDs.
Conflicts are retained and no ungrounded numeric confidence is invented.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable

@dataclass(frozen=True)
class Hypothesis:
    key: str
    statement: str
    scope: str
    supporting_ids: tuple[str, ...]
    contradicting_ids: tuple[str, ...]
    status: str
    uncertainty: str

def evaluate_hypothesis(*, key: str, statement: str, scope: str,
                        supporting_ids: Iterable[str], contradicting_ids: Iterable[str],
                        evidence: list[dict]) -> Hypothesis:
    if not all(isinstance(v, str) and v.strip() for v in (key, statement, scope)):
        raise ValueError("key, statement and scope required")
    if scope == "*":
        raise ValueError("wildcard scope prohibited")
    support = tuple(dict.fromkeys(supporting_ids))
    contra = tuple(dict.fromkeys(contradicting_ids))
    if len(set(support)) != len(support) or len(set(contra)) != len(contra):
        raise ValueError("duplicate evidence references")
    if set(support) & set(contra):
        raise ValueError("same evidence cannot be both supporting and contradicting")
    by_id = {row["id"]: row for row in evidence}
    if len(by_id) != len(evidence):
        raise ValueError("duplicate evidence ids in input")
    for eid in (*support, *contra):
        row = by_id.get(eid)
        if row is None or row["scope"] != scope:
            raise ValueError("evidence reference unavailable or outside scope")
        if row.get("disputed"):
            raise ValueError("disputed evidence requires reconciliation")
    status = ("contested" if support and contra else
              "supported" if support else
              "contradicted" if contra else "unassessed")
    uncertainty = ("conflicting evidence" if status == "contested" else
                   "no evidence" if status == "unassessed" else
                   "qualitative only; coverage and sampling unknown")
    return Hypothesis(key, statement, scope, support, contra, status, uncertainty)

def evaluate_from_approved_view(*, root, view_id, key, statement, scope,
                                supporting_ids, contradicting_ids,
                                max_privacy="private", **validation_options):
    from foundation_readonly import read_view
    rows = read_view(root, view_id=view_id, scope=scope,
                     max_privacy=max_privacy, **validation_options)
    return evaluate_hypothesis(
        key=key, statement=statement, scope=scope,
        supporting_ids=supporting_ids, contradicting_ids=contradicting_ids,
        evidence=rows)
