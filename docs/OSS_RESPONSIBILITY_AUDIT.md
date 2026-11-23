# OSS responsibility audit — 2026-09-20

## Decision
Use each adopted OSS for the generic mechanism it owns, while AI Foundation keeps product policy and safety semantics. Do not replace a verified Foundation boundary merely to increase OSS usage.

| Component | OSS should own | Foundation must keep | Current production state |
|---|---|---|---|
| Pydantic AI 2.44.0 | agent loop, semantic tool selection, tool/model schemas, structured agent output, model fallback mechanism inside an Agent | capability route policy, optimized provider order, provider health/quota, credentials, Guard authority | AgentPort/tool capability E2E exists; normal inference path is still the narrow provider execution path |
| Hatchet 1.40.1 | scheduling, queueing, redelivery/retries, worker distribution, runtime observability | verified-step state, effect idempotency, reconciliation, Guard | real Lite/SIGKILL composition is verified, but normal Operator bootstrap does not run work through Hatchet yet |
| ToolHive 0.49.0 | MCP workload containment/lifecycle, network isolation, audit boundary | host-bound tool scope, Guard, independent verification | generic MCP production boundary for promoted BROWSER / COMPUTE / DATA paths; filesystem adapter is separately verified and remains scoped/host-authorized rather than ambient chat FILES authority |
| Cedar | authorization policy evaluation | Canon, privacy, human approval, budget, effect/verification state | real production policy boundary/E2E verified |

## Routing versus Pydantic AI fallback
Pydantic AI FallbackModel is real and supports exception/response-triggered model fallback. It is not a replacement for the Foundation route policy. The canonical route contract persists an optimized order, temporarily skips unhealthy/exhausted candidates without rewriting it, restores recovered primaries, enforces FREE/PAID authority, and unifies provider-native and composed capabilities. Those are product routing semantics outside an Agent.

When production Agent execution is introduced for a route, use Pydantic AI's model/fallback mechanism inside that Agent adapter rather than reimplementing an agent-local fallback loop. Do not move Guard, quota/cost authority, or route persistence into Pydantic AI.

## Concrete gaps found
1. Hatchet is the largest underused OSS boundary: production operator_server.py invokes inference directly. The verified Hatchet runtime is not the normal scheduling/redelivery path.
2. ToolHive is the generic MCP production boundary for the promoted BROWSER / COMPUTE / DATA paths. Its filesystem adapter is a separate authority surface: it is verified and host-scoped, but generic chat receives no ambient FILES authority. Do not infer FILES exposure from ToolHive's production status.
3. Pydantic AI is correctly used for Agent boundary tests/tools, but the production normal inference path is intentionally not an Agent. Its optional provider SDK extras are not installed, so replacing the current provider transport with Pydantic models today would add dependencies and duplicate the already verified Provider Registry/health/quota boundary.
4. Cedar is already used at the correct narrow authority boundary. Expanding it into approval/budget/effect state would violate the architecture.

## Execution order and dependency gate
1. Preserve current routing policy and provider registry; they are Foundation product semantics.
2. ToolHive filesystem execution is already Guard-mediated and independently verified. Promotion to the visible FILES route additionally requires a real product entrypoint carrying an explicit target/capability scope; the current OpenAI-compatible entrypoint carries chat text only. Do not fabricate a FILES route candidate before that end-to-end input contract exists.
3. Hatchet scheduling/redelivery is verified, but normal chat inference currently has only in-memory result evidence. Moving that call blindly behind redelivery would create duplicate/uncertain cloud attempts after worker loss. Production migration therefore requires durable inference-attempt/result evidence or an explicit non-redelivered inference step before replacing the direct call.
4. Pydantic AI AgentPort and Guard-mediated tools are verified. Introduce it in production only for a route with an actual agent/tool contract; do not turn ordinary CHAT into an Agent merely to increase OSS usage. Within such an Agent use Pydantic AI native model/tool/fallback facilities.
5. These are dependency gates, not reasons to copy OSS behavior into Foundation. Re-run real ToolHive/Hatchet crash/reconciliation and complete user-flow gates when the missing product contracts are supplied by canonical work.

## 2026-09-20 implementation update
- ToolHive/FILES: the missing host-owned target/scope contract is implemented. Production creates a read-only scoped filesystem boundary over the configured ToolHive root; writes require explicit trusted-host opt-in. Generic chat still has no ambient FILES authority.
- Hatchet/durability: cloud dispatch now has durable attempt/result evidence. Verified replay is read-only and uncertain dispatch fails closed instead of falling through/retrying. Hatchet inference task defaults explicitly disable runtime retry because Foundation owns this uncertainty. Embedded Hatchet itself was not promoted to Operator authority because its embedded Postgres failed its live startup check during this implementation.
- Pydantic AI: a scoped production Agent factory now consumes the host-bound CapabilityAgentTools. This is the intended production adapter for actual agent/tool routes; ordinary CHAT is intentionally not converted.

### Developer/local-model protection follow-up
The FILES scope implementation now has an explicit deny boundary for the local-model control plane. ToolHive remains the isolated filesystem executor and Guard remains effect authority; Foundation's host-bound capability policy prevents Developer/Agent write scopes and writes from targeting model weights/caches, llama-swap/model registration state, training/fine-tuning actions, or model load/switch/register/replace actions. This is intentionally enforced outside the model prompt.


## 2026-09-26 daily ambient authority supersession

The earlier implementation-state statements above that generic/ordinary CHAT had no
ambient FILES authority or was not converted to an Agent are historical descriptions
of the pre-Agent-first daily path. They are not the current target contract.

The normal `foundation-auto` path is now the Pydantic AI Agent/tool loop while
remaining semantically `CHAT`. A trusted host may pre-compose already-reviewed,
bounded grants through the existing `CapabilityRequest`; this may include the
canonical repository CODE grant, bounded DATA operations, and bounded read-only
FILES authority for host-selected file roots or owner-verified attachments.
This composition does not give the model authority to create, select, or widen
grants.

CODE and FILES remain separate execution/authority surfaces. Repository files,
including repository documentation and configuration, belong to CODE inspect
through the bounded repository grant. FILES is for its separately host-authorized
general file area or exact owner-verified attachments. Ambient FILES therefore
does not imply repository access, filesystem write authority, or generic host
filesystem authority.

Pydantic AI owns semantic tool selection among the tools exposed by those existing
grants. Foundation must not add a prompt classifier, semantic pre-router, fallback
that widens authority, or a second generic grant framework.

## 2026-09-22 correction — restore the original Agent-first design

A temporary PydanticCapabilityClassifier / AutoCapabilityRequestFactory path duplicated Pydantic AI's own tool-selection responsibility and made normal chat depend on a separate semantic mode switch. That path is removed. Daily foundation-auto now enters one Pydantic AI agent loop. Host-authorized SEARCH/DATA/CODE/FILES functions are registered as tools only when their authority prerequisites exist; the Agent chooses among those tools. Foundation routing remains below the Agent model adapter, so provider/model health/quota/credential policy is not moved into Pydantic AI.

## Runtime routing responsibility (2026-09-22)
Foundation retains the small product-specific runtime-memory layer because fixed visible route policy, authoritative quota/health evidence and local-only execution history are Foundation semantics. Pydantic AI owns Agent/tool selection, not Provider ordering. Runtime metrics are deterministic local SQLite state (outcome + latency); they influence execution choice without rewriting the persisted route chain. Do not introduce a second LLM/router to maintain this state.

## SEARCH freshness boundary (2026-09-23)
Foundation owns only the execution-time temporal context and canonical evidence timestamps (observed_at, optional published_at). Search aggregation, provider-native time filtering, and document-store metadata filtering remain replaceable external responsibilities. Do not grow a custom freshness engine in Foundation. SearXNG may fill aggregation/time-range search later; Haystack/LlamaIndex must not duplicate the existing LibreChat RAG/pgvector responsibility without an explicit architecture change.


## Tool-result growth responsibility boundary (2026-09-23)
- Pydantic AI owns Agent/tool scheduling and tool-call/result pairing; Foundation must not replace that scheduler or delete structural tool history.
- Foundation owns its provider-neutral model payload boundary. Replaying arbitrarily large completed tool payloads to every later provider is therefore a Foundation transport/context responsibility.
- Older completed tool payloads may be compacted at that boundary; the newest result remains available for the next Agent decision. Capability/provider-specific truncation is prohibited.
- Pydantic AI 2.47.0 was audited and does not expose ToolOutputLimits in this installed slim distribution; do not create an OSS-shaped compatibility shim or couple Foundation to undocumented APIs.


## Real-request fallback evidence (2026-09-23)
- Removed synthetic one-token cloud fallback racing from Agent request recovery. A tiny probe does not exercise the failed request's payload, tool schema, follow-up phase, or context size and therefore must not promote a route for the real request.
- After a real CHAT attempt fails, the canonical deterministic router now selects the next eligible route using actual runtime/health/quota evidence and the failed binding exclusion. No provider-specific order or semantic judge is introduced.
- Routing success/failure evidence must come from the real execution path when it is used to decide continuation of that execution; health probes remain health evidence only.


## Live route membership reconciliation (2026-09-23)
- Persisted route order is derived policy, not authority. Recovered ONLINE capable routes missing from an older snapshot are reconciled before selection.
- Reconciliation is provider-neutral and capability-driven; health, quota, credential and runtime evidence remain authoritative.


## Provider observation authority (2026-09-23)
- Runtime inference response is stronger execution-health evidence than background recovery probe results. A transient recovery probe failure/rate-limit must not demote a provider that runtime last proved ONLINE.
- Recovery probes cannot clear an inference-observed RATE_LIMITED state either; actual inference success remains the recovery authority. This rule is provider-neutral and keeps health probing separate from execution evidence.


## Dead fallback probe removal (2026-09-23)
- Removed the unused custom synthetic cloud-race helper. Real request fallback remains canonical-router driven.


## Native agent history boundary (2026-09-23)
- Removed Foundation custom follow-up history reconstruction and compaction. Pydantic AI owns agent/tool history; the model adapter serializes native structured history uniformly.
- Foundation adds no semantic summary, provider-specific truncation, or hidden tool-result marker. Run and tool bounds remain Pydantic AI UsageLimits.

## Future security reference: CAIRN / CLOSEDQUORUM (2026-09-23)
- Reference Cisco Talos CAIRN research as a future threat-hunting/observability input, not a new Foundation dependency. Reuse existing observability/security boundaries before adding custom detection code.
- Use CLOSEDQUORUM as an adversarial test model: multi-LLM consensus is never authority. Even unanimous model/tool requests must remain bounded by host capability scope, Guard/policy, credentials, and durable-effect verification.
- Future attack gates should test compromised/malicious providers, suspicious tool chains, scope escape, secret exfiltration attempts, and autonomous repeated actions. Keep detection/tooling replaceable and OSS-first.
- References: Cisco Talos, "Introducing CAIRN: Frontier tracking for AI-integrated malware" and Talos CLOSEDQUORUM analysis.


## Provider recovery evidence simplification (2026-09-23)
- Removed custom stale-health preservation from refresh_provider. Catalog probe result is written as the current recovery observation. Runtime HTTP responses remain owned by ProviderResponseObserver. No provider-specific routing rule was added.


## SEARCH execution clarification (2026-09-24)
Canonical source reload confirmed that native Tavily/Exa SEARCH already bypasses an intermediate Research LLM: `CloudInferencePort` supplies the trusted `privacy_text` query, native protocol adapters execute retrieval directly, and `ObservedCloudExecution.extract_text` returns bounded evidence JSON. The research JSON instruction is for LLM-native SEARCH fallback (for example Groq browser search), not an additional native-search synthesis hop.

Do not add a native-search dispatcher to ResearchPort or GuardedInferenceService. Keep those boundaries provider-neutral. Native provider score/confidence is evidence and must survive canonical ResearchResult parsing.


## Agent phase routing boundary (2026-09-24)
Agent phase is not provider-selection authority. Pydantic AI owns the semantic distinction created by tool history; Foundation may observe `initial` versus `tool_followup` for traces and diagnostics, but both execute through the one CHAT routing policy. Phase-specific runtime telemetry must not create a hidden second provider order or override aggregate capability-level execution evidence.


## Runtime evidence must not manufacture traffic (2026-09-24)
Removed custom bounded-exploration and stale-runtime sampling from normal route selection. Runtime metrics are observations of real requests, not authority to divert user traffic for measurement. Provider recovery/probing owns capacity rediscovery; SettingsService reconciles recovered eligible membership into derived route policy. Real failures may temporarily cool a route and real successful completion latency may rank observed alternatives, but Foundation does not generate probe-like user requests through the normal execution path.


## Quota recovery is observation-driven (2026-09-24)
Removed routing-time inference that stale low-quota evidence becomes usable merely because its reset duration elapsed. Reset metadata may schedule ProviderRecoveryLoop, but only a new provider response/probe observation can restore quota/health authority. This keeps local wall-clock inference from becoming provider capacity truth.


## Route publication belongs to authoritative mutations (2026-09-24)
Registry/Catalog reconciliation remains intentionally asymmetric: shipped catalog metadata owns executable protocol/model/capabilities, while provider health/quota remains observed registry state. Removed execution-time route snapshot mutation from `choose_route`. Route publication now occurs only at startup catalog reconciliation or explicit provider mutation/recovery boundaries; ordinary route selection is read-only.


## Local failure recovery is observation-driven (2026-09-24)
Removed TTL expiry as authority to clear a real local-model execution failure. Local inventory/discovery supplies positive ONLINE capacity; actual execution failure supplies negative binding-level evidence; only a subsequent successful local execution may clear that exclusion. Wall-clock expiry must not turn a failed model load/request into inferred recovered capacity.


## Agent context remains Pydantic AI authority (2026-09-24)
Removed the remaining Foundation-side "final synthesis" interpretation from RoutedAgentModel. ToolReturn history is serialized as provider-neutral tool messages, and exactly Pydantic AI's current tool schemas are exposed. Foundation does not infer from `tool_followup` that the turn has become semantically final, suppress tool calls, compact history, or reinterpret tool output. Tool output remains untrusted evidence/data; Agent semantics remain owned by Pydantic AI.


## CODE / FILES authority stays layered, not duplicated (2026-09-24)
CodingSpecialist does not duplicate Guard/effect authority. CapabilityRequest owns trusted-envelope validation, bound Read/WriteCapability owns target containment, protected-resource policy owns protected targets, and Guard owns durable effect authorization/verification. The final static convergence audit found that CODE had accidentally stopped applying the distinct ProtectedResources policy after duplicate scope checks were removed; CODE now normalizes the target through the existing bound WriteCapability and applies ProtectedResources immediately before the guarded write. FILES likewise validates protected policy against its normalized bound target.


## Durable work cannot promote unresolved effects (2026-09-24)
DurableWork no longer treats reconciliation-required or in-progress Guard outcomes as successful step results. Such outcomes remain RUNNING until DurableWorkRuntimeCall invokes the explicit step reconciler; only a `VERIFIED_COMPLETE` reconciliation may promote that stored step to VERIFIED. Hatchet delivery, DurableWork status and returned strings remain orchestration evidence; Guard effect state plus independent observation remains external-effect authority.


## DATA / PC_CONTROL OSS boundary update (2026-09-24; DATA promoted 2026-09-25)
- DATA does not grow a Foundation-owned notebook/SQL engine. The deterministic DataSpecialist remains the narrow baseline. The read-only DuckDB MCP fast path is now production-promoted from self-hosted M1 run `36124752309`: host-selected `data_backend` -> existing generic MCP grant/ToolHive boundary -> pinned upstream DuckDB. Foundation adds no SQL parser/planner, denies `save_query` and COMPUTE authority, fails closed on missing backend, and never widens DATA failure into Jupyter. Datalayer Jupyter remains the explicitly broader, separately host-selected COMPUTE profile.
- PC_CONTROL must not grow a Foundation-owned desktop automation engine. The canonical P2 backend is Cua Driver in bounded permission mode, reusing the existing backend-neutral `BoundComputerPort / ComputerActionSpecialist` act -> observe -> expected verification contract. Foundation must not add a second manifest parser, policy engine, TCC manager, semantic desktop router, shell/JXA bridge, or Cua-specific verification framework.
- Cua Driver `0.28.3` / tag `cua-driver-rs-v0.28.3` was reviewed, but real M1 installation evidence showed the official macOS artifact fails upstream's own deep/strict signature gate and the installed app remains absent. P2 is therefore BLOCKED on a conforming reviewed upstream macOS release; Foundation must not ad-hoc-sign, bypass the installer check, reset TCC, substitute a nightly merely to pass, or expose PC_CONTROL to the Agent. Munim/other desktop backends are considered only if a concrete Cua requirement failure justifies that comparison; they are not automatic fallbacks.
- Browser-only automation remains a separate lower-authority choice where possible; do not escalate a web task to whole-desktop PC_CONTROL merely because the desktop backend can drive a browser.
- The DATA decision above is a measured production promotion. The remaining installation/permission/destructive-action/lost-response/real-M1 promotion gates in this subsection apply to PC_CONTROL/Cua only; do not regress the promoted DuckDB DATA status.


## Execution-layer convergence reconciliation — 2026-09-25

The final repository/workflow audit preserves the responsibility split above. ToolHive is the single generic MCP production transport/containment boundary for the promoted observational BROWSER, COMPUTE and DATA grants; Foundation retains trusted host scope, Guard/effect authority and independent verification. The filesystem adapter remains a separate host-scoped surface and does not imply ambient chat FILES authority. P2 PC_CONTROL remains BLOCKED on the reviewed Cua macOS artifact's upstream signature failure, so no desktop transport, fallback engine or Agent-visible PC authority is promoted. Manual backend probes are retained as evidence/revalidation surfaces, not product execution glue.
