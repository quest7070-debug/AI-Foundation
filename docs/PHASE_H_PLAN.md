# Phase H — Migration / Production Cutover

## Goal
Move daily use to AI Foundation without a big-bang replacement, while keeping existing production systems recoverable until authoritative comparison and rollback gates pass.

## Owner-approved daily-use capability contract (2026-09-20)
The owner explicitly requires the LibreChat daily-use entry to support SEARCH, CODE, DATA, FILES, attachments and PC CONTROL in addition to CHAT. Foundation must also support long-running work that survives chat disconnects and can resume after interruption; Hatchet is the selected durable runtime boundary for that asynchronous work. The project remains private for now, so no public project license is to be invented during this phase.

This approval changes the former L07-L13/F08/F10/F12 audit blockers into implementation gates, but it does **not** grant ambient authority. Existing security invariants remain mandatory:
- model/prompt text may select or propose work but cannot mint repository, filesystem, attachment, dataset, PC or credential authority;
- trusted host context must bind capability scope before specialist execution;
- CODE receives an explicit host-bound repository/target plus TestPort and retains inspect/test/write/retest;
- DATA receives an explicit bounded operation and caller-bound input;
- FILES read/write receive explicit host-bound roots, with write narrower than read and protected resources excluded;
- attachments cross an explicit owner-scoped handoff and never become arbitrary local paths;
- PC CONTROL uses a production ComputerPort with host-bound allowed methods/targets and independent observe/readback;
- SEARCH uses a production ResearchPort that returns canonical Evidence/uncertainty rather than relabeling a provider-native browser tool;
- asynchronous/long-running work enters Hatchet through an explicit submission contract; Operator remains supervision/decision authority rather than becoming an ambient scheduler, and Foundation/Guard continue to own effect idempotency and ambiguous-outcome reconciliation.

Implementation order is contract-first: trusted request/capability envelope -> specialist production adapters -> attachment handoff -> PC ComputerPort -> durable Hatchet submission/resume -> LibreChat mapping -> tests/live evidence. Do not replace these gates with prompt keyword heuristics or unrestricted tool clients.

## Read-only inventory (2026-09-19)
Observed on the M1 without changing existing services:
- AI Foundation Operator: `127.0.0.1:8766`.
- AI Home Server v1 and its directly managed llama-server were explicitly authorized for early retirement on 2026-09-19 and stopped. They are no longer valid production dependencies or rollback assumptions. Local Compute must fail closed until the selected replaceable backend boundary is available. Concept OS is excluded from this retirement and must not be touched.
- HumanConsole: TLS uvicorn on `*:8790`; treat as an existing human surface and do not replace until surface/authority comparison is complete.
- Automation Hub: legacy authority `127.0.0.1:8787` was inventoried here before migration and is now stopped after verified Echo/Foundation cutover; do not restore it as a Foundation authority dependency. Retained Hub-specific integrations, if any, remain separate producers.
- M1Remote: `127.0.0.1:8792`; explicitly outside Foundation.
- A separate UI preview server remains on `127.0.0.1:8765`; it is not authoritative production state.
- Repositories visible under `/Users/yourname/Develop`: `AI-Foundation`, `AI-Home-Server`, `AI-Home-Server-v2`, `M1-Infrastructure`. Repository presence alone does not establish runtime authority.

## Gates
H1 / Inventory + contracts
- Identify each existing runtime entry point, output/readback, authority boundary, credential boundary, and rollback owner.
- No service stop, port takeover, data mutation, or credential migration in this gate.

H2 / Shadow
- Feed representative work to Foundation in a way that does not duplicate external effects.
- Compare route decision, policy decision, result shape, verification status, and operator visibility against the existing authoritative path.
- External EFFECT work must remain observe-only or use isolated fixtures during shadow.

H3 / Authoritative comparison
- Define deterministic pass/fail evidence per path. No "looks equivalent" gate.
- Required baseline paths: local inference, cloud inference when a valid credential is available, human approval, human comment/input, cancellation, Tool/MCP effect + independent readback, UNCERTAIN recovery, provider failure/failover.

H4 / Limited cutover
- Move one low-risk path at a time to Foundation authority.
- Persist the previous authority/endpoint and an explicit rollback procedure before switching.
- No Concept OS semantic redesign during cutover.

H5 / Rollback proof
- Exercise rollback for each cut-over path and perform authoritative readback after rollback.
- A successful process restart is not sufficient evidence.

H6 / Broader daily use
- Expand only paths that passed H3–H5.
- Observe real operational use long enough to capture restart, provider outage, WAITING_HUMAN, and recovery behavior.

H7 / Old removal
- Remove an old path only after no supported entry point depends on it and rollback retention requirements are satisfied.
- Archive evidence/config needed to reconstruct the prior state before deletion.

## Current blockers / non-blockers
- Local inference: replacement llama-swap backend is live and Operator construction targets it; previous H3 AI Home Server evidence is historical and must be regenerated against the current Foundation path before claiming the new backend has H3/H4 proof.
- ToolHive filesystem observe-only reconciliation: real-host adapter verified; per-effect recipe gating remains mandatory.
- Live cloud success: PASS at the H3 three-sample LIVE evidence floor using intentionally configured production credentials; evidence stores no secret.
- HumanConsole/Automation Hub remain historical comparison sources, but their legacy authority ports :8790/:8787 are now stopped after responsibility-scoped cutover/rollback/re-cutover evidence. AI Home Server was explicitly retired and is likewise no longer a runtime/rollback target.
- Sites: optional isolated UI prototyping/read-only demo aid only; never a cutover authority/runtime dependency.

## Execution plan / anti-patchwork gates (2026-09-19)
1. H2/H3 evidence matrix first: local inference, cloud inference, human approval, human input, cancellation, Tool/MCP effect+readback, UNCERTAIN recovery, provider failure/failover. A path is not eligible for cutover until deterministic shadow evidence reaches the sample floor with zero mismatches.
2. Boundary hardening in parallel: broad exception handlers are reviewed by role. Fail-closed policy/transport/recovery catches stay only where their externally visible state is explicit and tested; catches that can hide programming/data-integrity errors must be narrowed or surfaced.
3. User-flow gate: validate submit/readback → WAITING_HUMAN → approve/input → resume → verify, cancel before/during effect, restart/reconcile, provider outage/failover/recovery, and narrow responsive surfaces. Source-only assertions are insufficient when a live HTTP readback exists.
4. H4 cut over one low-risk path only after H3. Persist old endpoint/authority and rollback recipe before switching.
5. H5 actually roll back and perform authoritative readback. Process restart alone is not proof.
6. H6 daily-use expansion only after H3–H5; H7 removal only after dependency inventory and reconstruction evidence pass.

## H3 evidence status rule
- H3 evidence is now reportable per required path, including zero-sample paths. A missing path must be visible as zero samples and cannot disappear from a summary.
- Connected task creation remains intentionally outside the Human Decision Surface; Operator supervises/statuses/results and human decisions only. H3 user-flow testing must therefore exercise a connected/intake boundary, then Operator readback/decision, rather than adding a convenience task composer that changes the product boundary.

## H3 execution/reporting rule
- H3 reports use exactly four operational states: PASS, MISMATCH, BLOCKED, NOT_RUN. BLOCKED and NOT_RUN are never appended as equivalent shadow samples and therefore can never satisfy the H3 sample floor.
- Cloud inference is no longer blocked: the H3 runner uses the configured production credential boundary and requires LIVE evidence. If valid cloud capacity later becomes unavailable, new evidence must fail/block honestly rather than substituting a fixture.

## H3 evidence reality floor
- Evidence carries a reality class: DETERMINISTIC, ISOLATED_REAL, or LIVE. Each mandatory H3 path has a code-defined minimum; higher-reality evidence may satisfy a lower floor, never the reverse.
- Local/cloud inference require LIVE evidence. Tool effect and UNCERTAIN recovery require at least ISOLATED_REAL evidence. Approval/input/cancellation/provider-failover require at least deterministic end-to-end evidence and may be strengthened with real/live runs.
- This prevents already-passing unit fixtures from being copied into the H3 ledger and misrepresented as live migration proof.

## H4/H5 authority ledger gate
- Before any authority switch, persist the previous authority/endpoint, candidate authority/endpoint, and an explicit rollback procedure in the durable CutoverRegistry. PREPARED -> CUTOVER -> ROLLED_BACK/VERIFIED transitions fail closed on stale state. The registry records migration authority only; it never performs a service switch itself.
- Local inference has fresh LIVE 3/3 evidence on the replacement llama-swap path. The old AIHS evidence is historical. H4/H5 now concern the current Foundation -> llama-swap responsibility boundary and its failure/recovery/readback, not a rollback to AIHS.

## H4 concrete switch-target gate
- A cutover record is insufficient unless the concrete switch target (the caller/config whose authority changes) and authoritative readback target are known. CutoverRegistry now requires both. This prevents marking an adapter dependency as a migrated authority when no external caller has actually been redirected.
- The historical AI Home Server caller audit is superseded by its explicit retirement. Foundation Operator now targets the llama-swap Local Compute boundary directly. The old H3 local-inference ledger remains historical evidence only; current-backend live evidence, restart/readback and rollback/failure behavior must be recorded before the replacement path is marked migration-complete.

## H4 responsibility migration correction (2026-09-19)
The old systems are rollback/reference sources during migration, not the intended steady-state architecture. H4 therefore migrates responsibilities into Foundation rather than adding permanent Foundation -> legacy authority adapters. Temporary comparison/rollback bridges are allowed only when they are explicitly migration-scoped and removable.

Responsibility targets:
- MultiLLM: provider routing/failover, privacy/local-vs-cloud selection, provider health/capacity and model-facing execution move to Foundation routing/execution boundaries.
- Automation Hub: generic durable execution/retry/recovery and human approval/input/cancellation semantics required by Foundation move to Foundation runtime/Guard/TaskIntake. Hub-specific external integrations may remain separate producers, but Foundation must not depend on Automation Hub as its authority.
- AI Home Server: model lifecycle/backend serving is replaceable Local Compute plumbing below Foundation; daily-use callers move to Foundation. AI Home Server as a standalone product is not the final authority boundary.
- HumanConsole: its required decision/notification experience is compared and migrated to the Foundation Human Decision Surface or a replaceable presentation client over Foundation semantics; it must not remain an Automation Hub authority dependency for Foundation work.
- HumanConsole retirement is responsibility-scoped, not name-scoped: the legacy :8790 server authority is retired independently. The migrated mobile WebPush subscription/client and the Echo Android package named com.quest7070.humanconsole are presentation clients and must not be deleted merely because they retain the legacy name; Echo authority has been redirected from legacy Automation Hub :8787 to Foundation Echo gateway :8788 with rollback/re-cutover evidence.
- M1Remote stays outside Foundation. Concept OS stays independent.

H4 readiness is evaluated per responsibility, not by inventing an external caller for every H3 evidence row. A responsibility is ready when Foundation owns the required semantics, the legacy behavior has been compared, a real daily-use entry can be redirected, and rollback/readback are explicit. H7 removes obsolete legacy paths after H5/H6 evidence.

## Responsibility parity gate (2026-09-19)
Before any H4 cutover, compare legacy responsibilities against Foundation by behavior, not module names. The old implementation is reference/rollback evidence only.

Current audit:
- MultiLLM -> Foundation: provider onboarding/credential isolation, health/quota-aware routing, local-only privacy and failover are substantially represented. LibreChat now uses the Foundation OpenAI-compatible entry for daily-use chat and production readback covers discovery, normal chat and streaming. Continue to gate SEARCH specialist mapping, attachment/media transport and title/readback separately; do not assume a chat/UI feature belongs in Foundation merely because MultiLLM had it.
- Automation Hub -> Foundation: Guard/DurableWork/TaskIntake cover the safety-critical execution core, approval/input/cancel/reconciliation and restart persistence. Legacy comparison found two semantics worth carrying forward without copying its command model: question answers are bound to a durable context digest, and effectful failed work is not retry-safe until reconciliation establishes the prior effect outcome.
- AI Home Server -> Foundation Local Compute: inference is integrated, but model lifecycle is not yet proven independent of the standalone AI Home Server. Replacement model inventory/load/switch/concurrency/failure-isolation/TTL-reload/health have live evidence through llama-swap; AI Home Server is retired and is not a rollback dependency. Replacing the serving backend may use llama-swap/llama.cpp per the selected Local Compute boundary; Foundation remains the authority above it.
- HumanConsole -> Foundation Human Decision Surface: decision/input/status semantics are represented and exposed through a Foundation-native loopback human projection. Remote-access policy is now separated from decision authority with explicit-host, same-origin, constant-time token and signed expiring-session primitives; push copy is projected from Foundation notices without raw task text and is deduplicable. Foundation HTTPS gateway auth edge has staged live evidence on an isolated port with ephemeral strong credentials: unauthenticated 401, forged Host 400, bad Origin 403 and login 204. The live Operator was then refreshed onto current main and the same staged HTTPS flow reached authenticated Foundation human readback 200. WebPush provider-send is now live-proven from Foundation after one-shot Keychain migration. Production gateway credential provisioning and H4/H5 server cutover/rollback/re-cutover are complete. Remote-device/browser validation and device-visible push receipt remain presentation-client evidence only; they do not restore :8790 authority.

A parity item may be classified REQUIRED, DELEGATED to a selected replaceable OSS/backend boundary, or OBSOLETE. Only REQUIRED/DELEGATED items block retirement. Classification must be explicit; absence is not evidence of obsolescence.
