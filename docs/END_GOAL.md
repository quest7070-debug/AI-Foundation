# AI Foundation — End Goal

## Program goal

The goal is not to finish AI Foundation as a framework or merely make internal tests pass.

The goal is to provide a dependable, daily-usable personal AI infrastructure consumed primarily by existing AI products and agents. AI Foundation is the common execution, memory, development and governance substrate, not a replacement chat product.

The primary representative end-to-end path is:

Owner -> ChatGPT / Muse / another owner-chosen AI agent -> authenticated, scoped MCP/API -> AI Foundation Host / Guard / Harness -> approved HumanModel evidence, developer worker, or tool/computer/service -> result -> independent verification/readback -> source-backed result and meaningful status returned to the calling AI. The existing Foundation Settings/Operator dashboard separately supervises the same work and exceptions.

LibreChat, a directly used Foundation Agent, and other presentation clients remain optional alternative entry points, never requirements for a successful primary workflow.

Completion is judged by the actual calling-agent-to-verified-outcome path **and** the ability to see and supervise the same operations in the existing Operator dashboard. A source implementation, registered tool, HTTP health check, simulation or source-only CI is not a substitute for real authorized host use.

## Canonical daily AI flow — non-negotiable

The default human conversation remains in an existing AI selected by the owner (currently principally ChatGPT or Muse); AI Foundation is a callable MCP/API service and execution substrate. It must not require the owner to move ordinary conversation into LibreChat, Foundation UI or a new Foundation chat product.

Owner -> existing calling Agent -> host-authenticated, scope-limited Foundation MCP/API -> Foundation Guard/Cedar, privacy/cost/role admission, durable work and routing -> authorized HumanModel evidence / Harness development / OSS/MCP/API/computer action -> independently verified result -> calling Agent's final answer and Operator observation.

The **calling Agent** selects among tools its authenticated host has exposed. When a subtask needs Foundation-owned model reasoning or implementation, the existing admitted Pydantic AI / Harness role may select only its separately host-authorized internal tools. Foundation MUST NOT insert a generic semantic mode classifier ahead of the calling Agent or recreate external assistants' chat/orchestration features.

SEARCH / CODE / DATA / FILES are internal capability, permission, audit and test boundaries, not required user-selected modes. Historical `foundation-auto` and explicit `foundation-search` / `foundation-code` / `foundation-data` / `foundation-files` may remain optional Foundation-internal/debug entry points; they are not the required normal owner UX.

An MCP tool's appearance in a source catalog does **not** establish installation, principal authentication, current owner consent, external-client connection or successful task execution. Existing default `foundation_mcp_stdio.py` exposes only `foundation_status`; privileged/delegated tools such as `human_model_answer` require a trusted, owner-bound host session and separately admitted scope. Do not expose owner data, arbitrary filesystem/PC operations or approvals by simply adding a tool name.

Foundation owns resource/tool exposure, Guard authority, privacy, provider/model routing, health/quota, credentials, durable effects and verification. Neither an external AI nor internal model output may mint repo roots, file roots, DATA operations, PC targets, attachment grants, credentials, payment authority, approvals or verification status. Prefer replaceable established OSS for generic mechanisms, rather than duplicating them in Foundation.

## Foundation as callable services and an existing-Settings dashboard — owner decision 2026-11-13

- **HumanModel** is an owner-owned source/evidence corpus used by authorized existing agents to reconstruct explicitly provisional answers; it is not an approval oracle, a permanent personality classifier or the owner speaking directly.
- **Development factory** provides research, decomposition, coding, repair, tests, review and Draft delivery within the existing M1 Foundation Host/Guard/Harness and admitted local/free models, with GitHub publication as a separate record-saving/delivery effect. Do not narrow this ambition to the current finite worker recipe.
- **Hands / execution** supply replaceable authorized tools, MCP/API, computer actions and external services; source-owned KLM keeps evidence and relationships current while preserving original source ownership.
- **Existing Foundation Settings/Operator** evolves *in place* into the one-page whole-system dashboard and exceptional-decision surface. Keep and improve current Settings, routing, credential, task, notification, Guard and human-action functions as drill-down panels/tabs. **Do not create a separate dashboard app, second Operator, second state database or second approval plane.** The initial/default landing view is OVERVIEW; the historical SETTINGS-first landing requirement is superseded. Maintain the accepted shared-layout C/I themes and responsive web/mobile/Echo boundaries.
- **Observable truth** per capability: source-implemented, installed/exposed, authenticated connected, actually active, independently verified, or blocked/unknown; label each from evidence with timestamp/freshness. Display original source/system identity, active/queued work, external AI MCP sessions (if genuinely observable), provider/9B resource, HumanModel View freshness, KLM, failure/uncertain work, approvals, last successful execution and next safe action. Missing observations are UNKNOWN, not offline or healthy by inference.
- **Acceptance** requires an authorized real ChatGPT/Muse/other calling-agent MCP question or job reaching Foundation and returning verified evidence plus matching Operator dashboard state, without leaking private content or creating unapproved side effects. Build and instrument only after real client/host connection is supported; no declared client connectivity is implied by this policy.

## Agent execution observability and evidence-based completion — AgentMon Live reference (owner goal, 2026-11-21)

Treat AgentMon Live as a **reference implementation/candidate for monitoring techniques**, not an autonomous model, a second execution plane, a required third-party runtime, or a source of approval/VERIFIED authority. Before adopting any upstream code, independently check actual features, interfaces, license, maintenance and runtime compatibility; prefer reusing current Foundation telemetry, event records, Guard, Work, Harness, Operator and verification boundaries.

The **existing one-page Settings/Operator OVERVIEW** shall expose meaningful per-job and per-agent status for authorized available runners (Codex, Strata, local 9B and later replaceable tools, when observable), including owner/caller, source/run identity, event timestamps and freshness, current step, tool failures, fixed-test results, stale checks, retries, blocking reason, safe next action and links to evidence. Correlate events to existing durable job/attempt/verification identities. Where an integration cannot actually observe a runner, display UNKNOWN / NOT_INSTRUMENTED; do not invent activity, infer progress from heartbeats alone or require a new dashboard, database, approval system or chat front end.

A worker's apparent "done", a successful command, tests passing, an accepted Draft PR, an Operator/Gateway health check and an installed release are **different states**. Job completion must be derived from the relevant explicitly authorized end-to-end acceptance contract: actual execution, current-source/fixed-test evidence, Guard-authorized delivery or release when requested, independent installed-source/effect readback, durable evidence and matching status returned to the calling AI. Incomplete/stale/contradictory evidence surfaces FAILED or UNCERTAIN rather than VERIFIED. A purely observational integration can report discrepancies but cannot grant approval, retroactively repair evidence or mark work verified.

When safe and admitted by existing Guard/compute/cost/privacy policy, repeated failures or stale verification may trigger bounded repair/revalidation on the same durable ticket; preserve idempotency, one-shot/retry limits, source identity and lease/resource boundaries. Otherwise report the precise blocker in the existing LV1–LV5 notification and human decision system. HumanModel provisional answer visibility and owner corrections from an authorized calling AI are part of the same evidence-driven notification/drill-down experience, not a separate authority shortcut.

No subscription, paid model call, chargeable "advisor" integration, automatic recharge or always-on extra resident model is required for this goal. Any upstream tool or optional AI-advice feature must be configurable, disabled unless confirmed free and safe, and removable without breaking the core Foundation workflow. Preserve the M1 single-9B rule, optional Strata execution and current privacy boundaries. Instrumentation must be lightweight and must not block healthy work or create duplicate execution.

**Acceptance:** using one actual host-authorized development job with an observable agent, show a correlated execution trace and failure/repair event (or explicit no-failure evidence), independently verify a current result, and show the same terminal state, evidence freshness and next action in the existing Operator and calling AI. Also demonstrate that a failing/stale check cannot be marked VERIFIED, that an uninstrumented worker is not claimed active, and that replays cannot duplicate effects. Source-only UI simulation is not completion.

## Development execution authority (November 2026)

Foundation on M1 owns development intent, durable task/attempt identity, local source snapshots, execution, independent verification, recovery and authorized installation. GitHub is primarily the canonical published repository and durable record of code, history, outcomes and evidence; it is not a required task dispatcher, approval surface, scheduler, execution environment or production-release controller. Foundation host/Guard/Harness owns admitted roles, inference profile, cost/privacy/scope and verification. DSH → OpenCode and Codex OSS are alternative developer frontends. Kandev/Paseo are historical integrations and are **not used** for this owner's active development workflow (see `SYSTEM_ROLE_BOUNDARIES.md`). In an existing approved low-risk scope, safe autonomous continuation does not require a redundant human action for every step. Source, CI and PR merges are not installed-service completion.

### Self-development release completion — owner decision 2026-11-17

Foundation owns its own development **through installed-runtime acceptance**, not
merely code generation, local fixed tests, a green CI, a Draft PR or inert
source-only staging. A self-development item whose intended result is a running
Foundation capability remains **INCOMPLETE** until all of the following have
independent, exact-revision evidence:

1. Exact local Git source, independent fixed acceptance and artifact
   provenance accepted on M1; remote CI is supplementary unless specifically
   required by the already accepted task contract
2. Current Canon/Guard and rollback scope resolved for the specific installed
   service, principal and effects
3. Previously delegated low-risk release applied automatically **only if the
   precise current production effect is actually preauthorized**; otherwise
   the existing owner/Guard production gate receives a narrowly scoped
   request and the development item remains WAITING_HUMAN, not DONE
4. Actual process/loaded-source identity, new MCP tool exposure and
   representative authorized function independently read back; an earlier
   VERIFIED journal entry or owner-private source checkout does not suffice
5. Current Operator and calling AI report the same verified runtime revision
   and task result; rollback is retained and failures reconciled without
   blind retry

A lack of release authority is an actionable **open release dependency**,
not a reason to terminate the development task at Draft. The developer must
perform all reversible preparation and technical investigation without asking
the owner to relay each command, and resume after the exact decision. Approval
must never be manufactured from agent output, a chat instruction, source
acceptance, old Guard requests, or a stale installed release. A running
Foundation service is not automatically the reviewed candidate version.
No paid inference, arbitrary main merge, new approval database, duplicate
scheduler or replacement tunnel is authorized by this completion rule.

### Owner development policy — coherent replacement over patch accumulation (2026-11-20)

**Default: audit the whole affected feature boundary first, then replace that
bounded component as one internally consistent unit.** Repeated local patches,
temporary compatibility paths, parallel adapters and layered workarounds that
leave a fragmented control flow are not acceptable as the normal development
method. For substantial repairs: (1) inspect the canonical source and every
caller, authority boundary, existing installation and acceptance test affected;
(2) define the complete desired state and the single existing owner of each
responsibility; (3) rewrite/replace the cohesive module or workflow in one
reviewable change, deleting obsolete branches rather than keeping duplicate
implementations; (4) run the smallest representative regressions plus
independent installed-runtime end-to-end readback; (5) report source-ready,
staged, Guard-approved, deployed and genuinely working as distinct states.

**Replacement scope is the affected bounded subsystem, not an indiscriminate
full-Foundation wipe.** Preserve existing durable data, source provenance,
the canonical Guard/Canon/Operator/Harness authority, backup/rollback and
legitimate historical approvals. The staged stateful-service migration rule
below still applies to actual cutovers: backup, exact authorized replacement,
independent readback and rollback, not a simultaneous unreviewed migration.
A request to move faster or replace nonfunctional code does not itself mint
a new Guard approval or convert CI success into a running deployment.

### Coherent owner-local production recovery — 2026-11-20

Broken mobile approval ingress and unresponsive Operator runtime form one
recovery incident, not an excuse for permanent, unrelated incremental
workarounds. The canonical implementation for this bounded incident is
`scripts/m1_owner_production_recovery.py`, which coordinates the existing
Operator `OperatorOnlyCutover` and the separate Gateway successor release
using their **independently current, exact owner-Guard-approved** scopes. The
one-time bootstrap must not be replayed; Operator and Gateway historical
ledgers, original Guard DB, Canon, owner TTY, backups and launchd remain the
single authority. Four unrelated historical Operator PREPARED requests are
not deleted, conflated or retroactively approved.

An unresponsive Operator may be replaced *only after* exact previous
installed plist, staged original bytes, loaded launchd arguments, PID and
listener are independently verified, exact Canon/source are bound, and the
existing Guard plus owner-host release gate approve the specific new effect.
A healthy Operator with active work is not replaced using the degraded
recovery exception. Operator readback must establish the newly running
API; on failure, rollback must restore the original exact source/launchd
even if its prior API was already unresponsive (report original service
health as DEGRADED, never claim normal recovery). Gateway restoration uses
its separately approved scope and strict-loopback PID/TLS/readback, not
the Operator's health as an unconditional prerequisite. Gateway can be
VERIFIED while Operator remains UNVERIFIED; a two-service operation is
never silently marked atomic or fully recovered from a partial receipt.

Both release approvals must independently exist **before** a two-service
cutover; old approval IDs, a ChatGPT request, GitHub PR/CI, an inert M1
stage or a Tailscale Host do not authorize the new runtime effects. A
successful Gateway TLS probe is not proof of a physical authenticated
Android phone POST. End-to-end completion additionally requires exact
loaded-process/source identity, healthy Operator `/api/human`, and a
real owner-bound :8454 Origin/WhoIs/Guard path. When no authenticated
owner-controlled release channel is available, status is BLOCKED with
source/stage evidence; never claim production was overwritten.

### Development portfolio and completion priority — owner direction 2026-11-22

Foundation owns three distinct development streams, using the SAME existing
Canon, Guard, Work, Harness, verification and production-release lifecycle:

1. **P0 — Self-maintenance and repair.** Keep installed services, durable
   state, source/runtime identity, connectivity, performance and owner
   requirements coherent. Independently diagnose genuine faults, recover or
   repair safely, and verify installed results. Operational incidents that
   block ongoing work take precedence.
2. **P0 — Committed development.** Complete already-defined goals, planned
   capabilities, accepted backlog and explicit owner orders. Reconcile existing
   implementations and evidence first; do not duplicate working capabilities.
   Foundation owns technical decomposition, execution, acceptance and the
   required release/readback, not just a request, patch or Draft.
3. **P1 — Research-driven development.** Investigate technologies, OSS and
   improvement opportunities, evaluate actual benefit, then propose or
   implement accepted improvements. Research is not itself implementation or
   evidence of a useful improvement. It must not displace completion of the
   first two streams.

The first two streams are the current completion priority. Advance them in
parallel only when existing resource and effect boundaries allow; do not
create competing local-model sessions. Idle time alone is not proof that
committed work is complete: review/dependency/verification/production-release
blocks remain open. Resolve or reconcile those blocks rather than filling
the backlog with speculative research tasks. Research necessary to diagnose
a fault or deliver an already committed goal is part of that P0 item, not a
separate exploration initiative. Independent exploratory development is
lower priority until the first two streams have genuinely completed their
current obligations. Preserve uncertain results and exact existing permission
boundaries. Do not grant execution or production authority based on priority,
a discovered candidate, or a general owner instruction.

A development item is complete only at its intended result: verified
maintenance recovery, accepted committed capability, or validated research
deliverable; when it changes a running Foundation service, the existing
installed-runtime acceptance rule above also applies. Existing one-page
notifications communicate genuine owner decisions only. No additional
approval surface, scheduler, task database or competing development engine.

### Autonomous development and discovery — original owner decision surface

Use the existing owner-local scheduled development worker and the already
connected CODE / Guard / Work / Harness lifecycle. Existing eligible tasks
take priority. When idle, an owner-authorized ordinary CODE scope may select
one tracked, non-protected source/test pair on exact current canonical main,
independently observe a fixed-test assertion failure in the existing offline
runner, and persist one immutable discovery observation and CODE request in
the SAME Work store. No model claim, log prose, test infrastructure failure,
stale source/test, consumed failure or revoked scope can create executable
authority. The subsequent cycle uses the same admission, independent acceptance
and separately authorized Draft delivery; production still requires its exact
existing Guard decision and installed readback. The ordinary-CODE scope's
original notification describes unattended discovery and execution; legacy or
disabled grants cannot silently activate the unattended worker. No new
scheduler, data store, approval screen, secret egress, paid route or second
model service. New-feature proposals require independently grounded benefit
and an accepted fixed acceptance contract; a failed test is not evidence
of a useful new feature. Source-ready is not an installed self-starting worker.

### Local-first development acceptance

An authenticated calling AI should be able to submit a preauthorized
host-bound development ticket directly to Foundation MCP. The existing Guard,
Harness, fixed tests and compute lease do edit/repair/verify within one M1
isolated checkout, independent of GitHub Actions turnaround. The local
acceptance receipt must identify the exact verified source hash and must not
expose private source, credentials or model logs. A separately authorized publication stage preserves commits, results and relevant
CI/review evidence on GitHub. It neither triggers nor gates ordinary local
execution or authorized production release/readback. M1's existing durable
Work/effect receipts retain a pending publication dependency if GitHub is
unavailable; retry record delivery without replaying development or service
effects. GitHub may remain an optional historical intake/CI channel, not the
normal control plane. No automatic main merge or publication of private data.

Source-level opt-in tooling is not an installed/M1/ChatGPT/Muse connection.
Completion requires a real authenticated external AI `development_run`
invocation that returns independently checked local success, followed by
local intended-result acceptance (including required installed readback), and
separate GitHub record delivery, with the existing Operator showing the
same source- and time-bound state. Existing status-only MCP clients must remain
read-only until a trusted owner host actually registers direct tickets.

## HumanModel's end-to-end purpose

A host-authorized agent can ask a substantive question about how the owner
would answer. HumanModel supplies current source-backed owner data; the
already admitted Agent/LLM reconstructs and clearly labels a **provisional**
owner-perspective answer with evidence IDs, uncertainty, contradictions and
historical changes. Returning a storage/search status, a fixed personality
classification, or a citation-free first-person guess does **not** complete
this user-facing interaction. Simulated answers never grant approvals or
become actual owner instructions. Test success and record counts do not replace
a real question→grounded-answer acceptance on the installed host.

The three standing local9B source/test regression pairs are only the presently
implemented *executor* admission contract, **not** the development ambition
or the full Harness/Agent capability surface. Wider development must reuse
the existing actual host grants and available free model routes rather than
be defined away, moved to Kandev or forced through a new per-step human gate.


### Single original owner-decision surface — 2026-11-21

The **only visible owner decision controls** in the existing one-page
Foundation Operator notification view are **AUTHORIZE**, **DENY**, and
**additional instruction** through the existing human-input work context.
There are no extra MCP-delegation/confirm/reconcile/dismiss approval buttons,
second review screen, second dashboard, or second authority database.
Uncertain work is shown as uncertain; independent readback remains available
as a separately authorized backend capability and is never an implicit replay.

Every release of Operator, Gateway, the scheduled worker or the existing guarded MCP tunnel must be
represented by the **original durable Guard's exact current scope/request** on
that Operator view, with the owner's intentional decision, existing Canon,
one-shot Work/effect semantics, rollback and installed-process readback.
A GitHub Issue, PR edit, CI green check, source staging, model/MCP caller, or
old approval may **not** substitute for that decision. Historical Issue-gated
MCP refresh and separate `/release` forms are migration debt, not the accepted
target experience: do not delete their authorization checks until an exact,
independently verified successor on the original Guard path is installed.

A release's VERIFIED status is valid only after independently confirming the
actual source revision loaded by the running service and the required
external-client/function path. Any missing consent, checked source, working
release trigger or installed readback leaves the item WAITING_HUMAN/BLOCKED,
not successfully deployed. This policy does not delegate approval authority
to the coding model or to another AI assistant.

## Human-facing requirement

The existing Foundation Settings/Operator becomes the default one-page OVERVIEW dashboard; its previous SETTINGS functions remain within the same UI and are directly reachable. Its primary responsibility is observing whole-system capability/connection/run/verification/failure truth and exceptional human decisions, **not** providing daily chat or duplicate task submission. The calling AI receives the actual answer and evidence. The dashboard must distinguish source code, installed runtime, connected MCP session, task execution and independent acceptance; show source, last observation and freshness rather than inventing live status.

The user-facing surface must make at least these states understandable and operable:

- normal execution and result
- waiting for human decision / approval
- failure
- UNCERTAIN / reconciliation required
- recovery
- system/provider/tool availability
- configuration and credentials without exposing raw secrets
- backup / restore / update status

The current human-facing supervision surface is the **existing Foundation Settings/Operator upgraded into a whole-system OVERVIEW dashboard**. The legacy HumanConsole server authority has been retired; historical references to it are migration evidence, not a current product boundary. Presentation clients remain replaceable and do not own Foundation authority.

## Foundation boundary

AI Foundation owns generic reusable execution concerns:

- Guard / authority / approval
- privacy
- budget
- durable orchestration
- specialist and execution ports
- cloud/local execution boundaries
- credentials
- observability and evaluation
- configuration
- backup / recovery / update
- generic operator capabilities

Concept OS remains independent.

Its unique opportunity-discovery, review and canonical semantics are not absorbed into AI Foundation. It may later consume generic Foundation ports without surrendering its own semantics.

M1Remote also remains outside AI Foundation.

## Migration rule

The staged migration from MultiLLM, Automation Hub, AI Home Server and the legacy HumanConsole server authority has already passed cutover/rollback evidence. These names remain in migration history only where needed to preserve that evidence.

Migration is staged:

parallel / shadow
-> authoritative comparison
-> limited cutover
-> rollback proof
-> broader cutover
-> representative daily use
-> removal of obsolete implementation

No big-bang migration.

## Program completion gate

The reconstruction program is complete only when:

1. Representative work from an owner-chosen external AI such as ChatGPT/Muse reaches AI Foundation through an authenticated scoped MCP/API, returns independently verified useful results to that AI, and appears in the existing Operator dashboard without requiring LibreChat.
2. Cloud/local routing and specialists perform those tasks through Foundation boundaries.
3. Required human approvals are understandable and authority is actually enforced.
4. Real effects are independently read back rather than trusted from tool success alone.
5. Failure and UNCERTAIN states can be recovered safely.
6. Restart and disaster recovery preserve durable work without blind duplicate effects.
7. Representative daily use requires neither a Foundation-owned chat surface nor the retired implementation as the normal path.
8. Rollback is proven before obsolete components are removed.
9. Concept OS independence is preserved.
10. The **existing Settings/Operator UI** opens to one-page system OVERVIEW with drill-down Settings, truthful evidence/freshness, and current exception decisions; no parallel dashboard/approval backend is introduced.

Completion of Phases A-F alone does not satisfy this program-level gate.

## Canonical runtime routing memory — non-negotiable

The persisted route chain is the human-visible policy order and MUST remain stable during ordinary runtime. Runtime health, quota, latency or recent failures MUST NOT visually reorder that chain. DOWN / RATE_LIMITED / CREDENTIAL_ERROR / RETIRED candidates may be shown as degraded (orange/warning presentation), but recovery returns them to their existing displayed position.

Execution is not a blind left-to-right retry on every request. Foundation keeps local deterministic runtime observations per binding (success/failure, timeout and measured latency) and uses those observations together with capability, health and fresh quota evidence to select the next eligible candidate. This runtime memory is Foundation-local state; no cloud LLM decides or updates routing history. A request-local exclusion still prevents retrying the same failed binding in one attempt chain.

After a real CHAT attempt fails, Foundation excludes that binding and asks the canonical deterministic router for the next eligible route using actual runtime, health, quota, credential and persisted-policy evidence. Synthetic one-token or otherwise reduced cloud probes MUST NOT promote a route for the failed request: they do not exercise that request's payload, tool schema, follow-up phase or context size. Health and recovery probes remain observation inputs only, ordinary user requests are not diverted to manufacture routing evidence, and fallback does not rewrite the persisted/displayed route order.

Agent tool authority is request-scoped. If a synthesis turn intentionally advertises no tools, a provider-emitted tool call from earlier conversation history is not executable authority and MUST NOT restart the tool loop. Text may be accepted while such an undeclared call is discarded; a tool-call-only synthesis response is a failed provider attempt and follows normal fallback. Final synthesis context is provider-neutral: Foundation carries forward the user request, host instructions and trusted tool result as ordinary context, but does not require a fallback provider or Local model to parse another provider's assistant tool-call protocol. Provider-native tool history remains confined to the scheduling turn where tools are actually advertised.

Quota evidence is observation-bound, not time-inferred authority. A near-empty quota observation suppresses normal execution until a fresh provider response or recovery-probe observation establishes recovered capacity. Reported reset metadata may schedule the next `ProviderRecoveryLoop` observation; elapsed local time, the reset window, or a bounded timeout MUST NOT by itself restore capacity or execution eligibility. When reset metadata is absent or unparseable, recovery scheduling may use a bounded conservative backoff, but that backoff is not recovery evidence. Fresh provider observations replace stale evidence.

```foundation-semantic
{"source":"src/ai_foundation/provider_recovery.py","subject":"src/ai_foundation/provider_recovery.py::CLASS::ProviderRecoveryLoop@3:0","subject_kind":"SYMBOL","claim_kind":"provider_recovery_observation_boundary","purpose":"schedule bounded re-observation of excluded provider capacity without treating elapsed time or reset metadata as recovery evidence","ownership":"Foundation owns recovery scheduling; fresh provider responses or recovery-probe observations own recovered-capacity evidence","rationale":"prevent local clock inference or reported reset windows from becoming provider capacity truth","failure_semantics":"without a fresh provider observation, suppressed capacity remains unavailable; absent or unparseable reset metadata uses conservative scheduling only and does not restore eligibility","side_effects":"may trigger bounded provider recovery observations and update derived provider health/quota evidence; it does not itself mint execution eligibility from time","change_impact":"changes must preserve observation-bound recovery authority, bounded probing and the prohibition on time-inferred capacity restoration","evidence":["tests/test_provider_recovery.py"]}
```

Runtime selection history changes execution preference only. It does not rewrite the saved/displayed route order. Explicit route optimization remains the operation that changes persisted policy order.

## Daily-use authority posture — 2026-09-26

Historical `foundation-auto` remains a convenient optional internal Agent surface, **not** the default daily-use entry point after the owner's 2026-11-13 decision. Normally the owner uses an existing external Agent, which chooses from explicitly host-authorized Foundation MCP/API tools. Where Foundation runs an internal Pydantic AI Agent, it may choose only the already-admitted tool set.

This convenience does not transfer authority to either caller or model. The trusted host composes only capabilities whose resource/effect boundaries have already been deliberately established.

Raw secrets remain inside credential-bearing boundaries. Protected resources,
destructive/external mutations, approval-bearing actions, and capabilities that
have not completed their promotion gates remain outside ambient authority and
retain their existing fail-closed Guard/effect/verification requirements.

Daily ambient authority is therefore composition of existing bounded grants,
not an unrestricted "all access" scope and not prompt-derived privilege.


## HumanModel automatic-answer supervision — 2026-11-18

The owner's chosen workflow is HumanModel automatic answers shown inside the existing notification levels, with owner objections or corrections instructed through Muse or another owner-chosen agent. Successful bounded answers appear as LV2 observations and do not themselves require a new owner-confirmation click. Technical failures retain LV3 and unresolved real owner requirements retain their existing levels; the model does not convert an unanswered permission request into approval.

A result card must show the actual question and selected answer, decision basis reference, exact task/question generation for correction, and independently observed related-work status. Mark superseded generations as history. A saved answer is distinct from native delivery, action authorization, and independently verified effect completion. Do not label a generated answer as the owner's new explicit instruction.

Persist only a bounded question/answer summary in the existing Work review event store; do not duplicate raw HumanModel source evidence. Historical hash-only records stay hash-only. Ordinary local Operator UI/API may display the result; constrained Echo polling and remote push must not receive the answer text. Do not generate an answer merely to populate a notification.

The source implementation presents and correlates automatic answers. Actual Muse-to-host correction ingestion, original source withdrawal/update and independent effect readback must be proven on their existing authenticated paths before claiming a complete correction loop. User corrections are explicit owner input, not automatic fidelity labels or permission grants.


## Existing-ledger release continuity and source correction — 2026-11-18

Operator-only release CLI must account for the already-existing per-release owner-main ledgers as well as the legacy Operator-only ledger. Select only one already-existing VERIFIED ledger whose immutable source, installed/loaded definition, PID and API independently match, or the exact existing in-flight release scope. Continue normal Guard preparation/verification/history in that same ledger. Do not rewrite historical VERIFIED rows, manufacture rollback, create a pointer/grant store, or fall back to a fresh ledger when any VERIFIED incumbent remains unidentified. Ambiguous, corrupt, symlinked or excessive ledger inventories remain blocked.

The optional human_model_correct MCP capability reuses the existing owner-source publication and supersession transaction. It accepts native source keys and an exact old-source digest only, never caller-supplied owner text or actor claims. A current authenticated owner session, current source-bound collection consent, independent original-source rereads, unique same-owner/scope attested observation and separate host authorization of the exact old evidence ID AND replacement grant are all required. Preserve original evidence/history and invalidate stale Views; this does not approve personal facts, correct arbitrary model-generated text as owner evidence, authorize task effects or automatically rebuild a View. Existing source/consent maintenance remains model-free and distinct from a verified rebuilt View. These tools remain absent from default status-only stdio sessions and are exposed only by a separately configured trusted host.

A Muse/Drive document remains source-only without independently authenticated original-owner provenance. Implemented source correction is not proof of live Muse transport or of automatic-answer correction and View reconstruction end to end.
