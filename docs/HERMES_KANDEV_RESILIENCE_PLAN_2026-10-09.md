# Hermes + Kandev mutual-resilience experiment — Foundation boundary

Status: PLAN / NO PRODUCTION INTEGRATION (2026-10-09)

Kandev Supervisor ADR-012 (`~/Develop/KandevManaged/Kandev-Supervisor/docs/decisions/ADR-012-independent-agent-resilience-probe.md`) owns the executable development-plane roadmap. This Foundation-side record owns the non-negotiable trust boundary and is not a new routing implementation.

1. Foundation retains sole Canon, policy/approval, zero-additional-cost eligibility, effect idempotency/reconciliation and Evidence authority. Hermes may read allowed context and request narrowly scoped Bridge actions only after current Foundation preflight. Unavailable Foundation means fail closed for effects.
2. Kandev remains the sole normal repository writer and provider selector for development. Hermes is an optional independently restartable read-only observer, conversational/skill/cron candidate and recovery assistant, not a parallel Kandev controller. A lightweight deterministic launchd watchdog checks both service processes and may restart them only with safe health/readback; it cannot rerun an uncertain task.
3. Hermes inference fallback is separate from Kandev's coding-agent fallback. No unverified paid model, new token exposure, automatic credit purchase, unrestricted shell or direct private Kandev database access.
4. Do not build a duplicate Foundation memory store, general-purpose cron scheduler, second LLM ranker, chat frontend or competing code-execution path while testing standard Hermes/Kandev functionality. This is a stop-work decision for **unstarted overlapping proposals**, not authorization to delete current Foundation capabilities or independent Individual Brain experiments without separate scope review.
5. Acceptance: isolated M1 deployment; read-only MCP and evidence correlation; kill/restart Hermes and Kandev separately; simulate provider quota, stuck task, duplicate dispatch and restart; prove no unapproved effects, no lost worktree, no duplicated effect, no paid fallback and complete task evidence. Compare actual removed code/maintenance burden and user-facing stability. Delete redundant live code only after shadow gate, full tests and guarded rollback. If unmet, uninstall Hermes experiment.
6. Shared M1 power/network failure is not covered by process redundancy; host-level failover requires an independently powered second host and is out of initial scope.

Existing uncommitted Foundation work is intentionally untouched. No installation, migration or deletion is asserted by this document.

## Detailed delivery contract (2026-10-09)

The authoritative P0-P7 delivery and deletion gates are maintained in the Kandev Supervisor canonical repository at `docs/AGENT_RESILIENCE_DELIVERY_PLAN_2026-10-09.md` (source commit `0e2f63b`). Foundation owns only policy and evidence acceptance, not a second development task router. Execution order: P0 baseline/native incident; P1 durable task handoff identity using existing stores; P2 Kandev-native failover and measured reduction; P3 isolated Hermes security/cost gate; P4 independent process fault tests; P5 mobile/skills/LibreChat comparison; P6 optional Windows manual cold standby; P7 guarded deletion, seven-day probation and final operational metrics. Do not treat planning as deployment, and do not modify existing uncommitted Foundation research or Individual Brain work. Foundation fail-closed authority is a prerequisite for every effectful phase.
