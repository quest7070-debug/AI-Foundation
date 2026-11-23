# Phase G execution plan — 2026-09-19

> **2026-11-13 owner supersession (historical plan retained):** The original Foundation Settings/Operator app remains the implementation basis but now opens to a **single-page OVERVIEW dashboard**, not SETTINGS. SETTINGS retains all provider, routing and credential tools in the same app. The real primary work path uses the owner's existing ChatGPT/Muse/other AI through authenticated MCP/API; the dashboard supervises work and exceptions, not chat. Do not build a parallel dashboard or authority plane. See current `docs/END_GOAL.md`, `docs/SYSTEM_ROLE_BOUNDARIES.md` and `docs/PHASE_G_PLAN.md`. The dated steps below describe earlier implementation checkpoints; any contrary UI-entry assumption is superseded.

Goal: finish Phase G as a usable human-facing integration slice without touching current production systems. Phase H remains the only migration/cutover phase.

## Batch 1 — Stabilize current G1/G2
1. Keep Settings as a dedicated surface; provider cards are real registry data only.
2. Harden provider HTTP transport (redirect credential leakage, bounded response body).
3. Close provider metadata validation (finite quota, health allowlist) and SQLite concurrency/permissions.
4. Keep Groq live-success E2E deferred until an operator supplies a valid credential; current real 401/403 fail-closed is evidence, not success evidence.
5. Do not block G on Mistral/OpenRouter/Gemini FREE quota adapters; unsupported trustworthy quota remains UNVERIFIED.

## Batch 2 — Routing and settings completeness
1. Add persisted automatic route policy and route snapshots: function -> PRIMARY/STANDBY.
2. Hard privacy/secret constraints remain outside user tuning and cannot be overridden.
3. Add OPTIMIZE as an explicit recomputation event; health may temporarily skip candidates without rewriting saved order.
4. Add credential expansion/removal and local-compute candidate representation without exposing model clutter.

## Batch 3 — Human operations
1. Tasks: human-requested work units, status/result/evidence; internal steps only on expansion.
2. Notifications/Approvals: LV1-LV5 ordering, Japanese explanatory body, individual AUTHORIZE/DENY, dismiss != audit deletion.
3. UNCERTAIN/reconciliation and recovery become explicit operator journeys; no private Guard method from UI.
4. Refactor fixture rendering so real state and preview fixtures are separate inputs to the same renderer.

## Batch 4 — Multi-surface
1. Desktop/web full surface.
2. Mobile: Notifications/Approvals first, task/result and required text input.
3. Echo: dashboard-only SYSTEM/NOTIFICATIONS, no approval/settings/text entry.
4. One state model and semantic colors across all surfaces.

## Batch 5 — G5 end-to-end gates
Prove from human surface: normal text result; private/local route; human approval; verified external effect; failure; UNCERTAIN reconciliation; restart recovery. Every gate requires authoritative readback/evidence, not HTTP 200 alone.

## Batch 6 — G6 closure
Run full regression, adversarial UI/HTTP tests, responsive review, real-host operator smoke test, update canonical docs/current state. Phase G closes only if the daily-use representative path is understandable and operable. Then begin Phase H staged migration: shadow -> comparison -> limited cutover -> rollback proof -> broader cutover -> daily use -> old removal.

## Non-goals in G
No Concept OS absorption. No production-system shutdown. No big-bang migration. No fake provider quota. No manual provider-order editor. No chat/LibreChat replacement inside Foundation UI.

## Progress readback
- Batch 2 started: persisted automatic routing policy implemented.
- Route snapshots persist function -> PRIMARY/STANDBY order.
- OPTIMIZE semantics are explicit recomputation; health skip does not rewrite saved order.
- A 3% completion safety margin skips near-empty candidates at selection time.
- Provider credential metadata can be enumerated for routing without exposing secrets.

## Consolidated execution batch — 2026-09-19
1. Close recovery plumbing: durable reconciliation recipe, operator port registry, restart E2E, fail-closed unavailable port.
2. Close state persistence: backup every Foundation SQLite DB consistently (including `.sqlite` routing/provider/reconciliation), restore traversal defense.
3. Close settings routing behavior: provider add/remove triggers deterministic route optimization; never expose credential binding in human UI.
4. Harden localhost HTTP/transport boundaries and then run full regression + authoritative operator readback.
5. Only after functional surfaces are present, perform the planned visual/layout redesign; do not polish the current fixture incrementally.

### UI reference added
G6 redesign will also use the Japan Digital Agency Dashboard Design Guidebook as an information-design baseline: user questions/decisions first, prototype before polish, consistent grid/components, unambiguous expression, and Do/Don't review. AI FOUNDATION's existing industrial-HMI visual identity remains independent.

## G5 gate review — 2026-09-19
Code-level representative gates now have evidence for:
- private/secret work taking LOCAL_ONLY with zero cloud execute/observe;
- WAITING_HUMAN surviving restart, then AUTHORIZE continuing exactly once and DENY remaining blocked;
- FAILED durable work recovering after restart without replaying an already verified step;
- ambiguous external effect surviving restart and reconciling by independent observe/readback only (zero re-execute), with unavailable verification port failing closed;
- provider primary DOWN -> standby selection -> recovered primary restoration without rewriting saved route order;
- <=3% quota safety margin skipping a candidate and no eligible provider failing closed;
- same-target exclusion, concurrent durable-step exclusion, cancellation during effect -> UNCERTAIN, and existing opt-in real ToolHive process-death/container-restart scenarios;
- target-lease-loss test changed from scheduler-sensitive sleep to synchronization on an actual heartbeat renewal attempt; 20 consecutive runs passed after the change.

Latest full regression at this review: 332 passed, 10 skipped, 1 warning.

G5 is code-complete for the currently available controlled/isolated paths, but Phase G is NOT closed. Remaining external/live gates are explicit:
1. valid live FREE-provider success E2E is deferred until a valid operator credential is supplied; previous real Groq rejection is only fail-closed evidence;
2. opt-in real ToolHive process-death/container-restart tests remain environment-dependent and skipped in the default suite;
3. the final daily-use human-surface path still needs G6 information architecture/rendering and real-host smoke/readback after that redesign;
4. multi-surface Desktop/Mobile/Echo behavior still needs final implementation/review from the shared state model.

## Pre-G6 functional / information-architecture inventory — 2026-09-19
Do not add decorative polish to the current fixture shell. G6 begins by mapping each visible element to a human question, decision, or action, using the Digital Agency dashboard guidebook as an information-design reference and Variant I as the AI FOUNDATION visual-language baseline.

Keep as first-class human journeys:
- submit a human task and understand its current state/result/evidence;
- understand WAITING_HUMAN and individually AUTHORIZE/DENY;
- understand UNCERTAIN and reconcile only when a durable recipe + verification port are available;
- see provider/local availability, quota/reset, current route and standby without raw binding/model/secret noise;
- understand failure/recovery and whether human action is required;
- inspect compact system/readiness/backup/update status only when it supports an action.

Remove or demote from the default surface:
- internal workflow steps, raw credential binding IDs, raw model clutter, implementation-only Guard/runtime metadata, decorative telemetry, and duplicated status panels that do not change a decision.

G6 implementation order:
1. shared semantic view model / dedicated renderer (real state and preview fixtures separated);
2. Desktop information hierarchy and responsive grid;
3. Mobile compact command/result/approval/alert layout from the same state model;
4. Echo dashboard-only SYSTEM/NOTIFICATIONS layout, no approval/settings/text input;
5. Do/Don't review of every block, then visual refinement in the accepted dark-blue industrial-HMI/techwear language;
6. adversarial UI/HTTP + responsive review + real M1 operator smoke/readback; update canonical state and only then judge Phase G closure.

## Canon/source/test audit — 2026-09-19
A fresh END_GOAL / PHASE_G_PLAN / G execution plan / ROADMAP / source / test inventory audit found remaining G requirements that were not yet closed by the semantic renderer work: raw credential binding identifiers can still appear in HTML action URLs; notification dismissal is specified (Echo-safe, audit-preserving) but not implemented; notification same-level newest-first ordering is not represented; reset/reason detail is incomplete; semantic G6 surface does not yet carry compact backup/update/system telemetry; route presentation does not yet represent Local as an ordinary saved-route candidate; task evidence is still only a result string; final Do/Don't information-architecture review remains open. Live valid FREE-provider success remains externally deferred by credential availability, and opt-in ToolHive real crash/restart remains environment-dependent.

Audit also adds previously under-tested HTTP directions: DNS-rebinding-style GET Host handling, Transfer-Encoding/chunked request ambiguity, and source-level leakage of internal credential bindings. These are treated as implementation gates, not documentation-only findings.

## G6 dual-design update — 2026-09-19
G6 closure now includes two accepted designs: C (Endfield-like dense telemetry) and I (current industrial-HMI). Implement a presentation-only C/I switch backed by one HumanView and one set of surface/action contracts. Add semantic parity tests across both designs and all three surfaces. Do not fork operator/domain logic or persist separate operational state. Visual refinement must review both designs, not collapse them into one hybrid.

### C/I implementation constraint — shared layout
Implement one semantic/layout renderer per surface and two interchangeable visual themes. Do not implement two page trees. Parity tests must compare section/order/control geometry contracts as well as semantic/action availability. Any discovered C-vs-I layout conflict is a user decision gate: pause that conflicting change and ask which common layout to retain.
