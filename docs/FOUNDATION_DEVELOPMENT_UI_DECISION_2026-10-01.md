# Foundation Development UI Decision — 2026-10-01

Status: ACTIVE DECISION / LOCAL PROBE IN PROGRESS / ADOPTION NOT YET VERIFIED

## Purpose

This document records the current canonical decision for the external development UI used to develop AI Foundation.

It is intentionally separate from existing runtime Canon. It does not modify or supersede runtime architecture, AgentPort, Guard, authority, Canon, Explainability, Safe Change, or verification semantics.

## Decision

Kandev is the current preferred candidate for the AI Foundation development UI and external coding-agent orchestration layer.

Kandev is NOT part of AI Foundation runtime.

The dependency direction is one-way:

- Kandev may operate on an AI Foundation development worktree/repository.
- AI Foundation runtime MUST NOT depend on Kandev.
- Removal, replacement, failure, or abandonment of Kandev MUST NOT prevent AI Foundation runtime from operating.
- Kandev MUST NOT become semantic authority.
- AI Foundation Canon remains the sole semantic authority for AI Foundation.

The current decision is PROBE-first. Kandev MUST NOT be treated as production-verified or permanently adopted until the final local acceptance probe passes.

## Current scope

For now, Kandev adoption is being proven only against AI Foundation development.

The underlying development policy should remain tool-independent and reusable across repositories: discover and obey each repository's own explicit canonical/source-of-truth hierarchy, fail closed when authority is missing or conflicting, and never turn Kandev configuration into a second semantic authority. This does not make Kandev a personal desktop automation platform, Foundation runtime component, or cross-project authority plane.

The intended user-facing role is to replace routine direct CUI interaction during AI Foundation development with a graphical development workspace.

Expected development surfaces include:

- task/workflow UI;
- coding-agent sessions;
- repository/worktree access;
- file tree and editor;
- terminal access;
- Git diff/change review;
- planning, implementation, review, and verification stages;
- explicit human approval gates.

Direct CLI use remains an emergency, audit, deterministic-verification, or recovery path rather than the normal user interface.

## External agent boundary

External coding agents remain development tools outside AI Foundation runtime.

Candidate agents currently include:

- Codex;
- GitHub Copilot;
- Kiro;
- OpenCode;
- Gemini CLI.

Kandev may launch or manage these agents through supported native CLI, ACP, passthrough, or managed-runtime mechanisms, but this does not transfer AI Foundation authority to Kandev or to an agent.

Existing installed CLI tools MUST NOT be removed before the Kandev migration is proven. During migration they are retained as a rollback/recovery path. After successful migration, a CLI may be removed only if it is proven unnecessary to Kandev and unnecessary for recovery/audit use.

## Cost invariant

Target incremental development cost is JPY 0.

The default development configuration MUST prefer existing subscriptions/entitlements and genuinely free account/model quotas.

New metered API billing MUST NOT be introduced merely to operate Kandev or an external coding agent.

For OpenAI/Codex, ChatGPT account authentication is preferred over an OPENAI_API_KEY billing path when supported by the selected runtime.

The intended steady-state behavior when a free quota is exhausted is fail/stop/wait or deliberate selection of another approved free route. Exhausting a free quota MUST NOT silently authorize a metered API route.

Cloud executors or paid hosted execution MUST NOT become the default merely for convenience.

Any later paid dependency requires a separate explicit decision.

## Original-code invariant

Target original integration code for the development UI is zero.

Prefer Kandev's existing Desktop application, profiles, workflows, permissions, worktrees, agent support, and configuration.

Do not create a custom Foundation UI, custom Kandev fork, custom adapter, custom launcher, custom billing router, or custom orchestration service merely to make Kandev fit.

Configuration and declarative workflow/profile setup are permitted when they do not create a second semantic authority.

If a mandatory Foundation safety requirement cannot be met without material custom integration code, the preferred response is to reject/reconsider Kandev rather than silently grow a new maintenance surface.

## Canon rule

Kandev prompts, workflow descriptions, task documents, plans, agent output, comments, filenames, tests, runtime observations, and model output are NOT Canon.

Kandev workflow prompts may instruct an agent to load and obey the current AI Foundation Canon, but MUST NOT copy or restate Canon in a way that becomes an independently maintained semantic specification.

The relationship is:

Kandev workflow instruction -> load current AI Foundation Canon -> act only within explicitly authorized development scope.

Existing fail-closed and no-semantic-inference rules remain unchanged.

Missing, malformed, stale, contradictory, or unresolved canonical meaning MUST NOT be repaired by agent guesswork.

## Human-control invariant

Initial Foundation development workflow MUST be conservative and manually gated.

Preferred sequence:

1. DESIGN
2. HUMAN GATE
3. IMPLEMENT
4. HUMAN GATE
5. REVIEW
6. HUMAN GATE
7. VERIFY
8. HUMAN GATE / READY

Automatic progression across authority-sensitive stages is not assumed safe.

Auto-approve-all MUST remain disabled.

Kandev's standard workflows MUST NOT be adopted unchanged if they automatically commit, push, create pull requests, or otherwise violate Foundation development controls.

## Git invariant

During the initial adoption/probe:

- automatic commit is prohibited;
- automatic push is prohibited;
- automatic PR creation is prohibited;
- agent-initiated merge is prohibited;
- destructive Git recovery is prohibited;
- human review of changes is required before accepting repository state.

A prompt saying "do not push" is not considered a sufficient technical control by itself.

Worktrees are useful change-isolation boundaries but MUST NOT be treated as filesystem security sandboxes.

## Local authority and filesystem boundary

The preferred initial executor is local/worktree because it minimizes setup, preserves existing local agent authentication, and best matches the zero-cost/zero-custom-code objective.

However, a local process may inherit host filesystem and shell capabilities. Kandev worktree isolation does not prove OS-level containment.

Therefore:

- local/worktree is a candidate execution mode, not proof of containment;
- agent permission behavior must be tested;
- write outside the intended worktree must be adversarially tested;
- commit and push behavior must be adversarially tested;
- sandboxed/container execution remains a fallback option if the local path fails safety acceptance.

Docker/container execution is not required by this decision and MUST NOT be added merely for architectural neatness. It should be introduced only if the final safety probe demonstrates a concrete need.

## Verification authority

Kandev status is not verification authority.

Repository tests, canonical acceptance criteria, Git state, and existing Foundation verification mechanisms remain authoritative for implementation acceptance.

An agent or Kandev reporting PASS does not override a failing repository test, dirty/unexpected Git state, Canon conflict, or missing evidence.

Deterministic repository verification should remain deterministic where possible. Do not replace an existing exact test with model judgment merely because the UI can run an agent.

## Concurrency and quota policy

Initial agent concurrency is one.

Parallel multi-agent execution MUST NOT be enabled by default during the adoption period because it can multiply quota consumption, complicate evidence attribution, and widen concurrent-write risk.

Multiple agents may still be used sequentially for independent design, implementation, review, or challenge roles.

## Installation policy

Installation is the final test stage, not the start of evaluation.

Before installation, desk research must close all issues that can reasonably be decided without touching the host.

The accepted installation path is the official stable Kandev Homebrew distribution for Apple Silicon/macOS. The target M1 probe installed Kandev v0.96.0 from `kdlbs/kandev/kandev` successfully.

Do not build a custom installer when the official distribution is sufficient.

Do not use nightly builds for the Foundation default development environment.

## Final local acceptance probe

Kandev MUST remain provisional until the local M1 acceptance probe verifies at minimum:

1. official stable installation succeeds on the target M1 host;
2. no new paid Kandev requirement is introduced;
3. existing/free agent authentication can be used without mandatory metered API billing;
4. Codex operates through the selected ChatGPT/free-or-existing-entitlement route;
5. GitHub Copilot operates through the selected free-or-existing-entitlement route;
6. Kiro operates through the selected free-or-existing-entitlement route;
7. Gemini operates through the selected free route when enabled;
8. OpenCode can operate through an approved free route and does not reproduce the previously observed unusable/hanging execution path;
9. existing CLI installations remain recoverable during migration;
10. Plan/design operation can be demonstrated without unintended repository mutation;
11. implementation changes remain isolated to the intended development worktree/scope;
12. worktree-external write behavior is explicitly adversarially tested;
13. automatic commit does not occur;
14. automatic push does not occur;
15. automatic PR creation does not occur;
16. explicit dangerous requests to commit/push/out-of-scope-write are tested rather than assumed safe;
17. human gates remain effective;
18. automatic permission approval remains disabled;
19. concurrent-agent execution remains disabled initially;
20. no silent fallback to a metered API/provider occurs;
21. repository tests and Git state remain independently inspectable;
22. Kandev can be removed without creating an AI Foundation runtime dependency.

The probe MUST use a disposable repository/task before AI Foundation is exposed to implementation writes.

Only after the disposable probe passes may AI Foundation be registered for controlled development use.

## Adoption result semantics

Possible results are:

- ADOPT: all mandatory safety/cost/control gates pass.
- ADOPT WITH EXPLICIT LIMITATION: only non-critical limitations remain and are canonically recorded.
- REJECT: a mandatory invariant requires unsafe behavior, new paid dependency, unacceptable custom integration, uncontrolled repository mutation, or unbounded authority.

Do not convert a failed mandatory gate into a prompt-only workaround.

## Current status

As of 2026-10-01, the local M1 probe is in progress.

Verified on the target host:

- host is Apple Silicon arm64 / macOS 26.6.2;
- official stable Homebrew installation succeeded with Kandev v0.96.0 at `/opt/homebrew/bin/kandev`;
- Kandev state/database is external to the Foundation repository under `~/.kandev`;
- a disposable repository `~/Develop/kandev-probe` was created for acceptance testing before Foundation exposure;
- the first launch revealed that the default server bind included non-loopback interfaces; the process was stopped before continuing the probe;
- `server.host: 127.0.0.1` was then set in `~/.kandev/config.yaml` with mode 0600 and runtime readback confirmed the listener only on `127.0.0.1:38429`;
- Kandev's feature readback reported authentication disabled, which is acceptable only together with the verified loopback-only bind for this single-user local probe;
- initial Kandev agent inventory created Codex, Gemini, Copilot, and Kiro profiles with `auto_approve=false` and `auto_fallback=false`;
- Codex was reported by Kandev as subscription billing; Gemini, Copilot, and Kiro provider/auth status is not yet accepted and no API key has been added to make them pass;
- no new metered API key or paid execution route was configured;
- AI Foundation has NOT yet been registered in Kandev and the disposable repository remains the required test target;
- existing CLI development paths remain intact.

Still unverified and therefore blocking adoption:

- actual free/existing-entitlement execution for each intended agent;
- OpenCode availability and the previously observed hang path;
- common Canonical-First workflow behavior;
- commit/push/PR suppression under adversarial requests;
- worktree-external write behavior;
- human-gate behavior during real task execution;
- proof that no silent metered fallback occurs;
- final removal/recovery behavior.

Remote Desktop Commander may be used as a temporary low-frequency setup/probe aid when already available, but it is NOT a dependency of Kandev, AI Foundation, the Canonical-First development policy, or future GPT/ChatGPT connectivity. Kandev acceptance MUST succeed without requiring Commander to remain available. GPT/ChatGPT-to-Kandev integration is optional future convenience only and MUST NOT be an adoption prerequisite.

Therefore the current state is:

Kandev = INSTALLED PROBE CANDIDATE, LOCAL ACCEPTANCE IN PROGRESS, NOT YET VERIFIED DEVELOPMENT STANDARD.


<!-- KANDEV_V3_ADAPTIVE_ROUTING_2026_10_02 -->

## Kandev v3 adaptive-routing closure — 2026-10-02

This section supersedes the earlier same-file probe-status statements where they conflict with the verified current state. Historical probe evidence remains retained above.

Verified target-host state:

- AI Foundation is now registered in Kandev for controlled development use.
- Development Workspace uses `Canonical Adaptive Development v3` as its sole active development workflow; the test-era `Canonical Development v2` workflow was retired.
- Kandev v0.96.0 Dynamic Agent Routing is enabled through the launchd service environment using `KANDEV_FEATURES_DYNAMIC_AGENT_ROUTING=true`; runtime feature readback confirmed `dynamicAgentRouting=true`.
- The v3 workflow default profile is the Dynamic profile `Adaptive Free Route`, not a Codex/Astra profile.
- The accepted availability candidates are Kiro Auto, GitHub Copilot Auto, Google Antigravity Gemini 3.8 Flash High, and Codex 6 Astra. OpenCode and the legacy Gemini route remain excluded from this accepted route; other discovered agents are not admitted merely because capability probing reports them healthy.
- The Dynamic route is an availability/failure-routing layer, not semantic task authority and not a claim that Kandev natively chooses the best model for task complexity. v3 CLASSIFY owns capability/complexity/quota-fit selection; Dynamic Routing owns bounded availability fallback. Agent roles are therefore not canonically fixed to Kiro, Astra, or any other provider.
- Current availability-chain ordering is Kiro -> Copilot -> Antigravity -> Astra. This ordering is a bootstrap/failure route, not a permanent role assignment.
- Hard availability failures such as exhausted quota/auth/credit/model-unavailable are configured to skip to the next accepted candidate until the terminal candidate; transient failures receive one bounded retry before skip. Ambiguous failures after partial output/tool activity/change MUST NOT be treated as safe silent handoff: checkpoint/reconciliation remains required before continuation.
- No new metered API key, paid-provider fallback, automatic credit purchase, or paid top-up route was added.
- The four accepted concrete profiles currently use `auto_approve=true` to remove repetitive approval prompts for ordinary local development operations. This supersedes the earlier probe requirement that automatic permission approval remain disabled.
- `auto_approve=true` is not authority to cross protected boundaries. v3 still requires Human Gate for unresolved canonical/product-policy decisions, secret/credential access, payment or new paid routes, irreversible actions, and external effects such as push, PR, deploy, publication, or remote-system mutation unless separately and explicitly authorized.
- Kandev v0.96.0 does not provide the required fine-grained profile ACL to express "auto-approve ordinary local edits/tests but independently prompt for push" at the profile layer. Therefore the local-autonomy setting and the canonical Human Gate boundary are intentionally separate controls.
- Existing running agent instances may retain the permission snapshot from session start; profile changes are authoritative for subsequent sessions/handoffs.
- Kandev remains execution/development tooling. Repository Canon, deterministic tests, Git state, runtime evidence, and Foundation verification remain acceptance authority.

The previous statement that Foundation had not yet been registered, the previous statement that Antigravity was not locally evaluated, and the previous blanket requirement for `auto_approve=false` are stale historical probe state and MUST NOT be used as current operational guidance.

Kandev adoption is accepted only within these bounded development-tooling semantics. This does not promote Kandev into Foundation runtime authority or a Foundation runtime Software Engineering Executor.


### Remote canonical-authority preflight — 2026-10-02

Canonical Adaptive Development v3 MUST perform a source-of-truth preflight at task start and again after agent handoff/reconciliation.

The rule is repository-generic:

- discover the repository's explicit source-relationship / source-of-truth declaration instead of assuming that GitHub, a local checkout, or a filename is authoritative;
- when that declaration names a remote repository/ref as current Canon, fetch/read that remote authority before substantive work and compare the authoritative remote ref/commit with the task worktree base, HEAD, and dirty state;
- a remote fetch/read used to establish authority is not an external mutation and does not grant push/PR/deploy authority;
- never describe an unfetched, stale, or diverged local Canon as the latest remote Canon;
- do not destructively reset, rebase, overwrite, or discard existing task work merely to match remote. If safe reconciliation is not uniquely established by repository rules and Git state, preserve the work, checkpoint the divergence, and reconcile before continuing;
- if remote authority cannot be reached, the authority declaration cannot be established, or remote/local state is materially contradictory, report that state explicitly and fail closed rather than filling the gap by inference;
- if a repository explicitly declares local or another non-GitHub authority, do not override that declaration by globally preferring GitHub.

For AI Foundation, the existing source relationship declares GitHub as the current canonical source, so a Kandev task must verify the current GitHub authority rather than relying only on the worktree snapshot created when the task began.

A 2026-10-02 Kandev continuation report demonstrated why this gate is required: the task worktree reported HEAD `f7cb612` while later canonical documentation commits already existed remotely. The worktree evidence remains valid for the code snapshot it tested, but it is not evidence that the task had consumed the latest canonical documentation.
