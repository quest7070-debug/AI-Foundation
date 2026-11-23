# AI control-plane boundary — 2026-10-06

Status: **HISTORICAL DECISION (2026-10-06); development ownership superseded 2026-11-12**.

Current execution ownership is `docs/SYSTEM_ROLE_BOUNDARIES.md`, not the
Kandev-owned description below. Foundation host/Guard/Harness owns admitted
roles/scope and GitHub owns task/PR/CI identity; Kandev is an optional legacy
path, not a prerequisite. This retains the dated decision as provenance, not
current operating instructions.

## Decision

AI Foundation is the personal-AI runtime/control plane. It preserves Canon/context, policy/authority, memory/history, tools/capabilities, provider-neutral routing, verification and evidence across replaceable intelligence suppliers.

Kandev is the software-development plane. It owns development task/workflow/session/worktree/agent execution, bounded recovery, review and development evidence. Foundation must not recreate Kandev's development lifecycle, and Kandev self-improvement must not become a general Foundation model/provider research plane.

The M1 host is a control node, not the source of model intelligence. Foundation and Kandev must remain portable so a future host replacement changes deployment/runtime placement rather than product authority or architecture.

## Intelligence supply

Cloud APIs, free/existing-entitlement APIs and local models are replaceable intelligence supplies behind Foundation-owned policy and routing boundaries. Local inference remains valuable for privacy, offline operation, bounded zero-marginal-cost work and resilient fallback, but maximizing local model size or benchmark performance is not a product objective.

Existing provider registry, ComputeRouter, LocalComputePort/registry, health/recovery and llama-swap boundaries remain KEEP where they provide provider-neutral routing, fail-closed authority, fallback or observable runtime truth. This decision does not authorize deleting proven routing/fallback code merely because cloud intelligence is stronger.

## Discovery policy

Foundation does not continuously chase every new model, provider or local runtime.

A model/provider/runtime evaluation is justified only by a concrete trigger such as:
- an observed capability or quality gap in a current route;
- current provider degradation, quota loss, retirement or material reliability change;
- a candidate with credible evidence of materially better zero-additional-cost or explicitly approved cost/performance;
- a privacy/offline/latency/tool-capability requirement current routes cannot satisfy;
- a backend/runtime change that materially reduces maintenance or custom code while preserving authority.

Discovery creates only a CANDIDATE. Promotion requires authoritative/current source evidence, cost/entitlement verification, isolated Probe/Eval where applicable, regression/non-trigger evidence, rollback and normal Canon reconciliation. No discovery process may directly mutate production routing, credentials, model artifacts or authority.

Magnitude remains HOLD under this rule. It is not worth forcing a new model download merely to maximize M1 inference performance. Re-evaluate only when an existing justified artifact can be consumed, or a concrete Foundation gap makes the backend materially relevant.

## Kandev learning boundary

Kandev daily self-improvement is development-plane scoped: Kandev native capabilities, coding agents, coding tools, development workflow/management, development safety/evaluation, relevant OSS and open standards.

It may track a model/provider only when that item is part of a coding-agent execution route or directly changes development-task completion. General LLM/model/provider/local-runtime discovery belongs to Foundation's gap-triggered evaluation policy, not Kandev's daily learning.

## Hardware independence

M1 is the current always-on host/control node. Hardware-specific acceleration is an implementation detail behind replaceable runtime boundaries. A future M-series or other supported host should require deployment/runtime migration and re-acceptance, not a redesign of Canon, Foundation authority or Kandev lifecycle.

## Supersession

This decision narrows prior wording that could be read as requiring continuous local-LLM performance pursuit or general proactive model discovery. It does not supersede historical audit requirements to inventory and reconcile providers/models that already exist in executable or canonical state.
