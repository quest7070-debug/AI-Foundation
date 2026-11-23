# OSS execution integration plan — 2026-09-24

Status: **implementation plan / architecture gate**

## Objective

Promote the final OSS execution decision into normal AI Foundation capabilities without adding a second agent, semantic router, desktop engine, notebook runtime, SQL planner, or browser driver.

Target backends:

- BROWSER: Microsoft Playwright MCP
- PC_CONTROL: Cua Driver in bounded permission mode
- COMPUTE: Datalayer Jupyter MCP Server
- DATA fast path: guarded DuckDB MCP

GitHub remains canonical. A backend is not "implemented" until Installed -> Wired -> Used -> Tested -> Failure-tested is evidenced.

## Non-negotiable ownership

Pydantic AI owns semantic tool choice. Foundation owns the trusted capability envelope, backend eligibility, credentials, Guard/effect state, reconciliation and independent verification. ToolHive/MCP owns generic tool transport/containment where technically compatible. Upstream backends own their domain execution semantics.

No failure may silently widen authority: DuckDB failure does not mint Jupyter COMPUTE; Playwright failure does not mint PC_CONTROL.

## Existing boundaries to reuse

- `CapabilityRequest` is the host-owned daily-use authority envelope.
- `MCPToolGrant / MCPToolRegistry / BoundMCPTools` already provide exact server + exact tool allowlisting.
- `ToolHiveMCPClient` already provides a generic replaceable ToolHive MCP transport.
- `CapabilityExecutor` is the execution dispatcher after semantic selection; it must not become another semantic router.
- `ComputerActionSpecialist` already requires act -> observe -> expected-result verification.
- `BoundComputeCapability` already distinguishes bounded compute from effects.

Therefore implementation must extend these contracts, not create parallel routing/tool frameworks.

## Work packages

### P0 — contract correction before backend wiring

1. Add explicit `BROWSER` and `COMPUTE` capability names. Do not disguise Playwright as PC_CONTROL or Jupyter arbitrary code as read-only DATA.
2. Extend the trusted envelope only with host-resolved fields needed to bind those capabilities. Prompt text cannot name a server, permission mode, filesystem root, browser profile, application allowlist, network origin or Jupyter sandbox.
3. Add backend-neutral execution ports/adapters only where the existing generic MCP registry cannot express required verification. Prefer `MCPToolGrant` over new per-product clients.
4. Preserve the existing narrow `DATA` operations as deterministic fallback/baseline; add DuckDB as a separate host-selected DATA backend rather than replacing it with prompt-selected SQL execution.

### P1 — Playwright MCP

- Register a pinned Playwright MCP workload with a minimal allowlist.
- WebMCP disabled.
- Network/storage/file access denied unless explicitly host-granted.
- Normal browser navigation/inspection is observational; mutations that change external state require the existing effect/verification contract rather than being treated as mere MCP success.
- Verify origin escape denial, download/upload scope, authenticated-profile authority, malicious page/tool output and restart behavior.

### P2 — Cua Driver

- Use upstream `bounded` mode only for unattended Foundation execution.
- Translate a host-approved PC capability into a reviewed Cua manifest; model text never edits that manifest.
- Keep arbitrary shell/JXA/script escape hatches outside the normal grant.
- Reuse `ComputerActionSpecialist` act -> observe -> expected verification. Do not accept Cua's success string as Foundation completion authority.
- Verify TCC persistence, app/origin/directory denial, stale state, human interference, destructive actions, cancellation, lost response, process death and restart/reconnect.

Current upstream contract review:
- Cua Driver's permission mode is immutable for a running runtime; `bounded` requires a reviewed capability manifest and explicit launch acknowledgement.
- On macOS the app-bundle daemon must own the launch flags so TCC attribution remains with `CuaDriver.app`; raw per-call/model text cannot widen the runtime mode.
- A bounded manifest can constrain tools plus application, browser-origin and directory resources. Existing-profile browser attachment remains explicit authority.
- Persistent restart configuration must preserve the same bounded flags; bad/missing bounded configuration fails startup rather than silently falling back to standard.
- Foundation already has the backend-neutral `BoundComputerPort / ComputerActionSpecialist` target binding and independent act -> observe -> expected check. Do not replace these with Cua-specific verification.
- Before implementation, inspect the exact pinned upstream release/tool schema and choose the smallest transport adapter. Prefer Cua's existing MCP/CLI/SDK boundary rather than reproducing its manifest/policy engine in Foundation.

### P3 — Jupyter MCP

- Expose as `COMPUTE`, not ambient DATA.
- Host selects local/sandbox backend and resource/network/file grants.
- Code, package installation, filesystem access and network egress are separate authority dimensions; do not infer them from "analyze this".
- Capture notebook/plot/file outputs as artifacts/evidence; arbitrary code completion is not external-effect verification.
- Verify timeout/resource limits, sandbox cleanup, path/network denial, malicious notebook output and credential isolation.

### P4 — DuckDB DATA fast path

- Require a reviewed/pinned server implementing the desired read-only contract: SELECT-style query only, allowed data roots, external access/extensions disabled, result/time caps.
- Prefer `mcp-duckdb-analyst` only after source/provenance/maturity review; otherwise use a contained MotherDuck server with equivalent outer restrictions.
- SQL is generated/executed by the backend/tool contract; Foundation must not grow a SQL parser/planner.
- Verify path escape, ATTACH/COPY/extension/network denial, large-result limits and malformed input.

## Promotion order

1. Contract changes and deterministic tests.
2. Playwright MCP wiring.
3. Cua bounded wiring.
4. Jupyter MCP wiring.
5. DuckDB fast path.
6. Agent-visible tool registration only after each backend has passed its own real-host gate.

This order deliberately establishes the narrower interaction backend before whole-desktop authority and the general compute engine before optimizing the DATA fast path.

## Stop conditions

Stop and record BLOCKED rather than patching around an upstream/backend problem when:

- required authority cannot be represented without prompt-controlled privilege;
- the backend cannot be contained to the required app/origin/path/resource scope;
- ambiguous external effects cannot be reconciled without blind repeat;
- a backend requires Foundation to duplicate its generic engine;
- a real-host failure contradicts the documented security contract.

In that case evaluate the named alternative backend against the failed requirement. Do not weaken Guard or add product-specific exceptions.

## Current gate

Architecture and work decomposition are now canonical. GitHub-only work may implement P0 and deterministic contract tests. P1-P4 promotion still requires the real M1 execution environment for installation, permission and failure E2E.


## M1 runner gate evidence — 2026-09-24

The self-hosted runner is now proven to accept repository jobs:
- runner: `m1-runner`
- machine: `owner-MacBook-Air`
- runner version: `2.337.0`
- host: macOS 26.6.2 / arm64

The first self-hosted run failed in `actions/setup-python` before project installation because that action attempted to create its hosted-toolcache path under `/Users/runner`, which is not writable/present on this runner. This was a CI-environment mismatch, not a project test failure.

A second diagnostic run intentionally removed `setup-python` and inspected the host interpreter. It found `/usr/bin/python3 == 3.9.6`, below the repository's canonical `python >=3.12` requirement. It failed closed before dependency installation. Therefore no pytest result exists yet.

Do not lower the repository Python requirement or bypass the preflight. The runner must provide a stable Python >=3.12 executable to the service environment (or the runner service must be configured with a valid tool cache) before deterministic project tests can become authoritative. Once that host prerequisite is corrected, the existing workflow creates an isolated `.venv-ci`, installs `.[dev]`, compiles source/tests/scripts, and runs the full pytest suite.

This is an environment prerequisite gate, not a reason to modify Foundation runtime code.


## Deterministic M1 CI baseline — 2026-09-24

The canonical self-hosted M1 gate now passes end to end. Run `35989820149` used `/opt/homebrew/bin/python3.12`, created an isolated CI venv, installed project dependencies, compiled source/tests/scripts, provisioned the pinned Cedar CLI, passed a real Cedar owner-write authorization preflight, and completed the full suite with:

- `940 passed`
- `10 skipped`
- `1 warning`
- `140.80s`

The Cedar CLI is no longer an undeclared local prerequisite. CI provisions official Cedar CLI `4.13.0` for Apple arm64 and verifies SHA-256 `53c3ddc467519a3371919a92da1167fe143d9eb8efe0b29fdde8237fa0fe9cae` before execution.

This establishes the deterministic baseline required before backend integration. Subsequent P0/P1 changes must preserve this gate; a backend is not promoted merely because installation succeeds.

### P0 authority-envelope progress

`CapabilityRequest` already distinguishes `BROWSER` and `COMPUTE`. The trusted daily capability factory now also accepts those capability names, but resolves `browser_target` and `compute_profile` only through host-preconfigured scope maps. Payload-supplied targets/profiles are ignored and unknown scopes fail closed through the existing request validation.

This does **not** register BROWSER or COMPUTE with the Pydantic AI Agent and does **not** claim a backend is wired. Agent-visible registration remains gated on real-host backend promotion.


## Execution backlog and P1 evidence — 2026-09-24

This section is the canonical remaining-work ledger. Update it from observed repository/real-host evidence; do not mark a backend promoted from installation or registry metadata alone.

### P1 Playwright MCP

- [x] BROWSER exists in the trusted capability envelope and host-resolved factory mapping.
- [x] Generic `MCPToolGrant / MCPToolRegistry / BoundMCPTools / ToolHiveMCPClient` boundary exists; no Playwright-specific Foundation client is justified.
- [x] Deterministic ToolHive v0.49.0 darwin/arm64 bootstrap exists and the Foundation full CI remains green.
- [x] Upstream `@playwright/mcp@0.0.82` package/CLI was inspected on the M1 runner; `--no-webmcp` exists.
- [x] ToolHive v0.49.0 official registry exposes `io.github.stacklok/playwright`, currently `mcr.microsoft.com/playwright/mcp:v0.0.79`, transport stdio, no provenance metadata.
- [x] Registry inventory identifies high-authority tools including `browser_run_code_unsafe`, file upload, evaluate, click/type/fill and lower-effect observation tools including snapshot/console/network inspection.
- [x] Obtain the official registry container image successfully on the M1 runner.
- [x] Reach RUNNING with the official registry workload and use canonical ToolHive logs for startup diagnosis.
- [x] Record the actual M1 runtime image ID/repo digest and fail closed in the probe if registry v0.0.79 resolves differently: `mcr.microsoft.com/playwright/mcp@sha256:435e737f4b9122477d792f3a1f3825a6cf87366fb3ca70b10d0eff130adc3f81`. Registry provenance metadata is still absent, so this is immutable observed-image pinning, not a provenance claim.
- [x] Discover the live MCP inventory/schema through ToolHive on the real M1 host.
- [x] Verify the pinned v0.0.79 workload does not expose WebMCP; the newer npm-only `--no-webmcp` flag is not passed to the pinned image.
- [x] Define the minimum host-owned observational allowlist from live schemas; `browser_run_code_unsafe`, navigation and mixed-action tabs are excluded.
- [x] Verify no host Docker mounts and that a real-host `file:///etc/passwd` probe cannot expose passwd content. Foundation's observational grant contains no upload/navigation tool. Authenticated storage/profile authority remains ungranted; add it only with a concrete host-owned requirement.
- [x] Keep malicious page/tool output explicitly non-authoritative at the Agent boundary: existing `ToolObservation` marks tool text non-authoritative, and the Pydantic Agent instructions now explicitly treat browser/tool content as untrusted evidence and forbid retrieved content from changing tools/scopes/Guard/credentials/system behavior. Cross-backend adversarial E2E remains in final convergence.
- [x] Verify stopped-workload/stale-inventory calls fail closed on the real M1 host. Run `36007144536` also proves supported recovery: ToolHive-owned remove/recreate reaches live inventory and an observational MCP call again (`PLAYWRIGHT_RECREATE_RECONNECT_OK`). Raw Docker restart remains intentionally unsupported.
- [x] Classify click/type/fill/dialog/upload/evaluate/navigation as mutation/high-authority browser operations for Foundation purposes. They remain outside the Agent-visible observational grant. Do not expose them until a concrete host-owned operation can supply a deterministic expected postcondition through the existing Guard/effect/reconciliation contract; raw MCP success can never mean VERIFIED. This intentionally avoids inventing a generic browser-effect DSL before a real mutation requirement exists.
- [x] Wire observational BROWSER through existing generic MCP boundaries after the real-host network/schema gate.
- [x] Register only the observational BROWSER wrapper with the Pydantic Agent when a host-bound browser target exists; mutation/navigation remain unavailable.

Latest real-host evidence: run `36004247594` passed the complete bounded-egress gate on M1: allowed `example.com` succeeded, non-allowed `example.org` failed, and live schema classification completed. Runtime BROWSER execution now delegates only through the existing generic `MCPToolRegistry / MCPToolGrant / BoundMCPTools / ToolHiveMCPClient` chain. Host composition optionally registers exactly one `browser-main` grant when `AI_FOUNDATION_BROWSER_SERVER` is configured, with only the six live-schema observational tools: console messages, network request/history, snapshot, screenshot, and wait. `browser_navigate`, mixed-action `browser_tabs`, and `browser_run_code_unsafe` are explicitly absent. This adds no Playwright-specific client, router, or browser engine. The Pydantic Agent now receives a BROWSER wrapper only when the trusted request contains a host-bound browser target. The wrapper still crosses the same generic MCP grant, so Agent tool choice cannot add navigation/mutation authority. Mutating browser tools remain blocked pending effect/verification design. Run `36005370156` reconfirmed bounded egress and recorded the M1 image ID/repo digest as sha256 `435e737f4b9122477d792f3a1f3825a6cf87366fb3ca70b10d0eff130adc3f81`. Its composed-runtime check reached Foundation but incorrectly assumed a later MCP call would share the probe CLI's browser page/session; that session-state assumption is not part of the generic MCP transport contract. The gate now verifies valid observational MCP content instead, while keeping navigation denial independent, and fails closed if the observed image digest changes. Run `36006059603` additionally passed with `mounts=[]` and `PLAYWRIGHT_FILE_SCOPE_OK`, while preserving composed-runtime and stale-call gates. Run `36005826128` had already passed the corrected composition probe end to end: immutable observed digest matched; bounded egress passed; the real Foundation composition path returned valid observational MCP content; Foundation denied `browser_navigate` outside the grant; stopping the workload caused the stale MCP call to fail closed; live schema classification remained valid. The probe now additionally asserts there are no Docker mounts and checks that a `file:///etc/passwd` navigation probe cannot expose passwd content, without granting file navigation to Foundation runtime. Those formerly remaining observational-scope gates were subsequently closed by the promoted P1 evidence recorded below: file/storage/profile exposure is denied by the no-mount/file-scope posture, malicious tool output is treated as untrusted data by the Agent boundary, and the observed image digest is an immutable fail-closed pin. Mutation/high-authority browser tools remain deliberately unpromoted and therefore are not a completion requirement for the observational BROWSER scope.

### P2 Cua PC_CONTROL

- [x] Pin/review upstream Cua version/commit and macOS bounded-mode contract. Runtime target is stable Cua Driver `0.28.3`, release tag `cua-driver-rs-v0.28.3`, release target commit `e1824be198d8d87f27402f6ac37549b581dd8d8a`. Official darwin-arm64 archive SHA-256 is `65b50e2f43df3dbd61dc615855c424f8c744dbb1527153b0dbbedb6f256d3801`; tag-pinned `install.sh` SHA-256 is `317ba3a49fdba10f2a7f1b9f392c1bc1b7657f3aae85e1e2e43684cf17a1bf3b`. Upstream explicitly states plain Driver SemVer is stable despite GitHub's monorepo prerelease label.
- [ ] Prove M1 installation, TCC persistence and bounded manifest behavior.
- [x] Reuse `BoundComputerPort / ComputerActionSpecialist`; add no Foundation desktop engine. Existing code already host-binds `pc_target`, chooses only host-supplied `ActionMethod` values, performs act -> independent observe -> exact expected-result verification, and rejects empty trusted operations.
- [x] Keep shell/JXA/script escapes outside normal grants. The existing Foundation PC boundary exposes only the `ComputerPort.act/observe` protocol and contains no shell/JXA/script execution path; the Cua transport must preserve that property.
- [ ] Test app/path/origin denial, stale state, human interference and destructive-action denial.
- [ ] Prove act -> observe -> expected-result verification plus lost-response/process-death/reconnect behavior.
- [x] Compare Munim only against a concrete Cua requirement failure; no such failure exists yet, so no second desktop backend is introduced.
- [ ] Wire PC_CONTROL and expose it to the Agent only after the real-host gate.

### P3 Jupyter COMPUTE

- [x] Pin/review Datalayer Jupyter MCP provenance/version and live tool schemas.
- [x] Prove local Jupyter first; non-local sandbox authority remains ungranted.
- [x] Bind `compute_profile` to host-selected backend/resources; prompt text cannot choose sandbox, roots, network or credentials.
- [x] Separate code execution from package installation, filesystem/network expansion and lifecycle authority: the promoted grant contains only `execute_code`.
- [x] Test host-path/network denial, timeout bounds, stale-backend fail-closed and owner-controlled cleanup/recreation on the real M1 path.
- [ ] Capture notebook/plot/file outputs as evidence/artifacts without treating execution success as external-effect verification. This is a later evidence extension, not authority to add notebook mutation/lifecycle tools.
- [x] Prefer generic MCP/compute boundaries; no Jupyter-specific Foundation client/router/sandbox manager was required.
- [x] Wire minimal COMPUTE and expose it to the Agent only through a trusted host-bound `compute_profile`; production-path E2E passed in run `36121399972`.

### P4 candidate review (historical pre-promotion stage) — 2026-09-25

At this pre-promotion stage, the canonical candidate was `nkrimmel/mcp-duckdb-analyst`, version 0.1.0 pinned for review at commit `31f2b9232fd4ad5f82f2ac7ff6ec99e36cc8d8c8` (tree `3ff778e91c024bd453fd0d7d6695410d62557abb`). It is MIT licensed, Python 3.11+, MCP SDK 2.x, stdio/streamable-HTTP capable, and intentionally read-only by default. Upstream implements the domain policy Foundation must not duplicate: single read-statement guard, path checks under a configured data directory, DuckDB `enable_external_access=false`, `allowed_directories`, extension autoload disabled, locked configuration, row/cell caps and query interruption. Saved-query writes and extension access are opt-in and therefore must remain disabled for Foundation.

Maturity is limited: the repository was created 2026-09-06 and currently has very low adoption. Therefore README claims are not promotion evidence. P4 must first pin/review exact source and prove the advertised restrictions independently on the M1 runner before any DATA wiring. Do not add a Foundation SQL parser/planner or replace the existing deterministic `BoundedDataPort/DataSpecialist` baseline.

### P4 exact-source review — 2026-09-25

Reviewed the pinned upstream implementation, not only its README. `server.py` exposes eight default read-only tools; `save_query` / `list_saved_queries` are registered only when `allow_saved_queries=true`. `guard.py` rejects write/DDL/effect keywords including COPY, ATTACH, INSTALL, LOAD, PRAGMA and SET by default, requires a single SELECT-family/EXPLAIN statement, validates literal file references under the configured data root, rejects remote schemes and applies a result LIMIT. `engine.py` supplies the independent DuckDB boundary and query interruption/result caps. Foundation must keep both opt-in flags off and independently adversarial-test the exact pin before promotion.

The upstream package dependency ranges are not themselves a reproducible Foundation pin (`mcp>=2.0`, `duckdb>=1.1`, etc.). The probe must therefore build/run from the exact upstream commit and retain its checked-in `uv.lock`; do not copy its Python implementation into Foundation and do not resolve floating dependencies ad hoc.

### P4 measured pre-wiring gate — 2026-09-25

Self-hosted M1 workflow `DuckDB MCP Probe` run `36123353781` passed at Foundation HEAD `90cddf05054e8953c4575d6b41a01ad99f760055`. Exact upstream commit `31f2b9232fd4ad5f82f2ac7ff6ec99e36cc8d8c8` was materialized from its checked-in `uv.lock`. Independent probes passed SELECT + row cap, multi-statement/COPY/ATTACH/INSTALL/LOAD/PRAGMA/SET denial, data-root path escape denial, remote HTTP denial, timeout interruption, opt-in write-tool absence, and the live MCP stdio contract/effect denial. Marker: `P4_REAL_HOST_PREWIRING_GATE_OK`.

This promotes the upstream backend security contract to the wiring gate; it does not itself grant DATA authority. The existing deterministic `BoundedDataPort/DataSpecialist` remains the default DATA path. DuckDB must be introduced only as a distinct trusted host-selected backend using the existing generic MCP registry/grant boundary, with no fallback or escalation into Jupyter COMPUTE.

### P4 production promotion — 2026-09-25

Self-hosted M1 `DuckDB MCP Probe` run `36124752309` passed at Foundation HEAD `aaef91d0238b14a02538ed21e86b867ecea7b2f9`. The exact pinned DuckDB backend ran through ToolHive and Foundation's existing generic MCP boundary. Measured markers include `P4_DUCKDB_TOOLHIVE_STDIO_OK`, `P4_FOUNDATION_DUCKDB_QUERY_OK`, `P4_DATA_DENIED_OK:save_query`, `P4_DATA_DENIED_OK:execute_code`, `P4_DATA_MISSING_BACKEND_FAIL_CLOSED`, `P4_DATA_BASELINE_PRESERVED`, `P4_FOUNDATION_COMPOSED_DATA_E2E_OK`, and `P4_PRODUCTION_WIRING_GATE_OK`.

Promoted authority is intentionally narrow: the deterministic DATA baseline remains separate; DuckDB is selected only by trusted host `data_backend`; the existing `MCPToolRegistry/MCPToolGrant/ToolHiveMCPClient` path owns generic transport; upstream owns SQL validation/execution; Foundation adds no SQL parser/planner and no DATA-to-COMPUTE fallback. The production probe mounts the host-owned data fixture read-only. Upstream query timeout/result caps remain in force; any stronger process-memory quota remains an outer runtime/container concern rather than Foundation SQL logic.

### P4 DuckDB DATA fast path

- [x] Re-review candidate provenance/maturity and choose an exact upstream commit for the probe; the required independent real-host evidence subsequently passed in runs `36123353781` and `36124752309`, so this historical prerequisite no longer represents an open promotion dependency.
- [x] Prove read-only/SELECT-style operation with host-owned data roots — M1 run 36123353781.
- [x] Deny path escape, ATTACH/COPY-style effects, extension loading and external/network access — M1 run 36123353781.
- [x] Enforce/query-test time and result bounds without building a Foundation SQL parser/planner — M1 run 36123353781. Upstream has no intrinsic memory cap; any memory bound must remain an outer runtime/container responsibility rather than Foundation SQL logic.
- [x] Preserve the narrow deterministic `DataSpecialist` baseline — production E2E run 36124752309 (`P4_DATA_BASELINE_PRESERVED`).
- [x] Never widen failed DATA authority into Jupyter COMPUTE automatically — production E2E run 36124752309 denied `execute_code` and proved missing backend fail-closed.
- [x] Wire the host-selected DATA backend only after the real-host gate — `data_backend` is mutually exclusive with deterministic `data_operation`; production ToolHive E2E run 36124752309 passed.

### Post-P1-P4 Thin Foundation Audit — 2026-09-25

A source-level responsibility audit was rerun after the measured P1-P4 promotions. The execution composition still has one generic MCP registry/transport boundary (`MCPToolRegistry -> ToolHiveMCPClient`). BROWSER, COMPUTE and DuckDB DATA dispatch only a generic `{tool,args}` envelope through that boundary; no backend-specific protocol client is present in `CapabilityExecutor`. Browser authority is an exact observational Playwright grant, not a Foundation browser driver. PC_CONTROL remains the narrow `ComputerActionSpecialist/BoundComputerPort` contract and contains no desktop automation engine. COMPUTE contains no Jupyter client/runtime/sandbox manager in Foundation. DATA retains only the pre-existing deterministic `json_summary/csv_summary` baseline plus generic MCP dispatch; there is no DuckDB client or SQL parser/planner. Agent semantics remain in Pydantic AI through `AutoCapabilityAgent/PydanticAgentPort`; the existing routing policy selects provider bindings and does not implement a second agent/tool scheduler.

The audit also identified two scope facts that must not be silently conflated with this thinness result: the promoted DuckDB grant currently exposes the reviewed upstream read-only tool set rather than only `query`, and `AutoCapabilityAgent` does not yet register the host-selected DuckDB backend as a model-visible DATA tool. Neither fact creates a duplicate engine, but both remain authority/exposure considerations for later gates; do not widen or expose them merely to satisfy this audit.

### Cross-backend authority convergence — 2026-09-25

Foundation CI run `36125806059` / #185 completed successfully at HEAD `2c7b081be48e67396e5f6a15b802312c4c2e801d`: compileall and Cedar preflight passed, followed by `954 passed, 10 skipped`. Existing regressions already cover untrusted browser/tool output, exact credential binding/target/principal/tenant/role checks with re-authorization before effects, fail-closed MCP grants, and unresolved-effect reconciliation. The convergence change adds one generic cross-backend regression with BROWSER, COMPUTE and DATA grants present simultaneously and proves prompt/tool-envelope fields cannot select another grant/server or invoke a tool outside the host-selected grant. This closes the authority-widening class at the shared MCP boundary rather than adding backend-specific filters. No runtime implementation was changed for this gate.

### Final convergence

- [x] Re-run Thin Foundation Audit after P1-P4: no second agent/router, browser driver, desktop engine, notebook runtime or SQL engine — source audit 2026-09-25; see evidence below.
- [x] Cross-backend prompt/tool-output injection, credential isolation, authority-widening and effect-reconciliation tests — Foundation CI run 36125806059 / #185 at `2c7b081be48e67396e5f6a15b802312c4c2e801d`: 954 passed, 10 skipped.
- [x] Full deterministic CI plus clean-checkout/rebooted-runner real-host E2E — post-reboot M1 evidence: Foundation CI run `36134635732`, Playwright run `36135977588`, Jupyter run `36136477885`, and DuckDB run `36137322948` all passed at HEAD `6b07d7375bdf34d092316b1ac98a794e3153fbbe`.
- [x] Remove obsolete probes/dead integration glue only after equivalent permanent evidence exists — the temporary dependency-lock probe and obsolete Playwright push trigger were retired after permanent frozen-CI/manual real-host evidence existed; final workflow/source audit retains only the manual Playwright/Jupyter/DuckDB revalidation probes and the Cua blocker probe, with no stale pre-authority/prewiring workflow tail.
- [x] Reconcile `CURRENT_STATE`, responsibility audit and boundary docs with actual implementation before declaring the execution layer complete — current docs and `oss_responsibility.py` agree that ToolHive is the generic MCP production boundary for promoted BROWSER/COMPUTE/DATA, FILES remains separately host-scoped, P2 PC_CONTROL remains BLOCKED on the upstream Cua signing gate, and no blocked authority is exposed. Final reconciled HEAD `59826680dfcabad59dc18cdc68917f65528d00d0` passed Foundation CI run `36138711055` / #204 on the rebooted M1: clean checkout, frozen uv 0.8.22 / Python 3.12.14, Cedar 4.13.0, and `954 passed, 10 skipped, 1 warning`.


### CI variance note — 2026-09-24

Foundation CI run `36006367865` reached 946 passed / 10 skipped and failed only the pre-existing broad latency-series ceiling because one of 200 CHAT selections measured 103.15 ms against a 100 ms worst-case ceiling while median was 0.46 ms. This change set does not touch provider selection. Do not widen the threshold or patch routing from this single runner outlier; rerun/collect evidence before treating it as a product regression.


### Playwright lifecycle correction — 2026-09-24

Run `36006859437` preserved digest, bounded egress, file containment, composed-runtime and stopped-workload denial, then failed only the attempted raw Docker restart. ToolHive reported the server as `starting` and refused the MCP call. Foundation must not add lifecycle reconciliation around Docker to compensate. Recovery remains ToolHive-owned; the probe now removes and recreates the same bounded workload through `thv`, then requires live inventory and an observational call.


### P1 promotion decision — 2026-09-24

Playwright observational BROWSER is promoted. Real-host run `36007144536` closes the remaining lifecycle gate with ToolHive-owned remove/recreate/reconnect while retaining immutable observed-image digest, bounded egress, no host mounts/file exposure, generic Foundation composition, exact observational grant, stale-call fail-closed and live-schema checks.

Mutation/high-authority tools are deliberately not promoted: navigation, click, type/fill, dialogs, upload, evaluate, mixed-action tabs and unsafe code remain absent from the Agent grant. The existing Guard already owns effect authorization, durable effect state, reconciliation and independent observation/verification. Foundation will not add a browser-specific effect engine or generic mutation DSL merely to expose upstream tools. A future concrete browser mutation may reuse Guard only when the host can define the target, action authority and deterministic expected postcondition without prompt-controlled privilege.

P1 is therefore complete for the promoted observational scope. Next implementation package is P2 Cua Driver bounded PC_CONTROL.


### P2 Cua Driver source audit — 2026-09-24

P2 starts from upstream `trycua/cua` commit `605d358a48ad938a41b384a8f23909153eb73f78`, not from a Foundation-owned desktop engine. Upstream now documents the exact authority shape Foundation needs:

- `bounded` is explicitly intended for unattended agents/gateways and requires a reviewed capability manifest; undeclared scope is denied.
- capability manifest v3 is deny-by-default and can bind exact tools plus application identity, browser origins, file roots and desktop display access; bounded mode also requires expiry and idle timeout.
- the host owns mode/manifest/approval. Agent tool calls cannot set or widen them.
- on macOS the supported daemon path is the installed `CuaDriver.app` identity; a raw daemon outside the app without embedded mode has no stable TCC identity and is unsupported.
- daemon-backed clients fail closed if the daemon disappears and verify contract/tool-schema/capability/MCP protocol compatibility before platform dispatch.
- origin-scoped browser work and generic desktop input must use separate runtimes/manifests; generic desktop input can otherwise bypass a browser-origin boundary.

Foundation consequence: keep `ComputerActionSpecialist` and `BoundComputerPort` as the thin act -> observe -> expected-result boundary. Do not implement a second manifest parser, app/origin/path policy engine, TCC manager, Cua session engine, or desktop router. The next real-host gate must install/run the upstream macOS identity in `bounded` mode with a short-lived host-reviewed application-scoped manifest, then prove allowed action plus out-of-scope app/tool/path denial, cancellation/process-loss/reconnect behavior, and independent post-action observation before PC_CONTROL becomes Agent-visible.

Browser-origin Cua is not a fallback for Playwright P1: Playwright remains the narrower browser backend. P2 desktop manifests must not include browser reach unless a separate reviewed runtime is explicitly introduced.


### P2 remaining gate — 2026-09-24

P2 is not yet promoted. The next implementation must pin an exact Cua Driver release, inspect its live macOS tool/schema surface, define one reviewed bounded manifest outside model control, and prove the real M1 denial/recovery matrix. Foundation-side code should be limited to the transport needed to satisfy the existing `ComputerPort` protocol plus trusted host composition. Do not add another PC router, manifest parser, policy engine, semantic action planner or Cua-specific verification framework.


### P2 Foundation-side thin audit — 2026-09-24

Current source already contains the complete backend-neutral Foundation boundary required before Cua transport: `CapabilityRequest.pc_target` is mandatory and host-resolved through `capability_factory`; `BoundComputerPort` rejects target widening; `ComputerActionSpecialist` accepts only host-supplied `ActionMethod` values and requires act -> observe -> exact expected result; `BoundPCAction` must be a trusted non-empty operation. There is no PC_CONTROL dispatch in `CapabilityExecutor` and no Agent registration yet, which is correct until the real-host Cua gate passes.

Do not add a Cua manifest model/parser, desktop semantic router, shell bridge, TCC manager, or Cua-specific verification layer. The only justified new runtime code after the real-host contract is proven is a minimal transport implementing the existing `ComputerPort` protocol plus trusted host composition. Until then P2 remaining work is upstream pin/live schema + M1 installation/TCC/bounded denial/recovery evidence, not Foundation abstraction work.


### P2 real-host preflight gate — 2026-09-25

A manual-only self-hosted workflow now checks the M1 for the supported installed `CuaDriver.app` identity and records code-signing/bundle identity evidence. It deliberately does not download/install Cua, grant TCC, create a manifest, or invoke desktop actions: those are authority-bearing host changes and must not be hidden inside CI. If the reviewed app identity is absent the probe exits fail-closed with `CUA_DRIVER_APP_MISSING`.

After the exact upstream release/artifact is reviewed and installed on the host, extend this same probe—not Foundation runtime—with live version/schema/contract evidence and the bounded allow/deny/recovery matrix. Only after that evidence passes should the minimal `ComputerPort` transport and trusted composition be added.


### P2 preflight expansion — 2026-09-25

The manual M1 preflight now also reads the installed app's bundle identifier/version/build/executable and requires the declared executable to exist and be executable. This remains read-only evidence collection. It does not infer that an arbitrary installed app equals the reviewed upstream artifact; artifact/version/signing equivalence must be established before any TCC or bounded desktop action test. This preserves fail-closed promotion without creating Foundation-side installation or identity logic.


### P2 current blocking boundary — 2026-09-25

Canonical HEAD `7a66a97095101bc11cd26038a0c4a529ca1f770d` passed Foundation CI run `36062835531`. No Cua Driver Probe run exists yet because the probe is intentionally `workflow_dispatch` only and the current repository integration does not expose a workflow-dispatch action. Do not convert this authority-bearing host probe to push-triggered CI merely to obtain a result.

Accordingly P2 is now explicitly BLOCKED on one host/operator action: manually dispatch `Cua Driver Probe` on the M1 runner. The resulting evidence determines the next branch:
- `CUA_DRIVER_APP_MISSING`: review/pin the exact upstream macOS artifact and install it as an operator action before any TCC/action testing.
- `CUA_DRIVER_RUNTIME_SURFACE_OK`: compare bundle/signing/version/build evidence with the reviewed upstream artifact, then extend the same probe with bounded/TCC denial and recovery tests.

While this gate is blocked, Foundation runtime must remain unchanged. Do not add PC_CONTROL dispatch, Agent exposure, a Cua adapter, manifest parser, TCC automation, or fallback desktop backend without the real-host evidence.


### P2 pinned installation plan — 2026-09-25

The failed M1 run `36066258379` is authoritative prerequisite evidence: macOS 26.6.2 arm64 is present and `CuaDriver.app` is absent. P2 therefore moves to installation, not Foundation implementation.

Reviewed target: Cua Driver `0.28.3` from tag `cua-driver-rs-v0.28.3` (release target `e1824be198d8d87f27402f6ac37549b581dd8d8a`). Prefer the official darwin-arm64 release asset and verify SHA-256 `65b50e2f43df3dbd61dc615855c424f8c744dbb1527153b0dbbedb6f256d3801` before installation; the tag-pinned installer itself is SHA-256 `317ba3a49fdba10f2a7f1b9f392c1bc1b7657f3aae85e1e2e43684cf17a1bf3b`. Do not use nightly artifacts or an unpinned `curl | bash` in the Foundation workflow.

After operator installation, rerun the manual probe. It now fails closed unless the installed bundle reports version `0.28.3`. Only after identity/version/signing evidence matches should the probe gain bounded manifest/TCC/action/denial/recovery checks. PC_CONTROL runtime remains unchanged until those gates pass.


### P2 identity/TCC gate hardening — 2026-09-25

The manual host probe now fails closed on macOS code-sign verification and Gatekeeper assessment before accepting the pinned 0.28.3 runtime surface. Previous best-effort `codesign ... || true` behavior was insufficient for promotion evidence and has been removed. The workflow explicitly records that Accessibility/Screen Recording remain operator-owned TCC permissions and contains no TCC reset/database-edit/grant automation.

This closes another Foundation-side design question without adding runtime code: artifact/version/signing identity is a host promotion gate, while TCC remains macOS/operator authority. The next action is still installation of the reviewed 0.28.3 app identity followed by this same manual probe; no PC adapter/dispatch/Agent code is justified before it passes.


### P2 installation handoff — 2026-09-25

The canonical host probe now requires all of the following before bounded testing: an installed `CuaDriver.app`, valid deep/strict code signature, successful macOS Gatekeeper assessment, executable bundle surface, and exact version `0.28.3`. TCC remains explicitly operator-owned; CI contains no `tccutil reset`, TCC database edit, or permission grant.

The remaining prerequisite cannot be truthfully completed by repository code: run `36066258379` proves the app is absent. Installing a desktop app and approving Accessibility/Screen Recording are host mutations outside the GitHub connector. Do not compensate with a bootstrap script committed to Foundation or an unpinned network installer. After the operator installs the pinned upstream 0.28.3 artifact, rerun `Cua Driver Probe`; its observed signature/Gatekeeper/version evidence becomes the input to the bounded manifest gate.


### P2 upstream release blocker — 2026-09-25

Real M1 installation evidence supersedes the earlier assumption that stable `0.28.3` is installable. The release installer was fetched with the release-published SHA256 `317ba3a49fdba10f2a7f1b9f392c1bc1b7657f3aae85e1e2e43684cf17a1bf3b` and pinned with `CUA_DRIVER_RS_VERSION=cua-driver-rs-v0.28.3`. It downloaded the official Darwin universal archive and stopped before changing the installed app with:

`error: downloaded CuaDriver.app failed signature verification; the installed app was not changed`

The separately verified Darwin arm64 archive also contains `CuaDriver.app` version `0.28.3` / bundle id `com.trycua.driver`, but `codesign --verify --deep --strict` reports `code object is not signed at all`.

Upstream tag-pinned installer source requires a valid deep/strict signature before replacing `/Applications/CuaDriver.app`; therefore Foundation MUST NOT ad-hoc-sign, bypass that check, copy the unsigned bundle into place, reset TCC, or add a Foundation-specific installer workaround. P2 is blocked on a reviewed upstream release whose official macOS artifact satisfies its own installer signature gate. Nightly builds are not substituted merely to make the gate pass.

The failed GitHub host probe `36067394778` remains consistent with this state: `CuaDriver.app` is absent. Foundation CI `36066714285` passed at canonical commit `c5c35e0624b8eec1b4272b5491324d160fc6d178`.

Until upstream provides a conforming release, continue independent OSS integration work (P3 COMPUTE / P4 DATA) without widening PC_CONTROL authority. Revisit P2 by reviewing a newer stable Cua Driver release and its macOS signing/install contract before changing the pin.


### P3 upstream contract review — 2026-09-25

Reviewed upstream Datalayer `jupyter-mcp-server` before adding Foundation code. It is a generic MCP server and already owns notebook/cell/execution semantics; Foundation must not add a notebook engine, code planner, or Datalayer-specific client. Current upstream documentation separates document storage from code execution and supports a local Jupyter Server sandbox as well as remote sandbox providers.

For Foundation the first promotion target is deliberately narrower than upstream's full surface:

- use the existing generic `MCPToolRegistry / BoundMCPTools / ToolHiveMCPClient` transport if the server can be run compatibly through ToolHive;
- bind COMPUTE to a host-selected `compute_profile`; model/payload text cannot choose Jupyter URL, token, sandbox variant, filesystem roots, credentials, package-install authority, or network authority;
- start with an existing local Jupyter Server sandbox rather than cloud sandbox lifecycle tools;
- do not grant runtime connection/sandbox-launch/terminate tools in the initial profile;
- grant only the exact execution/notebook tools proven necessary from the live MCP inventory, after inspecting their schemas;
- containment and Jupyter configuration own resource/filesystem/network boundaries; Foundation only selects the pre-reviewed profile and exact MCP tool grant;
- arbitrary code output is untrusted evidence, never instructions or proof of an external effect;
- no Agent exposure until the M1 probe proves live inventory, bounded execution, timeout, path/network denial, malicious-output handling, stale/restart failure behavior and cleanup.

Upstream currently documents package compatibility constraints between `jupyter-mcp-server` and `code-sandboxes`; therefore use an exact reviewed release pair, never `latest`, before the real-host probe.

Next P3 action: pin the exact upstream release/commit and inspect its Docker/package dependency surface plus live tool inventory. Only then add the smallest host composition/dispatcher branch needed for COMPUTE.


### P3 exact upstream pin — 2026-09-25

Reviewed the current stable Datalayer Jupyter MCP release from upstream rather than `main` or `latest`:

- release: `v2.2.2`
- tag commit: `a1a81d36ac66c0043eb1103ded9a4505af76840c`
- published: 2026-09-21
- Python: `>=3.10`
- MCP SDK: `mcp[cli]>=2,<3`
- `code-sandboxes>=1.9.0`
- `jupyter_server>=2.10,<3`
- upstream Dockerfile base: `python:3.12-slim`

This release resolves the earlier MCP-2 migration risk at the package boundary by explicitly requiring MCP SDK 2.x. The earlier generic compatibility note (`jupyter-mcp-server>=1.5.0` with `code-sandboxes>=1.1.1`) is superseded for the chosen pin by v2.2.2's own stricter `code-sandboxes>=1.9.0` dependency.

Do not vendor these Python dependencies into Foundation. The Jupyter MCP workload owns them. Foundation should pin the workload/release identity and communicate only over MCP.

P3 remains unpromoted until the real M1 probe establishes the exact live tool inventory and schemas. In particular, upstream exposes server/sandbox lifecycle, notebook mutation and arbitrary-code execution surfaces; the initial COMPUTE grant must be derived from the observed v2.2.2 inventory rather than copied from documentation or guessed tool names.

No Foundation runtime implementation is justified yet. The next repository change should be a fail-closed, manual M1 probe that installs/runs the pinned upstream workload independently of Foundation, records its identity/inventory, and makes no cloud credentials or Agent-visible grant available.


### P3 pre-authority probe staged — 2026-09-25

Added manual workflow `.github/workflows/jupyter-mcp-probe.yml` as the next fail-closed gate. It does not wire COMPUTE into Foundation. The probe:

- uses the canonical self-hosted macOS/ARM64 runner and canonical ToolHive bootstrap;
- checks out exact upstream commit `a1a81d36ac66c0043eb1103ded9a4505af76840c` and builds its upstream Dockerfile locally instead of consuming `:latest`;
- records the resulting local image identity;
- verifies the pinned CLI exposes the reviewed transport/sandbox/execution-timeout controls;
- records ToolHive's current Jupyter compatibility/registry surface;
- supplies no Jupyter token, notebook host root, cloud credential, sandbox lifecycle authority or Foundation COMPUTE grant.

This is intentionally only the pre-authority stage. Upstream v2.2.2 permits arbitrary IPython including shell syntax in `execute_code`, and its file/notebook tools operate against the configured Jupyter server root. Therefore a generic execution grant cannot be considered bounded merely because the MCP server itself runs in a container. The next gate must create a disposable local Jupyter fixture with an explicitly bounded root/network posture, then observe the live MCP inventory/schema and test timeout/path/network/stale/reconnect behavior before selecting any exact tool names for Foundation.

Do not add a Foundation shell filter, Python AST filter, SQL-style parser, notebook path sanitizer, or duplicated sandbox policy to compensate. If the upstream/Jupyter/ToolHive composition cannot contain arbitrary code to the reviewed profile, record P3 BLOCKED and evaluate the named backend/containment alternative rather than widening Foundation.


### P3 execution plan — 2026-09-25

Canonical planning gate after HEAD `632a3c5468814b9491e94469f6255522306b0ed3`. Execute P3 in this order and do not skip promotion gates:

1. **Pre-authority identity gate** — run the manual pinned-upstream probe and require exact commit checkout, successful upstream Docker build, reviewed CLI controls and no credentials/host roots/COMPUTE grant.
2. **Contained fixture gate** — extend the same probe, not Foundation runtime, with a disposable Jupyter Server fixture whose contents root is disposable and whose execution environment has no host filesystem mount. Prefer container/runtime/Jupyter ownership of containment; do not implement a Foundation code/path filter.
3. **Live contract gate** — connect the pinned Jupyter MCP server only to that fixture and record the actual MCP inventory, input schemas and annotations. Classify tools by observation/read, notebook mutation, arbitrary execution and connection/lifecycle authority. Do not infer safety from names or documentation.
4. **Adversarial containment gate** — prove ordinary execution, bounded timeout/interrupt, inability to read a host sentinel, inability to escape the disposable contents root, bounded/no network according to the chosen profile, malicious tool output treated as data, stale workload failure and supported recreate/reconnect cleanup. Any containment failure blocks promotion.
5. **Minimal composition gate** — only after 1-4 pass, reuse `MCPToolRegistry / BoundMCPTools / ToolHiveMCPClient`. Add only the smallest COMPUTE composition/dispatch branch required to select a host-defined `compute_profile`; do not add a Jupyter client, notebook engine, shell parser, sandbox manager or second router.
6. **Agent promotion gate** — expose COMPUTE to Pydantic AI only after exact allowed tool names are backed by the live contract and tests prove payload/model text cannot select server/profile/credentials/root/network/lifecycle authority.
7. **Regression/convergence gate** — run Foundation tests/CI, re-audit for redundant abstractions, update this canonical ledger with exact run evidence, then move to P4 DATA.

Stop conditions: upstream build/protocol incompatibility, inability to contain arbitrary IPython without Foundation policy duplication, unbounded host path/network access, stale authority surviving workload loss, or any need for model-controlled connection/sandbox configuration. Record such a result as P3 BLOCKED instead of patching around it.


### P3 pre-authority probe result — run 36070235055

The first manual Jupyter MCP probe reached the pinned upstream build successfully on the M1 runner. Host prerequisites, canonical ToolHive bootstrap and exact upstream Docker build all passed. The failure occurred only in the CLI contract assertion after the real `--help` output was produced: Typer/Rich shortened the long `--max-execution-timeout` label to `--max-execution-timeo…` at the runner terminal width, so an exact grep of presentation text returned exit 1.

This is not an upstream runtime/compatibility failure and no Foundation runtime code is changed. The probe contract check is corrected structurally: keep rendered help as runtime evidence, but verify exact option declarations against `serve.py` from the already exact-commit checkout. This avoids terminal-width/presentation coupling without weakening the pinned contract. Commit `1b7706af14922d41691b28ba04e5417cec327cff`.

Rerun the same manual probe. Do not advance to contained Jupyter authority until that corrected pre-authority gate passes.


### P3 Gate 1 passed / Gate 2 staged — 2026-09-25

Manual run `36070973360` passed the corrected pre-authority probe at canonical commit `c5ee0ead8982e877488191d0a0a5aac06cabf9d4`; Foundation CI run `36070881929` also passed at the same commit. P3 Gate 1 is therefore complete.

Gate 2 is now implemented only in the manual probe (commit `a022c11a6909f2c28c081c28865f7ae5ccec0afb`), not in Foundation runtime. It creates a disposable Jupyter container with:
- an internal Docker network;
- read-only container root plus bounded tmpfs scratch locations;
- exactly one host bind mount, a disposable runner-temp notebook root;
- Jupyter `root_dir` fixed to that mount and token authentication;
- loopback-only random host port;
- an independent host sentinel that must not appear in container mounts or the Jupyter contents API.

This gate intentionally does not yet connect the MCP server or expose COMPUTE. Its purpose is to establish the execution fixture boundary before live MCP inventory/schema observation. If this containment primitive fails on the M1 runner, fix or replace the OSS/runtime containment primitive; do not add a Foundation path/shell filter.


### P3 Gate 2 first-run evidence — run 36072122914

The contained-fixture run reached the new Gate 2 step after all Gate 1 checks passed. The Jupyter image was pulled and the container started, but the probe failed before any containment assertion because `docker port <name> 8888/tcp` returned `no public port '8888/tcp' published` for Docker Desktop's loopback/random-port form on this M1 runner.

This does not establish a containment failure: no root, sentinel, contents, execution or network assertion had run yet. The workflow now reads the authoritative published binding from Docker `NetworkSettings.Ports["8888/tcp"][0].HostPort` instead of relying on the convenience `docker port` presentation command (commit `8a626459366f4e85f957169da8e7628d698ad611`). No Foundation runtime code or security policy changed. Rerun Gate 2 before drawing any promotion conclusion.


### P3 Gate 2 boundary correction — run 36072625176

The second Gate 2 run again passed all Gate 1 checks and failed before a containment assertion. Docker's authoritative `NetworkSettings.Ports["8888/tcp"]` was empty, confirming that the prior host-publication assumption was wrong rather than merely a `docker port` formatting issue.

The probe no longer attempts to publish Jupyter to the M1 host. Commit `a24559741cd767a63774845f07601df9aeeee6dd` removes `-p` entirely and probes Jupyter from a disposable curl peer attached to the same Docker `--internal` network. It also asserts that the Jupyter fixture has no published ports. This is a boundary simplification and containment improvement: there is no host Jupyter listener to discover, authorize or later reproduce in Foundation.

Foundation runtime remains unchanged. Gate 2 must pass with this host-unpublished topology before MCP connection or COMPUTE composition is added.


### P3 Gate 2 third-run evidence — run 36073663741

The host-unpublished topology worked far enough for the disposable peer to contact the Jupyter fixture immediately after the curl image was available; the step then exited before mount/root/sentinel checks. The remaining assertion had conflated Docker image metadata with host authority: a container image can declare `EXPOSE 8888`, causing `NetworkSettings.Ports` to contain the container port even when no host publication exists.

Commit `3c42fcc21d9494eca023a136b2128380797c3fde` now asserts the actual authority-bearing Docker state, `HostConfig.PortBindings`, is empty/null. This does not relax the requirement: the fixture still has no `-p`/published host listener and is reachable only by a disposable peer on the internal network. No Foundation runtime code changed.


### P3 Gate 2 passed / Gate 3 staged — run 36074062966

Run `36074062966` passed at HEAD `3b6723cc945d1ffcce1de9736742994701b21892`; Foundation CI run `36073977045` also passed at the same HEAD. The run proved the host-unpublished/read-only/internal-network behavior, but later canonical reconciliation found that this fixture still used a runner-temp bind mount and therefore did not satisfy Gate 2's stricter requirement that the execution environment have no host filesystem mount. Treat run `36074062966` as partial Gate 2 evidence, not final Gate 2 completion.

Commit `bad8c32dc01b14048fee36c087c893b6cee057da` stages Gate 3 in the manual probe only. It starts the exact already-built v2.2.2 MCP image on the same internal network, explicitly disables new sandbox creation, pins the `jupyter-server` execution variant and the contained fixture URL/token, bounds default/max execution timeout, and publishes no MCP host port. The exact image's own MCP SDK is used only as a disposable observation client to call initialize/list_tools and record the live tool names, input schemas and annotations. This is evidence collection, not a new Foundation client/runtime dependency.

No Foundation COMPUTE dispatch or Agent grant is added. Gate 3 must pass before the observed tools are classified or any exact grant is selected; Gate 4 adversarial containment remains mandatory before runtime composition.


### P3 Gate 3 first-run evidence — run 36076869592

Gate 2 passed again. The exact pinned MCP container also started successfully and logged a healthy Uvicorn/streamable-HTTP startup, but the Gate 3 probe never reached MCP initialization because the workflow had assumed an HTTP `/health` route. Upstream v2.2.2 returned 404 for that route on every request; this was a probe assumption, not an MCP/Jupyter failure.

Commit `74e1afb6bb5621ec4efd30b32e76a5c7e77c17b0` removes the invented health endpoint entirely. Readiness is now established by the protocol contract being tested: the exact pinned SDK client retries MCP `initialize` plus `tools/list` while the server container remains running. There is no parallel HTTP health abstraction and no Foundation runtime change.


### P3 Gate 3 second-run evidence — run 36078222347

Gate 2 passed again and the pinned MCP server started successfully. The live-contract client failed before any network/protocol call because the installed pinned MCP SDK exports `streamable_http_client`, while the probe referenced the non-existent `streamablehttp_client`. The runtime error itself reported the exact installed symbol. Commit `07c1028922e391a0e2044c3b4d72fe933333a98b` corrects only that probe symbol; no Foundation runtime, authority, or abstraction changed.


### P3 Gate 3 third-run evidence — run 36080241608

Gate 2 and pinned MCP server startup passed again. The exact installed MCP SDK then reached the streamable-HTTP context manager, whose implementation at `mcp/client/streamable_http.py` yielded exactly `read_stream, write_stream`. The probe expected a three-item tuple and therefore failed locally with `ValueError: not enough values to unpack (expected 3, got 2)` before MCP initialization. Commit `379cee90464e89b0d7b11a55a2f618ec68e2f21a` aligns the probe with that observed pinned SDK contract only; Foundation runtime and authority remain unchanged.


### P3 Gate 3 third-run evidence — run 36080241608

Gate 2 passed and the pinned MCP server again started successfully. The corrected SDK symbol was imported, but the probe still encoded the wrong return arity: this pinned SDK's `streamable_http_client` yields exactly `(read_stream, write_stream)`, not a three-item tuple. The traceback came directly from the installed SDK implementation (`yield read_stream, write_stream`). Commit `eb66ddd335d9b6a0327dca9c96e6d9f1c4ea8b05` aligns the probe with that observed pinned contract only. No Foundation runtime or authority change.


### P3 canonical reconciliation after run 36081577820

Before another M1 run, the canonical plan and exact v2.2.2 upstream source were re-read rather than patching the latest symptom.

Two structural issues were identified and corrected in the probe only:

1. **Gate 2 host-filesystem inconsistency.** The canonical Gate 2 requirement says the Jupyter execution environment has no host filesystem mount. Earlier probe revisions used a disposable `RUNNER_TEMP` bind mount and later documentation incorrectly called Gate 2 complete. The fixture now uses a Docker-managed named volume for `/home/jovyan/work`, asserts that its only mount is that volume, and rejects any runner-temp mount. The disposable peer image is also digest-pinned to the identity already observed on the M1 runner.
2. **Gate 3 transport mismatch.** Run `36081577820` reached the exact pinned MCP server but was correctly rejected by MCP SDK DNS-rebinding protection with HTTP 421 because v2.2.2's CLI exposes no Host allowlist setting and its server calls `streamable_http_app()` without one. Do not disable that protection, spoof Host, or add a Foundation HTTP wrapper. Upstream v2.2.2 natively supports `stdio`, and ToolHive/MCP already owns the process/transport boundary, so Gate 3 now observes the exact server over stdio while that process remains attached only to the internal Docker network for access to the contained Jupyter fixture.

Commits `14b196d37897b767101bfb0c715817f1514f7c4d`, `2e4044b6c163c85b2478a73a7c643b50b4d7628f`, and `9738ae4ea845b1bf83375a8498f271df3b9aba0b` implement this convergence. Foundation runtime remains unchanged: no Jupyter client, Host sanitizer, transport-security override, notebook engine, shell filter, COMPUTE grant, or Agent exposure was added.

The next M1 run is therefore a combined re-validation of the corrected host-mount-free Gate 2 boundary and the live Gate 3 stdio contract. Do not claim either gate complete until that run's actual logs are inspected.


### P3 Gate 3 module-entrypoint evidence — run 36088058321

Run `36088058321` revalidated the corrected Gate 2 boundary: the fixture had no host port binding, its only mount was the Docker-managed volume at `/home/jovyan/work`, the internal network assertion passed, and the host sentinel remained outside the Jupyter contents surface (`JUPYTER_CONTAINED_FIXTURE_OK`). This is the first run that satisfies the canonical host-filesystem-free Gate 2 requirement, so Gate 2 is complete on this evidence.

Gate 3 then failed before MCP initialization because the probe invoked `python -m jupyter_mcp_server serve ...`. Exact upstream commit `a1a81d36ac66c0043eb1103ded9a4505af76840c` defines `jupyter_mcp_server.__main__` as a direct call to the Typer `serve` application; its options therefore belong at the module root and there is no nested `serve` command. The same upstream package also publishes `jupyter-mcp` and `jupyter-mcp-server` directly to that application. Commit `fda66e1ef9da5991e05665fc720ec51bd395e70b` aligns the stdio probe with that exact entrypoint contract and adds a pinned-source assertion for the module entrypoint. No Foundation runtime, COMPUTE authority, Jupyter-specific client, wrapper, parser, or security-policy code was added.

The next manual run is Gate 3 live-contract validation only; Gate 2 need not be redesigned unless its established assertions regress. If Gate 3 succeeds, use the observed live tool contract to classify and stage Gate 4 adversarial tests before any Foundation composition.


### P3 Gate 3 passed / Gate 4 staged — run 36089295035

Run `36089295035` completed successfully at HEAD `e0a94e020d3695b9664f98f6e485210bd94ac593`. The corrected host-filesystem-free Gate 2 fixture passed again, and the exact pinned v2.2.2 stdio server completed MCP initialize/tools-list. The live contract exposed 18 tools: `clear_cell_output`, `connect_to_jupyter`, `delete_cell`, `edit_cell_source`, `execute_cell`, `execute_code`, `insert_cell`, `insert_execute_code_cell`, `list_files`, `list_kernels`, `list_notebooks`, `move_cell`, `overwrite_cell_source`, `read_cell`, `read_notebook`, `restart_notebook`, `unuse_notebook`, and `use_notebook`. Gate 3 is complete on this evidence.

The observed contract confirms that `connect_to_jupyter` is connection/lifecycle authority because its caller controls `jupyter_url` and `jupyter_token`; it must not enter the initial COMPUTE grant. `execute_code` is explicitly destructive, non-idempotent, open-world and supports Python, IPython magic and shell commands. Do not add a Foundation shell/code parser: containment must be proved at the Docker/Jupyter execution boundary. Notebook/cell mutation and restart tools remain mutation authority and are not candidates for an initial observational/execution grant until effect policy is designed around them.

Commit `122a0a05d29e649a81d993f2f589a48b8193a68c` stages Gate 4 in the existing manual probe. Using only the exact upstream MCP SDK/server image, it tests: dynamic-connection tool classification; Jupyter contents-root traversal/absolute-path attempts without host-sentinel exposure; simple arbitrary Python and shell execution while the host path remains hidden; Internet egress denial from the kernel on the Docker internal network; upstream execution-timeout clamping with an oversized caller timeout; and preservation of instruction-shaped execution output as data only. No Foundation runtime, Jupyter-specific client, code/shell sanitizer, second router, sandbox manager, COMPUTE grant or Agent exposure is added.

This Gate 4 run is evidence-only. If any assertion shows that arbitrary execution escapes the runtime/Jupyter containment boundary, stop P3 and record it BLOCKED rather than compensating with Foundation policy duplication. Stopped/stale process and owner-controlled recreate/reconnect remain required before Gate 4 is complete; add them only after the execution-boundary assertions above establish that this composition is viable.


### P3 Gate 4 first-run evidence — run 36089719485

Run `36089719485` re-passed Gates 2 and 3 through `JUPYTER_MCP_LIVE_CONTRACT_OK`, then failed before the first adversarial containment action. The failure was local probe/schema representation mismatch: the pinned MCP SDK returns a Pydantic `Tool` whose Python attribute is `input_schema`; the earlier JSON serialization used the wire alias `inputSchema`. No filesystem, arbitrary-code, network, timeout, or malicious-output assertion had executed, so this run is not containment-failure evidence.

Commit `09a3db2f4a2bd87f4d52c6bc0ab3ac3f04bd978f` aligns the in-process Gate 4 inspection with the pinned SDK model contract while preserving the wire-format Gate 3 assertion. The same workflow now also starts a second fresh exact-pinned stdio process after the adversarial execution checks and requires a new live contract, proving owner-controlled process recreation without adding Foundation recovery/cache authority. Foundation runtime remains unchanged.

Do not compensate for any subsequent containment failure with a Foundation code/shell/path/network sanitizer. The next run must execute the actual Gate 4 boundary assertions. Stale-session/process-loss behavior remains a required gate; it should be proven using an owner/runtime lifecycle mechanism with a stable public process boundary rather than reaching into MCP SDK private internals.


### P3 Gate 4 convergence after run 36089719485

Run `36089719485` reached the already-proven live contract and failed before any adversarial containment assertion because the probe used the wire-schema spelling `inputSchema` on the MCP SDK's typed `Tool` object. The pinned SDK exposes that field as `input_schema`. This is probe-contract evidence, not a containment failure; Gate 2 and Gate 3 passed again in the same run.

The workflow now uses the typed SDK contract and, rather than requesting another run for that spelling alone, commit `3cee5d181b10a8b81ac63035527efb87d5b346ce` completes the staged Gate 4 batch with lifecycle evidence. After the execution-boundary assertions, the workflow owner stops the bounded Jupyter fixture, starts a fresh exact upstream stdio MCP session against the now-stale host-defined endpoint and requires its filesystem call to fail closed. It then recreates only the same Docker/Jupyter-owned fixture and re-runs the live contract probe. The model is never given `connect_to_jupyter`; no caller-selected URL/token, Foundation reconnect wrapper, Jupyter client, parser, sandbox manager, or new policy layer is introduced.

A successful next run therefore closes the planned Gate 4 evidence set in one execution: contents-root/host-path isolation, arbitrary Python/shell containment, network denial, timeout clamping, instruction-shaped output as data, stale-backend failure, and owner-controlled recreate/reconnect. Any escape or stale-authority success remains a P3 BLOCKED condition rather than a trigger for a Foundation workaround.


### P3 Gate 4 typed-contract normalization — run 36092548317

Run `36092548317` again passed Gates 2 and 3 through `JUPYTER_MCP_LIVE_CONTRACT_OK`, then stopped at the Gate 4 classification precondition. The previous fix correctly used the typed SDK field `input_schema`, but the next assertion used the wire alias `destructiveHint` directly on the typed `ToolAnnotations` object, whose Python field is `destructive_hint`. No adversarial filesystem/code/network/timeout assertion executed; this is not containment-failure evidence.

Commit `7de6341cf986122ae61028f9810ee6ceac16940f` removes the entire alias-class mismatch rather than chasing fields one by one: Gate 4 now serializes the typed SDK Tool once with Pydantic `model_dump(mode="json", by_alias=True, exclude_none=True)` and performs contract classification against the same MCP wire representation already validated by Gate 3. This is an upstream SDK serialization boundary, not a Foundation adapter. The already-staged execution, stale-backend, and owner-recreate tests remain in the same workflow; Foundation runtime remains unchanged.


### P3 Gate 4 SDK contract normalization — run 36092548317

Run `36092548317` failed before any adversarial containment assertion. Gate 2 and Gate 3 passed again through `JUPYTER_MCP_LIVE_CONTRACT_OK`. The failure was another Python SDK alias mismatch: the typed `ToolAnnotations` object exposes snake_case fields while the MCP wire contract uses camelCase. This is probe coupling, not containment evidence.

Commit `6b8a5d1b4abf98996fb7d2638a69eedab8d69934` removes that class of coupling instead of patching individual aliases: Gate 4 serializes typed MCP Tool objects through Pydantic with `by_alias=True` and performs contract classification against the actual MCP wire keys (`inputSchema`, `destructiveHint`). Result fields used as typed Python objects use their SDK snake_case names (`structured_content`, `is_error`). The same Gate 4 workflow already batches execution containment, contents-root escape attempts, host-path hiding, internal-network egress denial, timeout clamping, instruction-shaped output-as-data, fresh-process contract recreation, stale-backend fail-closed, and owner-controlled backend recreation. No Foundation runtime or authority grant is changed.


### P3 Gate 4 passed — run 36101646971

Run `36101646971` completed successfully at HEAD `ae298e865e6c9a34c8d5e9e0f75e858dfd46bb70`. Gate 2 and Gate 3 revalidated first: the Jupyter fixture had no host port binding, its only persistent mount was the Docker-managed volume at `/home/jovyan/work`, the host sentinel remained outside the Jupyter contents surface, and the exact pinned stdio MCP server again exposed the validated 18-tool live contract.

The complete staged Gate 4 adversarial batch then executed and passed. `connect_to_jupyter` was classified as connection/lifecycle authority and remains excluded from the initial COMPUTE grant. Jupyter contents-root traversal and absolute-path attempts did not expose the host; arbitrary Python and shell execution remained inside the bounded Jupyter/Docker environment; Internet egress was denied by the internal network; instruction-shaped execution output remained data; the upstream execution timeout bounded an oversized caller timeout; a fresh exact-pinned MCP process reproduced the live contract; stopping the Jupyter backend caused a fresh MCP session against the stale endpoint to fail closed; and owner-controlled recreation of the same bounded backend restored the contract. The run emitted `JUPYTER_MCP_GATE4_ADVERSARIAL_OK` and completed successfully.

Gate 4 is therefore complete on measured evidence. No Foundation Jupyter client, code/shell/path/network sanitizer, reconnect wrapper, sandbox manager, second router, COMPUTE grant, Agent exposure, or caller-controlled connection authority was added. The containment and lifecycle responsibilities remain owned by Docker/Jupyter/upstream MCP plus the existing generic MCP boundary.

P3 may now proceed to the next composition gate using the existing `MCPToolGrant / MCPToolRegistry / BoundMCPTools` and generic ToolHive/MCP transport. Composition must select only the minimum exact tools required by the COMPUTE contract; `connect_to_jupyter`, notebook/cell mutation tools, and restart/lifecycle tools remain excluded unless a later explicit effect-policy gate authorizes them. Gate 4 success is containment evidence, not ambient COMPUTE authority and not production completion.


### P3 minimum COMPUTE composition passed CI — run 36107487906

At HEAD `dc6d47522619624dcf8edce5a6c9e4017aa94445`, Foundation CI run `36107487906` completed successfully after the self-hosted runner resumed. The unit job passed setup, compile, Cedar policy preflight, and the full test step.

The implementation reuses the existing Generic MCP boundary rather than adding a Jupyter-specific Foundation layer. `CapabilityExecutor` dispatches trusted COMPUTE requests through `MCPToolRegistry`; host composition registers `compute-main` only when `AI_FOUNDATION_COMPUTE_SERVER` is configured; the initial exact grant contains only `execute_code`; and `AutoCapabilityAgent` exposes COMPUTE only when the trusted request already carries `compute_profile`. The model cannot select the MCP server or mint the compute profile.

Focused regressions prove that `connect_to_jupyter`, restart/lifecycle authority, and an unregistered compute profile fail outside the grant. No Foundation-owned Jupyter client, parser, sanitizer, reconnect wrapper, sandbox manager, or second router was introduced.

This closes the minimum exact-tool composition unit. It does not yet close P3 production evidence. The next unit must exercise the real Foundation production path through the configured Generic MCP/Jupyter boundary and prove successful bounded execution plus fail-closed authority behavior. Do not widen the grant to obtain that evidence.

### P3 production-path promotion evidence — 2026-09-25

Jupyter MCP Probe run `36121399972` (run #22), HEAD `90ba3893a68d9bbc90bbb1083b4d821fed9f7852`, completed successfully on the self-hosted M1 runner. The existing contained/adversarial Gate 4 remained green and the real Foundation production path also passed end to end.

Measured production path: Foundation trusted `compute-main` profile -> exact `execute_code`-only `MCPToolGrant` -> generic `ToolHiveMCPClient` -> ToolHive stdio workload -> pinned Datalayer Jupyter MCP -> contained local Jupyter. Markers: `JUPYTER_TOOLHIVE_STDIO_OK`, `FOUNDATION_EXECUTE_CODE_OK`, `JUPYTER_FOUNDATION_COMPOSED_E2E_OK`, and `JUPYTER_P3_PRODUCTION_PATH_OK`. Foundation independently denied `connect_to_jupyter` and `restart_notebook` through the same grant boundary.

The same run reconfirmed contained filesystem/root behavior, denied external network egress, bounded execution timeout, non-authoritative output handling, stale-backend fail-closed behavior, and owner-controlled recreation. No Jupyter-specific Foundation client, parser, sandbox manager, semantic router, or lifecycle authority was added. ToolHive/Jupyter lifecycle cleanup is owner-aware so stale manual workloads cannot silently collide with the CI fixture.

P3 is therefore promoted for the current minimal COMPUTE authority: host-selected local profile plus `execute_code` only. Package installation, notebook mutation/lifecycle tools, broader filesystem authority, network egress, and non-local/cloud sandbox authority remain ungranted and require a separate evidenced requirement before expansion. Artifact capture for notebook/plot/file outputs remains a later capability extension rather than a prerequisite for this minimal execution grant.
