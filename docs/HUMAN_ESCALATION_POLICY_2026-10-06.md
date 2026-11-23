# Human escalation and semantic authority policy — 2026-10-06

Status: ACCEPTED CANONICAL DECISION

**Current precedence (2026-11-13 reconciliation):** The October 6
development-executor assignment and conditional Self-Repair promotion in
Decisions 3 and 5 below are historic baseline rules, **superseded** by the
November 8 owner decision in this file and the active
`docs/SYSTEM_ROLE_BOUNDARIES.md` / `docs/END_GOAL.md`. Foundation
Guard/Harness is the present development admission authority; the developer
frontends (DSH/OpenCode/Codex OSS/local9B) are replaceable executors.
Kandev is excluded from the current owner development execution path, not merely an optional fallback. Already admitted low-risk code
work does not wait for another repository-wide Explainability Closure,
additional human approval at every step, or a new tool installation.
This does not expand the granted source, data, billing, deployment or
irreversible-effect scope.

## Decisions

1. Foundation fails closed on unresolved authority, safety, canonical target or scope. Recoverable technical uncertainty does not immediately escalate to the human: bounded investigation, Canon reconstruction, safe retry, accepted alternate routes and deterministic verification come first.
2. Existing Canon meaning and boundaries outrank implementation convenience. Internal implementation may change when that meaning is preserved and independently verified.
3. Where no narrower owner is assigned, Foundation owns ordinary Foundation implementation-policy decisions under higher Canon and Human Gates. **Historic 2026-10-06 executor assignment (superseded):** Kandev was then designated development execution authority; it is not the current owner, a mandatory gateway or the default executor.
4. Read-only analysis, inventory, semantic-link construction and observational internal processing have side-effect semantics NONE unless narrower Canon establishes an effect.
5. **Historic 2026-10-06 condition (superseded for already approved routine development):** The original Self-Repair promotion condition depended on repository-wide Explainability Closure. The later 2026-11-08 owner decision below permits autonomous routine code work within an existing exact bounded development grant, without reimposing the obsolete global completion gate. Independent checks remain proportionate to the changed code. New semantic meaning, wider authority, new cost, new secrets or permissions, irreversible or destructive operations, external publication or deployment, and explicit safety-boundary changes retain their separate current human/Guard gates.
6. When Canon lacks semantic meaning needed for an obligation, AI may consolidate candidate wording for human review but may not silently add that meaning. Human review asks only for the unresolved policy choice; mechanical semantic fields derived from an approved decision do not require separate approval.

## Escalation principle

Recoverable technical uncertainty is an autonomous-recovery problem. Residual semantic or authority choice is a Human Gate. This distinction exists to prevent repeated human/agent relay during startup and ordinary execution while preserving fail-closed authority.

## Owner decision — 2026-11-08: autonomous code work, HumanModel-first exception resolution, existing LV1–LV5

This amendment **specializes** the accepted human-by-exception policy without
creating another permission service, notification level, task scheduler,
personal-data store, model dispatcher, or general-purpose remote shell.

### Routine programming is autonomous

Within a **previously owner-approved, exact bounded development contract**,
ordinary code creation and fixes require **no per-Issue human approval**.
Existing local 9B development may select/generate a non-duplicate task, verify
its fixed repository base and owner scope, make the edit, run minimal affected
tests, attempt bounded repair, check the result independently, create a Draft PR
and continue to the next eligible task. AI-generated candidate text alone is
not an authorization. Apply any pre-authorized merge policy only if its
independent CI, branch protection and no-external-effect conditions all hold;
otherwise retain Draft review. Production deploy, expanded write authority,
secrets, payment and irreversible/external effects remain under their existing
explicit gates. A failed attempt cannot authorize retrying an already-consumed
Issue or indefinite work generation.

The routine hot path **does not query HumanModel just to repeat a known
mechanical permission**, preserving development speed and the existing
development-priority/compute-lease behavior.

### Exception path: consult HumanModel before asking the owner

For a genuine value/priority/intent ambiguity not mechanically resolved by
Canon/current instructions and evidence:

1. Reconstruct current Canon, target/revision, explicit current instruction and
   existing Guard scope. First resolve objective technical uncertainty through
   bounded tools/tests rather than escalating.
2. Read the **existing HumanModel-owned** current approved view through
   Foundation's owner-authenticated **read-only** retrieval boundary, scoped
   by purpose/privacy and local-only where restricted/private. Inspect source
   evidence, dates, explicit prior decisions/rejections and rationale,
   revisions, supersession and disputes. An absent, empty, stale, unauthorized
   or contradictory view is **not** a favorable decision.
3. Use an explicit **still-applicable prior delegation/decision** only to
   select an action already permitted by the same current Canon and Guard
   scope. Recheck the exact effect identity, source revision and allowed
   action before execution. An inferred preference, hypothetical model
   judgment, old approval for a different target, or probabilistic confidence
   is **not approval**; HumanModel never performs `Guard.approve`.
4. If no applicable authorization or criterion determines the decision,
   create the **existing** `WAITING_HUMAN` / LV4 request. Ask the owner only
   the unresolved question, with alternatives, primary-review reason and
   evidence references. Existing deny/cancel/revision-check/reconciliation
   boundaries remain authoritative.
5. No delegation is inferred from model text, retrieved data, third-party MCP
   output or previous conversation summaries. Never silently substitute a
   cloud model for a private HumanModel view.

Consequently `HumanModel-first` means **first retrieval of the owner's
source-backed data when a genuine personal decision criterion is needed**,
not a separate HumanModel approval layer. The existing admitted Agent/LLM
interprets the evidence to answer another agent's question provisionally;
only the owner's actual recorded delegation, independently rechecked against
the same current Canon and Guard grant, can determine a previously authorized
action. A simulated owner reply does not constitute consent. Do not turn
HumanModel into a fixed personality classifier, development scheduler or
per-step permission check.

### Keep the existing five-level notification contract

Do **not** add a second risk-level classification or make RUNNING jobs into
notifications. Preserve `HumanNotice(level=1..5)`, descending LV5→LV1
display, the existing Operator NOTIFICATIONS/SETTINGS, `/api/human`,
mobile Web Push adapter and optional remote gateway. Introduce only
source-owned, deduplicated, correlation-ID-bound **events** for the exception
path:

| Existing level | Existing meaning | New self-development event |
| --- | --- | --- |
| LV1 INFO | completed informational event | Optional final delivery summary; ordinary code progress remains TASKS/ACTIVITY |
| LV2 NOTICE | nonurgent important event | **Primary HumanModel review started** and **primary review result: matched delegation / no matching evidence**; notify both transitions, with exact task ID, outcome, evidence references and no source text |
| LV3 ATTENTION | failed/recoverable problem | Primary check denied for a technical reason, bounded retry exhaustion or independent verification failure without an unresolved user decision |
| LV4 ACTION | `WAITING_HUMAN` | HumanModel could not resolve the decision, required prior permission is absent, or a mandatory individual approval is required; human AUTHORIZE/DENY/RESPOND through existing action boundary |
| LV5 CRITICAL | `UNCERTAIN` | Ambiguous external effect or unverified recovery: freeze replay, request independent readback; never translate this into automatic approval |

Only **primary review triggered** and **primary result** are mandatory
autonomy-specific push notifications; ordinary task discovery, inference
RUNNING status, passing unit tests and every five-minute poll are **not**
new push messages. Emit distinct, idempotent `PRIMARY_REVIEW_STARTED` and
`PRIMARY_REVIEW_RESOLVED` events (or transition of the same durable notice)
tied to the original job ID and exact review generation. Keep status history
and allow multiple views to show the same notice without reissuing a decision.

### Shared authority for UI, MCP and external AI

Foundation Guard + its existing durable decision/effect record is the **only
approval authority**. UI and future externally reachable MCP are interchangeable
host-authenticated clients of the same narrow read/decision interface; neither
holds a separate independent approval DB nor adds an executor. MCP must use
client/identity/scoped authorization, revision-bound single-use decision claims,
existing effect verification and privacy ceilings. A connected external AI may
inspect candidates, submit a recommendation and execute only its **delegated**
capabilities; its own review is not a substitute for user consent.

Reuse the current M1 fixed-operation bridge for observed status and
reviewed operations. It is not itself a general-purpose MCP/RDP server, and
adding MCP must not silently expand it into arbitrary shell or filesystem
authority.

### Required next implementation and real acceptance

Reuse the existing `local9b` bounded selector/worker, diagnostic candidate
publisher (#281), compile preflight (#287), HumanModel read-only view port,
Guard decision store, Operator notices, Web Push, and GitHub/M1 readback.
Wire the missing producer of primary-review events and the explicit delegated
decision revalidation; **do not create new approval/risk-level mechanisms**.

Minimum tests before runtime claim: one routine authorized code edit completed
without a human or HumanModel call; one exceptional decision resolved through
current explicit HumanModel evidence **and** pre-existing Guard grant; one
missing/stale/conflicting view leading to LV4 and no effect; one LV5 ambiguous
effect not replayed; independently prove primary start/result notifications
are emitted exactly once and show in both UI and MCP views without private
content. Run focused suites during development and the existing main gate before
production promotion. Existing evidence of zero HumanModel approved views or
unbound production reader is a **blocker**, not permission to synthesize a
persona or approve anything.

**Explicit decision:** Owner policy accepted in Canon. This section is not
proof of current implementation, installed HumanModel view, MCP availability,
mobile delivery or unattended end-to-end acceptance.
