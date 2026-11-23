# Opportunity Findings — 2026-09-21 to 2026-09-22

Status: FUTURE / RESEARCH NOTES / NON-CURRENT REQUIREMENT

## Purpose

Record recent external opportunity-discovery findings that may matter to AI Foundation later, without promoting them into current requirements, architecture, dependencies, or implementation work.

This document is deliberately a holding area. Every item must be revalidated against current upstream sources, AI Foundation canon, implementation, dependency boundaries, and real-device/runtime evidence before adoption.

## Guardrails

- Do not change the current AI Foundation concept merely to absorb an external idea.
- Prefer the smallest missing principle over importing an entire project.
- Existing Foundation behavior and canonical boundaries win over these notes.
- No item here authorizes installation, implementation, routing changes, model replacement, or provider addition.
- External projects/services may change; re-check maintenance, licensing, security, pricing, API terms, and current behavior at promotion time.
- If current Foundation already satisfies the useful part, classify it as evidence/validation rather than adding another layer.

## 1. Git / coding-agent pre-execution attack surface

### Finding

Recent coding-agent security research showed that repository-local Git configuration and other lower-level development-tool behavior can become an execution path before or outside the model's intended action boundary. A copied repository containing its own `.git` state is materially different from a clean `git clone`.

### Reusable principle

Do not treat "the Agent did not request this action" as proof that no action can occur. Tools below the Agent — Git, hooks, filters, diff helpers, credential helpers, package tooling, shells, runners, IDE integrations, and similar preparation paths — belong inside the execution threat model.

### Fit with current Foundation

This is primarily **external evidence supporting an existing boundary**, not a new product feature.

Current Foundation already has host-bound READ / COMPUTE / EFFECT capability concepts, ToolHive containment, Guard-mediated effects, and fail-closed authority. Future execution-boundary work should explicitly include pre-agent and sub-tool execution paths rather than protecting only model-visible tools.

### Future verification candidate

When coding/developer execution is hardened further, include adversarial tests for:

- repository-local Git execution-affecting configuration;
- copied/restored repositories that preserve `.git`;
- persistent/self-hosted runner workspace contamination between jobs;
- inherited environment/process state;
- hooks, filters, external diff/merge helpers and equivalent indirect executors;
- proof that sanitization itself cannot silently broaden authority.

Classification: **existing architecture validated / future attack-test input**.

## 2. Developer must not own model mutation or production model replacement

### Finding

Recent agent experiments demonstrated an important failure mode: when an agent is asked to improve an AI application and has broad enough access, it may treat the underlying model itself as a repair target rather than limiting itself to application code/configuration.

### Reusable principle

The object being used to reason should not automatically become an ordinary writable repair target.

For AI Foundation, model files, model registration, training/fine-tuning facilities, and production model replacement are separate authority from normal Developer code work.

### Fit with current Foundation

**Already substantially present in canon.** The current audit handoff explicitly requires "no Developer model-control authority." Therefore this finding does not justify a new subsystem.

It is useful as an external reason to keep that boundary and to test it.

### Future verification candidate

Verify that a normal Developer task cannot, without separately granted authority:

- overwrite model weights;
- modify protected production model artifacts;
- silently register/replace the active production model;
- invoke training/fine-tuning merely as an alternative way to satisfy a coding task;
- mutate routing/model-role policy to make its own modified model authoritative.

Classification: **existing requirement reinforced / regression-test candidate**.

## 3. Small local model replacement candidate: MiniCPM5-2B class

### Finding

A new generation of roughly 2B-class local models is reaching capability levels that may make an older 3B default model unnecessary for lightweight routing, classification, short answers, and tool-selection work.

MiniCPM5-2B was identified as one concrete candidate to compare against the current lightweight local-default role.

### Reusable principle

Do not accumulate local models just because a new model is interesting. Treat new small models as **replacement candidates for an existing role**.

The useful metric is not benchmark rank alone. It is useful work per resident memory / load time / latency / energy in Foundation's actual Japanese and tool-routing workload.

### Promotion gate

Before any replacement:

1. Keep the current model available.
2. Run the same representative Foundation workload against both.
3. Measure Japanese quality, routing/classification correctness, tool-call behavior, first-token latency, total latency, RAM, model load behavior, tokens/s, and failure cases.
4. Include simple queries where excessive reasoning is itself a regression.
5. Replace only if the candidate is materially better for the existing role.

Classification: **A/B replacement candidate; no new role**.

## 4. Non-generative semantic decisions for routing

### Finding

Jev/SemIf-style work points to a useful distinction: many AI decisions have a finite answer set and do not inherently require generation of prose or JSON.

Examples inside a Foundation-like system include:

- CHAT vs SEARCH vs DEVELOPER vs another known capability;
- retry vs stop;
- candidate eligible vs ineligible;
- finite policy/routing classifications.

Instead of asking a model to generate an explanation and then parsing it, a system may sometimes score the allowed choices directly.

### Reusable principle

**Use generation for open-ended output; use constrained semantic scoring for finite decisions when it is demonstrably more reliable/efficient.**

This is not permission to replace Guard/Cedar/policy authorization with model probabilities. Security/authority decisions remain deterministic and independently enforced.

### Fit with current Foundation

Potentially a narrow internal optimization of classification/routing, not a new user-facing layer and not a reason to adopt a proprietary API.

It should not be used where the explanation, evidence, uncertainty, or generated artifact is itself the required result.

### Promotion gate

Only consider this if a real profiling result shows routing/classification generation is a meaningful latency/cost/reliability bottleneck. Compare:

- current deterministic/LLM route;
- constrained output;
- direct candidate scoring/logit approach where supported.

Require no semantic regression, especially on Japanese input, SEARCH detection, tool selection, privacy routing, and fallback.

Classification: **future optimization principle / benchmark first**.

## 5. Swarm-style distributed local inference across existing devices

### Finding

SwarmLLM-style browser/WebGPU work explores splitting one model across multiple heterogeneous devices rather than merely routing whole requests to one available machine.

This is different from ordinary provider routing or a local inference fleet: the devices collectively hold/run one model.

### Reusable principle

For local AI, "buy one larger machine" is not the only possible way to increase model capacity. Existing idle memory/compute across devices may become a capacity pool if communication overhead and software support are acceptable.

### Fit with current Foundation

Do **not** merge this into normal Foundation routing now. AI Foundation should continue to see a local inference backend through a replaceable boundary.

If this direction matures, it should appear behind that boundary as an inference backend, not force Foundation to understand model sharding.

### Risks / unknowns

- heterogeneous device support;
- browser/WebGPU limitations;
- network latency and bandwidth;
- privacy of intermediate state between peers;
- model-family restrictions;
- real tokens/s versus a single M1;
- energy cost of keeping several devices active.

Classification: **experimental backend candidate / monitor; not architecture change**.

## 6. Home MCP and externally exposed smart-home capability

### Finding

Smart-home platforms are beginning to expose household state/actions through AI-oriented protocol boundaries such as MCP rather than requiring every assistant to own a bespoke home-automation integration.

### Reusable principle

Where a mature external system owns the device domain, Foundation should call its public capability boundary rather than absorb device ownership.

### Fit with current Foundation

This aligns with the existing OSS-composable/replaceable-boundary direction. It does not justify an Echo-specific Foundation architecture or a new smart-home subsystem.

If/when a supported service is practically available in the user's region/environment, evaluate it as an external MCP capability with Foundation authority, privacy, readback, and failure handling around it.

Classification: **monitor / future external capability; no current implementation**.

## 7. Paper2Agent-style "documentation to verified capability"

### Finding

Paper2Agent-style research turns papers plus code/data/examples into executable tools and validates generated tool behavior against known outputs.

### Reusable principle

Reading documentation is weaker evidence than executing the described method and comparing the result with an expected outcome.

### Fit with current Foundation

For current AI Foundation development this is **mostly already covered by the canonical verification philosophy**: canon -> implementation -> persistence/runtime/API/UI -> tests/live/readback. Adding another framework would create complexity without a clear missing capability.

A future use may exist if Foundation ever needs to convert large collections of external human documentation plus reference code into reusable verified tools automatically.

Classification: **existing method substantially satisfies the useful principle / no action now**.

## 8. Industrial agent example: drawing/specification to physical execution

### Finding

Industrial AI deployments are increasingly moving beyond chat toward converting human engineering artifacts (for example drawings/specifications) into machine-executable operations, with the physical system providing the final execution/readback loop.

### Reusable principle

The valuable pattern is not "add chat to a machine." It is:

```text
human artifact
  -> machine interpretation
  -> bounded executable plan
  -> controlled physical action
  -> readback / verification
```

### Fit with current Foundation

Useful as evidence that bounded Agent -> Action -> Verification patterns are becoming practical outside software. No current Foundation feature gap is established by this example.

Classification: **external pattern to monitor; no adoption**.

## 9. Self-hosted runner lifecycle is part of product reliability

### Finding

GitHub Actions self-hosted runners can become unusable when they fall outside provider-enforced supported versions. This is operational rather than an AI architecture innovation, but it matters because a healthy Foundation can still lose automation when the external execution substrate ages out.

### Reusable principle

External execution dependencies need lifecycle/readiness checks, not only process-health checks.

For future Foundation/Automation integration, "runner is online" should not be treated as sufficient evidence if its version/support state makes future jobs ineligible.

Classification: **operations/dependency lifecycle check; not a new Foundation subsystem**.

## Consolidated priority

### Worth carrying forward

1. **Sub-tool/pre-agent execution belongs inside the execution threat model.**
2. **Keep Developer model-control authority separated; test that boundary.**
3. **Benchmark new small models as replacements, not additions.**
4. **Consider non-generative semantic scoring only for finite routing/classification decisions and only after profiling.**
5. **Monitor distributed local inference as a replaceable backend, not as Foundation architecture.**

### Monitor only

- smart-home MCP capability;
- industrial artifact-to-action patterns;
- self-hosted runner support/lifecycle changes.

### No current action

- Paper2Agent-style framework adoption: current verification philosophy already captures most of the useful principle for Foundation development.

## Relationship to existing future direction

This document complements `docs/future/oss-composable-foundation.md`.

The common rule is unchanged: AI Foundation should own stable capability/policy/safety boundaries and use replaceable implementations behind them. None of these findings should create a tightly coupled dependency or duplicate an already verified Foundation responsibility.

## Promotion rule

Before moving any item from this file into canonical requirements or implementation:

1. Re-check current upstream evidence and maintenance state.
2. Re-read current AI Foundation canon and latest decisions.
3. Prove a concrete missing capability or measurable improvement.
4. Check responsibility overlap and dependency/secret/security impact.
5. Define rollback/removal before integration.
6. Run focused regression, integration/live evidence, and real-device/user-flow checks appropriate to the change.
7. Update canonical docs only after the candidate survives those gates.
