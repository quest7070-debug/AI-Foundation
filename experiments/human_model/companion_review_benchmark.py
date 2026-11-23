"""HumanModel companion: independently adjudicated hypothesis-review benchmark.

Adopts the useful *evaluation method* of GitHub ReviewBench, not its code-review
dataset. A user's explicit correction or independent result is ground truth;
an AI's own assessment never creates ground-truth labels. This module has no
network, model calls, ledger reads/writes or ranking/auto-selection side effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

VERIFIERS = frozenset({"explicit_user_review", "independent_test"})


@dataclass(frozen=True)
class ReviewedCase:
    case_id: str
    source_uri: str
    adjudication_ref: str
    verified_by: str
    relevant_keys: tuple[str, ...]
    irrelevant_keys: tuple[str, ...]

    def __post_init__(self):
        if not all(isinstance(v, str) and v.strip() for v in (
            self.case_id, self.source_uri, self.adjudication_ref, self.verified_by)):
            raise ValueError("review case requires provenance and verification")
        if self.verified_by not in VERIFIERS:
            raise ValueError("AI proposals cannot be ground truth")
        for keys in (self.relevant_keys, self.irrelevant_keys):
            if not isinstance(keys, tuple) or len(set(keys)) != len(keys):
                raise ValueError("review labels must be unique tuples")
            if any(not isinstance(key, str) or not key.strip() for key in keys):
                raise ValueError("blank review label")
        if set(self.relevant_keys) & set(self.irrelevant_keys):
            raise ValueError("conflicting reviewer labels")


@dataclass(frozen=True)
class ModelFindings:
    model: str
    case_id: str
    found_keys: tuple[str, ...]

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() for x in (self.model, self.case_id)):
            raise ValueError("model and case ID required")
        if not isinstance(self.found_keys, tuple) or len(set(self.found_keys)) != len(self.found_keys):
            raise ValueError("model findings must be unique tuples")
        if any(not isinstance(x, str) or not x.strip() for x in self.found_keys):
            raise ValueError("blank model finding")


def evaluate_reviewed_findings(*, cases: Iterable[ReviewedCase],
                               findings: Iterable[ModelFindings],
                               trusted_adjudication_refs: Iterable[str] = ()) -> dict:
    """Score only adjudicated keys. Leave unknown findings unjudged.

    Every compared model must have a result for *every* case. Reports counts,
    precision and recall, but never crowns a winning model automatically.
    """
    cases = list(cases)
    findings = list(findings)
    trusted = set(trusted_adjudication_refs)
    if any(not isinstance(v, str) or not v.strip() for v in trusted):
        raise ValueError("invalid trusted adjudication reference")
    if not cases or not findings:
        raise ValueError("at least one case and model finding required")
    truth = {}
    for case in cases:
        if not isinstance(case, ReviewedCase) or case.case_id in truth:
            raise ValueError("duplicate or invalid case")
        if case.adjudication_ref not in trusted:
            raise PermissionError("adjudication must be independently confirmed by caller")
        truth[case.case_id] = case
    model_cases = {}
    for finding in findings:
        if not isinstance(finding, ModelFindings):
            raise ValueError("invalid model finding")
        if finding.case_id not in truth:
            raise ValueError("finding lacks independently reviewed case")
        models = model_cases.setdefault(finding.model, {})
        if finding.case_id in models:
            raise ValueError("duplicate model/case finding")
        models[finding.case_id] = finding
    expected_cases = set(truth)
    for results in model_cases.values():
        if set(results) != expected_cases:
            raise ValueError("model comparisons need complete equal case coverage")
    output = {}
    for model, results in sorted(model_cases.items()):
        tp = fp = fn = unjudged = 0
        for case_id, finding in results.items():
            case = truth[case_id]
            relevant = set(case.relevant_keys)
            irrelevant = set(case.irrelevant_keys)
            found = set(finding.found_keys)
            tp += len(found & relevant)
            fp += len(found & irrelevant)
            fn += len(relevant - found)
            unjudged += len(found - relevant - irrelevant)
        output[model] = {
            "true_positive": tp, "false_positive": fp,
            "false_negative": fn, "unjudged": unjudged,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
        }
    return {
        "cases": len(cases), "models": output,
        "winning_model": None,
        "no_personality_inference": True,
        "coverage_equal": True,
    }
