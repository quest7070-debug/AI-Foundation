# OSS-Composable Foundation — Future Direction

Status: Future concept / not an immediate implementation requirement

## Purpose

AI Foundation should avoid reimplementing mature infrastructure capabilities when a well-maintained OSS component can provide them. The Foundation should focus on orchestration, policy, routing, safety, failure handling, and stable capability boundaries, while keeping underlying OSS components replaceable.

This is a future direction, not a request to add all components now.

## Candidate capability areas

- Search aggregation: evaluate SearXNG or equivalent as a replaceable SEARCH backend.
- Knowledge / RAG: evaluate Qdrant or pgvector for vector storage, with LlamaIndex, Haystack, or equivalent for ingestion/retrieval pipelines.
- Observability / evaluation: evaluate OpenTelemetry and Langfuse or equivalent for traces, evaluation, cost and execution visibility.
- Existing components such as ToolHive, Hatchet and Cedar should remain independently replaceable rather than becoming tightly coupled to Foundation-specific code.

## OSS-first gate

Before implementing a new infrastructure capability inside AI Foundation:

1. Check whether a mature OSS project already solves the capability.
2. Prefer integration through a stable adapter/capability boundary when it meets requirements.
3. Build Foundation-specific implementation only when existing OSS cannot satisfy required behavior, security, reliability, or operational constraints.
4. Do not add an OSS merely because it exists; avoid duplicate responsibility and unnecessary stack growth.

## Integration maturity

An OSS integration is not considered complete merely because it is installed. Track each integration through:

1. **Installed** — dependency/service exists in the environment.
2. **Wired** — Foundation has a real execution path to it.
3. **Used** — normal product flows actually use that path.
4. **Tested** — normal operation is covered by integration/E2E tests.
5. **Failure-tested** — outages, malformed responses, timeouts, recovery and fallback behavior are verified.

A component that stops before these stages must not be presented as a completed Foundation capability.

## Architectural constraint

Keep capability boundaries explicit so implementations can be exchanged without rewriting callers.

Conceptually:

```text
Application / Tool
        |
   AI Foundation
        |
  Capability boundary
   |    |    |    |
  LLM SEARCH MCP KNOWLEDGE ...
        |
 Replaceable OSS / provider implementations
```

The goal is not to maximize the number of bundled OSS projects. The goal is to minimize reinvention while preserving replaceability and preventing tight coupling.

## Future completion criteria

When this direction is implemented, verify that:

- replacing one backend does not require changes to consuming applications;
- removing an OSS component does not leave hidden dependencies;
- provider/service failure follows defined degradation or fallback behavior;
- secrets and authorization remain controlled by Foundation boundaries;
- observability can show which backend actually executed a request;
- unused or duplicated components can be removed cleanly.

This document should be revisited during future architecture reviews rather than treated as an immediate feature backlog.


## 2026-09-24 DATA / PC_CONTROL OSS survey

This survey updates candidate backends only. It does not authorize installation or widen any capability.

### DATA

Use two replaceable execution profiles rather than growing Foundation's current JSON/CSV helpers into an analysis engine.

1. **Structured/read-only analytics candidate: DuckDB MCP.** Prefer a maintained DuckDB MCP with read-only mode and host-bound data roots. MotherDuck's local MCP server is the stronger upstream candidate found in this survey: it runs locally/self-hosted, supports DuckDB/local files and now defaults to read-only. Foundation must still bind the allowed dataset/root and treat SQL/results as untrusted tool data. A newer `mcp-duckdb-analyst` has attractive explicit guards (SELECT-only, path confinement, row/cell/time caps) but is currently too new to adopt as the production default without maturity/provenance evidence.
2. **Notebook/arbitrary-analysis candidate: Datalayer Jupyter MCP Server.** Current Jupyter MCP Server 2 uses MCP Python SDK 2 and can execute notebook cells/arbitrary code across local or sandbox backends. This is a broader COMPUTE authority than ordinary DATA and must not be ambient. If adopted, expose it only through a host-selected sandbox/profile with bounded files/network/resources and explicit artifact/readback rules. Do not copy notebook execution into Foundation.

The existing `DataSpecialist` remains the narrow deterministic baseline. OSS adoption should replace/extend the execution backend behind the capability boundary, not create a second semantic data router.

### PC_CONTROL

For the current M1/macOS host, the preferred first live candidate is **onixhdz/computer-use-mcp**: local stdio MCP, Accessibility-first inspection/action, optional screenshot fallback, and bounded before/after accessibility diffs for mutating actions. Its small MCP surface fits the existing ComputerAction rule of observe -> act -> independent verify. The raw `run_jxa` escape hatch is explicitly high authority and must be disabled/not exposed through the normal Foundation capability.

Cross-platform candidates remain evaluation targets rather than current dependencies:
- **zavora-ai/computer-use-mcp** supports macOS/Windows/Linux and has a smaller `core` profile as well as broad profiles. Its default full surface is much wider than Foundation should expose; any trial must start from the minimum profile and explicit app/window scope.
- **Munim Computer Use** also provides accessibility-first macOS/Windows/Linux control and browser tools with a look -> act -> verify workflow. It is promising for future portability, but the standalone repository is newer and should not displace a narrower M1 trial solely for cross-platform breadth.
- Browser-only work should remain separable from desktop control. `open-browser-use` can drive an existing signed-in Chromium browser over MCP and is preferable to granting whole-desktop authority when the task is purely web UI.

### Integration rule

The intended composition is:

```text
Pydantic AI Agent
  -> host-authorized DATA or PC_CONTROL tool
  -> Foundation capability / Guard boundary
  -> ToolHive or equally contained MCP execution boundary
  -> replaceable DuckDB/Jupyter/Computer-Use backend
  -> independent observation / verification
```

Do not expose an entire upstream MCP server merely because it is installed. Foundation publishes only the minimum host-approved tools/actions for the current job. Prefer API/filesystem/browser-specific capabilities before PC_CONTROL. PC_CONTROL is the fallback for work that genuinely requires desktop UI.

### Adoption gates

Before promotion from candidate to normal execution:
- pin an approved release/source and review license/provenance;
- verify ToolHive compatibility for the selected transport and host-permission model;
- prove scope escape, prompt/tool-output injection, destructive-action denial and cancellation fail closed;
- prove lost-response/process-death reconciliation does not repeat an external action;
- record exact tool allowlist and disable arbitrary scripting/command escape hatches by default;
- run real M1 E2E, then failure E2E, before calling the capability complete.

No Foundation implementation expansion is justified by this survey. The next implementation step is backend integration/testing, not new DATA or PC_CONTROL framework code.


## 2026-09-24 aggressive OSS adoption update

The project should use the most capable mature external execution engines that fit the existing authority boundary, rather than choosing the smallest backend merely to minimize integration work. "Aggressive" means broad capability behind strict host authority, not ambient privilege.

### DATA target stack

Adopt a **two-engine DATA/COMPUTE stack** as the target:
- **Datalayer Jupyter MCP Server** is the primary general analysis engine. It has active upstream development, MCP SDK 2 support, notebook/file/cell management, arbitrary code execution, multimodal outputs, OpenTelemetry hooks, and multiple local/cloud sandbox backends. It can cover Python/pandas/polars/statistics/plots and future GPU analysis without Foundation reimplementing a notebook runtime.
- **DuckDB MCP** remains the fast structured-query engine. MotherDuck's server is the established upstream option, but its own production guidance notes that read-only self-hosting alone does not prevent local-filesystem/settings access. Therefore use it only behind Foundation/ToolHive containment and DuckDB hardening. Track `mcp-duckdb-analyst` because its SELECT-only parser guard, allowed-directory confinement, extension disablement, result caps and query timeout are a better least-authority contract; promote it only after sufficient upstream maturity/provenance.

Do not force every DATA request through Jupyter. Agent tool selection may choose the bounded DuckDB tool for tabular querying and the explicitly broader Jupyter compute tool for transformations, statistical work, visualization or notebook artifacts. Foundation owns neither SQL planning nor notebook execution.

### PC_CONTROL target stack

Change the preferred strategic backend from a small macOS-only MCP candidate to **Cua Driver (trycua/cua)**, subject to real-host verification. The upstream project is substantially more mature and active, supports host desktop control through MCP/CLI, macOS and Windows background control with Linux pre-release, signed-app service behavior on macOS, lifecycle sessions, and—most importantly for Foundation—an upstream `bounded` permission mode with capability manifests for reviewed apps/origins/directories. That maps unusually well to Foundation's host-bound CapabilityRequest/Guard model.

Use **Microsoft Playwright MCP** as the default browser execution backend rather than escalating web work to PC_CONTROL. It is highly mature, accessibility-snapshot based, supports persistent/isolated profiles, explicit network/storage capabilities, and can connect to existing browsers. Disable experimental WebMCP by default until its page-supplied tool trust boundary is explicitly reviewed.

Keep **minghinmatthewlam/computer-use-mcp** as the macOS-native verification/alternative candidate. Its architecture is unusually aligned with Foundation: shared daemon, per-app leases, Accessibility-first dispatch, opt-in global cursor fallback, stale element rejection, read-act-reread verified outcomes, destructive-action confirmation, URL deny/confirm policy and human-interference yielding. It is pre-1.0 and has not yet published the stable release path described by its README, so it should not replace the more mature Cua strategic backend yet.

Track **open-computer-use** and **Munim Computer Use** as cross-platform alternatives. They are accessibility-first and attractive, but do not currently justify duplicating the Cua + Playwright integration unless a measured capability/reliability gap appears.

### Aggressive capability ladder

Normal execution should select the strongest *specific* backend before generic desktop control:

```text
DATA:
  deterministic built-in -> DuckDB MCP -> Jupyter MCP sandbox

INTERACTION:
  API/specialized MCP -> FILES/CODE -> Playwright MCP -> Cua Driver PC_CONTROL
                                                        -> macOS-native fallback
```

This is an execution ladder, not a fallback that silently widens authority. Every wider step requires a host-authorized capability envelope appropriate to that backend.

### Integration priority

When real M1 execution becomes available:
1. wire and test Playwright MCP as BROWSER/interaction execution without granting whole-desktop authority;
2. wire Cua Driver behind PC_CONTROL using upstream bounded permission mode plus Foundation scope/Guard, and verify macOS TCC/daemon behavior;
3. wire Datalayer Jupyter MCP as an explicit sandboxed analysis/compute backend;
4. wire a hardened DuckDB MCP profile for low-cost/read-only structured analysis;
5. compare Cua against the macOS-native computer-use-mcp on background operation, stale-state rejection, verified outcomes, crash/reconnect behavior and human interference before final backend pinning.

Do not create new Foundation orchestration layers for these integrations. Add only the minimum replaceable adapters/configuration needed to connect existing capability boundaries to the selected MCP runtimes.


## 2026-09-24 final decision — DATA and interactive computer execution

This supersedes the earlier candidate ordering in this document.

### Decision

Adopt the following target execution plane once real-host integration resumes:

- **BROWSER: Microsoft Playwright MCP — adopt.** Browser work must use this before desktop control. Start with core accessibility-snapshot tools; keep WebMCP disabled until page-supplied tool trust has a separate review. Network/storage capabilities are opt-in, not ambient.
- **PC_CONTROL: Cua Driver — adopt as the primary desktop backend.** Run the macOS app/daemon in upstream `bounded` permission mode with a reviewed capability manifest. Foundation's CapabilityRequest/Guard remains the outer authority; Cua's manifest is defense-in-depth. Never use `standard` or `unrestricted` for unattended Foundation execution merely for convenience. Existing-profile browser attachment remains an explicit grant.
- **PC_CONTROL secondary backend: Munim Computer Use — keep as the portability/UX challenger, not a simultaneous default dependency.** Its accessibility-first/background-input approach is attractive across macOS/Windows/Linux, but integrate it only if M1 comparison finds a concrete Cua gap.
- **DATA/COMPUTE: Datalayer Jupyter MCP Server — adopt as the general analysis runtime.** Prefer a local Jupyter Server first; use a non-local sandbox variant only when the job explicitly needs isolation/accelerator/durable remote compute and its credential/cost authority is separately granted. Expose code execution as broader COMPUTE authority, not as ambient read-only DATA.
- **DATA read-only fast path: guarded DuckDB MCP — adopt after pinning a reviewed implementation.** The desired contract is the security shape demonstrated by `mcp-duckdb-analyst`: SELECT/read-only SQL, allowed-directory confinement, external access/extensions disabled, result/time caps. Its current upstream is too young to become an unquestioned production dependency, so either pin it after source review and real-host tests or apply the same containment contract to the more established MotherDuck server. Do not build a Foundation SQL engine.

### Why this is the final direction

This selection maximizes capability without making Foundation own generic execution machinery. Playwright owns browser semantics; Cua owns native desktop mechanics and a second permission ceiling; Jupyter owns arbitrary analytical compute/notebook lifecycle; DuckDB owns bounded tabular query execution. Foundation keeps only product-specific authority, provider/tool routing, credentials, durable effects, reconciliation and independent verification.

The broadest backend is not automatically selected. The Agent receives only tools permitted by the host envelope. Escalation from DuckDB -> Jupyter or Playwright -> Cua is a capability change requiring matching host authority; it is not an automatic failure fallback.

### Rejected directions

- Do not implement a Foundation-owned desktop automation engine, notebook runtime, SQL planner, accessibility parser or browser driver.
- Do not expose arbitrary shell/JXA/script escape hatches through normal PC_CONTROL.
- Do not give an unattended desktop agent Cua `standard`/unrestricted authority.
- Do not use PC_CONTROL for ordinary browser tasks when Playwright can express them.
- Do not make a very new MCP server a single point of trust solely because its README has a stronger security story.
- Do not install multiple overlapping computer-use servers permanently just to maximize feature count.

### Required real-host gate

The architecture decision is final; backend promotion is not. M1 testing must prove: install/provenance pin, ToolHive/MCP transport compatibility where applicable, TCC persistence, bounded-manifest denial, app/origin/directory escape denial, stale-state behavior, human-interference behavior, destructive-action denial, cancellation, lost-response/process-death reconciliation, restart/reconnect, and observed-result verification. DATA must additionally prove data-root escape denial, network/extension restrictions, resource bounds, artifact handling and Jupyter sandbox cleanup.

If Cua fails these gates, compare Munim/open-computer-use against the failed requirement rather than adding Foundation desktop code. If a DuckDB server fails the required confinement contract, keep Jupyter as the general engine and defer the fast path rather than weakening DATA authority.

## 2026-09-25 development-intelligence / project-world-model direction

Status: future architecture direction / not an implemented capability

### Problem

The current canonical documents, tests and runtime evidence remain authoritative, but a coding agent should not depend on rereading large prose canons and reconstructing the project model from scratch on every task. The missing layer is persistent, machine-retrievable development context at symbol/dependency level, connected to existing human intent and canonical decisions.

This must **not** create a second canon. Canonical requirements, boundaries and implementation status remain in the existing canonical documents and repository evidence. Any development-intelligence layer is derived/indexed context used to retrieve the relevant canon and code facts for a task.

### OSS-first target

**Infigraph has been evaluated first and is retained as the first replaceable code-intelligence backend candidate.** Its accepted next-stage responsibility is source-derived symbol/dependency facts such as functions, methods, classes, variables/constants, calls, imports, reads/writes, tests and change/impact relationships. The isolated AI-Foundation evaluation showed useful method-level callers, impact and test relationships without requiring Foundation-owned generic graph machinery. SCIP enrichment remains optional and is not a prerequisite for initial adoption. Foundation must not reimplement an AST/SCIP parser, generic code graph or repository indexing engine while the replaceable backend satisfies the required contract. Production promotion remains subject to the staged gates in `FUTURE_POST_COMPLETION_ARCHITECTURE.md`.

Do **not** add OpenSpec as a second specification authority at this stage. The existing Foundation canon remains authoritative; a new spec system is justified only if a measured gap cannot be solved without duplicating or competing with current canon. Likewise, do not install LKG, GitNexus and Infigraph simultaneously merely for feature breadth. Competing code-graph backends should be benchmarked against the same Foundation cases and only a measured winner should be promoted behind a replaceable boundary.

### Minimal Foundation-owned responsibility

If code-graph retrieval alone is insufficient, Foundation may add only the thin project-specific layer that external code-indexing OSS does not own:

1. **Semantic Linker** — associate an existing canonical decision/constraint/requirement with relevant source symbols and tests. Links are derived navigation/context, not independent authority.
2. **Development Context Compiler** — for a concrete coding task, assemble the smallest sufficient context from the current request, relevant canonical decisions, linked symbols/dependencies, affected tests and known failure evidence before a coding agent acts.

Do not build a new generic knowledge-graph platform, AST engine, duplicate specification store, coding-agent framework or second memory system for this purpose.

### Intended development loop

```text
human task / natural language
        |
existing Foundation canon + decisions
        |
Development Context Compiler
        |\
        | +--> replaceable code-intelligence backend (Infigraph first candidate; evaluated)
        |          -> symbols / calls / reads-writes / tests / impact
        |
        +--> thin semantic links when needed
        |
        v
bounded coding agent context
        |
implementation / diff
        |
code-intelligence impact query
        |
existing tests / deterministic verification / real E2E as applicable
        |
canonical update through the normal project process when a real decision/state changed
```

Natural-language conversation may propose durable decisions or links, but model-extracted meaning must not silently become canon. A proposed decision is accepted only through the project's existing canonical update/verification process. Generated symbol/dependency facts must be reproducible from the repository or explicitly marked as semantic inference.

### Adoption gate

Before wiring any backend into the normal development loop, run it side-by-side against real historical Foundation failures and changes. At minimum verify that it can recover useful context for routing/search changes, initialization/lifecycle defects, cross-module impact and affected tests without broad irrelevant retrieval. Measure retrieval correctness, missed dependencies, stale-index behavior, incremental update behavior, MCP/tool reliability, resource cost and removal/replaceability.

Promotion follows the existing OSS maturity rule: **Installed -> Wired -> Used -> Tested -> Failure-tested**. Until those gates pass, this remains a future direction and must not be represented in `CURRENT_STATE.md` as an implemented Foundation capability.

### Desired end state

A coding request should no longer require the agent to reconstruct the whole project from prose. The system should compile a task-local project world model from authoritative canon plus reproducible repository facts, execute through existing bounded coding/verification paths, and carry forward only verified decisions/state. This is a development-context capability, not autonomous authority to change software.


<!-- INFIGRAPH_EVALUATION_CLOSED_V1 -->
## Infigraph evaluation closure

The initial code-intelligence evaluation is closed.

Decision:

- **KEEP** Infigraph `3.2.16` as the first replaceable
  `CodeIntelligencePort` backend.
- **KEEP** tree-sitter-backed indexing/query capability through the external
  backend rather than rebuilding equivalent parsing/graph logic inside
  Foundation.
- **OPTIONAL** SCIP remains an interoperability/evaluation path rather than
  a required Foundation subsystem.
- **DO NOT ADOPT** installer-driven agent integration as Foundation
  authority or lifecycle.
- **DO NOT ADOPT** Infigraph-owned specification, session, or canonical
  authority.
- **DO NOT DEPEND** on an implicit watcher for correctness.
- **DO NOT BUILD** a Foundation-owned generic AST parser, repository graph,
  semantic code-search engine, blast-radius engine, test-association engine,
  or generic graph store.

The adapter uses explicit full indexing for the verified correctness path.
Incremental indexing was physically rejected for this integration because
the evaluated path lost required relationship edges.

Backend-generated `.infigraph/` state is reproducible derived state and is
excluded from repository authority.

The backend remains replaceable. Foundation-specific meaning belongs only
in the thin Semantic Linker and Development Context Compiler layers above
the generic code-intelligence contract.
