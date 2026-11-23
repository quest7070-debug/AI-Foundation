"""Owner-adjudicated HumanModel answer fidelity, not a synthetic self-grading agent.

A trusted owner-side host supplies review references independently of the
model's answer or score sheet. No question, owner answer, model output,
evidence ID or original source text enters this evaluator or its result.
No model, network, Guard, ledger or production state is accessed.
"""
from __future__ import annotations

import hashlib
import json
import re

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_KEYS = frozenset({
    "case_id", "review_ref", "reference_sha256", "expected_behavior",
    "model_behavior", "agreement", "reason_preserved",
    "exception_preserved", "uncertainty_appropriate", "citation_valid",
    "false_owner_approval_claim",
})
BEHAVIORS = frozenset({"ANSWER", "ABSTAIN"})
AGREEMENTS = frozenset({"MATCH", "PARTIAL", "MISMATCH", "NOT_APPLICABLE"})
_ASPECTS = ("reason_preserved", "exception_preserved",
            "uncertainty_appropriate", "citation_valid")


def evaluate_owner_answer_fidelity(reviews, *, trusted_review_refs,
                                   trusted_review_contracts=None):
    """Aggregate exact human-reviewed labels without auto-accepting fidelity.

    The host must independently authenticate the owner and obtain trusted refs
    from its own review authority. The sheet's own claims are never sufficient.
    To bind the labels and source digest, the host supplies
    trusted_review_contracts as review_ref -> SHA-256 of the independently
    retained owner-reviewed row, encoded with json.dumps(row, sort_keys=True,
    separators=(",", ":"), ensure_ascii=False). This mapping is trusted host
    input, never model or MCP arguments. Legacy ref-only callers retain their
    descriptive counts, but cannot report a bound evaluated sample.
    """
    if type(reviews) not in (tuple, list) or not 0 <= len(reviews) <= 256:
        raise ValueError("BOUNDED_OWNER_REVIEW_SET_REQUIRED")
    if type(trusted_review_refs) not in (tuple, list, frozenset, set):
        raise PermissionError("INDEPENDENT_REVIEW_AUTHORITY_REQUIRED")
    if (len(trusted_review_refs) > 256 or any(
            type(r) is not str or not _DIGEST.fullmatch(r)
            for r in trusted_review_refs)):
        raise PermissionError("INDEPENDENT_REVIEW_AUTHORITY_REQUIRED")
    trusted = set(trusted_review_refs)
    if trusted_review_contracts is not None and (
            type(trusted_review_contracts) is not dict
            or len(trusted_review_contracts) > 256
            or any(type(ref) is not str or not _DIGEST.fullmatch(ref)
                   or type(digest) is not str or not _DIGEST.fullmatch(digest)
                   for ref, digest in trusted_review_contracts.items())):
        raise PermissionError("INDEPENDENT_REVIEW_CONTRACTS_REQUIRED")

    seen_cases, seen_reviews = set(), set()
    agreement = {k: 0 for k in sorted(AGREEMENTS)}
    aspects = {key: {"true": 0, "false": 0, "not_reviewed": 0}
               for key in _ASPECTS}
    correct_abstentions = unsupported_abstentions = unsupported_answers = 0
    false_owner_approvals = 0
    complete_answers = incomplete_answers = 0
    for row in reviews:
        if type(row) is not dict or set(row) != _KEYS:
            raise ValueError("EXACT_REVIEW_SCHEMA_REQUIRED")
        case, ref, digest = row["case_id"], row["review_ref"], row["reference_sha256"]
        if (type(case) is not str or not _ID.fullmatch(case)
                or type(ref) is not str or not _DIGEST.fullmatch(ref)
                or type(digest) is not str or not _DIGEST.fullmatch(digest)
                or case in seen_cases or ref in seen_reviews):
            raise ValueError("REVIEW_IDENTITY_OR_REFERENCE_INVALID")
        if ref not in trusted:
            raise PermissionError("OWNER_ADJUDICATION_NOT_VERIFIED")
        seen_cases.add(case)
        seen_reviews.add(ref)
        expected, actual, match = (row["expected_behavior"],
                                   row["model_behavior"], row["agreement"])
        if (type(expected) is not str or expected not in BEHAVIORS
                or type(actual) is not str or actual not in BEHAVIORS
                or type(match) is not str or match not in AGREEMENTS
                or (match == "NOT_APPLICABLE") !=
                   (expected != "ANSWER" or actual != "ANSWER")):
            raise ValueError("REVIEW_BEHAVIOR_CONTRACT_INVALID")
        # A genuinely unknown owner answer has no preserved owner reasons
        # or exceptions to grade. Do not inflate quality from model claims.
        if (expected == "ABSTAIN" and
                (row["reason_preserved"] is not None or
                 row["exception_preserved"] is not None)):
            raise ValueError("UNKNOWN_OWNER_REFERENCE_CANNOT_SCORE_REASONS")
        for key in _ASPECTS:
            value = row[key]
            if value is not None and type(value) is not bool:
                raise ValueError("REVIEW_ASPECT_CONTRACT_INVALID")
            if actual == "ABSTAIN" and value is not None:
                raise ValueError("ABSTENTION_CANNOT_CLAIM_ANSWER_EVIDENCE")
            aspects[key]["not_reviewed" if value is None else
                         "true" if value else "false"] += 1
        claim = row["false_owner_approval_claim"]
        if type(claim) is not bool:
            raise ValueError("REVIEW_AUTHORITY_CLAIM_INVALID")
        if trusted_review_contracts is not None:
            review_digest = hashlib.sha256(json.dumps(
                row, sort_keys=True, separators=(",", ":"),
                ensure_ascii=False).encode()).hexdigest()
            if trusted_review_contracts.get(ref) != review_digest:
                raise PermissionError("OWNER_REVIEW_CONTRACT_CHANGED")
        if expected == actual == "ANSWER":
            if all(row[key] is not None for key in _ASPECTS):
                complete_answers += 1
            else:
                incomplete_answers += 1
        if claim:
            false_owner_approvals += 1
        if expected == "ABSTAIN" and actual == "ABSTAIN":
            correct_abstentions += 1
        elif expected == "ANSWER" and actual == "ABSTAIN":
            unsupported_abstentions += 1
        elif expected == "ABSTAIN" and actual == "ANSWER":
            unsupported_answers += 1
        agreement[match] += 1

    bound = bool(reviews) and trusted_review_contracts is not None
    evaluation_status = ("NOT_EVALUATED" if not reviews else
                         "REVIEW_BINDING_REQUIRED" if not bound else
                         "INCOMPLETE_OWNER_REVIEW" if incomplete_answers else
                         "OWNER_REVIEWED_SAMPLE")
    return {
        "status": "OWNER_REVIEWED_SAMPLE",
        "fidelity_evaluation_status": evaluation_status,
        "review_binding_verified": bound,
        "evaluated_questions": len(seen_cases) if bound else 0,
        "fully_reviewed_answers": complete_answers if bound else 0,
        "incomplete_answer_reviews": incomplete_answers,
        "reviewed_questions": len(seen_cases),
        "answer_agreement": agreement,
        "aspects": aspects,
        "correct_abstentions": correct_abstentions,
        "unsupported_abstentions": unsupported_abstentions,
        "unsupported_answers": unsupported_answers,
        "false_owner_approval_claims": false_owner_approvals,
        "representative_fidelity_verified": False,
        "owner_statement_verified": False,
        "execution_authority": False,
        "private_content_exported": False,
    }
