# Future vision: continuous autonomous software operations

Status: **future concept only**. This document is not a current implementation claim, not an implementation task, and does not reopen completed phases.

**Authority update (2026-11-12):** The Kandev-exclusive ownership, native-question bridge, and Kandev lifecycle mandates in the dated 2026-10-07 sections below are **historical evidence only**, not active execution requirements. `SYSTEM_ROLE_BOUNDARIES.md` (ACTIVE CANON, reconciled 2026-11-12) assigns development intake and delivery to GitHub plus Foundation Host/Guard/Harness and the existing local9B worker; Kandev is optional legacy infrastructure. Do not launch, install, or wait for Kandev based on this future-vision document. Retain the dated notes below for provenance, not as current instructions.

Recorded: 2026-09-22

## Origin and intent

A reference architecture found externally described a 24/365 "AI agent software factory": GitHub as the single source of truth, an agent orchestrator and job queue, persistent SDK/tool runners, self-hosted specialist runners, CI/CD, deployment/monitoring, human instructions/notifications, and a continuous plan -> execute -> review/merge -> reflect/improve loop.

The useful part is not the slogan "agents keep coding forever". The useful part is the closed operational loop around a canonical repository. AI Foundation already implements or is converging on several lower-level boundaries needed for such a system, but the reference diagram compresses the hardest safety and convergence problems into boxes such as "orchestrator" and "job queue". This vision records the transferable architecture without importing those omissions.

## Foundation comparison

### Already present or materially more explicit in AI Foundation

- **GitHub/canon discipline**: GitHub remains canonical. External documents and model/tool output are evidence or inputs, never an alternate authority.
- **Control authority**: Guard owns Canon, Privacy, Authority/Approval, Budget, Effect Contract and Verification. Cedar is replaceable behind PolicyBoundary. Credentials remain outside model-visible state and are target-bound.
- **Durable execution**: SQLite durable state, Effect identity, idempotency/reconciliation, cancellation, target claims, recovery, DurableWorkRunner, and the Hatchet long-running boundary cover substantially more failure semantics than the reference diagram shows.
- **Replaceable execution boundary**: ToolHive/MCP, capability-bound READ/COMPUTE/EFFECT, specialists, host-bound scopes and shared capability composition keep tools/runners replaceable instead of embedding them into the Foundation core.
- **LLM/tool routing**: cloud/local/provider routing, budget authority, specialist/capability selection and failure handling are separate concerns rather than a single generic "agent SDK runner".
- **Human boundary**: the current Human Decision Surface / Operator is the authority-facing supervision boundary; presentation clients remain replaceable. The retired HumanConsole server is not restored.
- **Independent verification and observability**: success is not inferred from agent claims, HTTP 200, or CI execution alone. External effects require readback/verification; traces/evidence/evaluation are non-authoritative evidence.
- **Long-running work**: explicit producer/worker/authority re-resolution is being converged over Hatchet without turning ordinary chat/Operator into an ambient scheduler.

### Useful concepts to retain from the reference

- Treat development as an end-to-end operational loop rather than isolated code generation.
- Allow multiple replaceable worker roles (planning, development, review, retrospective, tests/docs/other specialists) to consume work through a common execution contract.
- Keep canonical task/result/progress state visible through GitHub rather than burying decisions inside agent conversations.
- Separate always-available orchestration from ephemeral/scalable worker execution.
- Feed verified runtime/CI/monitoring evidence back into future work selection.
- Make human instruction and notification first-class boundaries rather than hidden prompt intervention.

### Concepts not to copy literally

- **"24/365 coding" is not a goal.** Continuous availability and observation are useful; continuous mutation is not.
- **An orchestrator must not become omnipotent.** It coordinates work state but must not own Canon, credentials, policy, effect authority, verification, or specialist methodology.
- **A job queue is not sufficient durability.** Remote dispatch, local durable authority, effect state, idempotency, reconciliation, cancellation, crash recovery and ambiguous completion remain distinct concerns.
- **Agent self-review is not independent verification.** Reviewer agents may supply evidence/proposals, but deterministic tests, policy checks, target readback and independent validation remain authoritative gates where applicable.
- **Do not make GitHub/Slack/UI into hidden execution authorities.** They are canonical work records or human I/O surfaces; execution authority remains host-bound.
- **Do not bind the architecture to a specific agent framework, model, CI provider, chat surface or runner implementation.**

## Target conceptual split

### 1. Control Plane — AI Foundation

Owns only cross-cutting authority and coordination contracts:

- canonical request/task identity
- capability and specialist selection
- LLM/tool routing
- policy/Guard/approval
- budget and provider eligibility
- credential binding without exposing secrets
- durable Job/Run/Effect state
- scheduling/submission boundaries
- observability/evidence linkage
- verification/reconciliation state
- human-decision escalation

The Control Plane decides **whether, under which bounded authority, and with what evidence requirements work may proceed**. It should not absorb worker-specific implementation.

### 2. Execution Plane — replaceable workers/runners

Examples:

- Planner
- Research
- Coding
- Review
- Test
- Data
- Artifact
- retrospective/diagnostic worker
- future custom workers

Workers receive only the minimum host-resolved capability needed for a job. They run in isolated/scoped environments (for coding, preferably independent worktree/sandbox equivalents), produce evidence and proposed effects, and cannot grant themselves additional authority.

### 3. Verification / Delivery Plane

CI/test/security scan/deploy/monitor/readback are evidence-producing execution systems. A worker saying "done" never closes work by itself. Completion is determined by the strongest practical expected-vs-observed verification.

### 4. Human / Canon Plane

GitHub remains the canonical software/project record. Human-facing clients may create requests, approve decisions, inspect state and receive notifications, but presentation remains replaceable and cannot silently become policy or execution authority.

## Desired future loop

The future loop is:

**Observe -> Detect -> Propose -> Plan -> Authorize -> Execute -> Verify -> Record -> Reflect -> Stop/Wait**

not:

**Generate task -> change code -> merge -> generate another task forever**.

A cycle must be allowed to end in **NO_CHANGE / WAIT / NEEDS_HUMAN / BLOCKED**. "Nothing should be changed" is a valid and often preferred result.

## Convergence requirements before any autonomous 24/365 mode

This future concept must not be promoted to implementation until the architecture can answer all of the following without ad-hoc exceptions:

1. **Bounded objective** — every autonomous job has a canonical objective, scope and explicit non-goals.
2. **Stop conditions** — finite attempt/retry/change budgets; repeated equivalent failure converges to BLOCKED/NEEDS_HUMAN rather than looping.
3. **Plan stability** — persisted work identity detects semantic/ordering drift; agents cannot silently redefine already-running work.
4. **Concurrency safety** — multiple workers cannot duplicate or race the same external effect or protected target.
5. **Independent acceptance** — workers cannot weaken tests/policy/acceptance criteria merely to make their own change pass.
6. **Authority separation** — model text, repository content, web content and tool output cannot elevate privileges, reveal credentials or modify Guard/policy/budget/canon by instruction.
7. **Ambiguous-effect recovery** — crash/network loss after an external effect reconciles before retry.
8. **Resource bounds** — API cost, local compute, concurrency, storage and queue growth have hard limits and backpressure.
9. **Provider degradation** — model/API/search failures degrade or reroute without turning an unavailable specialist into silent lower-quality success.
10. **Change isolation** — parallel coding work is isolated and integrated only after conflict/CI/verification gates.
11. **Production separation** — merge/deploy/production mutation has an explicit policy and approval boundary; autonomous development does not imply autonomous production authority.
12. **Feedback integrity** — monitoring/CI/runtime feedback is evidence. It may propose new work, but cannot directly create unbounded self-authorized mutation.
13. **No-change convergence** — mature/stable areas can remain untouched indefinitely.
14. **Auditability** — every autonomous action can be reconstructed from canonical task identity, bounded authority, model/tool route, evidence, effect state and human decisions.

## Relationship to current roadmap

This is deliberately **above** the completed Phase A-H reconstruction/cutover program. It must not distort current production truth or reopen retired legacy systems.

The earlier unfinished-gate list in this section is superseded by the 2026-09-27 program closure recorded in `PROGRAM_COMPLETION_2026-09-27.md`. Hatchet production wiring, browser-visible capability convergence, the required negative/human/dependency evidence, provider/local lifecycle convergence and the current image/VISION path have completed under existing canon. PC_CONTROL is not an unfinished reconstruction gate: it is intentionally unavailable / accepted BLOCKED pending a future owner-approved backend and authority decision. Longevity, portability, broader capability promotion and autonomous-operation work remain post-completion concerns where separately specified.

Only after normal daily-use Foundation behavior is stable should parts of this vision be promoted individually through the normal sequence:

**requirement -> architecture/ADR -> issue -> implementation -> deterministic tests -> adversarial/failure tests -> real-host E2E -> independent verification -> release**

No big-bang "software factory" phase.

## Architectural direction

The intended end state is therefore not "AI employees embedded inside Foundation". It is:

> **AI Foundation is the replaceable, policy-bound control infrastructure that allows replaceable AI workers to perform bounded software work safely, durably, observably and verifiably.**

The system may eventually be available continuously, observe continuously and accept work continuously. It should change software only when evidence and bounded policy justify a change, and it must be able to decide to do nothing.


<!-- FOUNDATION_DECISION_AUTONOMY_TARGET_2026_10_02 -->

## Canon-grounded decision autonomy target — 2026-10-02

A required target of Foundation autonomous software operations is to eliminate routine human orchestration, not merely automate code execution.

Foundation should be able to perform the class of decision that currently requires an external human/assistant to read a worker report, reconstruct repository state, consult current Canon, reject unnecessary alternatives, and select the next canonical development action.

For a bounded software task, the intended behavior is:

`resolve current authority -> reconstruct actual state/evidence -> identify applicable canonical gate/sequence -> determine whether a real decision remains -> choose and dispatch the uniquely justified next action -> verify -> record`.

Therefore:

- a worker asking "A or B?" is not by itself a Human Gate;
- Foundation MUST first determine whether Canon, current Git/Run/Effect state, prior verified evidence, deterministic tests, or an already-authorized plan uniquely resolves the choice;
- when the choice is uniquely resolved, Foundation should answer/dispatch it itself and retain the decision rationale/evidence;
- Foundation MUST NOT repeatedly ask a human to approve ordinary read-only inspection, local bounded implementation, deterministic testing, evidence collection, or an already-canonical next step merely because an underlying worker exposed a prompt;
- Foundation MUST escalate only when a genuine unresolved authority boundary remains, such as contradictory/missing Canon that changes semantics, a product/policy choice with multiple permissible outcomes, secret/credential authorization, new payment/budget authority, irreversible action, or an external effect whose authority has not already been granted;
- lack of model confidence is not itself authority to invent a decision. If evidence cannot uniquely resolve the next action, converge to NEEDS_HUMAN/BLOCKED/WAIT as appropriate;
- autonomous decision-making MUST remain reconstructable from canonical task identity, authority source/version, observed state, evidence used, selected action, rejected alternatives when material, and verification result;
- this target does not grant autonomous merge/deploy/production mutation. External-effect authority remains separately bounded.

This is a control-plane responsibility. Kandev or another development worker may expose questions, plans, diffs, tests, or candidate next actions, but Foundation is the component that should eventually decide whether those require a human at all.

The Development Intelligence / Explainability work is a prerequisite because Foundation cannot safely remove human orchestration until it can connect canonical intent and obligations to architecture, source, tests, runtime evidence, and post-change drift without inference or a second hand-maintained Canon.

Promotion evidence for this target MUST include representative scenarios in which Foundation:

1. receives a worker question containing multiple proposed next steps;
2. reconstructs current repository/remote authority and verified evidence;
3. autonomously selects the canonical next step when uniquely determined;
4. refuses to choose when the decision is genuinely under-specified or authority-expanding;
5. executes/dispatches only within existing bounded authority;
6. verifies the resulting state and records why no human intervention was required.

The desired steady state is therefore **human-by-exception**, not human-in-the-loop for routine development orchestration.


<!-- EXTERNAL_EXECUTOR_RUNTIME_CONTROL_INVARIANT_2026_10_02 -->

## External executor runtime-control invariant — 2026-10-02

Replaceable development/execution workers may expose runtime controls such as agent mode, model, reasoning/config options, or provider-specific session settings. Foundation MUST treat those controls as lifecycle-bound state, not as arbitrary mid-turn mutations.

- Apply runtime-control changes only at a verified idle/lifecycle boundary: before the first prompt of a new session, a fresh start, or a reconciled handoff/recovery boundary.
- Do not change mode/model/config while a turn, prompt, tool call, or ambiguous partial result is active.
- A runtime-control conflict or provider refusal to switch while busy MUST NOT be classified as quota exhaustion, model unavailability, or task failure without separate evidence.
- If work may already have occurred, preserve the worktree/effect state, checkpoint and reconcile before any handoff. Do not silently discard the session/work or fall through to another provider merely because a runtime-control mutation failed.
- Worker/UI convenience controls never expand Foundation authority. Secrets, payment, irreversible actions, external effects, merge/deploy and other separately bounded authorities remain governed by their own gates.

This invariant is tool-independent. Kandev is current evidence for the need, but the rule applies to any replaceable external executor integrated later. It does not make Kandev a Foundation runtime dependency.


<!-- AGENT_INDEPENDENT_STALL_SUPERVISION_2026_10_02 -->

## Agent-independent stall supervision — 2026-10-02

Human-by-exception requires stall detection to live outside the worker being supervised. A worker cannot be the sole authority responsible for detecting or recovering its own deadlock, blocked credential/UI call, lost provider stream, or hung subprocess.

The external executor control plane MUST therefore provide an agent-independent supervision loop with these semantics:

1. Track task/session/execution identity, prompt generation, last meaningful activity and, where available, the active top-level tool. Wall-clock age alone is not proof of failure.
2. When activity stagnates beyond the configured observation window, capture bounded diagnostic evidence before mutation: current durable task/session state, worktree/diff, process tree, last output, and stack/tool state when safely available. Never capture secret values merely for diagnostics.
3. Re-read activity and ownership immediately before recovery. A stale watchdog snapshot MUST NOT cancel a worker that resumed meanwhile.
4. Distinguish at least: never-started/no-event failure; active-work stall after partial effects; deterministic verification subprocess hang; explicit workflow-completion signal stuck before reconciliation; and healthy long-running work.
5. Never-started/no-event execution may be failed and torn down with a bounded stop when ownership is still current. Partial-effect stalls MUST preserve/checkpoint the worktree and reconcile effects before cancellation or handoff. Healthy activity MUST be left alone.
6. A verification subprocess proven hung may be terminated independently of the agent, reduced to a minimal reproducer, fixed, re-verified with focused tests, then resumed at broader verification. Do not stack duplicate test processes or merely increase timeouts.
7. Provider/model handoff occurs only after safe settlement/checkpoint and reconciliation. The successor reconstructs from Canon plus durable state/evidence, not conversation memory. Runtime-control failure alone is not provider failure.
8. Recovery is bounded. Repetition of the same unresolved stall after the allowed recovery attempt becomes explicit BLOCKED/NEEDS_HUMAN rather than an infinite restart/fallback loop.
9. Human escalation is reserved for unresolved authority/semantics, secrets or credential interaction, payment, irreversible or unauthorized external effects, or repeated failure after bounded autonomous recovery. Ordinary stall diagnosis/recovery is not itself a Human Gate.

Kandev's upstream agent-stall and stuck-signal watchdog designs are implementation evidence for these semantics, not Foundation authority and not a runtime dependency. Until the installed stable executor provides equivalent native supervision, the development workflow must emulate the same fail-closed supervision contract using observable task/session/process state rather than trusting the stalled worker to rescue itself.


<!-- KANDEV_RECOVERABLE_FAILURE_PROTOCOL_2026_10_02 -->
## Recoverable executor failure protocol

External supervision MUST distinguish a running stall from an executor that has already failed and settled into a recoverable waiting state. When the executor/orchestrator persists a durable recoverable-error status with an explicit safe resume action and no human-input/authentication requirement, the supervisor may execute that declared recovery action without treating the failure as a new Human Gate. It MUST deduplicate the durable error identity, capture bounded evidence before recovery, preserve the worktree and partial effects, and use the orchestrator's normal recovery interface rather than private database mutation.

After a recovery action launches a new execution generation, boot/readiness alone is not completion. The supervisor MUST verify that meaningful work resumes. If the new execution becomes ready but no prompt/work starts, it may send a bounded continuation prompt that reconstructs state from current Canon, durable task state, worktree/diff and verified test evidence. A normal WAITING_FOR_INPUT state without a durable recoverable-error marker or supervisor-owned recovery generation MUST remain untouched; requests_input, authentication/credential interaction, payment, unresolved authority, irreversible action and unauthorized external effects remain Human Gates.

Recovery is generation-aware and bounded. A historical error marker already recovered MUST NOT trigger again. The same execution/recovery generation MUST NOT be retried indefinitely; repeated unresolved failure exhausts the autonomous recovery budget and becomes BLOCKED/NEEDS_HUMAN. Runtime-control mutation failure by itself remains insufficient evidence of provider/model failure.

## Historical ownership supersession — 2026-10-07 (revoked as current authority on 2026-11-12)

The generic software-factory/control-plane implementation direction in this historical future note is superseded by `SYSTEM_ROLE_BOUNDARIES.md`. Kandev now owns development task/session/workflow/worktree/subtask/dependency/executor/agent lifecycle and recovery. Foundation retains the semantic invariants described here — Canon-grounded decision authority, Guard/policy, evidence, verification, Human Gates and bounded Safe Change/Self-Repair admission — but must not implement a competing development orchestrator, scheduler, task graph or executor lifecycle. Where this document says Foundation should "dispatch" a development action, current meaning is: Foundation determines the Canon-authorized intent/evidence requirement and requests execution through Kandev's native lifecycle.

### Semantic Question Bridge acceptance — 2026-10-07

> **Superseded development-executor contract (2026-11-13).** The
> Kandev lifecycle/External MCP authority assertions below describe the
> original October 2026 transport acceptance, **not the present owner workflow**.
> Current AI-Foundation development is controlled by GitHub task identity
> and the existing Foundation host/Guard/Harness; Kandev is not invoked,
> required or a fallback. A legacy Question Bridge may remain in source for
> compatibility, but its old native-pending-claim rules cannot authorize a
> new scheduler, question source, model, answer or execution effect. The
> currently admitted host-authenticated question boundary and HumanModel
> evidence-only semantics are governed by `SYSTEM_ROLE_BOUNDARIES.md`,
> `HUMAN_ESCALATION_POLICY_2026-10-06.md` (November amendment) and
> `END_GOAL.md`.

Kandev remains authoritative for task/session/workflow/executor lifecycle and clarification transport. Foundation MUST NOT implement a competing scheduler or question transport. The supported boundary is Kandev External MCP pending-question discovery and correlated answer delivery through list_pending_questions_kandev and answer_question_kandev; live acceptance confirmed this path on Kandev v0.97.0.

Foundation is the semantic first receiver. Before any model call it MUST classify the observed question and prefer deterministic Canon/current Git/evidence resolution. Raw-secret questions remain at the native credential boundary and MUST NOT be sent to an LLM. Unresolved authority, semantics, payment, irreversible/production/external-effect decisions, or repeated bounded recovery failure remain Human Gates. Fresh public-information questions use the existing SEARCH capability; private reasoning is Local-only; ordinary reasoning reuses the existing inference router.

Every proposed answer is bound to the exact pending/task/session/question digest observed before reasoning. Immediately before delivery Foundation MUST re-read the current pending question; withdrawn, replaced, or changed generations fail closed and are re-evaluated. Durable bridge evidence stores only correlation/digests, never raw secret values. Kandev native pending-id claim semantics remain authoritative for concurrent/replayed answer delivery.

### Exact deterministic clarification authority — 2026-10-07

Automatic Kandev clarification answers MUST NOT be inferred from option wording,
model confidence, semantic similarity, or a keyword match. Foundation may answer
without a human only when an explicit decision record matches the exact task_id
and stable pending-question digest and names only option IDs that are still
present in that exact bundle. The record MUST identify its Canon/evidence
authority source and revision. Duplicate records, changed/withdrawn questions,
unknown options, free-text answers, missing authority provenance, or any digest
mismatch fail closed to the ordinary semantic Question Bridge.

The durable runtime representation is the Foundation data-root
question-authority.json schema v1. It is an authority projection, not a new
Canon: records are valid only insofar as their named source/revision remains the
resolved authority. Kandev remains authoritative for pending-question lifecycle
and first-write-wins answer claims; Supervisor only transports the exact bundle
through Foundation and re-reads the native pending bundle immediately before
delivery.

#### Promotion of answered clarifications

A human answer alone MUST NOT become reusable authority. Promotion into
question-authority.json requires explicit Canon provenance at promotion time:
a repository-relative docs/ authority source plus its exact current Git blob
SHA. Resolution rechecks that blob SHA every time; Canon drift invalidates the
record automatically. Promotion is exact-generation only, rejects duplicate
records, unknown options and free-text answers, and writes atomically. The
machine-local Supervisor question ingress has no authority to promote records.

#### Native parent-question supersession point — 2026-10-07

Kandev upstream documents an Autopilot child-to-parent clarification path in
which ordinary development decisions are raised to the direct parent and an
Autopilot root has no operator question tool. The installed Kandev v0.97.0
External MCP does not yet expose that coordination surface. Foundation MUST NOT
encode authority into question labels, infer decision keys from prose, or add a
competing parent-question protocol. Until the installed native surface catches
up, exact Canon question-authority records remain the only unattended
clarification-answer path. When the native parent-question surface is available,
ordinary worker ambiguity should be resolved through Kandev hierarchy first;
Foundation remains the semantic/Canon authority boundary for genuinely
unresolved authority and Human Gates.
