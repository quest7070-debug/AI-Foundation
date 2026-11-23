"""HumanModel-first exception resolver under the existing Canon and Guard.

Only an authenticated host may inject its exact owner-bound HumanModelContext,
Guard plan, Canon, and durable review transitions. This module does not grant
authority, execute any effect, synthesize identity, or infer a personal choice.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from .core import Decision
from .question_bridge import question_identity

class _DuplicateDecisionKey(ValueError):
    pass


def _unique_decision_keys(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            raise _DuplicateDecisionKey("ambiguous owner-decision JSON")
        row[key] = value
    return row


_SCHEMA = "foundation-explicit-delegation/v1"
_FIELDS = frozenset({
    "schema", "question_digest", "answers", "answer_sha256", "action",
    "target_sha256", "effect_id", "canon_revision",
})


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def _notice_answer(bundle, answers):
    """Only the actual matched answer and question, never ledger evidence."""
    lines = []
    for question, answer in zip(bundle["questions"], answers):
        options = {option["option_id"]: option.get("label", "")
                   for option in question["options"]}
        lines.append("質問: " + str(question.get("prompt", "")))
        lines.append("自動回答: " + " / ".join(
            str(options[option_id] or option_id) + " [" + option_id + "]"
            for option_id in answer["selected_options"]))
    text = "\n".join(lines)
    if len(text) > 16000:
        text = text[:15940] + "\n…（通知の表示上限により後半を省略しています。）"
    return text


def _exact_answers(bundle, answers):
    """No freeform answer, invented option, omitted question or duplicate ID."""
    questions = bundle.get("questions")
    if (not isinstance(questions, list) or not questions
            or not isinstance(answers, list) or len(questions) != len(answers)):
        return False
    seen = set()
    for question, answer in zip(questions, answers):
        if not isinstance(question, dict) or not isinstance(answer, dict):
            return False
        if set(answer) != {"question_id", "selected_options"}:
            return False
        qid = question.get("question_id")
        if not isinstance(qid, str) or not qid or qid in seen:
            return False
        seen.add(qid)
        if answer["question_id"] != qid:
            return False
        options = question.get("options")
        if not isinstance(options, list) or not options:
            return False
        valid = [x.get("option_id") for x in options if isinstance(x, dict)]
        if (len(valid) != len(options) or any(type(x) is not str or not x for x in valid)
                or len(set(valid)) != len(valid)):
            return False
        chosen = answer["selected_options"]
        if (not isinstance(chosen, list) or not chosen or
                any(type(x) is not str for x in chosen) or
                len(set(chosen)) != len(chosen) or not set(chosen) <= set(valid)):
            return False
    return True


@dataclass(frozen=True)
class PrimaryReviewResult:
    status: str
    reason: str
    answer: object | None = None
    evidence_sha256: str = ""


class HumanModelPrimaryReview:
    """Exact, current HumanModel delegation evidence plus Guard preflight.

    HumanModel evidence is decision history, never Guard approval. The current
    Canon and source-backed explicit owner decision must both match. Even a
    matched result returns only an answer candidate to the existing native
    question/authority boundary, not permission to execute the action.
    """

    def __init__(self, *, owner_id, context, scope, guard, plan, canon, transitions):
        if not isinstance(owner_id, str) or not owner_id:
            raise ValueError("host-authenticated owner binding required")
        if context is not None and context.owner_id != owner_id:
            raise PermissionError("HumanModel owner mismatch")
        if not isinstance(scope, str) or not scope or scope == "*":
            raise ValueError("explicit approved review scope required")
        if (not getattr(plan, "effect_id", "") or not getattr(plan, "run_id", "")
                or not getattr(plan, "target", "") or not getattr(plan, "canon_revision", "")):
            raise ValueError("exact Guard task/effect/Canon identity required")
        self.owner_id = owner_id
        self.context = context
        self.scope = scope
        self.guard = guard
        self.plan = plan
        self.canon = canon
        self.transitions = transitions

    def _snapshot(self):
        if self.context is None:
            return None
        snapshot = json.loads(self.context.read(self.owner_id, self.scope))
        if (not isinstance(snapshot, dict) or snapshot.get("status") != "AVAILABLE"
                or snapshot.get("source") != "HumanModel"
                or snapshot.get("execution_authority") is not False
                or not isinstance(snapshot.get("records"), list)
                or not snapshot["records"]
                or not isinstance(snapshot.get("snapshot_sha256"), str)
                or len(snapshot["snapshot_sha256"]) != 64):
            return None
        return snapshot

    def _matches(self, snapshot, identity, bundle):
        expected = {
            "schema": _SCHEMA,
            "question_digest": identity.digest,
            "action": self.plan.action,
            "target_sha256": hashlib.sha256(self.plan.target.encode()).hexdigest(),
            "effect_id": self.plan.effect_id,
            "canon_revision": self.plan.canon_revision,
        }
        matches = []
        for record in snapshot["records"]:
            if (not isinstance(record, dict) or record.get("kind") != "decision"
                    or record.get("scope") != self.scope):
                continue
            content = record.get("content")
            if not isinstance(content, str):
                continue
            try:
                row = json.loads(content, object_pairs_hook=_unique_decision_keys)
            except _DuplicateDecisionKey:
                # A duplicate key can carry contradictory owner instructions.
                # Never select a favorable row while an ambiguous decision
                # remains in the approved scope.
                return None
            except (ValueError, TypeError):
                continue
            if not isinstance(row, dict) or row.get("question_digest") != identity.digest:
                continue
            # A contradictory, disputed, incomplete or differently scoped
            # decision for THIS question generation blocks all candidates.
            # Never select one apparently favorable row among conflicts.
            if (record.get("disputed") not in (False, 0)
                    or not record.get("source_uri") or not record.get("source_revision")
                    or not record.get("observed_at")):
                return None
            digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
            if digest != record.get("content_sha256"):
                return None
            if set(row) != _FIELDS or any(row.get(k) != v for k, v in expected.items()):
                return None
            answers = row.get("answers")
            if (not _exact_answers(bundle, answers) or
                    row.get("answer_sha256") != _digest(answers)):
                return None
            matches.append((record, answers))
        # Zero or multiple current decisions are not an executable preference.
        return matches[0] if len(matches) == 1 else None

    def review(self, bundle):
        identity = question_identity(bundle)
        if identity.task_id != self.plan.run_id:
            raise PermissionError("question not bound to exact Guard run")
        self.transitions.started(identity.task_id, identity.digest)
        outcome = "NO_MATCHING_EVIDENCE"
        evidence_digest = ""
        answer = None
        answer_text = ""
        reason = "NO_EXACT_APPLICABLE_DELEGATION"
        try:
            first = self._snapshot()
            if first is None:
                outcome = "APPROVED_VIEW_UNAVAILABLE"
                reason = "CURRENT_APPROVED_HUMANMODEL_VIEW_UNAVAILABLE"
            else:
                match = self._matches(first, identity, bundle)
                if match is not None:
                    # Verify current View has not been rebuilt, revoked or
                    # superseded during the review.
                    second = self._snapshot()
                    if (second is None or
                            second["snapshot_sha256"] != first["snapshot_sha256"] or
                            second.get("view_revision") != first.get("view_revision")):
                        outcome = "APPROVED_VIEW_UNAVAILABLE"
                        reason = "HUMANMODEL_SNAPSHOT_CHANGED"
                    elif self.guard.preflight(self.plan, self.canon) is not Decision.ALLOW:
                        outcome = "EXISTING_GUARD_DENIED"
                        reason = "GUARD_SCOPE_NOT_AUTHORIZED"
                    else:
                        outcome = "MATCHED_EXISTING_DELEGATION"
                        evidence_digest = match[0]["content_sha256"]
                        answer = match[1]
                        answer_text = _notice_answer(bundle, answer)
                        reason = "EXPLICIT_DELEGATION_AND_GUARD_MATCHED"
        except Exception:
            # Protect source text, paths and exception details from notifications.
            outcome = "REVIEW_TECHNICAL_FAILURE"
            evidence_digest = ""
            answer = None
            answer_text = ""
            reason = "PRIMARY_REVIEW_TECHNICAL_FAILURE"
        # A conflicting prior outcome for the same generation must fail closed;
        # it is not silently replayed or overwritten.
        self.transitions.resolved(identity.task_id, identity.digest, outcome,
                                  evidence_sha256=evidence_digest,
                                  answer_text=answer_text)
        return PrimaryReviewResult(
            "RESOLVED_DELEGATED" if outcome == "MATCHED_EXISTING_DELEGATION" else
            "REVIEW_FAILED" if outcome == "REVIEW_TECHNICAL_FAILURE" else
            "WAITING_HUMAN", reason, answer, evidence_digest
        )

