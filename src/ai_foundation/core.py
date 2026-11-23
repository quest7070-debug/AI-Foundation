from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


class Decision(str, Enum):
    ALLOW = "ALLOW"
    LOCAL_ONLY = "LOCAL_ONLY"
    WAITING_HUMAN = "WAITING_HUMAN"
    DENY = "DENY"


class EffectStatus(str, Enum):
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    UNCERTAIN = "UNCERTAIN"
    OBSERVED = "OBSERVED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class CanonContract:
    source: str
    revision: str
    clear: bool = True

@dataclass(frozen=True)
class TaskPlan:
    run_id: str
    action: str
    target: str
    text: str = ""
    paid_cost: int = 0
    canon_revision: str = ""
    target_precondition: str = ""
    exclusive_target: bool = False
    credential_binding: str = ""
    effect_id: str = ""
    policy_revision: str = ""
    provenance: str = ""
    # Text actually crossing the inference boundary may contain system/assistant
    # prose. Privacy classification must inspect only user-originated content;
    # otherwise an assistant saying e.g. "personal files" can poison later turns.
    privacy_text: str | None = None


@dataclass
class EffectIntent:
    effect_id: str
    run_id: str
    target: str
    expected: str
    status: EffectStatus = EffectStatus.PLANNED
    paid_cost: int = 0


@dataclass
class GuardState:
    approvals: set[str] = field(default_factory=set)
    effects: dict[str, EffectIntent] = field(default_factory=dict)
    spent: int = 0
    cancellations: set[str] = field(default_factory=set)


class ExecutionPort(Protocol):
    def execute(self, plan: TaskPlan) -> None: ...
    def observe(self, plan: TaskPlan) -> str: ...

class CredentialBoundary(Protocol):
    def authorize(self, binding: str, target: str) -> bool: ...

class PolicyBoundary(Protocol):
    def authorize(self, plan: TaskPlan) -> Decision: ...
