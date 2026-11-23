# Thin Foundation architecture action plan — 2026-09-24

## Status
Canonical architecture decision after reading the current `main` implementation. This document is a reduction plan, not permission to add a new router, classifier, adapter hierarchy, or compatibility shim.

## Goal
Keep AI Foundation responsible only for product-specific composition, multi-LLM supply policy, host authority/safety semantics, and minimal replaceable OSS boundaries. Generic mechanisms stay with adopted OSS.

## Decisions

### 1. Keep the Agent-first daily entrypoint
`foundation-auto` continues to enter one Pydantic AI Agent. Ordinary CHAT is not given a separate semantic pre-router.

Reason:
- Pydantic AI already owns semantic tool selection.
- A CHAT fast-path would require Foundation to decide whether SEARCH/CODE/FILES/DATA is needed before the Agent, recreating the classifier removed on 2026-09-22.
- Tool-free CHAT can terminate after the Agent model response; no second Foundation semantic judge is required.

Prohibited:
- restoring `PydanticCapabilityClassifier`, `AutoCapabilityRequestFactory`, or an equivalent semantic mode switch;
- provider-specific tool-selection rules;
- a second LLM that decides whether the Agent may use a tool.

### 2. Reduce SEARCH to evidence retrieval + one Agent synthesis
SEARCH is the primary remaining reduction target.

Verified current behavior:
- `CapabilityExecutor -> ResearchSpecialist -> InferenceResearchPort -> inference.run(..., SEARCH)` is one provider-neutral SEARCH boundary, not proof of an extra LLM hop.
- Native Tavily/Exa execution already uses `privacy_text` as the direct search query in `CloudInferencePort -> ObservedCloudExecution.invoke_for_function`; the LLM-shaped `plan.text` instruction is not sent as a synthesis request to those native protocols.
- `ObservedCloudExecution.extract_text` already converts native results directly into bounded canonical evidence JSON. Therefore native SEARCH is already retrieval -> evidence -> Agent synthesis.
- The research JSON instruction remains necessary for LLM-native SEARCH fallback such as Groq browser search, where the provider must return grounded evidence in the common contract.

Target contract:
```
Pydantic AI Agent
  -> SEARCH tool
     -> SEARCH execution boundary
        -> native retrieval provider (Tavily / Exa / future SearXNG)
           -> canonical bounded Evidence
        -> LLM-native search provider (for example Groq browser search)
           -> grounded Evidence/result
  -> Pydantic AI Agent final synthesis
```

Implementation rules:
1. Introduce no new semantic router. Dispatch only from already-authoritative provider metadata/protocol.
2. Native protocols (`tavily-search`, `exa-search`, future native search protocols) must bypass the Research-LLM JSON instruction. Their adapter output is canonical bounded evidence directly.
3. LLM-native SEARCH remains supported as fallback when a native retrieval route is unavailable. It may use provider-native browser/search execution, but it must not become a second general conversational Agent.
4. Preserve `observed_at`, `published_at`, source URL, bounded excerpt, provider score/confidence where available, and uncertainty.
5. The final conversational synthesis belongs to the Pydantic AI Agent exactly once.
6. Do not implement search aggregation, crawling, ranking, freshness inference, or document indexing in Foundation. A future SearXNG integration must satisfy the same replaceable SEARCH execution contract.
7. Keep fail-closed grounding: a SEARCH result without observed evidence must not be presented as grounded retrieval.

Expected effect:
- fewer LLM calls for native SEARCH;
- lower free-quota consumption and latency;
- fewer model-formatting failures;
- fewer E2E boundaries;
- no loss of Groq/provider-native search fallback.

### 3. Keep RoutedAgentModel, but freeze its responsibility
`RoutedAgentModel` remains the minimal Pydantic-AI-to-Foundation multi-LLM bridge.

It may own:
- conversion between Pydantic AI model messages/tool schemas and Foundation provider-neutral execution payloads;
- request phase (`initial` / `tool_followup`) execution metadata;
- delegation to canonical ComputeRouter;
- real-request fallback using canonical route evidence;
- conversion of provider response/tool calls back to Pydantic AI model responses.

It must not own:
- semantic capability classification;
- Agent history scheduling/reconstruction;
- provider-specific prompt truncation;
- synthetic fallback probes;
- tool authority;
- SEARCH evidence synthesis;
- a second model-selection policy independent of ComputeRouter.

Do not replace the Foundation ComputeRouter with Pydantic AI FallbackModel: quota, health, FREE/PAID authority, local-only policy, persistent route order and specialist capability membership are Foundation product semantics.

### 4. Keep CapabilityExecutor simple
The existing explicit capability dispatch is execution dispatch after authority/tool selection, not semantic routing. Do not replace the small explicit branch with a registry/plugin/factory framework unless a concrete extension proves the branch unmaintainable.

Capability implementations remain independently replaceable behind the executor.

### 5. Keep ToolHive as the MCP execution/containment boundary
ToolHive owns MCP workload lifecycle, containment, network isolation and process boundary. Foundation owns host-bound scope, Guard authority and independent effect verification.

Future PC control must follow the same pattern:
```
Pydantic AI host-authorized PC tool
 -> trusted target/scope
 -> Guard/policy
 -> replaceable MCP execution port
 -> ToolHive
 -> PC-control MCP
```

Do not embed Desktop Commander-specific behavior into the Agent, ComputeRouter, or Guard.

### 6. Keep Guard and Cedar separate
Cedar remains policy evaluation. Guard remains Foundation safety/effect semantics: Canon, privacy/local-only, credential/budget/approval boundaries, effect state, reconciliation and independent verification.

Do not move effect lifecycle or human approval state into Cedar merely to increase OSS usage.

### 7. Keep Hatchet and DurableWork responsibilities separate
Hatchet owns scheduling, queues, worker distribution and redelivery. DurableWork owns Foundation verified-step progress and human-wait state. Guard owns real-world effect idempotency/reconciliation.

Normal short CHAT/SEARCH/FILES reads must not be forced through Hatchet. Use Hatchet for genuinely durable/long-running workflows.

## Implementation order

### Phase A — SEARCH contract correction
1. Keep the existing native Tavily/Exa direct retrieval path; do not add protocol branching to `InferenceResearchPort` or `GuardedInferenceService`.
2. Keep one canonical bounded Evidence representation at the existing provider-neutral SEARCH boundary.
3. Preserve the research JSON instruction only as the contract for LLM-native SEARCH fallback; native protocols ignore `plan.text` and use the trusted `privacy_text` query.
4. Preserve native numeric provider confidence/score instead of discarding it during ResearchResult parsing.
5. Keep `CapabilityExecutor` consuming the same grounded SEARCH result regardless of native or LLM-native source.
6. Verify one final Agent synthesis and no repeated SEARCH loop for a successful native retrieval.

### Phase B — regression and boundary proof
Run focused tests before broad E2E:
- SEARCH routing/capability tests;
- native Tavily/Exa adapter tests with bounded evidence;
- Groq/browser-search fallback tests;
- Pydantic Agent tool-call/result pairing;
- route health/quota/fallback tests;
- grounding/fail-closed tests;
- privacy/local-only tests.

Then run the real user-flow E2E once for each materially different boundary:
- ordinary CHAT without tools;
- native SEARCH;
- LLM-native SEARCH fallback;
- FILES read through ToolHive;
- CODE inspect/read through repo MCP.

Do not multiply E2Es for implementation details already covered by contract/unit tests.

### Phase C — thinness verification
After Phase A/B, inventory the changed call graph. Reject the change if it:
- adds a semantic classifier;
- increases the number of Foundation-specific routing layers;
- introduces provider-name branches where protocol/capability metadata is sufficient;
- duplicates Pydantic AI Agent scheduling/history;
- duplicates ToolHive lifecycle/containment;
- duplicates Cedar policy evaluation;
- duplicates Hatchet scheduling/redelivery.

## Non-goals
- No ordinary-CHAT bypass.
- No rewrite of RoutedAgentModel.
- No replacement of ComputeRouter.
- No new Foundation search engine.
- No SearXNG integration in this change.
- No PC_CONTROL implementation in this change.
- No broad refactor of Guard, ToolHive, Hatchet, DurableWork, CODE or FILES.

## Completion criteria
This reduction is complete when:
1. Native SEARCH continues to return observed bounded evidence without a Research-LLM formatting/synthesis hop.
2. LLM-native SEARCH remains a working fallback.
3. Pydantic AI remains the only semantic tool selector and final conversational synthesizer.
4. Foundation route/health/quota/privacy/authority behavior is unchanged.
5. Existing CODE/FILES/ToolHive/Guard/Hatchet boundaries remain unchanged except for tests/docs required by the SEARCH contract.
6. Focused tests pass before the minimal real E2E matrix.
7. No new custom semantic routing abstraction was introduced.

## Architecture rule going forward
When a new capability is proposed, first ask which adopted OSS or external replaceable service owns the generic mechanism. Foundation may add only the product-specific authority, composition, routing policy, and minimal exchange boundary that cannot be delegated without losing its core semantics.


## 2026-09-24 canonical reload correction
A source-level reload before implementation disproved the earlier assumption that native Tavily/Exa SEARCH incurred an intermediate Research LLM call. The existing execution path already sends `privacy_text` directly to native search protocols and canonicalizes their provider results in `ObservedCloudExecution.extract_text`. No new native-search dispatcher was added.

The corrective implementation therefore stays smaller:
- keep `GuardedInferenceService` provider-agnostic;
- keep the LLM-native grounding instruction in `InferenceResearchPort`;
- document that native protocols bypass that instruction at execution time;
- preserve numeric native confidence/score in canonical `Evidence`;
- add regression coverage for that evidence preservation.

This correction is an example of the thinness rule: when reloading the source shows that the desired boundary already exists, remove the planned abstraction instead of implementing it.


## RoutedAgentModel / CHAT routing correction — 2026-09-24
Canonical reload of `RoutedAgentModel`, `SQLiteRoutingPolicy`, `SettingsService` and their tests found one real responsibility leak: Agent request phase (`initial` / `tool_followup`) had moved from observability into execution selection. Phase-specific runtime rows could cause the same CHAT capability to choose a different provider solely because it was a tool follow-up. That is a second routing policy inside the Agent bridge and makes sparse E2E observations disproportionately authoritative.

Correction:
- Pydantic AI continues to own Agent history and tool scheduling.
- `RoutedAgentModel` still records phase for tracing/runtime diagnosis, but delegates both initial and tool-followup calls to the same canonical CHAT route.
- Phase runtime rows remain diagnostic evidence only and cannot alter route selection.
- `SettingsService.choose_route(..., phase=...)` retains the argument only as a compatibility boundary; it does not forward phase into execution selection.
- No replacement router, classifier, adapter, or provider-specific rule was introduced.

Verified non-problems retained unchanged:
- native Pydantic AI structured history is serialized rather than reconstructed by Foundation;
- real-request fallback excludes the failed binding and asks the canonical router for the next eligible route;
- synthetic fallback probes remain removed;
- tools remain available after a tool result so Pydantic AI can perform legitimate multi-tool flows;
- Foundation still owns provider health/quota/free-paid/local policy while Pydantic AI owns semantics.

This reduces a real source of complexity/E2E drift without changing the Agent-first architecture.


## Runtime exploration / stale sampling correction — 2026-09-24
Canonical reload of `SQLiteRoutingPolicy`, provider recovery, SettingsService reconciliation and routing tests found another unnecessary active policy: real CHAT/SEARCH execution was being used to manufacture exploration traffic. After three clean successes an unobserved standby could be selected solely to collect measurements, and a stale observed route could be selected solely because its runtime evidence was old.

That behavior is removed.

Boundary after correction:
- persisted optimized order remains deterministic policy;
- authoritative health/quota/credential state controls eligibility;
- real request outcomes may rank routes that have real successful-completion evidence;
- recent real failures retain bounded cooldown/backoff;
- provider recovery/probes own discovery of recovered capacity;
- live route membership reconciliation restores recovered ONLINE capable routes to the policy snapshot;
- ordinary user requests are not sacrificed to synthetic exploration or stale sampling.

An unobserved route is no longer promoted merely because another route has succeeded three times. A stale route is no longer promoted merely to refresh its runtime metric. No timer, background sampler, random exploration, provider-name rule or replacement router was introduced.

The remaining runtime policy is intentionally small: real success latency + real failure evidence + persisted order as tie/fallback. This keeps runtime evidence descriptive of actual execution rather than making the router generate the evidence it later treats as reality.


## Quota / health / recovery authority correction — 2026-09-24
Canonical reload of routing, provider registry, response observation and recovery found one remaining inferred-state shortcut: `SQLiteRoutingPolicy._quota_eligible` treated a stale near-empty quota observation as recovered capacity after the parsed reset duration elapsed. That converted a reset hint plus local wall-clock time into execution authority without a new provider observation.

That inference is removed.

Boundary after correction:
- response headers/probes are quota observations;
- near-empty observed quota suppresses normal execution;
- reset text schedules the next recovery observation only;
- elapsed local time does not itself restore quota;
- ProviderRecoveryLoop performs the re-observation;
- only a new provider observation can publish recovered quota/health;
- runtime HTTP response remains execution evidence and provider probe remains recovery evidence;
- route membership reconciliation may republish a genuinely recovered ONLINE capable provider, but does not invent recovery.

This intentionally prefers temporary under-use over sending a user request based on guessed quota recovery. No quota predictor, provider-specific timer policy, or second health state machine was added.


## Provider Registry / Catalog / route publication correction — 2026-09-24
Canonical reload confirmed the main Registry/Catalog separation is sound: catalog owns executable endpoint/model/protocol/capabilities, while registry health/quota remains observed state. Startup reconciliation updates only adapter-owned execution metadata and retires providers whose executable adapter disappeared.

One remaining responsibility leak was removed from `SettingsService.choose_route`. A read/selection call previously detected an ONLINE candidate missing from the persisted snapshot and silently called `optimize`, mutating route policy during execution. That made the act of choosing a route also a reconciliation/publication mechanism.

Boundary after correction:
- startup catalog reconciliation republishes routes when executable metadata changes;
- provider add/remove/credential replacement republishes routes;
- provider refresh/recovery republishes routes after the new observation;
- direct registry writes are low-level state mutations and do not gain hidden route-publication semantics;
- `choose_route` is read-only with respect to persisted route policy;
- route snapshots remain derived policy/display state, not an execution-side cache repaired opportunistically by user traffic.

No new reconciliation service, event bus, watcher or registry abstraction was introduced.


## Local compute health / fallback correction — 2026-09-24
Canonical reload of LocalComputeRegistry, ComputeRouter, GuardedInferenceService and LocalFailureCooldown confirmed inventory and execution are correctly separated: discovery reports current local candidates, ComputeRouter selects only discovered ONLINE candidates, and real local execution failure falls through to another eligible route.

One inferred-recovery shortcut remained: LocalFailureCooldown automatically deleted a real local execution failure after a TTL. That made elapsed local wall-clock time equivalent to evidence that a model could load/respond again. A subsequent user request could therefore be used as an implicit recovery probe.

That inference is removed.

Boundary after correction:
- LocalComputeRegistry/discovery owns positive inventory/ONLINE claims.
- A real local execution failure adds binding-level negative execution evidence.
- GuardedInferenceService excludes known failed local bindings from ordinary requests.
- Elapsed time does not clear that evidence.
- Only an actual successful local execution clears the failure exclusion.
- Normal cloud/local fallback remains real-request fallback after definitive inference failure; no synthetic local retry/probe is manufactured by the cooldown layer.

The existing `ttl` constructor argument/database `expires` column are retained temporarily as storage/API compatibility only; they no longer grant recovery authority. A future dedicated local-runtime health probe may explicitly call `success(binding)` after a real successful observation. Do not reintroduce time-based recovery in route selection.


## Tool result / Agent context boundary correction — 2026-09-24
Canonical reload of `RoutedAgentModel`, AutoCapabilityAgent, tool-output handling and Pydantic AI flow tests confirmed that Foundation no longer reconstructs or compacts Agent history: Pydantic AI supplies structured ModelRequest/ModelResponse history and the adapter serializes it provider-neutrally.

One residual semantic rule was removed from `RoutedAgentModel`: special handling for a `tool_followup` with no advertised tools attempted to define a Foundation-level "final synthesis" phase and suppress/reject provider tool calls. That is Agent-loop semantics derived from history, which belongs to Pydantic AI, not the model adapter.

Boundary after correction:
- Pydantic AI owns Agent history, tool scheduling, retry semantics and whether subsequent tool calls are valid;
- Foundation serializes System/User/Assistant/Tool/Retry parts without semantic reconstruction;
- Foundation exposes exactly the tool schemas Pydantic AI supplies;
- Foundation does not summarize, truncate, compact or reinterpret tool results;
- Agent phase remains telemetry only;
- tool output remains untrusted data/evidence and never becomes Guard/authority input merely because it is in model context;
- provider fallback reuses the same provider-neutral structured history.

No custom context manager, token compactor, history summarizer or tool-result classifier was introduced.


## CODE / FILES scope and Guard boundary correction — 2026-09-24
Canonical reload of CapabilityRequest, CapabilityExecutor, CodingSpecialist, FILES execution and Agent capability tools confirmed the authority chain is fundamentally correct: host context creates absolute/bounded grants; model-visible tools expose only target/content/operation; bound capability objects enforce path containment; Guard owns durable write authorization/effect state; verification remains independent.

One duplicate authority check was removed from CODE. `CodingSpecialist.apply_verified_change` pre-authorized the target and ran protected-resource validation, then `CapabilityAgentTools.write` authorized the same target again and the underlying write execution boundary retained its own protected-resource policy. The specialist now orchestrates read/test/write/test only; it does not become another scope/policy authority.

FILES was clarified so the protected-resource check receives the exact normalized target produced by the bound WriteCapability before the guarded write. The public bound write API/effect sequencing remains encapsulated in CapabilityAgentTools.

Intentionally retained:
- CapabilityRequest validates trusted envelope shape and root relationships;
- ReadCapability/WriteCapability enforce per-target containment at execution time;
- protected-resource policy is separate from path containment;
- Guard authorizes durable effects and verifies completion;
- CODE host-controlled tests run before/after writes;
- FILES read remains observational and FILES write remains separately granted.

No generic permission engine, path-policy abstraction or new Guard layer was added.


## Hatchet / DurableWork / Effect reconciliation correction — 2026-09-24
Canonical reload confirmed the intended separation is valid: Hatchet owns durable scheduling/redelivery, DurableWork owns Foundation-specific step progress, and Guard owns external effect truth through durable effect state plus independent observation/reconciliation. Hatchet inference retries remain disabled so runtime redelivery cannot blindly repeat uncertain inference/effects.

One state-promotion leak remained in `DurableWorkRunner.execute`: any returned string other than `WAITING_HUMAN` was persisted as a VERIFIED work step. Therefore a Guard-backed step returning `UNCERTAIN_RECONCILE_REQUIRED`, `CANCELLED_RECONCILE_REQUIRED`, `EFFECT_IN_PROGRESS`, or `TARGET_IN_PROGRESS` could be mislabeled as verified orchestration progress even though external reality was unresolved.

That promotion is removed. Those reconciliation-required/in-progress effect outcomes leave the work step RUNNING. `DurableWorkRuntimeCall` then requires a named reconciler on resume, and only `VERIFIED_COMPLETE` from reconciliation may atomically promote the stored RUNNING step to VERIFIED.

Boundary after correction:
- Hatchet delivery state is not effect truth;
- DurableWork RUNNING is not effect truth;
- arbitrary returned text is not effect truth;
- Guard EffectStatus + independent `port.observe` reconciliation owns external-effect truth;
- work becomes VERIFIED after a definitive step result, and orphaned effectful RUNNING work becomes VERIFIED only after explicit successful reconciliation;
- no blind replay is introduced.

No new workflow engine, effect state machine or Hatchet wrapper was added.


## Cross-cut convergence audit — 2026-09-24
Reloaded the final changed boundaries together rather than auditing another subsystem in isolation: routing, local health, Agent context, CODE/FILES authority and DurableWork reconciliation plus their focused regression tests.

One stale contract test was found: `test_coding_specialist.py` still expected CodingSpecialist itself to run protected-resource validation before observation. That expectation contradicted the new single-owner boundary where the specialist orchestrates and the bound write tool owns write authority. The test is replaced with a contract that verifies a denied bound write is not bypassed by CodingSpecialist.

No new production abstraction was required by this convergence pass. The remaining time-shaped `ttl/clock/expires` fields in LocalFailureCooldown are explicitly documented as legacy storage/API compatibility and non-authoritative; removing the persisted column is a later migration cleanup, not a correctness prerequisite.

Static canonical consistency is now aligned across the audited source/tests/docs. Runtime pytest/E2E is still a separate gate because this GitHub-only pass does not execute the repository.


### Final repository-wide static convergence correction
A repository-wide GitHub-only pass reloaded the full source/test inventory and rechecked the thin-boundary edits together. It found one real regression in the earlier CODE cleanup: `CodingSpecialist` had stopped calling `ProtectedResources.validate_write`, while `CapabilityAgentTools.write` owns path containment/Guard execution but does not own protected-model/runtime policy. The old comment claiming that protected-resource policy was enforced downstream was therefore false.

The correction keeps the boundary thin: CODE scope/effect authority remains in `CapabilityAgentTools`; immediately before the guarded write, the specialist asks the existing bound `WriteCapability` only for the normalized target and applies the distinct existing `ProtectedResources` policy. No new policy/router/adapter was introduced. A focused contract test proves the protected normalized target is rejected before any write.

GitHub code-search checks found no indexed remnants of the removed classifier/request-factory/history symbols or the retired exploration/stale-sampling test names. Search reports are marked incomplete by GitHub for this private repository, so they are supporting evidence rather than interpreter-level proof. The remaining execution proof is the deferred real runner gate.
