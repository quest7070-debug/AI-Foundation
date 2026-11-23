# Phase G — Integration / User Experience

## Goal
Evolve the already-implemented Foundation Settings/Operator into an evidence-driven one-page whole-system dashboard that supervises the primary daily path: owner -> ChatGPT/Muse/other existing AI -> authorized MCP/API -> Foundation -> real execution -> independent verification -> calling AI result and Operator observation. The UI is not the default chat/task entry.

## Design language
Use terminal/HMI references from DEATH STRANDING, Arknights and Arknights: Endfield, together with Techwear-inspired UI, Urban Tactical Interface, Diegetic Industrial UI and Tactical HMI. Borrow design principles, not logos, assets, or literal screen copies.

The surface should feel like an operational device: functional grid/panel structure, compact identifiers and status codes, clear hierarchy, dense local telemetry balanced by deliberate negative space, and visual treatment driven by actual system state. Avoid decorative cyberpunk noise.

## Human state model
Primary states are READY, RUNNING, WAITING_HUMAN, VERIFIED, UNCERTAIN, FAILED and RECOVERING. Cloud/local route, specialist, tool/MCP, Guard decision, verification/evidence and provider/tool health remain inspectable without exposing raw credentials.

## Development priority and acceptance (owner direction 2026-11-22)

Follow the three-stream policy in END_GOAL.md: P0 self-maintenance/repair and
P0 committed development (existing plans, incomplete capabilities and owner
orders); P1 research-driven development. First restore blockers that prevent
either P0 stream from progressing, then complete their actual intended
results through independent acceptance and, when relevant, authorized
production release/readback. Pending reviews, failed local acceptance,
stale source, unpublished or uninstalled changes and uncertain outcomes are
not completed work. Research in support of these P0 outcomes is part of the
same work, not an independent exploration backlog. M1 owns the existing schedule,
Work ledger, local Git source, independent acceptance and authorized release.
GitHub is primarily record preservation; keep remote publication failures as
separate pending delivery, not a reason to rerun effects or block otherwise
permitted local work. Remove mandatory Issue/PR/Actions dependencies from the
normal path through a verified in-place replacement, retaining actual Guard
scope and local source provenance. Do not prioritize
unrelated new-feature investigation merely because there is no executable
ticket at this instant. Reuse the existing Work inventory, resource lease,
Guard decisions and one-page Operator evidence; no new authority or queue.

## Agent execution observability — AgentMon Live-inspired capability (goal added 2026-11-21)

Extend the existing OVERVIEW/TASKS/NOTIFICATIONS views; do not install a second dashboard or delegate approval, durable work or VERIFIED truth to a monitoring agent. Reuse Foundation job/attempt identity and existing execution/evidence telemetry, and map genuinely observable Codex, optional Strata and M1 9B activity into one trace model through adapters. Unknown or unsupported integrations are explicitly marked as such.

- For each authorized agent-run: runner identity, source/job/attempt ID, real status and timestamp/freshness, current step, relevant tool errors, test/check age, retry/repair state and evidence link.
- Distinguish generated/finished, test-accepted, delivered, released and independently read back; failures, stale tests and source mismatches must not produce VERIFIED. Guard/Operator remains authoritative for release and approvals.
- Use bounded, Guard-admitted repair/reverification only where existing policy already permits it; otherwise emit precise LV1–LV5 diagnostic/decision notices in the current surface.
- Retain privacy boundaries: do not stream secrets, raw owner HumanModel data or protected logs to an external dashboard. Third-party tool adoption depends on independently verifying functionality/license and may be replaced by small adapters instead of installing the full product.
- No mandatory chargeable advisor/model calls or new resident model. No extra state store or duplicate activity poller. Preserve the existing C/I layouts and mobile responsiveness.

**Done when:** one actual host-authorized run proves live task-event correlation, a failed or stale verification remains visibly NOT VERIFIED, legitimate repaired/rechecked work reaches the already-defined independent acceptance gate, and Operator plus the calling AI display the same evidence-bound status. This is an implementation goal, not a statement that the adapters or dashboard are deployed.

## G1 — Human Decision Surface
Evolve the **existing Foundation Settings/Operator UI in place**, making OVERVIEW the default one-page whole-system dashboard and preserving its full SETTINGS, routing, task, notification, approval and recovery functions as drill-down surfaces. Do not create a second dashboard frontend, database or authorization plane. Normal work originates from upstream daily-use products/automations; this surface must not become a duplicate chat/task-entry product. Keep presentation clients replaceable; the Human Decision Surface / Operator owns the current Foundation supervision semantics.

## G2 — Execution integration
Connect representative owner-chosen external-AI MCP/API calls through the existing authenticated Host/Guard and, when needed, its Pydantic AI Agent, Specialist and ExecutionPort boundaries. Provider routing remains outside the UI.

## G3 — Decision and recovery journeys
Approval, cancellation, failure, ambiguous-effect reconciliation and recovery are first-class human journeys. Guard remains the authority boundary.

## G4 — Real environment
Add cloud/local compute and Tool/MCP adapters incrementally. Meaningful external effects require independent readback and evidence.

## G5 — End-to-end gate
Prove a real authenticated external-AI MCP request -> Foundation -> verified result returned to its caller, with the same activity and exceptional decisions observable in the existing Operator dashboard; also verify private/local route, human approval, external effect, failure, reconciliation and restart recovery.

## G6 — Closure
Representative work from daily-use entry points is supervised through this UI and returns understandable verified results/status; the Foundation operator is not itself the normal task-entry surface. Production migration remains Phase H.

## Multi-surface UI requirement
Phase G uses one existing Operator semantic state model and design language across desktop/web (complete OVERVIEW dashboard, settings and decisions), responsive mobile (the same dashboard and exception controls), and Echo Show 5 (glanceable read-only status/notifications with only already-approved safe dismissals). Echo Show must prioritize system state, active work, alerts, provider/local status and a very small number of safe actions rather than reproducing the desktop UI.

## Rapid visual review loop
UI work is iterative and must be reviewable immediately after each meaningful visual change. Keep a development preview server on the M1, expose explicit desktop, mobile and Echo dashboard preview routes, and preserve representative fixture states so READY, RUNNING, WAITING_HUMAN, VERIFIED, UNCERTAIN, FAILED and RECOVERING can be reviewed without manufacturing real incidents. Visual changes are not considered accepted after first implementation; review and revision are expected before Phase G closure.

## Accepted visual baseline — I (2026-09-18)
Variant I is the accepted Phase G design baseline, not a frozen final layout. C remains a reference for dense telemetry; I is authoritative for new UI work. Earlier E/F/G/H variants are exploration history only.

Baseline rules:
- dark blue is the dominant field/background;
- brighter blue denotes interactive controls and actionable selection;
- Endfield-inspired yellow is the secondary information accent for identifiers, route/index markers, manifest boundaries and trace/industrial annotation;
- red is sparse and reserved for warnings, human interrupt/authority and exceptional attention;
- retain G's terminal/order/manifest mental model and C's useful information density;
- preserve layered information hierarchy and deliberate negative space; do not distribute accent colors uniformly;
- borrow principles only: no game logos/assets, literal screen copies, or product-specific fictional branding;
- button, workflow and responsive implementation may change layout where usability requires it. The baseline constrains design language, hierarchy and semantic color roles, not pixel positions.

Next implementation step: turn the I baseline from a view-only fixture into the G1 Human Decision Surface shell. First functional slice is active order/status + human decision/input queue + evidence/readback, while keeping Guard as the authority boundary and keeping preview fixtures separate from real actions.

## 2026-11-13 current owner decision — upgrade the existing Settings screen, not a new dashboard

This section **supersedes only conflicting older SETTINGS-first or LibreChat-centric instructions** below and in the dated G execution plan. It preserves the already-built Settings/Operator code, current HumanView and action endpoints, accepted C/I skins and one-layout-per-surface semantics; historical UI work is an implementation asset, not disposable prototype work.

1. **One existing application, default OVERVIEW**: change the current Settings/Operator opening view from SETTINGS to an evidence-driven, single-page whole-system OVERVIEW. SETTINGS stays a complete, prominently reachable panel/tab; do not replace provider onboarding, credential binding, route optimization, Guard decisions or Tasks with new widgets. Keep the existing URLs/actions working where compatible.
2. **What the one page answers**: which Foundation capabilities actually exist; which are source-only versus installed; which ChatGPT/Muse/other authenticated client MCP connections are genuinely observed; which tools/scopes are exposed; active/queued/failed/uncertain development or durable work; 9B/lease and free provider/health/quota; HumanModel accessible View revision and real owner-answer acceptance; KLM coverage/lag/reviews; Guard decisions; latest verified result, timestamp and recovery action. Avoid made-up percentages and ungrounded session telemetry.
3. **Source of truth**: reuse current `OperatorApplication.human_payload`, Guard/Work/Operator observations, existing read-only M1 runtime and KLM receipts, owner-bound MCP capabilities and HumanModel evidence. Add a bounded **read-only aggregation/projection** only for missing observed fields; never create new task, approval or monitoring databases, schedulers or polling loops to paint a dashboard. Explicit UNKNOWN/STALE/BLOCKED must remain visible instead of false green/offline.
4. **Visual and responsive continuity**: retain semantic C/I themes, same section order/action meaning across themes and responsive widths, existing one-app web/mobile framework, and Echo restrictions. Expand/collapse to underlying existing Settings, task, notices and trace/detail screens without creating a second independent product.
5. **Evidence gates**: (a) current Settings controls still function; (b) source-only/installed/connected/running/independently verified are distinguishable; (c) failures are not hidden by dismissal or HTTP 200; (d) real owner-approved external-AI MCP request and its readback appear in the Operator; (e) no raw secrets/private records in dashboard or GitHub; (f) M1 installed-runtime acceptance separately from source/CI.
6. **Delivery order**: inventory current settings navigation and payload -> add reusable overview composition to current Operator -> expose existing drilldowns -> wire only currently available trusted observations -> verify desktop/mobile/Echo and C/I parity -> complete real external-MCP-to-result E2E. UI work must not hold back separately authorized HumanModel/Harness/KLM development.

## Human Surface product decisions — 2026-09-19
These decisions are canonical for Phase G unless explicitly revised later.

Latest clarification (2026-09-19): the Human Decision Surface supervises work originating elsewhere; any earlier Phase G text describing this Operator as the normal `task entry` surface is superseded. Internal TaskIntake may remain an integration/test boundary, but it is not a user-facing work composer.

### Surface roles and language
- Product naming must display `AI FOUNDATION` in full on user-facing surfaces; do not abbreviate the product name to `AF`.
- Desktop layouts must be responsive to the actual browser viewport and must not rely on a centered fixed-width canvas that visually clips/loses the right side.
- Foundation's existing Settings/Operator is the operational dashboard for work invoked primarily from ChatGPT, Muse or other external agents over approved MCP/API; chat is not part of this UI.
- **Superseded 2026-11-13:** Desktop/M1 opens to **OVERVIEW within the existing Settings/Operator UI**, not a new standalone HOME/dashboard app. Existing SETTINGS remains the complete provider/credential/route configuration destination; Tasks, notifications and Guard decisions remain accessible from the same UI. The overview prioritizes actual integrations, capability/run/verification state and exceptional attention; device/backup/update appear only when genuinely relevant.
- UI chrome, labels, states and action controls are primarily English (for example SETTINGS, ROUTING, ACTIVITY, AUTHORIZE, DENY, DETAIL). Human-facing explanatory content that must be understood correctly is Japanese. Notification and approval explanatory text is Japanese-fixed.
- Browser UI is one responsive Human Decision Surface. Viewport width changes geometry only; it does not create a separate Mobile authority/information surface. The full browser feature set remains available at narrow widths. Echo remains the only intentionally constrained surface.
- Echo Show 5 is dashboard-only: SYSTEM and NOTIFICATIONS views, manual switching, no settings, approval, or text entry. `了解` may dismiss a displayed notification but never authorizes an effect.

### LLM/provider settings
- MultiLLM v1's admin/settings scope is the functional baseline: API-key-first provider addition, safe provider detection with explicit provider fallback only when detection fails, connection status/refresh, local discovery, automatic assignment/optimization and credential management. Foundation simplifies the model-facing details rather than expanding the settings surface indiscriminately.
- Provider cards are provider-level instruments; individual model names are normally hidden and Foundation chooses models internally. Local compute participates as an ordinary routing candidate rather than a separate privileged route.
- Provider cards are grouped by Provider x pricing tier. Multiple credentials in the same provider/tier collapse into one card with `N CREDENTIALS`; expansion shows per-credential quota/status and update/delete controls without revealing raw keys. Deleting the final credential removes the card.
- FREE identifies credentials intended to incur no API charge; PAID remains architectural future-proofing and is not spend-authorized by registration. FREE registration requires successful provider credential validation but does not require a provider to expose machine-readable quota. Missing quota remains unknown: never invent it, render it as 0%, or treat it as proof of remaining capacity.
- Quota presentation prioritizes short-term capacity (~80% visual weight) and reset, with long-term capacity (~20%) and reset secondary. Show provider health and real request/inference activity. DOWN/rate-limited/quota-empty/credential-error cards remain visible but subdued with a reason and recover automatically.
- API-key addition flow: ADD PROVIDER -> paste key -> safe provider detection/connection/capability/quota checks -> secure credential storage -> registration -> automatic routing optimization. If safe detection fails, ask for provider selection. Raw keys are never redisplayed.

### Routing
- Routing is automatic; there is no manual provider-order editor. User criteria are soft preferences; Secret/Privacy Guard constraints remain mandatory and cannot be overridden.
- Normal view is per-function coarse routing. Expansion shows current PRIMARY plus all STANDBY candidates, capability/tool execution path and verification path. Local/cloud candidates share the same ordered route. Actual provider/route segments light only from real execution activity.
- `OPTIMIZE` recomputes and saves the actual provider adoption order for every route from current rules. It does not visually sort provider cards and does not show before/after history. Adding/removing relevant provider capacity may trigger optimization.
- Route order is fixed between optimization events. Health Registry temporarily skips unavailable/exhausted candidates and can return to the fixed route after recovery; small quota movement alone does not continuously reorder routes.
- FREE capacity should generally be used close to exhaustion, while preserving a small task-completion safety margin rather than knowingly starting work that is likely to fail mid-request.

### Notifications and human authority
- Notification/approval severity uses the five-level human-facing scale: LV1 INFO, LV2 NOTICE, LV3 ATTENTION, LV4 ACTION, LV5 CRITICAL.
- Current runtime mapping keeps FAILED at LV3 ATTENTION, WAITING_HUMAN at LV4 ACTION, and UNCERTAIN at LV5 CRITICAL. LV1/LV2 remain valid lower-severity notification classes for informational/notice events; RUNNING itself is task activity and is not duplicated into the notification queue.
- LV4 has no automatic expiry when human authority/input is required and blocks only the dependent work. Unrelated work may continue. Bulk authorization is unsupported.
- Sort order is LV5 -> LV4 -> LV3 -> LV2 -> LV1, newest first within each level. Guard, not the UI, enforces blocking.
- Notification explanatory text remains concise Japanese and must state what happened, why attention/action is needed, and the available safe next action. Dismissal remains presentation-only and never changes Guard/work truth.
- Dismissing a notification removes it from the UI but does not erase Guard/effect/work/trace/evidence audit facts. AUTHORIZE means permission to continue the requested operation; DENY means that request is not permitted. Post-DENY replanning policy is an execution concern and is intentionally not frozen by the UI specification.

### Tasks and telemetry
- TASKS is a supervision/readback surface, not the normal work-entry point. Its primary unit is the upstream human-requested or automation-requested job, not internal workflow steps. Show current state, meaningful progress/result/evidence, and why work is blocked; internal steps may be expandable. Keep this surface lightweight.
- Human intervention belongs to the decision/input queue: authority decisions use AUTHORIZE/DENY; missing information uses a distinct COMMENT/RESPOND path that resumes only the waiting work. Do not overload approval with free-text input, and do not expose SUBMIT TASK as a normal Foundation operator action.
- System/device/backup/update information is compact telemetry, not a layout-driving screen. External information such as time/date may appear unobtrusively. Device state must mean Foundation-observed connectivity/heartbeat, not an unsupported claim about physical device power state.

### G1 implementation note — Provider Registry (2026-09-19)
- Added a persistent SQLite provider/credential metadata registry as the first non-visual Settings backend slice.
- Registry stores binding identifiers and operational metadata only; raw credential secrets are not stored there.
- Provider cards aggregate by Provider x pricing tier and collapse multiple credentials into one card.
- FREE registration fails closed on credential/provider validation failure. Missing short/long quota evidence is preserved as unknown and is not itself a credential-registration failure.
- Removing the last credential removes its provider/tier card.
- Activity and health are state fields intended to be driven by real execution/health events; the UI must not fabricate them.
- Current aggregation is deliberately conservative for multiple credentials (minimum reported remaining capacity) until provider-specific trustworthy quota semantics are implemented; do not describe this as integrated total quota yet.

### G1 implementation note — Secure provider onboarding (2026-09-19)
- macOS Keychain boundary now supports save/load/delete in addition to existence checks; real M1 save -> authoritative load -> delete -> absence readback passed with an isolated test service.
- Provider onboarding keeps raw API keys out of the Provider Registry. It stores the secret in the native credential store first, then writes only binding/operational metadata to the registry; registry failure rolls the secret back.
- Known key prefixes may provide a provider hint, but onboarding still requires a safe provider probe/validation result. Unknown keys fall back to explicit provider selection when the probe cannot identify them.
- FREE onboarding still fails closed when credential validation cannot establish a usable provider binding. Trustworthy short/long quota evidence is recorded when available; unavailable quota remains unknown rather than fabricated.
- This is a boundary implementation, not yet live-provider integration: real Gemini/Groq/etc quota adapters and the Settings HTTP/UI action are still pending.

### G1 implementation note — Provider quota evidence (2026-09-19)
- Provider quota semantics are now evidence-driven rather than assumed uniform across vendors.
- Groq has a concrete adapter for documented response headers: token remaining/limit/reset is treated as the short window, request remaining/limit/reset as the longer window. Missing required headers returns unknown rather than fabricated capacity.
- Mistral currently exposes only a short-window parser from documented `X-RateLimit-Remaining` style response metadata. A trustworthy FREE long-window remainder is not established by this adapter, so it does not satisfy FREE onboarding by itself.
- Gemini documentation states limits are project-level, model/tier dependent and visible in AI Studio; do not pretend an API-key-local remaining percentage exists without an authoritative machine-readable source.
- Provider-specific semantics must remain explicit. The UI's short/long presentation is a normalized view over trustworthy evidence, not a promise that every provider exposes identical quota windows.

### G1 implementation note — Runtime provider observation (2026-09-19)
- Added a response-observation boundary that updates Provider Registry state from actual provider responses rather than UI guesses.
- Real request activity can set a credential/card active while the request is in flight and clear it at completion.
- Supported quota evidence updates the last-known short/long values; a response without trustworthy quota headers does not erase or fabricate quota.
- HTTP 401/403 -> CREDENTIAL_ERROR, 429 -> RATE_LIMITED, and 5xx -> DOWN. These are operational observations, not permanent provider deletion.
- This boundary is ready to be called by the actual cloud execution adapter. It is not yet proof that every current cloud call flows through it; wiring that execution path is the next gate.

### G2 implementation note — Observed Cloud Execution boundary (2026-09-19)
- Added an explicit cloud execution boundary that resolves a native credential binding, sends the request through a transport, observes the authoritative HTTP response, updates Provider Registry health/quota/activity, and always clears in-flight activity.
- Raw secrets exist only at the secret-store -> transport handoff and are not written into Provider Registry metadata.
- HTTP failure responses are observed before the caller receives failure. Transport failures without an HTTP response mark the provider DOWN while preserving last trustworthy quota evidence.
- This closes the internal wiring seam, but the repository still has no production vendor HTTP transport/LiteLLM adapter. Therefore this is transport-level E2E with a controlled transport, not a live Groq/Gemini request claim.

### G2 implementation note — Production HTTP transport (2026-09-19)
- Added a dependency-light stdlib HTTPS transport for OpenAI-compatible cloud endpoints: Groq, Mistral and OpenRouter.
- Authorization is injected only into the outbound request; the transport result contains status/headers/body but not the credential.
- HTTP errors such as 429 are returned as CloudResponse so ProviderResponseObserver can classify and persist provider state before execution raises to its caller.
- Unsupported providers fail before network access. Gemini is intentionally not forced through the OpenAI-compatible transport; it needs its own adapter or an explicitly adopted generic router boundary.
- Endpoint/model selection remains above transport and is not frozen here.

### G1 implementation note — Settings service ownership (2026-09-19)
- Added SettingsService as the application boundary that owns the real `providers.sqlite` location under Foundation data_dir, native credential store, Provider Registry and onboarding transaction.
- A fresh installation no longer requires a pre-existing provider database; Settings creates the registry and the first successful ADD PROVIDER populates it.
- API keys are accepted only by the onboarding boundary and are not returned in the Settings result/card model.
- The browser POST action and real provider probe remain the next wiring step; do not ask the operator to discover or manually create the registry database.

### G1 implementation note — Browser ADD PROVIDER action (2026-09-19)
- The loopback Operator surface now has a real password-type ADD PROVIDER form wired to SettingsService through CSRF/origin-protected POST `/settings/provider/add`.
- API key input uses password/autocomplete-off semantics and is passed directly to onboarding; it is not inserted into rendered HTML or returned in the success payload.
- The route returns only provider/tier/credential-count/health metadata.
- Live use still requires constructing OperatorApplication with a real SettingsService and provider probe. That bootstrap/probe wiring is the next gate.

### G1/G2 implementation note — Real operator bootstrap (2026-09-19)
- Added a runnable loopback operator bootstrap that loads FoundationConfig, constructs the real Guard store/actions, SettingsService, native Keychain boundary and production HTTPS transport, then serves the Operator surface.
- LiveProviderProbe uses provider-specific credential validation and records trustworthy quota evidence when the provider exposes it. FREE ADD PROVIDER may register a validated credential with unknown quota; routing/presentation must not convert that unknown state into fabricated capacity.
- This exposes the remaining real gap precisely: provider-specific live validation/quota acquisition, not Operator/Settings/Keychain/Registry plumbing.

### G1/G2 pre-live audit (2026-09-19)
- A dedicated pre-live adversarial audit is recorded in `docs/G1_G2_PRELIVE_AUDIT.md`.
- Live credential testing is explicitly blocked until native secret saving no longer places the secret in process argv.
- Full regression at this gate: 277 passed, 10 skipped, 1 warning.

## Accepted dual visual baselines — C + I (2026-09-19)
The product now deliberately keeps two accepted presentation designs rather than converging on one skin. Variant C (the earlier, more Arknights: Endfield-like dense telemetry direction) and Variant I (the current dark-blue industrial-HMI/techwear direction) are both supported visual baselines. The earlier statement that C was reference-only and I alone was authoritative is superseded by this section.

This is also an architecture gate: C and I must consume the same presentation-neutral HumanView and the same surface/action contracts. Theme/design selection belongs strictly after the semantic surface boundary. Guard, execution, provider/routing, task, notification, reconciliation, persistence and authority semantics must not branch on C vs I. Adding, replacing or removing a visual design must not require domain/runtime changes.

Provide an explicit design switch so the Responsive Browser Surface and Echo can render either accepted design from the same semantic state. Persist only a presentation preference; never duplicate operational state per design. Tests must prove equivalent semantic information and permitted actions across C and I for each genuine surface. Browser viewport width is responsive geometry, not a separate authority surface.

## C/I layout invariant — 2026-09-19
C and I are **visual designs, not alternate layouts**. For a given surface (Desktop, Mobile, Echo), both designs must use the same semantic section order, grouping, placement model, information density decisions, responsive breakpoints, and available controls. The switch may change visual tokens such as color, typography, borders, textures, icon treatment, decorative annotation and component skin, but it must not rearrange the page or create design-specific information architecture.

If faithfully applying a C or I visual characteristic would require a different layout, section order, grouping, density, responsive behavior, or control placement, stop that implementation point and ask the user which shared layout should win. Do not silently fork layouts, create per-theme exceptions, or merge the two designs into a compromise layout.

## Human Decision Surface semantic correction — 2026-09-19
- Reloaded the canonical end-goal/roadmap/Phase G documents after a task-surface interpretation drift was identified.
- The Foundation Operator is a supervision/decision/configuration surface, not the normal work composer. Removed user-facing `SUBMIT TASK` and manual `RUN` controls/routes from the Operator. `TaskIntake` remains an internal integration/test boundary for work originating from connected products/automations.
- WAITING_HUMAN is no longer interpreted uniformly as approval. A Guard/run authority decision may expose AUTHORIZE/DENY; a work item waiting for missing information is classified separately as input-required. Until a durable structured-response/resume contract exists, the UI must not pretend that AUTHORIZE supplies that information.
- SETTINGS is explicitly the LLM/provider capacity administration surface. Provider addition is API-key-first; provider/tier selection is secondary fallback/advanced input. Credential detail now exposes real status refresh, credential replacement, and deletion without redisplaying raw secrets.
- AUTOMATIC ROUTING remains automatic and separate from provider administration. `OPTIMIZE` recomputes/saves adoption order; health/quota skips remain temporary and Privacy/Secret Guard remains mandatory.

## Durable human-input contract — 2026-09-19
- Missing-information input is now a distinct durable contract from Guard approval. A response is bound to exactly `job_id + step position`, persisted before resume, and cannot grant authority.
- Operator exposes RESPOND only when the durable HumanInputService is wired. Otherwise it fails closed. AUTHORIZE/DENY remains reserved for Guard/run authority decisions.
- Resume re-enters only the addressed waiting work. The stored response is supplied as additional work context; it does not mutate Canon, policy, approval, target, effect identity, or Guard authority fields.
- A response survives process restart before resume. It is consumed only after the resumed work leaves WAITING_HUMAN; if resume fails or still needs information, the durable response remains available for recovery rather than being silently lost.
