"""Source-qualified interaction events for opportunity-chat audits.

Pure validation only: no automatic HumanModel Ledger ingestion, inference,
external calls, or mutation. Distinguish user decisions from assistant claims.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Actor = Literal["user", "assistant", "automation", "external"]
Event = Literal[
    "user_question", "user_approval", "user_rejection", "user_correction",
    "assistant_proposal", "assistant_retraction", "assistant_execution_claim",
    "verified_outcome", "external_report",
]
Quality = Literal["direct", "summary_only", "external"]

_USER_EVENTS = frozenset({"user_question", "user_approval", "user_rejection", "user_correction"})
_ASSISTANT_EVENTS = frozenset({"assistant_proposal", "assistant_retraction", "assistant_execution_claim"})

@dataclass(frozen=True)
class OpportunityEvent:
    source_uri: str
    source_locator: str
    actor: Actor
    event: Event
    quality: Quality
    target_id: str
    text: str
    observed_at: str | None = None
    supersedes_locator: str | None = None

    def __post_init__(self):
        if not all(isinstance(x, str) and x.strip() for x in
                   (self.source_uri, self.source_locator, self.target_id, self.text)):
            raise ValueError("source, locator, target and text required")
        if self.actor not in ("user", "assistant", "automation", "external"):
            raise ValueError("unknown actor")
        if self.event not in (_USER_EVENTS | _ASSISTANT_EVENTS |
                             {"verified_outcome", "external_report"}):
            raise ValueError("unknown event")
        if self.quality not in ("direct", "summary_only", "external"):
            raise ValueError("unknown evidence quality")
        if self.event in _USER_EVENTS and self.actor != "user":
            raise ValueError("only user source may establish user decisions")
        if self.event in _ASSISTANT_EVENTS and self.actor not in ("assistant", "automation"):
            raise ValueError("assistant event requires assistant or automation actor")
        if self.event == "verified_outcome" and self.quality != "direct":
            raise ValueError("verified outcome requires direct evidence")
        if self.event == "assistant_retraction" and not self.supersedes_locator:
            raise ValueError("retraction requires prior claim locator")
        if self.quality == "summary_only" and self.source_locator.startswith("internal_message_id:"):
            raise ValueError("do not invent internal message IDs from summaries")

def classify(events: list[OpportunityEvent]) -> dict:
    """Counts explicit user decisions without treating proposals as approvals."""
    keys = [(e.source_uri, e.source_locator, e.event) for e in events]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate source event")
    locators = {(e.source_uri, e.source_locator) for e in events}
    for e in events:
        if e.supersedes_locator and (e.source_uri, e.supersedes_locator) not in locators:
            raise ValueError("retraction refers to unavailable source event")
    return {
        "total": len(events),
        "direct": sum(e.quality == "direct" for e in events),
        "summary_only": sum(e.quality == "summary_only" for e in events),
        "user_approvals": sum(e.event == "user_approval" for e in events),
        "assistant_proposals": sum(e.event == "assistant_proposal" for e in events),
        "verified_outcomes": sum(e.event == "verified_outcome" for e in events),
    }
