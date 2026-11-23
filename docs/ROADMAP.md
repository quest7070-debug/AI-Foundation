# AI Foundation roadmap

## Phase A — Safe execution foundation (substantially verified)
Guard Core; durable effects/reconciliation; privacy/budget/cancellation; Cedar boundary; credential target binding; Hatchet durability experiments; ToolHive/MCP execution boundary; Pydantic AgentPort; host-bound authority; scoped READ/COMPUTE/EFFECT capabilities.

## Phase B — Specialist contracts (boundary baseline implemented)
1. Research: evidence records, source provenance, uncertainty, no external-content authority.
2. Coding: inspect/test/propose; writes only through EFFECT; merge/production remain human-controlled.
3. Data: bounded input/compute/output with reproducible evidence.
4. Computer Action: API/MCP first, UI fallback; every external effect verified/read back.
5. Artifact: generate then independently validate output.

Exit: specialists cannot bypass capability/Guard boundaries and return structured evidence rather than completion claims.

## Phase C — Integrated orchestration (baseline complete; 2026-09-18)
Durable specialist Jobs/Runs, explicit immutable persisted step identity, failure/recovery, ambiguity -> waiting_human, cancellation and no-change behavior. Preserve replaceability; orchestration owns work state, specialists own methodology.

## Phase D — Production security/runtime (complete; 2026-09-18)
Credential-provider boundary and principal/role/tenant/target authorization baseline implemented; containment lifecycle baseline implemented. OS-neutral native credential storage boundary and the first production adapter (macOS Keychain) are implemented and real-M1 availability/revocation readback is verified with a disposable dummy item. Windows/Linux native adapters remain portability work, not a Phase D blocker on the current M1 production host. Remote-effect cancellation E2E, real ToolHive containment adapter/lifecycle E2E, policy revision/provenance hardening, and age/single-owner startup recovery are implemented. Final source/test closure audit found no unresolved current-M1 Phase D gate. Phase D is closed; Windows/Linux credential adapters and broader product policy remain portability/productization work.

## Phase E — Observability and evaluation (complete; 2026-09-18)
Baseline implemented: OTel-compatible trace/span identifiers, parent linkage, safe append-only JSONL/in-memory sinks, evidence IDs, deterministic evaluator, and an explicit opt-in semantic evaluator. Safe trace metadata allowlisting is implemented default-deny. Guard, durable work and specialist boundaries now have composition-based instrumentation wrappers; evidence-linked run reports and deterministic gate summaries are implemented. Integrated deterministic security denial and durable replay/no-duplicate recovery gates now produce evidence-linked results. JSONL traces survive reopen and strict readback rejects corrupt/schema-drifted records. Real ToolHive/MCP external-effect trace -> durable JSONL -> readback -> evidence-linked deterministic report is verified on M1. Specialist baseline quality contracts for research/coding/data/artifact are deterministic and explain failures without a model judge. Semantic evaluation remains an optional boundary for future genuinely subjective quality dimensions, not a Phase E requirement. Phase E is closed.

## Phase F — Productization (closed for first supported host; 2026-09-18)
Detailed plan: `docs/PHASE_F_PLAN.md`. Baseline implemented: versioned/path-confined configuration, explicit host capability reporting, consistent SQLite + trace backup with SHA-256 manifest, verify-before-write restore, read-only preflight for config/DB/native-secret/required-credential readiness, operator runbook, and a pinned-environment dependency snapshot. Fresh isolated-venv bootstrap is now real-M1 verified with Python-version preflight and import readback. A staged full-state DR drill restores Guard/work/trace state into an independent directory and proves VERIFIED effects are not replayed. Migration/update baseline fails closed on unsupported paths/non-empty stage. Dependency metadata inventory is captured, but 25 installed distributions expose no license metadata/classifier and therefore remain unresolved for release licensing review. Remaining: implement a real version-to-version migration + rollback once schema v2 exists, resolve dependency licenses from authoritative package/source metadata, and real-host portability beyond M1/macOS.

## Phase G — Integration / User Experience
Connect the Foundation to a real daily-use human-facing surface and the real execution environment. This phase covers the practical Human Decision surface, cloud/local LLM routing, specialists, tools/MCP/computer actions, meaningful approval/recovery states, and end-to-end user journeys.

The current supervision boundary is the AI Foundation Human Decision Surface / Operator; presentation clients remain replaceable. The legacy HumanConsole server authority is retired and is not a future product boundary.

Exit: representative human-initiated tasks travel through the real UI -> Foundation -> execution -> independent verification path and return meaningful results/status to the human.

## Phase H — Migration / Production Cutover
Historical migration phase: staged cutover from MultiLLM / AI Home Server / the legacy HumanConsole server authority and related replaceable generic components without a big-bang switch. The authority cutovers are recorded in Phase H evidence; remaining client-visible validation does not restore legacy authority.

Sequence: parallel/shadow -> authoritative comparison -> limited cutover -> rollback proof -> broader cutover -> representative daily use -> removal of obsolete implementation.

Exit: the new environment sustains representative daily use without requiring the old implementation as the normal path, rollback has been proven, and obsolete components are removed only after that evidence exists.

## Program completion rule
The authoritative end goal is defined in `docs/END_GOAL.md`.

A feature is not complete because a tool returned success, HTTP 200, or tests merely executed. Completion requires expected-vs-observed verification at the strongest practical layer and no unresolved unsafe external effect.

Phase F is the final Foundation productization phase, but it is not the end of the reconstruction program. Program completion requires the Phase H end-to-end cutover gate.

## Phase F status update — 2026-09-18
F1 configuration/readiness baseline is implemented. F2 atomic staged backup/restore and real-state DR are closed for the current single-host filesystem gate. F3 staged update/readback/rollback plus interrupted-update recovery is closed without inventing a schema v2; a real future schema change must add a real migration through the same gate. F4 explicitly supports only the real-verified Darwin/arm64 M1 host; Linux/Windows/other macOS architectures remain unsupported-unverified. F5 inventory was corrected for PEP 639 metadata: 45 installed dependency/tool distributions have license evidence, while the AI Foundation project itself intentionally has no external-distribution license selected yet; this is not an internal-use blocker. F6 minimal operator surface is implemented and regression-covered; full daily-use UX remains Phase G. Latest full regression: 235 passed, 10 skipped, 1 known third-party warning.

## Phase G checkpoint — 2026-09-19
G5 controlled-path gates are substantially complete. Do not close Phase G yet. Next: G6 shared semantic renderer + Desktop/Mobile/Echo information architecture, then adversarial/responsive review and real-M1 smoke/readback. Live valid FREE-provider success and opt-in real ToolHive crash/restart evidence remain explicit deferred/external gates. Phase H migration starts only after G closure.

## Generic VISION capability extension — planned 2026-09-22
A generic image-analysis route is a planned Foundation extension, not a CAD-specific feature. It reuses trusted CapabilityRequest, owner-scoped AttachmentHandoff, automatic routing, local/cloud execution, privacy/budget, observability and verification boundaries. Caller products retain domain authority; model observations never become CAD or other product evidence automatically. Detailed gate: `docs/VISION_CAPABILITY_PLAN.md`. It must not restore retired legacy authority or bind Foundation to Florence-2 or any one model.


## OSS execution-plane integration — converged 2026-09-25

The DATA / interactive-computer OSS decision is no longer future research. Implementation is governed by `docs/OSS_EXECUTION_INTEGRATION_PLAN_2026-09-24.md`.

Target backends are Playwright MCP (BROWSER), Cua Driver bounded mode (PC_CONTROL), Datalayer Jupyter MCP (COMPUTE), and a reviewed guarded DuckDB MCP (DATA fast path). The existing Foundation authority/Guard/MCP boundaries remain canonical; no duplicate desktop, notebook, SQL or browser engine is to be built.

The execution-plane convergence ledger is closed on measured M1 evidence. P1 observational BROWSER (Playwright MCP), P3 COMPUTE (Datalayer Jupyter MCP), and P4 DATA (guarded DuckDB MCP) are production-promoted through the existing generic ToolHive/MCP boundary with exact host-selected grants. P2 PC_CONTROL remains explicitly BLOCKED because the reviewed Cua Driver 0.28.3 macOS release artifact fails upstream's own strict signature gate; Foundation has not bypassed signing/TCC, substituted a fallback desktop engine, or exposed PC_CONTROL to the Agent. Final rebooted-runner regression and real-host probes passed on 2026-09-25; see the canonical execution plan and CURRENT_STATE for run IDs and exact authority limits.

## 2026-09-27 VISION production completion

The earlier roadmap description of generic image analysis as a planned extension is superseded for current image/VISION status. The generic capability is implemented and production-accepted through the existing owner-scoped attachment, routing, execution and Agent boundaries. Physical LibreChat actual-pixel E2E passed through normal `foundation-auto` with Agent-selected VISION; explicit `foundation-vision` remains diagnostic/verification only. Final post-security-fix regression is `1067 passed / 10 skipped`, runtime-drift contract `3 passed`. PDF, Office, audio and other non-image media remain separate future capability gates.

## Post-completion roadmap — recorded 2026-09-27

The current M1 reconstruction program has reached the nine `END_GOAL.md` program-completion gates. The evidence ledger and accepted residual classification are recorded in `PROGRAM_COMPLETION_2026-09-27.md`.

Post-completion work is not one new monolithic implementation phase.

It is divided into independently promotable directions:

1. preserve a Thin Foundation and continue replacing generic custom mechanisms with mature replaceable OSS where evidence justifies it;
2. build Project World Model / development intelligence connecting canon, architecture, source symbols/configuration, dependencies, tests and runtime evidence;
3. define and eventually prove GitHub-only clean-machine reconstruction in addition to ordinary backup/restore;
4. expand bounded external capabilities such as GitHub and useful MCP/API service integrations without inheriting another product's authority model;
5. evaluate a Commander-level replaceable PC_CONTROL backend after an explicit authority/backend decision, without using a fallback merely to green the current Cua blocker;
6. prove cross-capability Agent composition on representative multi-tool tasks;
7. establish answer-quality regression against a GPT-class external baseline and an evidence-based ChatGPT Plus exit criterion;
8. evolve toward the separately canonical autonomous software-operations lifecycle only after its convergence requirements are satisfied.

<!-- DEVELOPMENT_EXPLAINABILITY_GATE_V1 -->

### Development Intelligence explainability gate

Post-completion direction 2 is now the immediate development prerequisite
before further Foundation self-repair or autonomous-development expansion.

The required progression is:

`END_GOAL / canonical intent`
-> `requirements / invariants / decisions`
-> `architecture / subsystem / authority`
-> `module / file`
-> `class / protocol`
-> `function / method`
-> `constant / configuration / state / variable`
-> `source relationships`
-> `tests`
-> `runtime evidence`

The relationship must be queryable in both directions.

Do not create hand-maintained catalogs for all source elements. Reproducible
source-derived inventory and the existing Development Intelligence boundary
own mechanical source facts. Canon owns intent and accepted semantics.

Resume practical self-repair only after the repository-wide explainability
baseline defined in `FUTURE_POST_COMPLETION_ARCHITECTURE.md` is established
and unresolved implementation-driving conflicts are zero.

Detailed architecture and promotion constraints are recorded in `FUTURE_POST_COMPLETION_ARCHITECTURE.md`.

The existing `FUTURE_AUTONOMOUS_SOFTWARE_OPERATIONS.md` remains authoritative for Observe -> Detect -> Propose -> Plan -> Authorize -> Execute -> Verify -> Record -> Reflect -> Stop/Wait and its NO_CHANGE / WAIT / NEEDS_HUMAN / BLOCKED convergence semantics.

PC_CONTROL, FILES-write authority, non-image media and portability/productization residuals do not reopen the completed current M1 reconstruction program merely because they remain future or intentionally unavailable.

## External development UI / Canonical-First development policy — historical 2026-10 probe

> **Current authority (2026-11-12):** `SYSTEM_ROLE_BOUNDARIES.md` and `END_GOAL.md` supersede the dated Kandev/v3 development-owner claims below. GitHub owns AI-Foundation Issue/PR/CI identity; Foundation host/Guard/Harness owns admitted execution and verification. The installed local9B worker handles admitted finite tasks; DSH→OpenCode and Codex OSS are optional frontends. Kandev/Paseo remains optional legacy tooling, **not** a mandatory owner or default developer path. Retain the historical probe results below as evidence, not as live instructions or a production grant.

External development tooling must remain outside Foundation runtime and replaceable. Kandev is the current installed probe candidate, not yet an accepted development standard. Its detailed evidence, safety gates, cost invariants, and adoption semantics are canonicalized in `docs/FOUNDATION_DEVELOPMENT_UI_DECISION_2026-10-01.md`.

The cross-project process principle is tool-independent: a development UI/agent must discover and obey the target repository's explicit source-of-truth/canonical hierarchy, must not infer missing authority, and must stop for human resolution when authority is absent, stale, contradictory, or ambiguous. Tool prompts/workflows are process controls, never a second semantic Canon.

For AI Foundation specifically, Kandev adoption remains blocked until the disposable-repository acceptance probe closes free/existing-entitlement agent execution, no-silent-paid-fallback, human gates, Git commit/push/PR controls, worktree-external write behavior, and recovery/removability. Foundation itself must not be exposed to Kandev implementation writes before those gates pass. Remote Desktop Commander and GPT/ChatGPT-to-Kandev connectivity are explicitly non-required conveniences and must not become dependencies.


<!-- KANDEV_V3_ROADMAP_UPDATE_2026_10_02 -->

### External development UI — v3 controlled-development transition 2026-10-02

This subsection supersedes the earlier roadmap statement that Foundation must not yet be exposed to Kandev implementation writes.

The disposable-agent probe established sufficient evidence to move Kandev into bounded controlled-development use while preserving the detailed limitations in `docs/FOUNDATION_DEVELOPMENT_UI_DECISION_2026-10-01.md`.

The active development workflow is now `Canonical Adaptive Development v3`; the v2 test workflow is retired. v3 uses the `Adaptive Free Route` Dynamic profile rather than a fixed provider profile.

Routing is deliberately two-layered:

1. v3 CLASSIFY selects capability requirements from task complexity, risk, current health, free/existing-entitlement availability, quota and useful review independence. No provider owns a permanent design/implementation/review role.
2. Kandev Dynamic Agent Routing provides bounded availability/failure routing across the currently accepted Kiro, Copilot, Antigravity and Codex profiles. Its current Kiro -> Copilot -> Antigravity -> Astra ordering is bootstrap/failure ordering only, not semantic ranking.

Routine local development is intentionally more autonomous than during the probe. The accepted concrete profiles use `auto_approve=true` because the installed Kandev version exposes a coarse profile permission switch rather than the desired fine-grained local-vs-external ACL. This permission relaxation MUST NOT be interpreted as permission for secret/credential access, payment/new paid routes, irreversible operations, or external effects. Those remain v3 Human-Gate boundaries.

No silent paid fallback is permitted. Mid-turn ambiguity after tool activity or repository mutation remains fail-closed until checkpoint/reconciliation.

This development-tooling transition does not change Foundation runtime authority, does not make Kandev a runtime dependency, and does not satisfy or bypass Development Intelligence / Explainability / Self-Repair promotion gates.


### Canonical remote preflight requirement — 2026-10-02

The active v3 development workflow must resolve repository authority before substantive work and after handoff/reconciliation. Where the repository's explicit source relationship identifies a remote as Canon, the workflow must fetch/read that authority and compare it with the current worktree base/HEAD/dirty state. It must not silently treat a stale task snapshot as current Canon, and it must not destructively synchronize divergent work. Unreachable or ambiguous authority fails closed. This rule is repository-generic; GitHub is used for AI Foundation because AI Foundation itself declares GitHub canonical, not because v3 globally assumes GitHub for every project.


<!-- HUMAN_BY_EXCEPTION_AUTONOMY_TARGET_2026_10_02 -->

### Human-by-exception development autonomy target — 2026-10-02

The post-Explainability autonomous-software direction now explicitly targets **human-by-exception orchestration**.

Foundation must eventually resolve routine worker questions itself by combining current repository-declared authority, remote/current state, canonical sequence/gates, verified prior evidence, deterministic tests and bounded execution authority. If those inputs uniquely determine the next action, Foundation should select and dispatch that action rather than forwarding an unnecessary choice to the human.

Human intervention remains required for genuinely unresolved semantic/product-policy choices, authority expansion, secrets/credentials, new payment/budget authority, irreversible actions, and unauthorized external effects. Uncertainty that cannot be resolved from authoritative evidence converges to NEEDS_HUMAN/BLOCKED/WAIT rather than inference.

This target is downstream of the current Development Intelligence / Explainability Closure. It does not bypass DI04-DI09 or Self-Repair gates; those capabilities provide the traceability needed for Foundation to justify why a worker question can safely be answered without a human.

Detailed semantics and promotion scenarios are canonicalized in `FUTURE_AUTONOMOUS_SOFTWARE_OPERATIONS.md`.


<!-- EXTERNAL_EXECUTOR_RUNTIME_CONTROL_ROADMAP_2026_10_02 -->

### External executor runtime-control lifecycle rule — 2026-10-02

External development executors must treat mode/model/config changes as lifecycle-bound controls. They are applied only at a verified idle/new-session/fresh-start/reconciled-handoff boundary, never during an active prompt, turn, tool call, or ambiguous partial result. A busy-session switch refusal is not evidence of quota/model/provider failure. Partial work must be checkpointed and reconciled before any provider handoff; runtime-control failure alone must not discard work or trigger silent fallback.

This is a tool-independent control-plane invariant. Detailed semantics are canonicalized in `FUTURE_AUTONOMOUS_SOFTWARE_OPERATIONS.md`; Kandev remains a replaceable external development tool rather than runtime authority.


<!-- AGENT_INDEPENDENT_SUPERVISOR_ROADMAP_2026_10_02 -->

### Agent-independent supervisor — 2026-10-02

Human-by-exception orchestration requires an external supervisor that can detect and recover a stalled worker without relying on that same worker. Supervision must use current execution/generation ownership plus meaningful-activity evidence, capture bounded diagnostics before mutation, re-check activity immediately before recovery, preserve and reconcile partial effects, and permit provider handoff only after safe settlement. Verification subprocess hangs are isolated and reduced rather than allowed to accumulate duplicate runs. Recovery is bounded; repeated unresolved stalls become explicit BLOCKED/NEEDS_HUMAN instead of infinite retries.

This requirement is downstream-compatible with the existing Development Intelligence / Explainability gates and does not authorize secrets, payment, irreversible/external effects, merge, deploy or other authority expansion. Detailed semantics are canonicalized in `FUTURE_AUTONOMOUS_SOFTWARE_OPERATIONS.md`.

### Cross-capability Agent composition closure — 2026-10-07

Post-completion direction 6 is CLOSED for the representative bounded multi-tool gate. Existing `AutoCapabilityAgent` + capability execution proved deterministic FILES -> DATA composition inside one objective, tool-specific authority separation, observed-result transfer, and no grant carry-over into a later scope-free objective. No new composer/router/scheduler was introduced. Acceptance: focused 45 passed; full Foundation regression 1221 passed / 10 skipped / 0 failed.

- 2026-10-07 local-compute lifecycle: backend-neutral OpenAI-compatible local endpoint support is accepted as a thin host-authorized adapter alongside M1 llama-swap. Main-PC registration remains an environment acceptance step requiring real endpoint/model readback, not a new architecture phase. M1 stale Qwen2.5-3B cache was retired; active CHAT/CODE/CODE_REVIEW/VISION roles remain Qwen3.5-9B / Ornith-1.5-9B / Granite-4.2-8B / Qwen2.5-VL-3B. CHAT+VISION consolidation onto Qwen3.5-9B is probe-only until measured.
