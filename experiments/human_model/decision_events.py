"""Explicit user decision events for HumanModel transitions.

Canon boundary: the Opportunity->Chat, Chat->Concept and Concept->Review
transitions require explicit user actions; AI cannot silently confirm a
Concept or opportunity, and feedback never automatically becomes a rule.
This module is the append-only contract for recording those decisions in
the evidence Ledger as kind="decision" rows. Isolated experiment, not a
Foundation service.

The actor check is a contract check only, not caller authentication: real
process isolation and Guard policy are still required before any product
integration, exactly as with the Ledger itself. A recorded decision is
data, never an instruction: recording one does not execute the transition,
approve a Concept, or change any view by itself.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

TRANSITIONS = frozenset({
    "opportunity_to_chat",
    "chat_to_concept",
    "concept_to_review",
})
ACTIONS = frozenset({"accept", "reject"})
USER_ACTOR = "user"


@dataclass(frozen=True)
class DecisionEvent:
    event_id: str
    transition: str
    target_id: str
    scope: str
    action: str
    actor: str
    rationale: str = ""
    decided_at: str | None = None


def _canonical(event: DecisionEvent) -> str:
    return json.dumps({
        "event_id": event.event_id,
        "transition": event.transition,
        "target_id": event.target_id,
        "scope": event.scope,
        "action": event.action,
        "actor": event.actor,
        "rationale": event.rationale,
        "decided_at": event.decided_at,
    }, ensure_ascii=False, sort_keys=True)


def _validate(event: DecisionEvent) -> None:
    if not all(isinstance(v, str) and v.strip() for v in
               (event.event_id, event.target_id, event.scope)):
        raise ValueError("event_id, target_id and scope required")
    if event.scope == "*":
        raise ValueError("wildcard scope prohibited")
    if event.transition not in TRANSITIONS:
        raise ValueError("unknown transition")
    if event.action not in ACTIONS:
        raise ValueError("action must be an explicit accept or reject")
    if event.actor != USER_ACTOR:
        raise ValueError("only the user can record a transition decision")


def record_decision(ledger, event: DecisionEvent, *, privacy="private",
                    supersedes=None) -> str:
    """Append a user decision to the Ledger; returns the evidence id.

    Idempotent for an identical event_id and payload (the Ledger returns
    the existing row). Reusing an event_id with a different payload is
    refused by the Ledger. A correction is a new event whose `supersedes`
    cites the earlier decision's evidence id, in the identical scope.
    """
    _validate(event)
    target = ledger.db.execute(
        "SELECT scope FROM evidence WHERE id=?", (event.target_id,)).fetchone()
    if target is None:
        raise ValueError("decision target evidence unavailable")
    if target[0] != event.scope:
        raise ValueError("decision target is outside the decision scope")
    if supersedes is not None:
        prior = ledger.db.execute(
            "SELECT kind, scope FROM evidence WHERE id=?",
            (supersedes,)).fetchone()
        if prior is None or prior[0] != "decision" or prior[1] != event.scope:
            raise ValueError("supersedes must cite a decision in the same scope")
    return ledger.add(
        source_uri=f"decision-event:{event.event_id}",
        source_revision="1",
        kind="decision",
        scope=event.scope,
        content=_canonical(event),
        privacy=privacy,
        observed_at=event.decided_at,
        supersedes=supersedes,
    )


def list_decisions(ledger, *, scope: str) -> list[dict]:
    """All recorded decisions in one scope, oldest first (audit view)."""
    if not scope or scope == "*":
        raise ValueError("explicit non-wildcard scope required")
    rows = ledger.db.execute(
        "SELECT id, content, supersedes, captured_at FROM evidence "
        "WHERE kind='decision' AND scope=? ORDER BY captured_at, id",
        (scope,)).fetchall()
    out = []
    for eid, content, supersedes, captured_at in rows:
        item = json.loads(content)
        item["evidence_id"] = eid
        item["supersedes"] = supersedes
        item["captured_at"] = captured_at
        out.append(item)
    return out


def current_decision(ledger, *, target_id: str, scope: str) -> dict | None:
    """The effective decision for a target, or None if the user has not decided.

    A decision superseded by a later decision event no longer counts; the
    newest non-superseded decision for the target wins. Absence of a
    decision is not an approval: callers must treat None as undecided.
    """
    decisions = [d for d in list_decisions(ledger, scope=scope)
                 if d["target_id"] == target_id]
    superseded = {d["supersedes"] for d in decisions if d["supersedes"]}
    effective = [d for d in decisions if d["evidence_id"] not in superseded]
    return effective[-1] if effective else None
