"""Pure closeout contract assessment for the existing Paseo-owned task.

This module does not own task state, persist a second task graph, close work,
send notifications, register improvement targets, or delete data. It validates
owner-provided evidence before the existing task owner may close a task.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class WorkOutcome(str, Enum):
    VERIFIED_CHANGE = "VERIFIED_CHANGE"
    NO_CHANGE_VERIFIED = "NO_CHANGE_VERIFIED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    UNCERTAIN = "UNCERTAIN"
    CANCELLED = "CANCELLED"


class RequestedAcceptance(str, Enum):
    COMMIT = "COMMIT"
    PULL_REQUEST = "PULL_REQUEST"
    MERGE = "MERGE"
    DEPLOY = "DEPLOY"


class DeliveryKind(str, Enum):
    COMMIT_PRESENTED = "COMMIT_PRESENTED"
    PR_PRESENTED = "PR_PRESENTED"
    MERGED_ACCEPTED = "MERGED_ACCEPTED"
    DEPLOYED_ACCEPTED = "DEPLOYED_ACCEPTED"
    NO_CHANGE_PRESENTED = "NO_CHANGE_PRESENTED"


class DeliveryNotificationStatus(str, Enum):
    DELIVERED = "DELIVERED"
    READ = "READ"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPPRESSED_QUERYABLE = "SUPPRESSED_QUERYABLE"
    FAILED = "FAILED"
    PENDING = "PENDING"
    EXPIRED = "EXPIRED"


class TaskTerminalState(str, Enum):
    """Normalized readback only; the Paseo owner's underlying state is unchanged."""
    SETTLED = "SETTLED"
    NO_CHANGE = "NO_CHANGE"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    UNCERTAIN = "UNCERTAIN"
    ACTIVE = "ACTIVE"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"


class CleanupDomain(str, Enum):
    SOURCE_DOCS_GENERATED = "SOURCE_DOCS_GENERATED"
    WORK_AREAS = "WORK_AREAS"
    TASK_SESSION_EFFECTS = "TASK_SESSION_EFFECTS"
    TRACE_LOG_KNOWLEDGE = "TRACE_LOG_KNOWLEDGE"
    MODELS_DEPENDENCIES_CONTAINERS = "MODELS_DEPENDENCIES_CONTAINERS"
    DATABASE_ATTACHMENTS_SEARCH = "DATABASE_ATTACHMENTS_SEARCH"
    BACKUPS_UPDATES_RECOVERY = "BACKUPS_UPDATES_RECOVERY"
    CONFIG_CREDENTIALS_EXTERNAL = "CONFIG_CREDENTIALS_EXTERNAL"


class CleanupDisposition(str, Enum):
    CLEANED = "CLEANED"
    RETAINED = "RETAINED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    UNRESOLVED = "UNRESOLVED"


class CloseoutStatus(str, Enum):
    READY_TO_CLOSE = "READY_TO_CLOSE"
    NO_CHANGE_READY = "NO_CHANGE_READY"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class CloseoutScope:
    task_id: str
    original_request_id: str
    owner_scope: str
    repository: str
    improvement_target_repo: str
    intent_revision: str
    source_revision: str
    canon_revision: str
    producer_ref: str
    requested_acceptance: RequestedAcceptance
    requires_human_acceptance: bool = False
    human_acceptance_ref: str | None = None
    pending_questions: tuple[str, ...] = ()
    pending_approvals: tuple[str, ...] = ()
    unreconciled_effects: tuple[str, ...] = ()
    unresolved_semantics: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerificationEvidence:
    task_id: str
    original_request_id: str
    owner_scope: str
    repository: str
    intent_revision: str
    source_revision: str
    canon_revision: str
    outcome: WorkOutcome
    verifier_ref: str
    evidence_ref: str


@dataclass(frozen=True)
class DeliveryEvidence:
    task_id: str
    original_request_id: str
    owner_scope: str
    repository: str
    intent_revision: str
    source_revision: str
    canon_revision: str
    kind: DeliveryKind
    notification_status: DeliveryNotificationStatus
    notification_ref: str | None
    result_query_ref: str | None
    target_ref: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True)
class TaskTerminalEvidence:
    task_id: str
    original_request_id: str
    owner_scope: str
    repository: str
    intent_revision: str
    source_revision: str
    canon_revision: str
    state: TaskTerminalState
    owner_ref: str
    receipt_ref: str
    readback_ref: str


@dataclass(frozen=True)
class ImprovementHandoffReceipt:
    task_id: str
    original_request_id: str
    owner_scope: str
    source_repository: str
    intent_revision: str
    source_revision: str
    canon_revision: str
    target_repo: str
    target_revision: str
    semantic_index_revision: str
    receipt_ref: str
    readback_ref: str
    accepted_by_target_owner: bool
    purpose_ref: str
    non_goals_ref: str
    dependency_refs: tuple[str, ...]
    acceptance_refs: tuple[str, ...]
    constraint_refs: tuple[str, ...]
    failure_knowledge_refs: tuple[str, ...]
    monitoring_refs: tuple[str, ...]
    authority_refs: tuple[str, ...]
    rollback_refs: tuple[str, ...]


@dataclass(frozen=True)
class CleanupEntry:
    task_id: str
    original_request_id: str
    owner_scope: str
    repository: str
    intent_revision: str
    source_revision: str
    canon_revision: str
    domain: CleanupDomain
    owner_ref: str
    disposition: CleanupDisposition
    reason: str
    evidence_refs: tuple[str, ...]
    postcheck_ref: str


@dataclass(frozen=True)
class CloseoutRequest:
    scope: CloseoutScope
    task_terminal: TaskTerminalEvidence | None
    verification: VerificationEvidence | None
    delivery: DeliveryEvidence | None
    improvement_handoff: ImprovementHandoffReceipt | None
    cleanup_ledger: tuple[CleanupEntry, ...]


@dataclass(frozen=True)
class CloseoutBlocker:
    code: str
    detail: str


@dataclass(frozen=True)
class CloseoutAssessment:
    status: CloseoutStatus
    task_id: str
    blockers: tuple[CloseoutBlocker, ...] = ()
    evidence_refs: tuple[str, ...] = ()

    @property
    def ready_to_close(self) -> bool:
        return self.status in {
            CloseoutStatus.READY_TO_CLOSE,
            CloseoutStatus.NO_CHANGE_READY,
        }


def assess_closeout(request: CloseoutRequest) -> CloseoutAssessment:
    """Validate the five closeout gates without performing any side effect."""
    scope = request.scope
    blockers: list[CloseoutBlocker] = []
    evidence: set[str] = set()

    for field_name in (
        "task_id",
        "original_request_id",
        "owner_scope",
        "repository",
        "improvement_target_repo",
        "intent_revision",
        "source_revision",
        "canon_revision",
        "producer_ref",
    ):
        if not _present(getattr(scope, field_name)):
            blockers.append(CloseoutBlocker(
                "SCOPE_INCOMPLETE",
                f"scope.{field_name} is required",
            ))

    if not isinstance(scope.requested_acceptance, RequestedAcceptance):
        blockers.append(CloseoutBlocker(
            "REQUESTED_ACCEPTANCE_INVALID",
            "requested acceptance must be an explicit contract value",
        ))
    if not isinstance(scope.requires_human_acceptance, bool):
        blockers.append(CloseoutBlocker(
            "SCOPE_INVALID",
            "requires_human_acceptance must be boolean",
        ))

    for field_name in (
        "pending_questions",
        "pending_approvals",
        "unreconciled_effects",
        "unresolved_semantics",
    ):
        values = getattr(scope, field_name)
        if not isinstance(values, (tuple, list)):
            blockers.append(CloseoutBlocker(
                "PENDING_WORK_INVALID",
                f"{field_name} must be a sequence so pending work can be assessed",
            ))
        elif values:
            blockers.append(CloseoutBlocker(
                "PENDING_WORK",
                f"{field_name} still contains {len(values)} unresolved item(s)",
            ))

    if (
        scope.requires_human_acceptance
        and not _present(scope.human_acceptance_ref)
    ):
        blockers.append(CloseoutBlocker(
            "HUMAN_ACCEPTANCE_MISSING",
            "the requested human acceptance has no independent receipt",
        ))
    if _present(scope.human_acceptance_ref):
        evidence.add(scope.human_acceptance_ref)

    verification = request.verification
    outcome = None
    if verification is None:
        blockers.append(CloseoutBlocker(
            "VERIFICATION_MISSING",
            "independent verification evidence is required",
        ))
    else:
        outcome = verification.outcome
        _check_identity("verification", scope, verification, blockers)
        if not isinstance(outcome, WorkOutcome):
            blockers.append(CloseoutBlocker(
                "VERIFICATION_OUTCOME_INVALID",
                "verification outcome must be an explicit contract value",
            ))
        if not _present(verification.evidence_ref):
            blockers.append(CloseoutBlocker(
                "VERIFICATION_EVIDENCE_MISSING",
                "verification evidence reference is required",
            ))
        else:
            evidence.add(verification.evidence_ref)
        if not _present(verification.verifier_ref):
            blockers.append(CloseoutBlocker(
                "VERIFIER_MISSING",
                "independent verifier identity is required",
            ))
        elif verification.verifier_ref == scope.producer_ref:
            blockers.append(CloseoutBlocker(
                "VERIFIER_NOT_INDEPENDENT",
                "producer and independent verifier must be distinct",
            ))
        if isinstance(outcome, WorkOutcome) and outcome not in {
            WorkOutcome.VERIFIED_CHANGE,
            WorkOutcome.NO_CHANGE_VERIFIED,
        }:
            blockers.append(CloseoutBlocker(
                "VERIFICATION_OUTCOME_NOT_SUCCESS",
                f"outcome {outcome!s} cannot be closed as successful delivery",
            ))

    terminal = request.task_terminal
    if terminal is None:
        blockers.append(CloseoutBlocker(
            "TASK_TERMINAL_READBACK_MISSING",
            "Paseo owner-issued terminal-state readback is required",
        ))
    else:
        _check_identity("task_terminal", scope, terminal, blockers)
        if not isinstance(terminal.state, TaskTerminalState):
            blockers.append(CloseoutBlocker(
                "TASK_TERMINAL_STATE_INVALID",
                "terminal state must be an explicit owner-normalized value",
            ))
        expected_terminal = (
            TaskTerminalState.NO_CHANGE
            if outcome is WorkOutcome.NO_CHANGE_VERIFIED
            else TaskTerminalState.SETTLED
        )
        if terminal.state is not expected_terminal:
            blockers.append(CloseoutBlocker(
                "TASK_TERMINAL_STATE_MISMATCH",
                f"terminal state {terminal.state!s} does not match {expected_terminal!s}",
            ))
        for field_name in ("owner_ref", "receipt_ref", "readback_ref"):
            value = getattr(terminal, field_name)
            if not _present(value):
                blockers.append(CloseoutBlocker(
                    "TASK_TERMINAL_EVIDENCE_MISSING",
                    f"task_terminal.{field_name} is required",
                ))
            else:
                evidence.add(value)

    delivery = request.delivery
    if delivery is None:
        blockers.append(CloseoutBlocker(
            "DELIVERY_MISSING",
            "delivery or explicit no-change presentation is required",
        ))
    else:
        _check_identity("delivery", scope, delivery, blockers)
        if not isinstance(delivery.notification_status, DeliveryNotificationStatus):
            blockers.append(CloseoutBlocker(
                "NOTIFICATION_STATUS_INVALID",
                "delivery notification status must be an explicit contract value",
            ))
        elif delivery.notification_status in {
            DeliveryNotificationStatus.DELIVERED,
            DeliveryNotificationStatus.READ,
            DeliveryNotificationStatus.ACKNOWLEDGED,
        }:
            if not _present(delivery.notification_ref):
                blockers.append(CloseoutBlocker(
                    "NOTIFICATION_EVIDENCE_MISSING",
                    "delivered/read/acknowledged notification requires its receipt",
                ))
            else:
                evidence.add(delivery.notification_ref)
        elif delivery.notification_status is DeliveryNotificationStatus.SUPPRESSED_QUERYABLE:
            if (
                outcome is not WorkOutcome.NO_CHANGE_VERIFIED
                or not _present(delivery.result_query_ref)
            ):
                blockers.append(CloseoutBlocker(
                    "NOTIFICATION_SUPPRESSION_UNJUSTIFIED",
                    "suppression is allowed only for verified NO_CHANGE with a queryable result",
                ))
            else:
                evidence.add(delivery.result_query_ref)
        else:
            blockers.append(CloseoutBlocker(
                "NOTIFICATION_NOT_DELIVERED",
                f"notification status {delivery.notification_status!s} is not terminal delivery",
            ))
        if (
            scope.requires_human_acceptance
            and delivery.notification_status is not DeliveryNotificationStatus.ACKNOWLEDGED
        ):
            blockers.append(CloseoutBlocker(
                "HUMAN_DECISION_NOT_ACKNOWLEDGED",
                "a task requiring human acceptance needs an acknowledged UI notification",
            ))
        if _present(delivery.notification_ref):
            evidence.add(delivery.notification_ref)
        if _present(delivery.result_query_ref):
            evidence.add(delivery.result_query_ref)

        if not _present(delivery.target_ref):
            blockers.append(CloseoutBlocker(
                "DELIVERY_TARGET_MISSING",
                "delivery target/result reference is required",
            ))
        else:
            evidence.add(delivery.target_ref)
        delivery_refs = delivery.evidence_refs
        if (
            not isinstance(delivery_refs, (tuple, list))
            or not delivery_refs
            or not all(_present(item) for item in delivery_refs)
        ):
            blockers.append(CloseoutBlocker(
                "DELIVERY_EVIDENCE_MISSING",
                "delivery must have a sequence of non-empty evidence references",
            ))
        else:
            evidence.update(delivery_refs)

        if outcome is WorkOutcome.NO_CHANGE_VERIFIED:
            expected_delivery = DeliveryKind.NO_CHANGE_PRESENTED
        elif isinstance(scope.requested_acceptance, RequestedAcceptance):
            expected_delivery = {
                RequestedAcceptance.COMMIT: DeliveryKind.COMMIT_PRESENTED,
                RequestedAcceptance.PULL_REQUEST: DeliveryKind.PR_PRESENTED,
                RequestedAcceptance.MERGE: DeliveryKind.MERGED_ACCEPTED,
                RequestedAcceptance.DEPLOY: DeliveryKind.DEPLOYED_ACCEPTED,
            }[scope.requested_acceptance]
        else:
            expected_delivery = None
        if delivery.kind is not expected_delivery:
            blockers.append(CloseoutBlocker(
                "DELIVERY_KIND_MISMATCH",
                (
                    f"delivery kind {delivery.kind!s} does not match "
                    f"required {expected_delivery!s}"
                ),
            ))

    handoff = request.improvement_handoff
    if handoff is None:
        blockers.append(CloseoutBlocker(
            "IMPROVEMENT_HANDOFF_MISSING",
            "permanent improvement-target receipt is required before closeout",
        ))
    else:
        _check_identity(
            "improvement_handoff",
            scope,
            handoff,
            blockers,
            repository_field="source_repository",
        )
        if handoff.target_repo != scope.improvement_target_repo:
            blockers.append(CloseoutBlocker(
                "IMPROVEMENT_HANDOFF_REPOSITORY_MISMATCH",
                "improvement target repository does not match the task contract",
            ))
        if handoff.accepted_by_target_owner is not True:
            blockers.append(CloseoutBlocker(
                "IMPROVEMENT_HANDOFF_NOT_RECEIVED",
                "target owner has not accepted and read back the handoff",
            ))
        for field_name in (
            "target_repo",
            "target_revision",
            "semantic_index_revision",
            "receipt_ref",
            "readback_ref",
            "purpose_ref",
            "non_goals_ref",
        ):
            value = getattr(handoff, field_name)
            if not _present(value):
                blockers.append(CloseoutBlocker(
                    "IMPROVEMENT_HANDOFF_EVIDENCE_INCOMPLETE",
                    f"improvement_handoff.{field_name} is required",
                ))
            else:
                evidence.add(value)
        for field_name in (
            "dependency_refs",
            "acceptance_refs",
            "constraint_refs",
            "failure_knowledge_refs",
            "monitoring_refs",
            "authority_refs",
            "rollback_refs",
        ):
            values = getattr(handoff, field_name)
            if not _valid_reference_sequence(values):
                blockers.append(CloseoutBlocker(
                    "IMPROVEMENT_HANDOFF_EVIDENCE_INCOMPLETE",
                    f"improvement_handoff.{field_name} must be a sequence of non-empty references",
                ))
            else:
                evidence.update(values)

    cleanup_by_domain: dict[CleanupDomain, CleanupEntry] = {}
    for entry in request.cleanup_ledger:
        if not isinstance(entry.domain, CleanupDomain):
            blockers.append(CloseoutBlocker(
                "CLEANUP_DOMAIN_INVALID",
                "cleanup domain must be one of the eight declared domains",
            ))
            continue
        if not isinstance(entry.disposition, CleanupDisposition):
            blockers.append(CloseoutBlocker(
                "CLEANUP_DISPOSITION_INVALID",
                f"cleanup domain {entry.domain.value} has an invalid disposition",
            ))
            continue
        if entry.domain in cleanup_by_domain:
            blockers.append(CloseoutBlocker(
                "CLEANUP_DOMAIN_DUPLICATE",
                f"cleanup domain {entry.domain!s} appears more than once",
            ))
            continue
        cleanup_by_domain[entry.domain] = entry

    for domain in CleanupDomain:
        entry = cleanup_by_domain.get(domain)
        if entry is None:
            blockers.append(CloseoutBlocker(
                "CLEANUP_DOMAIN_MISSING",
                f"cleanup domain {domain.value} has no owner disposition",
            ))
            continue
        _check_identity(f"cleanup:{domain.value}", scope, entry, blockers)
        if entry.disposition is CleanupDisposition.UNRESOLVED:
            blockers.append(CloseoutBlocker(
                "CLEANUP_UNRESOLVED",
                f"cleanup domain {domain.value} remains unresolved",
            ))
        if not _present(entry.owner_ref):
            blockers.append(CloseoutBlocker(
                "CLEANUP_OWNER_MISSING",
                f"cleanup domain {domain.value} has no responsible owner",
            ))
        if not _present(entry.reason):
            blockers.append(CloseoutBlocker(
                "CLEANUP_REASON_MISSING",
                f"cleanup domain {domain.value} has no disposition rationale",
            ))
        if not _valid_reference_sequence(entry.evidence_refs):
            blockers.append(CloseoutBlocker(
                "CLEANUP_EVIDENCE_MISSING",
                f"cleanup domain {domain.value} has no valid evidence/readback sequence",
            ))
        if not _present(entry.postcheck_ref):
            blockers.append(CloseoutBlocker(
                "CLEANUP_POSTCHECK_MISSING",
                f"cleanup domain {domain.value} has no postcheck",
            ))
        if _valid_reference_sequence(entry.evidence_refs):
            evidence.update(entry.evidence_refs)
        if _present(entry.postcheck_ref):
            evidence.add(entry.postcheck_ref)

    status = CloseoutStatus.BLOCKED if blockers else (
        CloseoutStatus.NO_CHANGE_READY
        if outcome is WorkOutcome.NO_CHANGE_VERIFIED
        else CloseoutStatus.READY_TO_CLOSE
    )
    return CloseoutAssessment(
        status=status,
        task_id=scope.task_id,
        blockers=tuple(blockers),
        evidence_refs=tuple(sorted(evidence)),
    )


def _check_identity(
    label,
    scope,
    evidence,
    blockers,
    *,
    repository_field: str = "repository",
) -> None:
    for field_name in (
        "task_id",
        "original_request_id",
        "owner_scope",
        "intent_revision",
        "source_revision",
        "canon_revision",
    ):
        if getattr(evidence, field_name) != getattr(scope, field_name):
            blockers.append(CloseoutBlocker(
                "EVIDENCE_IDENTITY_MISMATCH",
                f"{label}.{field_name} does not match the active task scope",
            ))
    if getattr(evidence, repository_field, None) != scope.repository:
        blockers.append(CloseoutBlocker(
            "EVIDENCE_REPOSITORY_MISMATCH",
            f"{label}.{repository_field} does not match the source repository",
        ))


def _present(value: str | None) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_reference_sequence(value) -> bool:
    return (
        isinstance(value, (tuple, list))
        and bool(value)
        and all(_present(item) for item in value)
    )
