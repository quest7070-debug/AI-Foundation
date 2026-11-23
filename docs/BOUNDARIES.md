# Boundaries

Human/UI -> Guard Core -> ExecutionPort -> Durable Runtime -> Containment -> Specialist -> Tool/Local Compute -> Real World -> Verification/Reconciliation.

Guard owns only Canon, Privacy, Authority/Approval, Budget, Effect Contract and Verification semantics.
Runtime owns scheduling, queues, retries and worker distribution, but may not bypass Guard.
Agents never receive approval authority, canonical-authority mutation, raw credentials, or unrestricted target selection.
External effects are never blindly retried after uncertain completion; reconcile actual state first.
Concept OS is independent and excluded.

## Concurrent writes to the same target
Protected writes use optimistic concurrency by default: read the target state/version, preserve it as a precondition, and verify that precondition immediately before the write. If it changed, do not write; re-plan from the new state, and require a human decision when the conflict cannot be resolved without changing canonical intent.

High-risk targets additionally use exclusive target leasing so only one Run may enter the write section at a time. Exclusive leasing complements rather than replaces the precondition check. Target-wide serialization is therefore not the default for harmless independent work.

## Credential boundary and target binding
Sensitive authentication material is owned only by a replaceable Credential Broker / credential-bearing Execution Boundary. Guard and workflow records receive only non-sensitive authorization assertions.

Before an external effect, Guard validates current credential availability and the exact authorized target binding through that boundary. Revoked access, changed bindings, missing assertions, or mismatched targets fail closed. The broker may be replaced without changing Guard semantics.

## Policy engine
Cedar is the selected authorization-policy engine behind PolicyBoundary. Guard owns stable ALLOW / DENY / WAITING_HUMAN semantics; Cedar remains replaceable and does not absorb Canon, Privacy, Budget, Effect, Verification, credential, scheduling, or agent responsibilities.

Cedar requests map the authenticated actor to principal, the planned operation to action, and the exact bound target to resource. Evaluation is default-deny. A Cedar forbid or absence of a matching permit maps to Guard DENY. Human-approval requirements remain Guard semantics and are not granted by agent-authored policy. Policy-engine errors or unavailable policy data fail closed.
