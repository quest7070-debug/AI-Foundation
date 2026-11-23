# System Role Boundaries

**Status: ACTIVE CANON — external-AI-first use and existing Settings dashboard reconciled 2026-11-13; single-9B/optional-Strata compute policy reconciled 2026-11-15.** Supersedes the 2026-10-07 declaration that Kandev alone owns development execution. See `END_GOAL.md` for the program completion gate. Historical drafts and release notes are evidence, not current authority.

## Model / compute supply

Cloud and local LLMs are replaceable inference resources, not owners of task identity, scope, credentials, billing, release approval or VERIFIED status. Foundation host/Guard owns FREE-only eligibility and LOCAL_ONLY privacy; models do not choose their provider or grant permissions. M1 uses one approved local 9B shared by admitted local roles; historical multi-model specialist slots and 4B experiments are not active residency requirements. Independent verification does not require a second resident model. See `LOCAL_MODEL_ROLE_POLICY.md` for the reconciled policy and dated historical slot proposal.

For already-admitted exact public payloads, authenticated/capable MainPC Strata is preferred for coding and public analysis, summary, planning, error triage and preliminary code review. HumanModel, private KLM/context, secrets, data-sensitivity decisions, recovery and final independent acceptance remain M1-owned. Current public CHAT may select already-online M1 9B only on fresh comparative completion evidence of materially better efficiency; CODE remains Strata-first within scope. MainPC is optional. By the owner's explicit 2026-11-16 instruction, a host-authorized READY reviewed public Strata/auto CODE ticket may issue one bounded, persisted wake attempt via the **existing** owner M1 `wake-desktop.py` when MainPC is unreachable, before any Work claim. Status/list, missing credentials, auth or model mismatch, completed/review-required tickets, and private M1 work never trigger wake. No polling daemon, global auto-wake on route failure, replay, forced eviction or paid fallback; auto CODE keeps its existing M1 capacity fallback if MainPC remains unavailable. The single-local-LLM rule does not cap authorized browser/external AI routes; existing privacy, cost and M1 resource gates still apply. These are routing/admission rules, not proof of installed models, accepted VISION or a live external-client E2E.

## Foundation and product runtime

Foundation owns Canon, Guard/Cedar, durable effects, policy, privacy, scope, routing, role admission, deterministic verification, recovery and Human Gates. Operator owns the human-facing decision and status surface. LibreChat is replaceable presentation; Pydantic AI selects only host-authorized tools. HumanModel is the owner-data corpus for reconstructing provisional answers to other agents' questions in the owner's perspective. It provides evidence, not the owner's actual words or authority; the existing admitted Agent/LLM does the reconstruction. KLM handles source-bound derived knowledge, not generic development task orchestration. Concept OS and M1Remote remain independent.

## Owner interaction and existing Settings/Operator — 2026-11-13

- **Primary clients:** the owner normally interacts with ChatGPT, Muse or another already-used AI. These remain the caller/orchestrator; Foundation is their host-authorized MCP/API memory, development factory and tool/execution substrate. LibreChat and the internal `foundation-auto` Agent are optional, not required defaults. An upstream Agent may select exposed tools but cannot grant authority.
- **MCP boundary:** host principal authentication, exact binding, per-tool scope, privacy/egress and existing Guard apply to every external caller. The default stdio adapter currently publishes only `foundation_status`; cataloged `human_model_answer` / approval tools are opt-in authenticated-host functionality, not proof of a ChatGPT/Muse live connection, approved owner data access or broad production readiness. Do not introduce a second Agent framework, permission system, router or privileged network listener to implement MCP-first.
- **UI continuity:** the *already implemented* Foundation Settings / Human Decision Surface / Operator evolves **in place** into a one-page whole-system OVERVIEW dashboard as the default landing page. Existing SETTINGS/provider/routing/credential controls, task activity, notifications, LV1–LV5 approvals and recovery actions remain first-class drill-down functions in the same UI. No separate dashboard product or parallel state/authorization store. Keep shared semantic HumanView and C/I themes.
- **Dashboard evidence:** observe capability implementation, installed revision, authenticated MCP clients/sessions when observable, authorization, worker/queue/compute lease, provider health/quota, HumanModel View, KLM freshness, execution/effect receipts, errors/UNCERTAIN and latest success independently. Every visible state needs producer, timestamp/freshness and safe deep link; distinguish unobservable from disconnected. A merged source/HTTP 200/fixture is never a claimed user E2E.
- **Acceptance:** a real authorized external-AI MCP request completes a meaningful Foundation operation, returns evidence to its calling agent, and shows the same independently observed status in the existing Operator without leaking raw private records. Human-facing work is supervision and exception handling, not a duplicate chat.

## Development ownership now

- **GitHub** is primarily the canonical published repository and record-preservation destination for source, changes, history and permitted evidence. GitHub Issue/PR/CI identity is publication metadata, not the active task identity or authority. M1 Foundation owns local work, acceptance, installation and recovery. GitHub availability, an Issue, PR or Actions run must not be a routine prerequisite for local development or authorized service recovery.
- **Existing Foundation host / Guard / Harness** own admitted development scope, roles (triage, decomposition, implementation, repair, review), permitted inference profile, cost and privacy conditions, independent acceptance and effect reconciliation.
- **Existing installed local9B worker** accepts only exact preauthorized ready-Issue or independently source-verified, finite standing-main-regression contracts through the existing compute lease. It retains one-shot claims, deferred-before-effect handling, fixed tests and Draft-only delivery. Do not restart the model or replay consumed work.
- **Execution frontends**: DSH → OpenCode is one host-admitted route; Codex OSS is a separate optional route. Neither CLI nor LLM response grants Guard scope, payment, model management or merge privileges. Offline canary is not live 9B task completion.
- **Kandev / historical Paseo Native** remain historical or separately isolated integrations, **not active AI-Foundation development executors in the current owner workflow**. Do not invoke Kandev Control/MCP, launch its installers, Native signals, scheduler or worktree managers, or use Kandev as a fallback. Reactivation needs a new explicit owner instruction; old PR/Canon text is not such an instruction.
- **Human approval**: service/model onboarding remains a manual choice when requested. Within an already approved finite low-risk scope, the system may discover, propose, execute and continue without asking for fresh identical permission at each step. New expense, scope escalation, private egress, production cutover and irreversible changes still need their distinct current Guard/owner authority.

## Default development transport — M1-owned execution, GitHub record preservation (owner clarification 2026-11-22)

For already authorized ordinary development, the intended fast path is:
**calling AI (ChatGPT / Muse / other) → authenticated Foundation MCP Host →
host-bound Guard/Harness → M1 isolated checkout → minimal local fixed tests →
bounded local repair → independent local acceptance → authorized local
release/readback when needed**. Save source and outcome evidence separately to
GitHub using existing delivery receipts. Preserve local results and pending
publication when remote storage is unavailable; retry the record effect alone.
GitHub Issue/Actions is optional legacy intake or supplementary CI/audit, not
an ordinary work/release trigger or owner-approval substitute.
Do not interpret this design as permission to merge main or deploy on a model's
own assertion.

The source-level opt-in `development_run` and `development_status` MCP
contracts select only an immutable, trusted host-created ticket ID. They reuse
the existing Guard, Work, local execution port, tests and lease and cannot
accept arbitrary shell, paths, provider selection, payment flags, approval or
merge targets from a calling agent. One claimed ticket is non-replayable after
ambiguous failure or interruption; fresh work requires a fresh authorized
ticket. Existing MCP status-only defaults and owner-delegation behavior do
not silently gain write scopes.

Local `VERIFIED_LOCAL` proves fixed acceptance for one isolated candidate,
**not** a PR, main integration, installed M1 revision or live ChatGPT/Muse
connection. GitHub publication and supplementary CI are record/delivery activities;
M1's independently verified release/readback proves production installation.
Neither requires the other to be falsely marked complete. A source PR or
synthetic stdio test cannot be represented as an active direct client path.
The installed trusted M1 launcher must bind a real host-owned ticket factory
and existing client transport before this route is called live.

Independent host-authorized external Free models may overlap for distinct
isolated tasks where existing lease, data-egress, budget and Guard contracts
permit it. Local 9B and resource-heavy CI retain actual M1 resource admission;
a shared local slot is not parallelized by adding more MCP clients.

## Purpose is broader than the current finite executor

The current local9B worker's three standing source/test pairs and one-file
`python-fixed-test` recipe are **implementation/admission limits of that
one executor**, not a restriction of Foundation's development mission or of
already host-authorized external free-model developers. Task discovery,
research, cross-repository explanation, coding, review and delivery remain
agent/Harness responsibilities with their *own* exact existing grants.
Do not solve an incomplete general development loop by redefining success
as repeatedly scanning three fixed regression files, by requiring a new
human permission for each routine authorized step, or by routing work back
to Kandev.

HumanModel's success is not a larger corpus, more audit jobs or approval
matches. It is **another authorized agent asking a substantive question and
receiving a provisional owner-perspective answer grounded in the owner's
actual current records**, with corrections, disagreements and unknowns
retained. The invoking Agent interprets the data; the result is never
the owner's real decision, authenticated instruction or authority to act.
If the model supplies no valid source references, withhold the purported
owner answer rather than exporting an unsupported persona.

KLM's semantic intake, relationship maintenance and Drive placements are
input-side organization for source owners, not a second answering model or
output-side meaning gate. GitHub is authoritative for this repository's
code and policy version; individual Drive records, HumanModel originals,
runtime receipts and third-party source data retain their own source
ownership. A repo commit is not proof of an installed runtime.

## Nonduplication, contention and completion

Reuse the existing M1 development host, compute lease, scheduler and durable Work/effect receipts. Keep historical GitHub intake optional and use the existing GitHub delivery mechanism for record preservation; do not make remote availability a routine local control dependency. Do not invent a second router, scheduler, task DB, approval plane or model lifecycle controller. Passive GitHub observation has no reason to acquire a model lease; resource-heavy host checks still respect M1 capacity. HOST_COMPUTE_BUSY is a deferred test, not a source regression.

Distinguish source-on-main, installed host revision, authorized task, consumed attempt, independently verified outcome and production cutover. Neither tests, CI, Draft nor merged PR imply user-facing E2E completion. Unknown/uncertain effects require reconciliation, not blind replay.

## Conflict rule

Old documentation assigning all development to Kandev or saying all GitHub intake awaits Paseo Native is superseded by this file, current code and independently verified host evidence. Keep the historical source record; repair only the narrow existing owner.
