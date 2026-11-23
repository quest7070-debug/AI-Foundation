# Capability- and Scarcity-Aware Compute Routing — Detailed Design Record

Status: PROPOSED / FUTURE DESIGN — NOT CURRENT IMPLEMENTATION
Recorded: 2026-09-29
Scope: AI Foundation compute/model selection only
Authority: subordinate to current canon, Guard/privacy/authority policy, and SETTINGS_SEMANTICS.md. This document does not change current runtime behavior.

## 0. Why this is a separate record

This record intentionally does not rewrite CURRENT_STATE.md, SETTINGS_SEMANTICS.md, or the existing docs/future/SCARCITY_AWARE_ROUTING.md. Those documents remain clean records of current state and the earlier narrow scarcity concept. This file is the loadable implementation-level expansion.

Load this document when changing model/compute routing, capability evidence, task requirements, quota scarcity, Local-vs-Cloud selection, or escalation behavior. Do not load it for unrelated Guard/effect/security work.

## 1. Canonical decision

Target routing principle:

> First remove candidates that cannot safely execute the request. Then identify the minimum-sufficient candidate set whose measured evidence predicts adequate task completion. Among that set, prefer the least strategically scarce resource. On capability failure, escalate capability rather than blindly walking laterally through equivalent weak models.

Non-goals:
- no permanent provider-name ranking;
- no assumption that Cloud is stronger than Local;
- no assumption that Local is cheaper merely because API cost is zero;
- no LLM self-rating as authoritative routing evidence;
- no guessed quota, price, benchmark, energy, or success probability;
- no second authority system parallel to Guard;
- no replacement of Pydantic AI's ownership of the agent/tool loop;
- no semantic reinterpretation of tool output by the router.

## 2. Current behavior that must remain distinguishable

Current production behavior is simpler:
- foundation-auto model calls use the CHAT route;
- capability eligibility, ONLINE health, known near-empty quota, persisted route order and runtime success latency/failure history participate;
- runnable FREE cloud is policy-ordered ahead of Local;
- PAID inference remains disabled until authoritative monetary accounting exists;
- Local is currently a fallback in ComputeRouter behavior;
- provider quota evidence is incomplete and UNKNOWN is not fabricated;
- initial/tool_followup phase metrics are observations, not separate selection policies.

The target design below MUST NOT be documented as implemented until code and verification are complete.

## 3. Decision pipeline

Selection MUST be staged. A later score MUST NOT compensate for failure of an earlier hard gate.

1. Normalize RequestRequirements.
2. Build executable candidates.
3. Apply authority/privacy hard gates.
4. Apply execution/capability hard gates.
5. Apply health and authoritative quota hard gates.
6. Estimate task-demand class from host-observable evidence.
7. Match candidates against empirical CapabilityEvidence.
8. Form MinimumSufficientSet.
9. Compute scarcity/resource preference only inside that set.
10. Select one candidate deterministically.
11. Execute and collect outcome evidence.
12. Classify failure.
13. Either lateral failover for infrastructure/capacity failure or capability escalation for capability/verification failure.
14. Persist evidence without mutating canonical policy from model output.

## 4. Proposed data contracts

### 4.1 RequestRequirements

Suggested new module: src/ai_foundation/routing_requirements.py

```python
@dataclass(frozen=True)
class RequestRequirements:
    capability: str
    difficulty: str              # LOW|MEDIUM|HIGH|CRITICAL
    reliability_class: str       # NORMAL|HIGH|CRITICAL
    privacy_class: str           # NORMAL|LOCAL_ONLY
    context_tokens_estimate: int | None
    requires_tools: bool
    required_tool_classes: tuple[str, ...]
    requires_vision: bool
    long_running: bool
    observable_features: tuple[tuple[str, str], ...]
```

Rules:
- capability MUST use normalize_capability().
- difficulty is host-derived routing metadata, not authority.
- privacy_class may only narrow execution. Model output cannot relax it.
- unknown context estimate remains None; do not invent a token count.
- observable_features must be bounded, non-secret structural metadata.

### 4.2 Difficulty derivation

Suggested pure function:

```python
derive_requirements(
    capability,
    *,
    context_tokens_estimate=None,
    attachment_count=0,
    file_count=0,
    exposed_tool_count=0,
    expected_step_count=None,
    long_running=False,
    critical_operation=False,
    privacy_class="NORMAL",
) -> RequestRequirements
```

Initial deterministic signals:
- LOW: bounded short request, no/low tool complexity, no critical operation.
- MEDIUM: ordinary tool/code/data work with bounded context.
- HIGH: multi-file, multi-step, long-context, repeated tool-loop, architecture/debug/integration work.
- CRITICAL: host-marked high-consequence design/security/canonical/destructive decision paths.

Do not infer CRITICAL merely from emotional wording. Criticality must come from host context or explicit trusted workflow metadata.

Difficulty derivation SHOULD remain deterministic at first. An LLM classifier may later provide non-authoritative evidence only after an eval demonstrates net value.

### 4.3 CapabilityEvidence

Suggested new module: src/ai_foundation/capability_evidence.py

```python
@dataclass(frozen=True)
class CapabilityEvidenceKey:
    binding: str
    capability: str
    difficulty: str
    phase: str                  # ANY initially; phase remains observational
    tool_profile: str           # NONE|TOOLS|MULTI_TOOL
    context_bucket: str         # SHORT|MEDIUM|LONG|UNKNOWN

@dataclass(frozen=True)
class CapabilityEvidence:
    attempts: int
    verified_successes: int
    capability_failures: int
    infrastructure_failures: int
    verification_failures: int
    success_latency_ms: float | None
    updated_at: float
```

Evidence hierarchy:
1. independently verified end-to-end completion;
2. deterministic task/eval completion;
3. successful real runtime completion with sufficient postcondition;
4. external benchmark prior;
5. declared model/provider capability.

Lower levels MUST NOT overwrite stronger evidence.

A provider returning HTTP 200 is not evidence of task completion quality.

### 4.4 Sufficiency

Do not begin with fake percentages.

Initial implementation SHOULD use evidence bands:

```
UNKNOWN
INSUFFICIENT
PROVISIONAL
SUFFICIENT
STRONG
```

Suggested deterministic promotion rules are implementation constants and require tests. Example shape, not canonical thresholds:
- insufficient after verified capability/verification failures;
- provisional with sparse successful evidence;
- sufficient only after minimum verified samples and acceptable failure bound;
- strong only with larger recent evidence set.

If later converted to probability, use calibrated confidence intervals rather than raw successes/attempts.

Function boundary:

```python
assess_sufficiency(requirements, candidate, evidence) -> SufficiencyAssessment
```

The function must return reasons/evidence IDs for explainability.

### 4.5 FailureClass

Suggested module: src/ai_foundation/routing_failures.py

```python
class FailureClass(Enum):
    RATE_LIMIT = "RATE_LIMIT"
    PROVIDER_DOWN = "PROVIDER_DOWN"
    CREDENTIAL = "CREDENTIAL"
    TIMEOUT = "TIMEOUT"
    CONTEXT_LIMIT = "CONTEXT_LIMIT"
    TOOL_PROTOCOL = "TOOL_PROTOCOL"
    CAPABILITY = "CAPABILITY"
    VERIFICATION = "VERIFICATION"
    POLICY = "POLICY"
    UNKNOWN = "UNKNOWN"
```

Classification MUST use bounded structural evidence: exception type, HTTP status, provider error code where safe, context-limit code, deterministic verifier result. Never route based on raw provider prose unless a separately bounded parser is verified.

Escalation semantics:
- RATE_LIMIT / PROVIDER_DOWN / CREDENTIAL / transient TIMEOUT -> lateral candidate of sufficient class is allowed.
- CONTEXT_LIMIT -> candidate satisfying larger context requirement.
- TOOL_PROTOCOL -> candidate/path with verified tool compatibility.
- CAPABILITY / VERIFICATION -> escalate to a stronger evidence band; do not blindly try equivalent insufficient candidates.
- POLICY -> stop/fail closed; routing cannot bypass Guard.
- UNKNOWN -> conservative bounded retry policy, then escalate or stop; never infinite fallback.

## 5. Candidate representation

Extend normalized candidate state rather than create Cloud and Local policy silos.

Proposed normalized fields:

```
binding
kind                       CLOUD|LOCAL
provider
model
tier                       FREE|PAID|LOCAL
health
capabilities
protocol
context_limit              known or None
tool_support               verified/declared/unknown
short_remaining
short_reset
long_remaining
long_reset
quota_evidence_at
runtime occupancy          Local only when authoritative
energy evidence            optional, observed only
monetary accounting        authoritative or unknown
```

Local and Cloud MUST pass through the same sufficiency assessment.

## 6. Hard gates

Suggested function:

```python
eligible_candidate(candidate, requirements, now) -> GateDecision
```

Order:
1. valid binding/execution metadata;
2. required capability;
3. privacy/authority;
4. protocol/tool/vision requirement;
5. known context-limit requirement;
6. health ONLINE;
7. authoritative known quota not near-empty;
8. paid authorization/accounting;
9. explicit exclusions from the current attempt.

Rules:
- UNKNOWN quota passes this gate; UNKNOWN is not zero.
- known <= current canonical near-empty threshold remains suppressible.
- elapsed reset text does not manufacture recovered quota.
- PAID remains excluded until authoritative per-request accounting exists.
- Local is not gated out merely because Cloud exists.

## 7. MinimumSufficientSet

Suggested function:

```python
minimum_sufficient_set(requirements, eligible, evidence_store) -> tuple[CandidateAssessment, ...]
```

Algorithm:
1. assess every eligible candidate against requirements;
2. discard INSUFFICIENT;
3. if one or more SUFFICIENT/STRONG candidates exist, do not consume UNKNOWN candidates merely for exploration;
4. if only PROVISIONAL/UNKNOWN exists, use deterministic bootstrap policy with bounded exploration;
5. CRITICAL work requires stronger evidence and may require independent verification;
6. never treat parameter count, Local/Cloud kind, price, or latency as direct intelligence evidence.

"Minimum sufficient" means do not consume a stronger/scarcer resource when a less scarce candidate already satisfies the reliability requirement. It does NOT mean always select the smallest model.

## 8. Scarcity

Existing docs/future/SCARCITY_AWARE_ROUTING.md remains the source concept. This design consumes it through a narrow interface.

Suggested module: src/ai_foundation/routing_scarcity.py

```python
@dataclass(frozen=True)
class ScarcityEvidence:
    binding: str
    requested_capability: str
    alternative_count: int
    scarce_other_capabilities: tuple[str, ...]
    known_quota_band: str        # PLENTIFUL|NORMAL|SCARCE|UNKNOWN
    reason_codes: tuple[str, ...]
```

Compute dynamically from currently executable candidates.

Principle:
- if candidate X is one of few viable providers for capability Y, ordinary capability Z should preserve X when another sufficient Z candidate exists;
- no provider name hardcoding;
- adding/removing Tavily/Exa/etc. automatically changes scarcity;
- UNKNOWN quota is neither full nor empty;
- scarcity changes preference, never authority/capability eligibility.

Do not collapse scarcity into one opaque floating score initially. Keep lexicographic reasoned fields for auditability.

## 9. Selection order inside the sufficient set

Use lexicographic ordering before considering a weighted score.

Recommended order:
1. evidence sufficiency/reliability band;
2. no recent capability/verification failure;
3. scarcity preservation;
4. authoritative monetary cost class;
5. Local occupancy/energy class when known;
6. successful completion latency;
7. historical failure rate;
8. persisted deterministic policy order;
9. binding as final stable tie-break.

Rationale: latency must not cause a fast but materially less reliable model to win.

Do not assign arbitrary weights such as quality*0.5 + quota*0.3 + latency*0.2 until calibration evidence exists.

## 10. Local compute policy

Target rule: Local is a first-class candidate, not a permanent terminal fallback.

Local advantages represented as evidence:
- no provider rate quota;
- no paid API charge;
- privacy/local-only eligibility;
- potentially low strategic scarcity.

Local costs represented only when observed:
- execution latency;
- host occupancy;
- measured/known energy class;
- model load/startup delay.

Rules:
- a small Local model may own LOW work if sufficient;
- a stronger Local model may own HIGH work if its empirical evidence qualifies;
- Local does not receive an intelligence bonus or penalty merely for being Local;
- Cloud does not receive an intelligence bonus merely for being Cloud;
- LOCAL_ONLY remains a hard policy constraint, not a routing preference.

ComputeRouter target change:
- remove implicit "Cloud selection then Local fallback" semantics;
- Settings/routing candidate projection should return Cloud and Local through one selection path;
- retain local_required as a hard restriction;
- prefer_local should be retired or explicitly scoped to diagnostic/manual behavior if no canonical need remains.

## 11. Quota policy

Current trustworthy quota collection remains authoritative.

Three states:
- KNOWN: provider exposes trustworthy machine-readable evidence.
- UNKNOWN: no trustworthy remaining value.
- EXHAUSTED/RATE_LIMITED: runtime/probe evidence proves unusability.

Rules:
- UNKNOWN != 0.
- UNKNOWN != unlimited.
- reset timestamp/string alone never proves recovery.
- 429 is strong runtime capacity evidence.
- observed quota should carry observation time/source.
- scarcity may conservatively prefer known-plentiful capacity over unknown when both are equally sufficient, but must not permanently starve UNKNOWN candidates.

Future provider-specific quota collectors belong behind provider adapters, not in routing.py.

## 12. Runtime evidence and schema evolution

Do not overload route_runtime until semantics become ambiguous.

Keep existing:
- route_runtime: generic execution success/failure/latency;
- route_phase_runtime: phase observation.

Add a dedicated SQLite table, suggested:

```sql
CREATE TABLE capability_runtime (
  binding TEXT NOT NULL,
  capability TEXT NOT NULL,
  difficulty TEXT NOT NULL,
  tool_profile TEXT NOT NULL,
  context_bucket TEXT NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0,
  verified_successes INTEGER NOT NULL DEFAULT 0,
  capability_failures INTEGER NOT NULL DEFAULT 0,
  infrastructure_failures INTEGER NOT NULL DEFAULT 0,
  verification_failures INTEGER NOT NULL DEFAULT 0,
  success_latency_ms REAL,
  updated_at REAL NOT NULL,
  PRIMARY KEY(binding, capability, difficulty, tool_profile, context_bucket)
);
```

Do not store prompts, response text, tool payloads, secrets, or user content in routing evidence.

Migration must be additive and backward-safe. Existing route policy must remain reconstructible.

## 13. Where code changes should land

### src/ai_foundation/routing.py
Keep:
- persisted route order;
- generic runtime memory;
- quota eligibility primitive where still useful.

Refactor target:
- routing.py should orchestrate selection, not contain provider-specific logic;
- delegate requirement matching, sufficiency and scarcity to pure modules;
- keep deterministic tie-breaking.

### src/ai_foundation/compute_routing.py
Change target:
- unified Local/Cloud selection;
- preserve local_required hard gate;
- eliminate Local-as-automatic-terminal-fallback once unified policy is verified;
- return richer RouteDecision metadata without exposing secrets.

Proposed:
```python
@dataclass(frozen=True)
class ComputeRoute:
    binding: str | None
    kind: str | None
    model: str | None = None
    execution_slot: str | None = None
    reason_codes: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
```

### src/ai_foundation/routed_agent_model.py
Keep:
- Pydantic AI owns agent/tool loop;
- CHAT remains model-call capability unless a separately canonical semantic change is approved;
- actual failure causes exclusion/fallback;
- no toy probe promotion.

Change target:
- provide trusted RequestRequirements from host context where available;
- pass structural failure evidence to classifier;
- on CAPABILITY/VERIFICATION failure request escalation rather than ordinary lateral fallback;
- do not let model output set its own difficulty/reliability.

### src/ai_foundation/settings_service.py
Keep provider registry and catalog reconciliation.

Change target:
- expose unified candidate snapshot to routing;
- route recalculation remains derived policy;
- no user sliders for fake quality values;
- capability evidence is read-only operational evidence, not manual provider ranking.

### src/ai_foundation/provider_quota.py / provider_observer.py
Keep provider-specific authoritative extraction.
Add observation timestamp/source if not already recoverable from registry.
Do not place strategic scarcity logic here.

### src/ai_foundation/provider_registry.py
Keep health/quota credential state.
Do not mix empirical task-quality evidence into provider credential rows.

### New modules
- routing_requirements.py — deterministic request requirement construction.
- capability_evidence.py — evidence store/types/sufficiency assessment.
- routing_scarcity.py — dynamic alternative/scarcity evidence.
- routing_failures.py — bounded failure classification and escalation class.

New modules are justified only if each owns one stable concept; do not create wrappers with no independent invariant.

## 14. Agent/task-level "one shot" semantics

"One-shot completion" means one submitted user/work task completes without unnecessary human restart or chains of predictably insufficient model attempts. It does NOT mean one LLM inference call.

A single task may legitimately contain:
- initial model call;
- multiple tool calls;
- tool-followup model calls;
- deterministic verification;
- one bounded escalation.

Measure task-level completion separately from call-level HTTP success.

Future evidence SHOULD link model-call attempts to a task/run ID using non-sensitive identifiers so completion quality can be attributed without storing content.

## 15. Critical work

CRITICAL work should not merely use the "largest" model.

Required behavior:
- require STRONG or highest available sufficient evidence;
- require deterministic verification when a deterministic postcondition exists;
- where independent semantic verification is justified, executor and verifier should be separable;
- verifier disagreement is evidence, not authority;
- destructive/effectful action remains Guard-mediated regardless of model strength.

Examples of host-marked critical classes may include canonical architecture mutation, security-sensitive design, and destructive operational plans. Exact promotion list requires a separate explicit decision; do not infer it from free text.

## 16. Bootstrap / cold start

A new model has UNKNOWN empirical capability.

Bootstrap order:
1. declared executable capability proves only protocol eligibility;
2. optional external eval prior may be stored as prior evidence with provenance;
3. bounded Foundation eval tasks establish local evidence;
4. real verified work updates empirical evidence;
5. do not route CRITICAL work to an UNKNOWN model solely to gather samples.

Avoid forced production exploration. Exploration belongs to explicit eval/probe workloads where possible.

## 17. Evidence aging

Model/provider behavior changes. Evidence must not be immortal.

Future implementation must define:
- model identity/version key;
- adapter/protocol revision;
- evidence recency;
- invalidation after model/catalog change;
- whether old evidence decays or is partitioned by version.

Until those are defined, do not claim statistically current completion probabilities.

## 18. Explainability

Every RouteDecision should be explainable with bounded reason codes, e.g.:

```
CAPABILITY_MATCH
PRIVACY_OK
HEALTH_ONLINE
QUOTA_UNKNOWN_ALLOWED
SUFFICIENCY_STRONG
PRESERVE_SCARCE_SEARCH_PROVIDER
LOCAL_UNLIMITED_CAPACITY
LOWER_SUCCESS_LATENCY
ESCALATED_AFTER_VERIFICATION_FAILURE
```

Do not expose raw prompts, provider bodies, secrets, or private content.

Operator UI should distinguish:
- policy order;
- current eligibility;
- empirical sufficiency;
- scarcity reason;
- actual execution choice.

## 19. Required tests before promotion

### Requirement tests
- aliases normalize correctly;
- host critical flag cannot be weakened by prompt/model;
- unknown structural values remain unknown;
- bounded metadata only.

### Hard-gate tests
- LOCAL_ONLY excludes every Cloud candidate;
- missing capability excludes candidate;
- known context insufficiency excludes candidate;
- ONLINE + UNKNOWN quota remains eligible;
- <= canonical quota threshold is suppressed;
- PAID fails closed without accounting;
- excluded attempted binding cannot repeat.

### Sufficiency tests
- HTTP success alone does not promote capability quality;
- verified completion updates correct bucket;
- infrastructure failure does not count as capability failure;
- verification failure does;
- sparse evidence does not become fake high-confidence probability;
- model/version change does not silently inherit incompatible evidence.

### Scarcity tests
- sole SEARCH-capable provider is preserved for CHAT when another sufficient CHAT candidate exists;
- adding second SEARCH provider reduces preservation pressure;
- removing it restores pressure;
- scarcity never bypasses hard capability/privacy gates;
- UNKNOWN quota behavior is deterministic.

### Local tests
- Local may beat Cloud for LOW work when sufficient;
- Local may beat Cloud for HIGH work only with evidence;
- Cloud may beat Local when Local is insufficient;
- local_required always wins as restriction;
- no implicit terminal fallback remains after migration.

### Failure/escalation tests
- 429 -> lateral sufficient failover;
- provider 5xx -> lateral sufficient failover;
- context-limit -> larger-context candidate;
- capability failure -> stronger evidence band;
- verification failure -> stronger evidence band;
- policy denial -> no fallback bypass;
- UNKNOWN failure has bounded attempts;
- no infinite route cycle.

### Persistence/concurrency tests
- concurrent evidence updates are atomic;
- restart preserves evidence;
- corrupt evidence fails closed or degrades to UNKNOWN, never fabricated success;
- route policy remains reconstructible;
- old schema migrates additively.

### Agent E2E
- ordinary LOW task selects sufficient low-scarcity route;
- hard task bypasses known-insufficient small Local;
- scarce SEARCH provider is preserved during ordinary CHAT;
- tool-followup does not accidentally create a second contradictory policy;
- actual capability failure escalates once;
- verified task completion records task-level evidence.

## 20. Promotion gates

Do not replace current routing in one patch.

Recommended sequence:
P0 — record this design only. No runtime change.
P1 — add RequestRequirements + tests, observation-only.
P2 — add capability evidence schema/store + deterministic eval ingestion, no selection effect.
P3 — add shadow sufficiency decisions and compare against current router.
P4 — implement scarcity evidence in shadow mode.
P5 — unified Local/Cloud candidate selection in shadow mode.
P6 — enable minimum-sufficient selection for LOW/non-critical work.
P7 — enable escalation classification.
P8 — expand to HIGH after measured regressions are acceptable.
P9 — CRITICAL only after verification policy and evidence-aging/versioning are closed.
P10 — only then consider PAID participation after authoritative monetary accounting.

Each phase requires rollback by disabling the new selector without deleting evidence.

## 21. Decisions intentionally deferred

Do not invent these values yet:
- exact success probability thresholds;
- minimum sample counts;
- confidence interval method;
- exact LOW/MEDIUM/HIGH structural thresholds;
- energy weighting;
- Local occupancy weighting;
- quota-plentiful/scarce bands beyond current hard near-empty gate;
- benchmark providers and benchmark-to-runtime calibration;
- model-version evidence decay duration;
- PAID currency/accounting conversion;
- whether phase-specific capability selection ever becomes justified.

These require measurement/eval evidence. Hardcoding them now would be ad-hoc.

## 22. Relationship to existing records

- SETTINGS_SEMANTICS.md: current operational semantics; remains authoritative for current UI/runtime.
- CURRENT_STATE.md: current verified implementation; do not claim this future design there until promoted.
- docs/future/SCARCITY_AWARE_ROUTING.md: narrower source concept for capability scarcity; retained unchanged.
- provider_catalog.py: executable provider/model declarations, not intelligence rankings.
- routing_capabilities.py: capability namespace and support gate.
- routing.py: current policy/runtime selector to evolve incrementally.
- compute_routing.py: current Cloud/Local bridging point.
- routed_agent_model.py: Pydantic AI model adapter and real fallback loop.
- provider_quota.py / provider_observer.py / provider_recovery.py: authoritative quota/health observation boundaries.

## 23. Compact load order for future implementation work

When implementing this design, load only:
1. docs/SETTINGS_SEMANTICS.md
2. docs/future/CAPABILITY_AWARE_ROUTING_DESIGN.md
3. docs/future/SCARCITY_AWARE_ROUTING.md
4. src/ai_foundation/routing.py
5. src/ai_foundation/compute_routing.py
6. src/ai_foundation/routing_capabilities.py
7. src/ai_foundation/routed_agent_model.py
8. provider registry/quota/observer modules only when touching those boundaries
9. corresponding focused tests

Load CURRENT_STATE.md/ROADMAP.md for promotion/status reconciliation, not as a substitute for this detailed design.

## 24. Invariants summary

R1 Hard policy beats preference.
R2 Capability eligibility precedes optimization.
R3 UNKNOWN evidence is never fabricated.
R4 Local and Cloud share the same capability/sufficiency framework.
R5 Local/Cloud identity is not intelligence evidence.
R6 Minimum-sufficient means reliability-sufficient, not smallest parameter count.
R7 Scarcity preserves strategically rare capacity only among sufficient alternatives.
R8 Latency cannot compensate for known capability insufficiency.
R9 Infrastructure failure permits lateral failover; capability/verification failure triggers escalation.
R10 No unbounded fallback loops.
R11 Model output cannot grant authority, lower privacy, or authoritatively rate itself.
R12 Runtime evidence contains no prompt/response/tool payload/secret content.
R13 Current production behavior remains distinguishable until each promotion gate passes.
R14 Paid execution remains fail-closed until authoritative accounting exists.
R15 Reset text is not recovery evidence.
R16 Stronger model is not selected merely because it exists; weaker model is not selected merely because it is cheaper.
R17 Critical work requires stronger evidence and verification, not merely larger parameter count.
R18 Provider/model/version changes must not silently inherit incompatible quality evidence.
R19 Persisted policy order remains deterministic and explainable.
R20 Every behavior-changing routing decision must be regression-tested before canonical promotion.
