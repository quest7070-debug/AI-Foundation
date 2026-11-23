"""In-process, host-owned entrypoint for exact Kandev/HumanModel questions.

The existing /internal/kandev/question HTTP peer is NOT authenticated as an
owner and MUST NOT call this interface with data created from its JSON body.
Only a host producer that independently observed the current pending question,
authenticated the owner, fixed the Canon/Guard plan and verified the execution
slot may construct HostQuestionAuthority. No new approval store or executor.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

from .core import CanonContract, TaskPlan
from .human_model_context import build_human_model_context
from .human_model_primary_review import HumanModelPrimaryReview
from .primary_review_events import PrimaryReviewTransitions
from .question_bridge import classify_question, question_identity
from .question_ingress import _validate_bundle, resolve_ingress

_SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class HostQuestionAuthority:
    """Trusted in-process *result* of host authentication, never request JSON.

    The caller must have checked pending_id/task_id/session_id/generation against
    the CURRENT native question and obtained owner/plan from its own authority.
    A caller merely copying these fields from an HTTP bundle is not trusted.
    """
    owner_id: str
    pending_id: str
    task_id: str
    session_id: str
    question_digest: str
    scope: str
    plan: TaskPlan
    canon: CanonContract
    semantic_owner_required: bool = False
    local_confined: bool = False

    def __post_init__(self):
        for value in (self.owner_id, self.pending_id, self.task_id,
                      self.session_id, self.scope):
            if type(value) is not str or not 1 <= len(value) <= 128 or not value.strip():
                raise ValueError("invalid authenticated host question identity")
        if (type(self.question_digest) is not str or
                not _SHA.fullmatch(self.question_digest)):
            raise ValueError("exact host question generation required")
        if self.scope == "*":
            raise ValueError("wildcard HumanModel scope prohibited")
        if (type(self.semantic_owner_required) is not bool
                or type(self.local_confined) is not bool):
            raise ValueError("host-only classification/locality must be boolean")
        if not isinstance(self.plan, TaskPlan) or not isinstance(self.canon, CanonContract):
            raise ValueError("trusted Canon and Guard objects required")
        if (self.plan.run_id != self.task_id or not self.plan.action or
                not self.plan.target or not self.plan.effect_id or
                not self.plan.canon_revision or self.canon.revision != self.plan.canon_revision
                or not self.canon.clear):
            raise ValueError("host task/effect/Canon boundary mismatch")


def resolve_host_question(bundle, authority, *, guard, work_db, binding_path,
                          repository_root, deterministic_resolver=None,
                          context_builder=build_human_model_context):
    """One authenticated host request: Canon first, HumanModel only on exception.

    `authority` is passed by the trusted in-process producer, not parsed from
    HTTP headers, request body, Kandev prompt or GitHub Issue/LLM text. No
    reference to this method is exposed by the unauthenticated peer endpoint.
    """
    if type(authority) is not HostQuestionAuthority:
        raise PermissionError("host-authenticated question authority required")
    _validate_bundle(bundle)
    identity = question_identity(bundle)
    if (identity.pending_id != authority.pending_id or
            identity.task_id != authority.task_id or
            identity.session_id != authority.session_id or
            identity.digest != authority.question_digest):
        raise PermissionError("native pending question changed or identity mismatch")
    if guard is None:
        raise ValueError("canonical Guard required")

    # Resolve existing Canon before creating a private context or an event.
    deterministic = deterministic_resolver(bundle) if deterministic_resolver else None
    result_resolver = lambda _bundle: deterministic
    route = classify_question(bundle, canon_resolved=deterministic is not None).route
    needs_review = (deterministic is None and
                    (route == "HUMAN_GATE" or
                     (authority.semantic_owner_required and route in {"REASONING", "LOCAL"})))
    if not needs_review:
        return resolve_ingress(bundle, result_resolver)

    # The trusted producer must independently attest to a confined local output
    # path before any restricted/private approved View is read for this answer.
    context = context_builder(binding_path, authority.owner_id,
                              repository_root=repository_root, guard=guard,
                              run_id=authority.task_id)
    if context is not None and context.owner_id != authority.owner_id:
        raise PermissionError("HumanModel context owner differs from host")
    if context is not None and context.local_required and not authority.local_confined:
        return {
            "route": "HUMAN_GATE", "reason": "PRIVATE_VIEW_REQUIRES_LOCAL_HOST",
            "question_digest": identity.digest, "requires_human": True,
        }
    transitions = PrimaryReviewTransitions(work_db)
    primary = HumanModelPrimaryReview(
        owner_id=authority.owner_id, context=context, scope=authority.scope,
        guard=guard, plan=authority.plan, canon=authority.canon,
        transitions=transitions,
    )
    return resolve_ingress(
        bundle, result_resolver, primary_review=primary,
        exception_requires_owner=authority.semantic_owner_required,
    )
