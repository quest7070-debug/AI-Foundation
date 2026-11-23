# Future post-completion architecture

Status: **FUTURE CANON / NOT CURRENT IMPLEMENTATION**

Recorded: 2026-09-27

This document defines post-completion directions after the current M1 AI Foundation reconstruction program.

It does not reopen `END_GOAL.md`, does not convert intentionally unavailable authority into a defect, and does not authorize implementation merely because a future direction is desirable.

`FUTURE_AUTONOMOUS_SOFTWARE_OPERATIONS.md` remains the detailed canonical source for continuous autonomous software operations. This document extends the surrounding architecture and must not flatten or replace that lifecycle.

## 1. Thin Foundation remains the primary architecture rule

Foundation should own only product-specific concerns that cannot safely be delegated:

- authority and approval;
- privacy and budget;
- host-selected resource scope;
- effect identity/reconciliation;
- credential boundaries;
- product-specific composition;
- independent verification/readback;
- minimal replaceable integration adapters.

Generic mechanisms should remain owned by mature OSS where practical.

Candidate components must be evaluated as:

- KEEP;
- REPLACE;
- ADD;
- DO NOT ADD;
- RESEARCH ONLY.

Adoption must reduce custom code, drift or maintenance burden rather than merely add another abstraction layer.

Do not create a Foundation-owned replacement for a mature generic search engine, vector store, RAG framework, MCP transport, scheduler, policy engine, observability system, browser engine, desktop engine, notebook runtime or SQL engine without evidence that the adopted OSS boundary cannot satisfy a concrete requirement.

Possible future ecosystem evaluations include search aggregation such as SearXNG; knowledge/RAG composition using Qdrant or pgvector with LlamaIndex/Haystack-class frameworks; and observability/evaluation systems such as OpenTelemetry/Langfuse-class components.

These are evaluation candidates, not implementation claims.

## 2. Project World Model / Development Intelligence

The long-term development system should connect:

Canonical truth
<-> architecture
<-> source files
<-> symbols
<-> configuration
<-> dependencies
<-> tests
<-> runtime evidence
<-> external services and OSS.

The purpose is not to generate more documentation.

The purpose is to make semantic drift mechanically detectable and to reduce hidden knowledge required to safely modify the system.

### Symbol-level knowledge

For important constants and settings, the system should be able to recover or generate:

- semantic meaning;
- why the value exists;
- why the current value was selected;
- safe range or valid domain;
- owner/authority;
- change impact;
- relationships to other symbols;
- external OSS/service coordination;
- tests and runtime evidence that constrain the value.

For functions/classes/modules:

- purpose;
- responsibility;
- invariants;
- forbidden responsibilities;
- callers/callees/dependencies;
- authority assumptions;
- failure semantics;
- replacement possibilities;
- relevant tests and evidence.

### Environment knowledge

The project model should explicitly represent integration contracts such as:

- LibreChat;
- ToolHive;
- Hatchet;
- Cedar;
- llama-swap;
- Docker;
- launchd;
- Keychain;
- ports/listeners;
- filesystem roots;
- credentials;
- MCP schemas;
- startup ordering;
- timeout/retry rationale;
- persistence ownership;
- external version assumptions.

### Generation model

Do not manually maintain all symbol descriptions as prose.

Preferred direction:

source/static analysis
-> symbol/config/dependency extraction
-> structured graph
-> AI semantic/rationale enrichment
-> comparison against canonical contracts
-> CI drift detection
-> human review where semantic authority changes.

Potential technologies such as SCIP, Griffe, Import Linter, Semgrep, CUE/StrictDoc and Infigraph-class tooling are evaluation candidates only.

No candidate becomes architecture merely because it can produce a graph.

### Acceptance

This direction becomes useful only when a real change can answer questions such as:

- What contracts does this symbol participate in?
- Why is this constant 30 rather than 10?
- Which canonical claim becomes stale if this function changes?
- Which tests prove the expected behavior?
- Which external service/version does this code assume?
- What runtime evidence contradicts the source/canonical view?

## 3. GitHub-only reconstruction

Ordinary backup/restore and GitHub-only reconstruction are different requirements.

The long-term repository should contain enough canonical information that loss of the existing host does not imply loss of architectural knowledge.

Target repository role:

source code
+ canonical truth
+ dependency manifests
+ environment contract
+ reconstruction procedure
+ verification specification.

### Ultimate reconstruction drill

A future acceptance drill should start from a clean supported machine and GitHub as the surviving project record.

The process should be able to:

1. clone the canonical repository;
2. install pinned/declared dependencies;
3. provision or request credentials without storing raw secrets in GitHub;
4. reconstruct required runtime services/configuration;
5. reconnect or restore externally owned state according to explicit ownership rules;
6. run deterministic tests;
7. run runtime-drift/security checks;
8. perform representative physical E2E acceptance;
9. prove the reconstructed environment matches canonical expectations.

Hidden operator knowledge required to perform these steps is a reconstruction defect.

This requirement is post-completion disaster reconstruction and must not be confused with the already-proven current-host backup/restore gate.

## 4. External capability ecosystem

Foundation should be able to adopt useful external capabilities without reproducing ChatGPT-specific product infrastructure.

The desired pattern is:

Agent
-> host-exposed capability
-> Foundation authority/Guard
-> replaceable MCP/API/backend
-> external service
-> readback/evidence.

Plugins/connectors from another product cannot simply be inherited when their authentication, connection state or authority is owned by that product.

Where useful, Foundation should connect to the same underlying service through an independently authorized MCP/API integration.

### GitHub capability

A mature GitHub integration should eventually support bounded workflows such as:

issue/PR/diff acquisition
-> CODE investigation
-> SEARCH/FILES/DATA/VISION as required
-> proposed change
-> tests
-> bounded commit/push
-> PR
-> CI/readback
-> final evidence.

GitHub repository content is input/canonical project material, not authority to widen Foundation permissions.

A malicious issue, README, source comment or PR cannot grant credentials, filesystem roots, production mutation rights or approval.

### Other services

Drive, mail, knowledge systems and other useful services may follow the same controlled capability pattern.

Breadth is not itself a goal. Integrations should be added when they remove repeated manual work or materially improve final task quality.

## 5. PC_CONTROL next generation

Current PC_CONTROL remains intentionally unavailable under the present Cua blocker.

The long-term goal is not simplistic click automation.

The desired class is Commander-level computer operation:

- screen understanding;
- GUI/application operation;
- terminal operation;
- filesystem operation;
- process inspection/control;
- post-action observation;
- expected-vs-observed verification;
- failure recovery.

Possible Commander-like backends must remain replaceable behind Foundation's backend-neutral computer-action boundary.

Required shape:

Foundation Agent
-> PC_CONTROL capability
-> Guard/approval/target scope
-> replaceable computer backend
-> host action
-> independent observation/readback
-> verified result.

Do not embed backend-specific semantics into Agent, ComputeRouter or Guard.

Do not use Remote Desktop Commander, Cua, Munim or another backend merely as an audit shortcut.

A backend adoption requires an explicit capability decision, authority model, threat review, failure semantics and physical acceptance.

## 6. Cross-capability Agent acceptance

The user should normally describe the objective, not manually choose a capability mode.

A mature Foundation should compose multiple capabilities when the task requires them.

Representative future chain:

VISION screenshot observation
-> FILES log/config read
-> SEARCH external evidence
-> CODE repository investigation
-> DATA aggregation/analysis
-> CODE change
-> tests/readback
-> final grounded answer.

GitHub and PC_CONTROL may later participate in the same chain after their own authority gates.

Cross-capability execution must not collapse authority boundaries.

Successful use of FILES does not imply CODE write authority.
Successful browser observation does not imply browser mutation.
Successful PC observation does not imply arbitrary desktop control.
A previous grant does not become ambient future authority.

## 7. Answer-quality baseline and ChatGPT Plus exit criterion

Feature parity alone is insufficient.

A Foundation that can invoke many tools but produces materially worse final answers is not an acceptable replacement for the user's current ChatGPT workflow.

The practical target is to make Foundation good enough that ChatGPT Plus is no longer required for ordinary personal use.

### Baseline

Use the current high-quality ChatGPT/GPT experience as an external quality baseline rather than assuming that a local model must intrinsically match the same raw model intelligence.

Foundation may compensate through:

- better evidence retrieval;
- specialist tools;
- controlled execution;
- persistent project knowledge;
- local/private context;
- independent verification;
- better routing.

The relevant metric is the quality of the final result.

### Evaluation set

Maintain a representative regression set of real tasks, preferably approximately 20–30 or more prompts covering:

- ordinary reasoning;
- research;
- coding;
- data analysis;
- file understanding;
- image understanding;
- multi-tool work;
- long multi-turn development;
- canonical adherence;
- failure/recovery situations.

Compare at least:

- current external baseline;
- Foundation cloud path;
- Foundation local path where relevant.

### Evaluation dimensions

Assess:

- factual errors;
- instruction following;
- depth/insight;
- evidence quality;
- unsupported claims;
- semantic drift;
- tool selection;
- canonical adherence;
- long-horizon consistency;
- final usefulness.

Do not optimize only for benchmark scores or model-judge preference.

Real user tasks and independently checkable outcomes have higher value.

### Exit condition

A future Plus-exit decision should be evidence-based.

The target is:

A GPT-class baseline for answer quality, with Foundation's search, specialist tools, persistent knowledge and execution capability producing final work that is not materially worse on the user's representative task set.

Model/routing/tool changes should rerun this quality regression so a cheaper/faster architecture cannot silently degrade the system below the accepted baseline.

## 8. Relationship to autonomous software operations

`FUTURE_AUTONOMOUS_SOFTWARE_OPERATIONS.md` remains authoritative for the autonomous lifecycle:

Observe
-> Detect
-> Propose
-> Plan
-> Authorize
-> Execute
-> Verify
-> Record
-> Reflect
-> Stop/Wait.

Valid terminal states include:

- NO_CHANGE;
- WAIT;
- NEEDS_HUMAN;
- BLOCKED.

The Project World Model, GitHub capability, reconstruction specification, answer-quality evaluation and cross-capability execution described here are supporting architecture for that future.

They do not weaken its convergence requirements.

Autonomous software operations must still preserve:

- bounded objectives;
- stop conditions;
- plan stability;
- concurrency safety;
- independent acceptance;
- authority separation;
- ambiguous-effect recovery;
- resource bounds;
- provider degradation behavior;
- change isolation;
- production separation;
- feedback integrity;
- no-change convergence;
- auditability.

## 9. Promotion rule

No section in this document is permission to implement everything at once.

Promotion remains:

requirement
-> architecture/ADR
-> OSS evaluation
-> bounded implementation
-> deterministic tests
-> adversarial/failure tests
-> real-host E2E
-> independent verification
-> canonical update
-> release.

Prefer deleting/replacing custom code over growing Foundation when mature OSS can own the generic mechanism.

No big-bang future architecture phase.

## 10. Replaceable local-compute backends and Ollama interoperability

The current production local-compute path remains llama-swap. Installing Ollama does not currently register Ollama models into Foundation local-compute inventory, and Ollama is not a current production inference backend.

A future local-compute evolution may evaluate Ollama as an additional replaceable backend behind the existing Foundation local-compute/routing boundary.

The desired outcome is not to make Foundation depend on Ollama or to duplicate llama-swap without evidence. The desired outcome is backend-neutral local model interoperability, where a user may install or expose a model through a supported local runtime and Foundation can, after host-owned discovery and validation, represent it as a bounded local-compute candidate.

Potential future flow:

local runtime (llama-swap / Ollama / future backend)
-> backend-specific discovery adapter
-> normalized Foundation local-compute inventory
-> host-owned capability/role metadata
-> ComputeRouter
-> backend-specific execution adapter
-> health/failure feedback
-> observable inference identity.

Important constraints:

- local runtime discovery does not itself grant semantic roles or execution authority;
- model names or metadata supplied by Ollama or another backend are evidence, not trusted authority;
- Foundation remains responsible for normalized capability/role policy and routing;
- backend-specific semantics must not leak into Agent, Guard or the general ComputeRouter contract;
- credentials, filesystem/model-cache access and model-management authority remain host-controlled;
- installing Ollama alone must not silently widen Foundation capability or authority;
- duplicate model storage and duplicate runtime management should be avoided where practical;
- llama-swap remains the current production backend unless a separately promoted decision replaces or complements it.

Before promotion, compare Ollama and llama-swap on at least:

- model discovery and inventory truth;
- load/unload and memory behavior;
- model add/remove/replace lifecycle;
- multimodal support;
- structured/tool-capable inference where relevant;
- health and failure observability;
- restart reconstruction;
- resource control and concurrency;
- model-cache/storage duplication;
- operational complexity;
- API stability;
- portability across intended hosts;
- compatibility with Foundation semantic role routing.

Ollama should be classified KEEP / ADD / REPLACE / DO NOT ADD / RESEARCH ONLY through measured evidence. It must not be added merely because it is installed or popular.

A useful future acceptance case is:

install or expose a model through an approved local backend
-> Foundation discovers the concrete model
-> host policy assigns or approves an eligible semantic role
-> the model becomes routable without hard-coding it into Foundation
-> real inference executes through that backend
-> health/model identity is observable
-> removal or backend loss removes the route without stale inventory.

This is a post-completion architecture direction, not a current implementation claim or permission to modify the production local-compute path.

## 11. Project World Model — first code-intelligence backend decision

Status: FUTURE ARCHITECTURE DECISION / EVALUATED BACKEND / NOT CURRENT PRODUCTION CAPABILITY

The first evaluated code-intelligence backend for the Project World Model is
Infigraph.

This decision does not make Infigraph a new source of canonical truth.
Existing Foundation canonical documents remain authoritative for product
intent, authority, policy, architectural decisions, accepted runtime state,
and completion claims.

Infigraph is a replaceable derived code-intelligence backend.

### 11.1 Evidence-based classification

Current classification:

- Infigraph: KEEP as the first code-intelligence backend candidate.
- Infigraph tree-sitter graph/index/query surface: accepted for the next
  Project World Model implementation stage.
- SCIP enrichment: OPTIONAL ENRICHMENT / NOT REQUIRED for initial adoption.
- Infigraph installer-driven agent integration: DO NOT ADOPT as the
  Foundation integration boundary.
- Infigraph-owned canonical/spec/session authority: DO NOT ADOPT.
- Foundation-owned AST parser, generic call graph, dependency graph, generic
  repository indexer, or generic test-association engine: DO NOT BUILD while
  the backend satisfies the required contract.

This classification is based on an isolated evaluation against real
AI-Foundation source, tests, scripts, and previously captured ground-truth
relationships.

The evaluation demonstrated useful code relationships including:

- ComputeRouter.choose callers across routing tests, performance tests, and
  lifecycle scripts;
- GuardCore.execute impact across Guard, Cedar, ToolHive, credential,
  crash/recovery, coding, reconciliation, and related safety boundaries;
- LlamaSwapExecution.chat callers across adapter tests and operational
  evidence/lifecycle scripts;
- incremental indexing fast enough for the current repository scale;
- useful TESTED_BY and impact relationships without requiring Foundation to
  implement its own generic graph engine.

The evaluation also demonstrated limitations that must remain explicit:

- generic code intelligence does not establish canonical product truth;
- symbol-level resolution is not complete for every relationship;
- class-level queries may be weaker than method-level queries;
- Python SCIP auto-enrichment did not add useful evidence in the isolated
  evaluation and must not be treated as a prerequisite;
- ordering or heuristic graph results must not be treated as deterministic
  semantic authority;
- watcher, agent configuration, MCP registration, memory/session features,
  and other bundled product behavior are outside the minimal Foundation
  backend contract unless separately promoted by evidence.

### 11.2 Required architecture boundary

The Project World Model should use three distinct layers:

1. Code Intelligence Backend
   - replaceable backend;
   - initially Infigraph;
   - owns generic source-derived graph/index/query mechanisms;
   - may provide symbols, calls, imports, references, file dependencies,
     impact relationships, test relationships, and structural search;
   - does not own Foundation authority or canonical decisions.

2. Foundation Semantic Linker
   - thin Foundation-specific layer;
   - links backend-derived code identities to existing canonical claims,
     architectural constraints, runtime evidence, external-service/version
     assumptions, authority boundaries, and verification evidence;
   - stores derived links/provenance rather than creating a second canon;
   - must make uncertainty and missing links explicit.

3. Development Context Compiler
   - thin Foundation-specific layer;
   - takes a bounded development/change request;
   - selects only relevant canonical claims, linked symbols/dependencies,
     affected tests, runtime evidence, and known failure evidence;
   - produces bounded task-local context for a coding or review agent;
   - does not become a generic coding-agent framework or independent memory
     system.

Conceptually:

human/change request
-> existing canonical truth
-> Development Context Compiler
-> Foundation Semantic Linker
-> replaceable code-intelligence backend
-> affected code/tests/evidence
-> bounded implementation/review context
-> implementation/diff
-> deterministic tests + runtime/physical verification
-> canonical update only when actual decision/state changed

### 11.3 Thin Foundation constraints

Foundation must not duplicate mature generic code-intelligence mechanisms.

Do not implement Foundation-owned replacements for:

- AST/tree-sitter parsing;
- SCIP parsing/import;
- generic symbol extraction;
- generic import/call/dependency graph construction;
- generic repository indexing;
- generic semantic code search;
- generic blast-radius traversal;
- generic test-association graphing;
- generic graph storage/query engines.

Foundation-specific code is justified only where it connects generic
code-derived facts to Foundation-owned semantics that a generic backend
cannot know.

Examples include:

- which canonical statement constrains a symbol;
- why a constant has its accepted value;
- which authority boundary a function participates in;
- which physical/runtime proof supports a current claim;
- which external service/version assumption constrains an implementation;
- whether a code-derived relationship contradicts current canonical truth.

### 11.4 Integration constraints

Initial integration must remain removable and bounded.

Do not require the upstream all-in-one installer as the Foundation
integration contract.

Do not make automatic mutation of agent configuration, MCP registration,
global instructions, user-home configuration, or background watcher state a
precondition for Project World Model operation.

Prefer an explicit Foundation-owned adapter that invokes the backend through
a stable CLI/API/MCP contract with:

- explicit repository root;
- explicit state/index location where supported;
- bounded timeouts;
- deterministic read/query operations;
- explicit refresh/index operation;
- health/readiness reporting;
- backend version evidence;
- failure isolation;
- no authority inheritance from backend metadata.

Automatic file watching may be evaluated later, but correctness must not
depend on an implicit watcher. A deterministic explicit refresh path must
exist.

### 11.5 SCIP policy

SCIP remains an optional precision enhancement.

Initial Project World Model adoption must not modify Foundation's Python
configuration merely to satisfy automatic SCIP enrichment.

SCIP may be promoted later only if a controlled side-by-side evaluation
shows material improvement in Foundation-relevant precision or recall over
the accepted baseline.

If evaluated again, prefer an explicit:

source/compiler indexer
-> SCIP artifact
-> backend import
-> measured differential

rather than relying on opaque automatic enrichment.

Failure or absence of SCIP must degrade to the accepted generic
code-intelligence backend rather than making the Project World Model
unavailable.

### 11.6 Promotion gates

The backend is not a current Foundation production capability merely because
it has passed isolated evaluation.

Promotion remains staged:

Evaluated
-> Contracted
-> Adapter implemented
-> Used by Semantic Linker
-> Tested
-> Failure-tested
-> Drift-tested
-> Rebuild-tested
-> Production-promoted if still justified

Before production promotion, verify at minimum:

- known Foundation ground-truth relationship recall;
- false-positive behavior on real changes;
- stale-index detection and explicit refresh;
- backend unavailable/corrupt-index behavior;
- backend upgrade/version drift;
- clean-machine reconstruction;
- removal/replacement without loss of canonical truth;
- bounded resource use;
- no unintended authority, credential, agent-config, or global-state
  mutation.

### 11.7 First implementation target

The next implementation target is not a larger knowledge graph.

It is the smallest replaceable code-intelligence contract required by the
Foundation Semantic Linker.

The first contract should be able to answer bounded questions such as:

- resolve a source symbol or file identity;
- return direct callers/references;
- return bounded impact relationships;
- return relevant tests;
- return file/module dependencies;
- report backend/index identity and freshness;
- explicitly report unavailable/unknown rather than inventing a
  relationship.

Only after this contract is stable should Foundation-specific semantic links
and Development Context Compiler behavior be implemented.


<!-- DEVELOPMENT_INTELLIGENCE_ESTABLISHED_V1 -->
## Established Development Intelligence slice

The minimum Development Intelligence slice described in this document has
now been physically established.

Established implementation:

- `src/ai_foundation/code_intelligence.py`
  defines the replaceable code-intelligence contract.
- `src/ai_foundation/infigraph_adapter.py`
  implements the first backend adapter against Infigraph `3.2.16`.
- `src/ai_foundation/semantic_linker.py`
  provides the thin Foundation-specific semantic-link layer.
- `src/ai_foundation/development_context.py`
  compiles bounded task-local development context from explicit semantic
  links and code-intelligence observations.

These established file-level obligations are machine-readable without adding
meaning beyond this Canon and the accepted human escalation policy:

```foundation-semantic
{"source":"src/ai_foundation/code_intelligence.py","subject":"src/ai_foundation/code_intelligence.py","subject_kind":"FILE","claim_kind":"architecture_boundary","purpose":"define the replaceable code-intelligence contract for bounded source-derived identity, relationship, test, dependency and freshness queries","ownership":"Foundation owns the contract boundary under higher Canon; a backend does not own Foundation authority","rationale":"keep generic code-intelligence mechanisms replaceable and outside Foundation-specific semantic authority","failure_semantics":"report unavailable or unknown explicitly rather than inventing a relationship","side_effects":"NONE","change_impact":"changes must preserve existing Canon meaning and the replaceable backend boundary and require independent verification","evidence":["tests/test_code_intelligence.py"]}
```

```foundation-semantic
{"source":"src/ai_foundation/infigraph_adapter.py","subject":"src/ai_foundation/infigraph_adapter.py","subject_kind":"FILE","claim_kind":"backend_adapter_boundary","purpose":"implement the first replaceable code-intelligence backend adapter against Infigraph 3.2.16","ownership":"Foundation owns the adapter boundary; Infigraph output remains derived repository observation and does not own Foundation authority","rationale":"use a mature generic code-intelligence backend instead of implementing a Foundation-owned parser, graph, index or semantic search engine","failure_semantics":"fail closed when the backend is unavailable and require explicit refresh before freshness is established","side_effects":"may refresh or rebuild only backend-derived .infigraph state; that state is non-canonical and rebuildable","change_impact":"replacement or change must preserve the CodeIntelligencePort contract, canonical truth and independently verified failure and reconstruction behavior","evidence":["tests/test_infigraph_adapter.py"]}
```

```foundation-semantic
{"source":"src/ai_foundation/semantic_linker.py","subject":"src/ai_foundation/semantic_linker.py","subject_kind":"FILE","claim_kind":"semantic_authority_boundary","purpose":"provide the thin Foundation-specific layer linking backend-derived code identities to existing canonical claims, constraints and evidence","ownership":"Foundation owns the linking policy under higher Canon; semantic links are derived navigation and provenance and do not mint authority","rationale":"connect generic code-derived facts to Foundation-owned semantics without creating a second canon or generic graph engine","failure_semantics":"make uncertainty and missing links explicit and never infer missing canonical semantic obligations from code, tests, runtime or model output","side_effects":"NONE","change_impact":"changes must preserve Canon as the sole semantic authority and require independent verification of mapping, drift and fail-closed behavior","evidence":["tests/test_semantic_linker.py","tests/test_explainability.py"]}
```

```foundation-semantic
{"source":"src/ai_foundation/development_context.py","subject":"src/ai_foundation/development_context.py","subject_kind":"FILE","claim_kind":"development_context_boundary","purpose":"compile bounded task-local development context from explicit semantic links and code-intelligence observations","ownership":"Foundation owns context compilation under higher Canon; compiled development context is non-authoritative task-local context","rationale":"provide only relevant canonical claims, linked code, tests and evidence without becoming a generic coding-agent framework or independent memory system","failure_semantics":"missing or uncertain semantic/code-intelligence relationships remain explicit and cannot be promoted into canonical meaning","side_effects":"NONE","change_impact":"changes must preserve bounded non-authoritative context semantics and existing Canon meaning and require independent verification","evidence":["tests/test_development_context.py"]}
```

The established authority boundary remains unchanged:

- canonical documents, tests, and runtime evidence remain authoritative
  according to their existing roles;
- code-intelligence output is derived repository observation;
- semantic links are derived navigation/provenance and do not mint
  authority;
- development context is non-authoritative task-local context;
- model-extracted meaning is not silently promoted to canon.

The implementation deliberately does not add a Foundation-owned AST parser,
generic code graph, semantic code-search engine, graph database, independent
memory system, or second specification authority.

Physical verification has established:

- exact supported Infigraph version `3.2.16`;
- explicit full refresh before freshness is established;
- symbol references, impact, test association, and file dependencies;
- stale-source detection after repository source changes;
- recovery after explicit refresh;
- fail-closed behavior when the backend is unavailable;
- removal and reconstruction of backend-derived graph state;
- real end-to-end compilation for
  `src/ai_foundation/compute_routing.py::ComputeRouter::choose`;
- bounded context output;
- backend relation spelling is not used to infer query semantics;
- full Foundation regression of `1123 passed, 10 skipped`.

`.infigraph/` is rebuildable backend-derived state and is intentionally not
canonical repository state.

This establishes the minimum Development Intelligence / Project World Model
slice. It does not promote Infigraph itself to Foundation authority and does
not require future development to remain coupled to Infigraph. The
`CodeIntelligencePort` boundary remains the replacement boundary.

Further knowledge-graph expansion, automatic semantic inference, watcher-
dependent correctness, generic coding-agent frameworks, and additional
backend breadth remain outside this minimum established slice.


<!-- DEVELOPMENT_EXPLAINABILITY_HIERARCHY_V1 -->

## Development explainability hierarchy and implementation gate

The Project World Model / Development Intelligence direction is extended into
a repository-wide development-explainability contract.

The purpose is not to create another prose catalog or another source of truth.
The purpose is to make every meaningful implementation element traceable to
its reason for existing, its relationships, and the evidence that constrains
it, so that redundant behavior, accidental complexity, bugs, unsafe edits,
and development drift can be detected before implementation proceeds.

The required hierarchy is:

`product goal`
-> `canonical requirement / invariant`
-> `decision / architectural constraint`
-> `architecture / subsystem`
-> `capability / authority boundary`
-> `module / file`
-> `class / protocol / interface`
-> `function / method`
-> `constant / configuration / state / variable`
-> `call / import / read / write / dependency relations`
-> `test / verification contract`
-> `runtime evidence / attestation`

The hierarchy MUST also be traversable in the reverse direction.

For example:

- a product requirement must be traceable down to the implementation and
  evidence that realizes it;
- a function must be traceable upward to the responsibility and canonical
  constraint that justify it;
- a constant must expose what it means, why the current value exists, who or
  what owns that value, where it is consumed, what changing it affects, and
  what tests/evidence constrain it;
- a variable must expose its scope, producers/writers, consumers/readers,
  relevant data-flow relationships, and semantic role;
- a code path must expose relevant callers, callees, dependencies,
  authority assumptions, side effects, failure semantics, tests, evidence,
  and removal/change impact.

### Truth and derivation boundary

Different layers have different authority.

1. Product intent, requirements, invariants, architectural decisions and
   authority boundaries come only from the existing canonical repository and
   accepted project decision process.

2. Source structure, symbols, imports, calls, reads, writes, dependencies,
   references and test relationships are reproducible source-derived facts.
   They are derived observations, not canonical authority.

3. Semantic explanations or rationale inferred by an AI are derived
   annotations. They MUST retain provenance and confidence/uncertainty and
   MUST NOT silently become canonical truth.

4. Runtime evidence describes observed reality. It can prove, contradict or
   make a canonical claim stale; it cannot silently rewrite the intended
   canonical claim.

5. Missing explanation or mapping is represented explicitly. The system must
   not invent a relationship in order to make coverage appear complete.

### Element classification

Every explainability subject must have an explicit state:

- `MAPPED` — semantic purpose and required relationships are grounded in
  canonical/source/test/evidence facts;
- `PARTIAL` — some required relationships or rationale are known, with the
  missing fields explicit;
- `UNMAPPED` — no sufficient semantic mapping exists yet;
- `CONFLICT` — authoritative intent and source/test/runtime evidence disagree;
- `DERIVED_ONLY` — the element is fully identified structurally but has no
  independent canonical semantic obligation.

`DERIVED_ONLY` is expected for many local implementation details and is not a
second-class failure if their role and data flow are mechanically recoverable
and they do not carry independent policy/authority semantics.

A local variable that materially controls behavior, authority, persistence,
routing, failure handling, verification, external effects or an accepted
constant/invariant may not be hidden behind `DERIVED_ONLY` merely because it
is local to one function.

### Local-variable policy

Do not create a hand-maintained canonical catalog containing every local
variable.

Local variables belong to a reproducible source-derived inventory. Their
identity is scoped by the containing source/module/class/function context.
Their source location is observation metadata rather than permanent semantic
authority.

For each local variable the generated development view should recover, where
applicable:

- containing scope;
- assignment/write sites;
- read/consumer sites;
- producer/callee relationship;
- value flow relevant to outputs, state, effects or branches;
- semantic role grounded from surrounding canonical/source facts;
- affected tests and downstream impact.

If a semantic role cannot be grounded, report it as unknown rather than
inventing an explanation.


<!-- EXPLAINABILITY_SEMANTIC_CONTRACT_V1 -->

### Canon-native semantic obligation contract

Repository explainability MUST NOT infer canonical semantic obligations from
source names, AST shape, docstrings, comments, keyword matching, model output,
runtime observations, test names, or derived code-intelligence relationships.

A source element has an independent semantic explanation obligation only when
that obligation is explicitly declared by existing Canon.

The machine-readable representation is a `foundation-semantic` block colocated
with the canonical statement that owns the obligation.

Required fields are:

- `source`: exact repository-relative source path
- `subject`: exact CodeIntelligence subject identity
- `subject_kind`: exact CodeIntelligenceSubjectKind
- `claim_kind`: canonical claim kind
- `purpose`: explicit canonical purpose
- `ownership`: explicit canonical owner/authority
- `rationale`: explicit canonical rationale, or explicit `NOT_APPLICABLE`
- `failure_semantics`: explicit canonical failure semantics
- `side_effects`: explicit canonical side-effect semantics, or explicit `NONE`
- `change_impact`: explicit canonical change/removal impact
- `evidence`: zero or more explicit repository evidence references

Rules:

1. The block is Canon, not a generated catalog, cache, graph, runtime record,
   or AI annotation.
2. It MUST be colocated with canonical prose establishing the same meaning and
   MUST NOT introduce a semantic claim absent from that Canon.
3. Source, subject and subject_kind use exact identity. Fuzzy matching,
   basename/stem inference, keyword inference, docstring inference and
   model-based matching are forbidden.
4. Missing semantic fields remain missing and MUST NOT be inferred.
5. `NOT_APPLICABLE` and `NONE` are explicit canonical assertions, never
   defaults.
6. Exact source-path references outside a `foundation-semantic` declaration
   remain navigation/provenance only and MUST NOT mint semantic authority.
7. Source-derived inventory remains structurally complete independently of
   semantic obligations.
8. `MAPPED` requires an explicit valid declaration plus required fresh
   source/test/evidence relationships. Canon declaration alone does not prove
   implementation conformance.
9. Malformed or incompatible duplicate declarations, missing exact
   source/subject, stale required evidence, and contradictions fail closed.
10. Development Intelligence remains derived and non-authoritative and may
    parse and traverse declarations but may not invent or silently promote
    them.
11. Change preflight blocks an affected explicit semantic obligation that is
    missing, partial, stale, conflicting, or lacks deterministic verification.
12. Post-change drift rebuilds canonical declarations and derived source
    relationships and reports disappeared, orphaned, stale or conflicting
    affected relationships.
13. No hand-maintained repository-wide function/variable/constant/process
    catalog is introduced.
14. Self-Repair remains blocked until every Canon-declared authority/invariant
    obligation is grounded and no independently identified
    authority/invariant-bearing implementation element remains unexplained.
15. For this gate, "independently identified" does not authorize semantic
    inference from source. The deterministic candidate set is the union of
    valid `foundation-semantic` declarations and exact current-Canon source
    or symbol identities that resolve in the complete source-derived
    inventory. Each candidate is classified only from Canon: a valid explicit
    declaration may become MAPPED/PARTIAL/CONFLICT through derived evidence;
    an exact Canon reference without a complete colocated semantic declaration
    is UNMAPPED when Canon explicitly states that the referenced implementation
    element owns or enforces authority, policy, an invariant, externally
    visible behavior, failure handling, verification, persistence, routing or
    external effects; otherwise it is DERIVED_ONLY navigation/provenance.
    Future/proposed/superseded/historical evidence text does not create a
    current obligation. Missing or ambiguous current-Canon ownership remains
    UNMAPPED and fail-closed rather than being guessed. This classification is
    derived/rebuildable and MUST NOT become a hand-maintained semantic catalog.

This contract defines representation and validation only. It does not itself
declare an implementation element MAPPED, automatically convert existing
prose into semantic fields, or weaken the repository-wide baseline gate.

#### Machine-readable grammar

A declaration is exactly one Markdown fenced code block with info string `foundation-semantic`. Its body is one strict JSON object. JSON is syntax only; the surrounding canonical document remains authoritative.

The object contains exactly the eleven fields already defined above. The first ten values are non-empty JSON strings. `evidence` is an array of zero or more unique non-empty strings. Extra or duplicate keys, other value types, comments, trailing data, nesting, and implicit defaults are invalid and fail closed.

The canonical locator is the repository-relative Markdown source path plus the 1-based line number of the opening fence. The parser records it as provenance; a declaration cannot supply or override its locator.

`subject_kind` exactly equals a defined `CodeIntelligenceSubjectKind` value. `source` is a normalized repository-relative POSIX path: not absolute, no `.` or `..` segments, and no backslashes. `subject` is opaque exact identity and is never normalized, guessed, or fuzzy-matched.

Within one canonical parse, duplicate `(source, subject, subject_kind)` identities are invalid, whether identical or conflicting. Prose, examples, ordinary code fences, and source-path references outside an exact `foundation-semantic` fence never create declarations.


### Repository-wide baseline gate

Before further Foundation self-development, self-repair or autonomous
software-operation implementation proceeds, establish a repository-wide
explainability baseline.

The baseline requires:

1. deterministic source inventory for modules, classes, protocols/interfaces,
   functions, methods, public constants, configuration/state fields and
   scoped local variables;
2. deterministic structural relations for imports, calls, reads, writes,
   dependencies, references and relevant tests where the backend can recover
   them;
3. canonical lineage for every authority-bearing, invariant-bearing,
   externally visible or behavior-defining element;
4. explicit `MAPPED / PARTIAL / UNMAPPED / CONFLICT / DERIVED_ONLY`
   classification rather than silent omissions;
5. no unresolved `CONFLICT` on an implementation-driving boundary;
6. no unexplained authority-bearing or invariant-bearing implementation
   element;
7. bidirectional queries from canonical intent down to implementation/evidence
   and from a source element upward to purpose/authority;
8. reproducible refresh/rebuild so the inventory cannot become a manually
   maintained second canon;
9. change-impact queries that identify the relevant canonical claims,
   source relationships, tests and evidence before mutation;
10. deterministic drift checks after a change.

This is a development gate, not a requirement to duplicate all implementation
facts into Markdown.

### Change gate after baseline

After the repository-wide baseline is established, each proposed change must
compile the affected explainability subgraph before mutation.

Implementation is blocked when the affected subgraph contains:

- unresolved canonical conflict;
- missing authority/invariant ownership;
- stale or unavailable required source evidence;
- an unexplained behavior-defining element;
- an affected deterministic test/evidence boundary that cannot be identified.

The existing Safe Change Loop remains the bounded mutation mechanism after
this gate. Development Intelligence explains and bounds the change; it does
not gain mutation authority.

Practical self-repair therefore follows:

`canonical intent`
-> `explainability / traceability context`
-> `detected discrepancy`
-> `bounded repair proposal`
-> `Safe Change`
-> `independent verification`
-> `drift re-evaluation`

and not:

`model opinion`
-> `new requirement`
-> `self-approved mutation`.

<!-- SAFE_CHANGE_LOOP_ARCHITECTURE_V1 -->
## Safe Change Loop implementation direction

Following establishment of the minimum Development Intelligence slice, the
next architecture increment is a Safe Change Loop for Foundation
self-development.

This is intentionally one vertical capability rather than a sequence of
new internal frameworks.

Required composition:

1. existing canonical authority and Development Intelligence select and
   bound relevant development context;
2. the host supplies the authorized repository/write scope;
3. existing authorization and protected-resource controls gate mutation;
4. the change is applied through the narrowest existing mutation mechanism;
5. independent readback/diff establishes the observed effect;
6. affected tests and deterministic verification establish outcome;
7. effect/reconciliation state records VERIFIED, FAILED, or UNCERTAIN;
8. canonical state changes only through the existing canonical update path.

Git may provide repository-native diff and recovery primitives where they
fit, but Git itself does not mint authority and automatic destructive
reset/revert is not an agent permission.

The first implementation must not introduce general autonomous host
mutation. It is restricted to the Foundation repository and an explicit
owner-approved write boundary.

The architectural objective is rapid vertical completion with existing
components, not construction of a new autonomous-development framework.

<!-- SAFE_CHANGE_LOOP_PHASE1_VERIFIED_V1 -->

### Safe Change Loop Phase 1 verification

The architecture described above now has a physically verified minimum
vertical implementation.

The verified path reuses the existing Development Intelligence, CODE,
Guard, filesystem capability, and deterministic verification boundaries
rather than introducing a parallel self-modification framework.

Phase 1 evidence:

- isolated physical vertical E2E: 3 passed
- Safe Change integration slice: 54 passed
- full Foundation regression: 1134 passed / 10 skipped
- physical write/readback and before/after pytest verification succeeded
- context/target mismatch and repository escape remained fail-closed

The architectural next boundary is practical self-repair/self-maintenance:
an owner-approved real Foundation change executed through this same path.

Autonomous authority expansion remains explicitly out of scope.

<!-- SELF_REPAIR_PROMOTION_2026_10_06 -->
## Practical Self-Repair promotion

Status: PROMOTED FOR BOUNDED LOW-RISK CANON-PRESERVING REPAIRS

Repository-wide Explainability Closure is VERIFIED and the existing Safe Change
path is physically verified. Practical Self-Repair therefore requires no new
repair engine, mutation framework, authority system, graph, semantic catalog or
agent framework. It is the existing development path under a narrower admission
rule:

`existing Canon discrepancy`
-> `Explainability preflight READY`
-> `bounded repair proposal preserving existing Canon`
-> `Safe Change`
-> `independent deterministic verification`
-> `drift READY`.

Autonomous admission is limited to a repair whose required outcome is already
fully determined by current Canon, whose affected implementation obligations are
MAPPED and fresh, whose target is inside the explicitly authorized Foundation
repository/write scope, whose deterministic test/evidence boundary is known,
and whose change does not require new semantic meaning or authority.

The following remain Human Gates and MUST NOT be converted into autonomous
Self-Repair: new or ambiguous semantic meaning; wider authority or safety
boundary; new cost, paid/metered route or auto-top-up; new secret, credential or
permission; irreversible or destructive operation; external publication,
deployment or remote mutation; ambiguous canonical target; or any repair whose
preflight, effect verification or post-change drift is not READY/VERIFIED.

Recoverable technical uncertainty is handled through bounded investigation,
Canon reconstruction, accepted zero-additional-cost alternatives and
deterministic retry before human escalation. It does not authorize mutation
while the repair admission conditions are unresolved.

A failed or uncertain Safe Change remains FAILED/UNCERTAIN. Self-Repair does not
silently roll back a verified write, weaken tests, rewrite Canon to fit the
implementation, expand scope, or self-approve a Human Gate.

This promotion releases only the bounded low-risk path above. **Executor
ownership amendment (2026-11-13):** the previous designation of Kandev as
development execution plane is superseded by `SYSTEM_ROLE_BOUNDARIES.md`
and `END_GOAL.md`. GitHub owns Issue/PR/CI identity; existing Foundation
host/Guard/Harness owns development admission and verification. Local9B,
DSH→OpenCode and Codex OSS are admitted execution routes; Kandev is not a
permitted fallback or required dependency in the present owner workflow. Foundation Canon remains semantic authority;
the existing Guard/CODE/filesystem boundaries remain mutation authority.
The superseded statement is preserved in history, not a reactivation gate.

<!-- DEVELOPMENT_INTELLIGENCE_LIBCST_SIDECAR_2026_09_29 -->
## Development Intelligence — scoped-name sidecar decision

The repository-wide explainability investigation established a concrete
backend-composition boundary for Python scoped-name observations.

The accepted composition is:

`CodeIntelligencePort`
-> `CompositeCodeIntelligence`
-> Infigraph `3.2.16` for references / impact / tests / dependencies
-> LibCST `1.9.0` for scoped variables / reads / writes.

This is a capability split, not a second code-intelligence architecture.

Infigraph remains the structural graph backend for the relationship kinds
that it physically supports. LibCST is a narrow source-derived sidecar for
Python scope and assignment/reference analysis that the evaluated Infigraph
path does not expose.

The two backends have explicit, disjoint ownership:

- Infigraph: `REFERENCES`, `IMPACT`, `TESTS`, `DEPENDENCIES`;
- LibCST: `SCOPED_VARIABLES`, `READS`, `WRITES`;
- the composite contract covers every current `CodeIntelligenceKind`
  without overlap.

LibCST owns parsing, Python scope analysis, assignment/reference resolution
and source positions. Foundation only translates those observations into the
existing backend-neutral `CodeIntelligencePort` contract.

The LibCST sidecar MUST remain derived and non-authoritative. It does not own:

- canonical intent or architectural decisions;
- execution or mutation authority;
- a generic repository graph;
- type inference;
- arbitrary object-attribute identity;
- a second specification or semantic authority.

Its correctness path is explicit source snapshot
-> LibCST analysis
-> source snapshot readback.

A source change during analysis yields explicit uncertainty rather than a
silently fresh result. Unsupported query kinds, invalid source scope,
backend absence and backend-version mismatch fail closed.

LibCST `1.9.0` is pinned as a development dependency because this capability
belongs to Foundation development intelligence rather than the normal
request-serving runtime.

<!-- DI_BACKEND_COMPOSITION_SEMANTICS_2026_10_06 -->

```foundation-semantic
{"source":"src/ai_foundation/libcst_adapter.py","subject":"src/ai_foundation/libcst_adapter.py","subject_kind":"FILE","claim_kind":"scoped_name_backend_boundary","purpose":"provide the narrow Python source-derived inventory, scoped-variable, read and write observations missing from the evaluated Infigraph path","ownership":"LibCST owns parsing, Python scope analysis, assignment/reference resolution and source positions; Foundation only translates those observations into CodeIntelligencePort","rationale":"supply the bounded scoped-name slice without adding a Foundation-owned AST parser, generic graph, type inference or second semantic authority","failure_semantics":"source changes during analysis yield explicit uncertainty; unsupported query kinds, invalid source scope, backend absence and backend-version mismatch fail closed","side_effects":"NONE","change_impact":"changes must preserve source-snapshot/readback freshness, bounded Python semantic scope and disjoint backend ownership","evidence":["tests/test_libcst_adapter.py","tests/test_code_intelligence.py"]}
```

```foundation-semantic
{"source":"src/ai_foundation/composite_code_intelligence.py","subject":"src/ai_foundation/composite_code_intelligence.py","subject_kind":"FILE","claim_kind":"backend_composition_boundary","purpose":"compose disjoint code-intelligence backends behind the existing backend-neutral CodeIntelligencePort","ownership":"Foundation owns only the composition contract; Infigraph owns structural graph observations and LibCST owns bounded Python scoped-name observations","rationale":"cover required code-intelligence query kinds without creating a second Foundation-owned parser, graph or semantic authority","failure_semantics":"unsupported or unavailable backend observations remain explicit UNKNOWN or UNAVAILABLE and backend ownership must not overlap","side_effects":"NONE","change_impact":"changes must preserve disjoint exhaustive query-kind ownership, backend replaceability and non-authoritative derived semantics","evidence":["tests/test_composite_code_intelligence.py"]}
```

### SCIP disposition

The controlled SCIP investigation is closed for this requirement.

Direct `scip-python` generation proved that a SCIP artifact can be produced,
and manual Infigraph import added some symbols/references, but the evaluated
Infigraph import path still did not expose the required scoped-variable,
READS or WRITES observations.

SCIP therefore remains optional interoperability/research material and is
not promoted into the production Development Intelligence composition for
this slice.

Do not add a Foundation-owned AST parser to compensate.

### Gate effect

This slice materially advanced DI02 and DI03 but did not complete either
gate.

DI02 is now `VERIFIED`: repository-wide source inventory is exposed
through the checked-in Development Intelligence boundary with explicit
completeness metadata and deterministic same-source rebuild evidence.
At this DI02 slice, DI03 remained `PARTIAL`; structural relationship completeness was the next
unresolved Development Intelligence gate.

At this DI02 slice, DI03 remained `PARTIAL` until the required structural relationship set was
repository-wide reproducible, or unsupported/missing relationships are
explicitly represented as UNKNOWN/UNAVAILABLE.

This decision does not release the practical Self-Repair gate.

<!-- DI02_INVENTORY_CONTRACT_2026_09_29 -->
## Repository inventory contract

Repository inventory is derived Development Intelligence, never canonical or
execution authority.

The current backend contract is:

`CodeIntelligencePort`
-> `CompositeCodeIntelligence`
-> LibCST `INVENTORY`.

LibCST semantic scope defines source classification:

- each snapshotted Python source is a `MODULE`;
- every `ClassDef` is a `CLASS`;
- Protocol/ABC/ABCMeta classes additionally receive `INTERFACE`;
- `FunctionDef` directly owned by `ClassScope` is a `METHOD`;
- other `FunctionDef` elements, including functions nested inside methods,
  are `FUNCTION`;
- uppercase module/class assignments are source-level constants;
- non-uppercase module assignments are module variables;
- non-uppercase class assignments are class state;
- FunctionScope and ComprehensionScope assignments are scoped variables,
  deduplicated by logical scope and name;
- parameters are not promoted to a separate DI02 inventory category.

Completeness is mechanical, explicit and fail-closed: every expected source
file must be analyzed and failed/unresolved observations must be zero.
Otherwise inventory cannot claim completeness.

Historical static-audit counts are evidence used to validate the migration,
not a second specification. In particular, implementation must not be altered
merely to reproduce a historical count whose classification rule differs from
LibCST semantic scope.

DI02 completion does not establish DI03 relationship completeness, DI04
semantic explanation, DI05 bidirectional traceability, DI06 conflict/orphan
closure, DI08 complete preflight, DI09 post-change drift closure, or authority
for practical Self-Repair.

<!-- DI03_STRUCTURAL_RELATIONSHIPS_VERIFIED_2026_09_29 -->

### DI03 structural relationship baseline — verified

The repository-wide structural relationship baseline required by DI03 is now
`VERIFIED`.

The thin ownership model remains:

`CompositeCodeIntelligence`
-> Infigraph `3.2.16` for structural graph relationships
-> LibCST `1.9.0` for bounded Python scoped-name observations.

Infigraph owns references, impact, tests, dependencies/import relationships
and resolved CALLS edges. LibCST owns inventory, scoped variables, READS and
WRITES. Their query-kind ownership remains disjoint and exhaustive.

Completeness is not overstated. Infigraph-resolved CALLS are graph edges, not
a claim that every source-level call was resolved. Backend-omitted builtin,
external, dynamic or otherwise unresolved calls remain `UNKNOWN`. LibCST
READS/WRITES cover scoped Name/Param identity relationships; attribute,
subscript, dynamic and non-scoped object identity semantics outside that model
also remain explicitly `UNKNOWN`.

For the bounded Python source analysis, READS and WRITES now publish
`CodeIntelligenceCompleteness`; the physical current-worktree readback
analyzed 127/127 files with zero failed files and zero unresolved
observations.

This closes DI03 without introducing a Foundation-owned AST parser, call
resolver, graph database or handwritten relationship catalog.

DI03 verification is independent of the still-open DI04-DI09 work and does
not release practical Self-Repair.

## 12. OpenShell secure execution runtime evaluation

Status: **HIGH PRIORITY PROBE / ADOPTION NOT YET PROMOTED**

Recorded: 2026-09-30

NVIDIA OpenShell is the current high-priority candidate for a replaceable secure
execution-runtime layer beneath Foundation authority and above generic
tool/workload execution.

This is not an adoption claim and does not authorize production wiring.

### 12.1 Intended responsibility boundary

If promoted, the intended layering is:

```text
Human / LibreChat
-> Pydantic AI Agent
-> trusted CapabilityRequest
-> Foundation Guard / Cedar
-> OpenShell secure runtime
-> ToolHive / MCP / approved execution backend
-> OS / network / external service
-> independent Foundation verification/readback
```

Foundation continues to own product-specific authority and semantics:

- Guard, approval and cancellation;
- privacy and budget;
- host-owned capability/resource scope;
- Cedar authorization;
- durable Run/Effect identity;
- uncertain-effect reconciliation;
- product-specific credential authorization/target binding;
- independent expected-vs-observed verification;
- Agent/tool composition and human decision state.

ToolHive/MCP remains the generic tool transport/integration boundary where
technically appropriate. OpenShell must not replace MCP semantics merely
because it contains the workload.

OpenShell is evaluated for generic enforcement mechanisms that Foundation
should prefer not to reimplement:

- filesystem containment;
- process containment;
- network-egress enforcement;
- runtime credential isolation/injection;
- sandbox lifecycle;
- machine-checkable policy-boundary verification;
- low-level allow/deny audit evidence.

The architectural goal is therefore **ADD first, with selective REPLACE only
after evidence**, not an additional overlapping security framework.

### 12.2 Current classification

- OpenShell overall: **ADD candidate / HIGH PRIORITY PROBE**.
- Generic filesystem/process/network containment: **REPLACE candidate** where
  OpenShell proves equivalent or stronger required semantics.
- Runtime credential isolation/injection: **REPLACE/INTEGRATE candidate**;
  Foundation retains authorization and exact target-binding authority.
- OpenShell Policy Prover: **ADD candidate** for machine-checkable runtime
  policy-boundary verification; it does not replace Cedar's product
  authorization role.
- Guard, Cedar, Effect/reconciliation, CapabilityRequest, independent
  verification and Pydantic AI: **KEEP**.
- ToolHive/MCP: **KEEP** unless a later concrete integration test proves a
  narrower redundant responsibility; no removal is implied by this decision.
- NVIDIA Sentry / BlueField hardware path: **DO NOT ADD for the current M1
  Foundation** absent a new hardware-backed threat requirement.

### 12.3 Why this candidate is material

OpenShell is relevant to the Thin Foundation rule because its documented
runtime boundary can enforce filesystem, process, network and credential
restrictions outside the model/agent process. Its policy-proving path may also
reduce the need for Foundation-authored generic sandbox-policy validation.

The current supported-platform documentation includes Apple Silicon macOS for
the OpenShell control components and a macOS virtualization path for Linux
sandbox workloads. Therefore the current M1 production host is eligible for a
real isolated probe rather than documentation-only evaluation.

This does not establish compatibility with Foundation's exact ToolHive/MCP,
credential, recovery or observability contracts. Those remain empirical gates.

### 12.4 Required isolated M1 probe

Do not wire OpenShell into the production Foundation path before all of the
following are measured on the real M1 host:

1. **Filesystem escape denial** — a workload cannot read/write outside the
   host-approved scope.
2. **Network default-deny / egress denial** — allowed destinations work and an
   ungranted destination fails closed without widening authority.
3. **Credential non-exposure** — the agent/workload cannot obtain the raw
   credential while an explicitly authorized target request can use the
   credential-bearing boundary.
4. **Policy escalation rejection** — a proposed runtime policy that exceeds
   the host maximum boundary is rejected; unsupported/unprovable policy
   dimensions must fail closed rather than be treated as proven safe.
5. **Lifecycle/reconstruction** — sandbox destroy/recreate/restart preserves
   the intended host-owned policy and does not create ambient authority or
   stale credentials.
6. **Operational cost** — record startup latency, steady-state CPU/RAM,
   virtualization/container overhead, failure behavior and recovery behavior
   on the M1.

The probe must additionally verify that Foundation's existing independent
effect/readback semantics still work through the candidate runtime. OpenShell
success, policy acceptance or sandbox process exit is never Foundation
completion authority.

### 12.5 Promotion gate

Promotion requires evidence that OpenShell:

- reduces custom Foundation containment/credential-isolation code or ongoing
  maintenance rather than adding a duplicate layer;
- can preserve the existing host-owned authority envelope without allowing
  prompt/model-controlled privilege expansion;
- composes with the selected ToolHive/MCP execution path or provides a clearly
  justified narrower replacement for a specific responsibility;
- exposes failure/restart semantics that Foundation can fail closed around;
- does not weaken effect reconciliation, credential target binding or
  independent verification;
- has acceptable measured M1 resource/latency cost;
- can be pinned and reconstructed reproducibly enough for the Foundation
  production gate.

If these conditions pass, write a separate integration architecture/ADR and
identify exact Foundation code that can be deleted or reduced before production
wiring. Do not retain redundant custom containment merely as a second
implementation without a documented defense-in-depth requirement.

### 12.6 Stop conditions

Record **DO NOT ADD** or keep OpenShell as **RESEARCH ONLY** if any of the
following is observed:

- required authority can only be expressed through model/prompt-controlled
  policy;
- filesystem/network/process/credential isolation is materially weaker than
  the current required Foundation boundary;
- ToolHive/MCP composition requires a parallel semantic tool framework;
- ambiguous external effects become unreconcilable or invite blind retry;
- credential injection cannot preserve Foundation's exact target-binding
  contract;
- unsupported policy dimensions are silently accepted as verified;
- M1 operational overhead or instability outweighs the custom-code reduction;
- adoption adds more product-specific adapter/policy code than it can retire.

Until the isolated probe and subsequent promotion gate pass, the current
production execution path and current canonical authority remain unchanged.

<!-- CURRENT_DEVELOPMENT_EXECUTION_OWNERSHIP_2026_10_07 -->
## Current development-execution ownership supersession — 2026-10-07

**Historical 2026-10-07 supersession only:** The statement that Kandev owned
the generic development lifecycle reflected that date, and was superseded on
2026-11-12 by `SYSTEM_ROLE_BOUNDARIES.md`. GitHub owns task/PR/CI identity;
Foundation host/Guard/Harness owns the development admission and role boundaries;
existing local9B and optional host-admitted frontends perform scoped execution.
Do not implement a second task/session/worktree/dependency scheduler merely
because this future vision mentions one. Development Intelligence,
Explainability, Safe Change and Self-Repair remain Foundation capabilities
because they govern meaning, admission, evidence and verification.
