# Settings Surface Semantics

This file is the semantic contract for every operational term exposed by SETTINGS / LLM CAPACITY and AUTOMATIC ROUTING. A label must not be shown as actionable or authoritative unless the implementation below exists.

## Capacity / provider terms
- **LLM CAPACITY** — inventory and observed availability of cloud-provider credentials plus discovered local compute. It is not a model catalog and does not promise current execution eligibility by itself.
- **OBSERVED STATUS** — last persisted cloud probe/runtime observation for the credential/card. `ONLINE` means the latest observation succeeded; it is not a guarantee that the next request will succeed. Runtime health may temporarily skip it.
- **LAST OBSERVED** — local timestamp of the newest persisted observation represented by the provider card/credential.
- **STORED KEYS** — count of credential bindings represented by a Provider × Tier card. Raw secrets are stored in the native credential store and are never redisplayed.
- **FREE** — provider tier for credentials intended to incur no API charge. Registration requires successful provider credential validation, but machine-readable quota evidence may be unavailable. Missing quota evidence remains unknown and must never be fabricated as 0% or treated as proof of remaining capacity.
- **PAID** — billable-tier classification reserved for supported/future provider use. Selecting it does not itself authorize spending; budget/authority remains outside this presentation control.
- **SHORT WINDOW REMAINING / LONG WINDOW REMAINING** — provider-reported remaining quota percentages for two authoritative rate-limit windows. `UNAVAILABLE` means the system has no trustworthy value; it must not be rendered as 0%.
- **RESET AT** — provider-reported reset marker/string for that quota window. No reset time is invented when absent.
- **REASON** — persisted reason associated with non-healthy/observed provider state when supplied.
- **DISCOVERED STATUS** — current LocalCompute discovery result. It is not cloud probe state.
- **CAPABILITIES** — task-function classes the discovered local candidate declares it can accept.
- **ADD PROVIDER** — validates a supplied key against the selected/detected provider, records any trustworthy quota evidence that is actually available, saves the secret to the native credential store, registers runtime metadata, then recalculates routes. FREE registration does not require invented or unavailable quota values.
- **AUTO DETECT PROVIDER FROM KEY** — safe key-format detection where supported. Provider selection under ADVANCED/FALLBACK is only a fallback when detection is insufficient.
- **REFRESH STATUS** — performs a fresh provider probe using the stored secret, persists observed health/quota/reset evidence, then recalculates routes.
- **UPDATE CREDENTIAL** — validates the replacement secret before replacing the native stored secret; registry update is rolled back on failure where possible; routes are recalculated.
- **DELETE CREDENTIAL** — removes the native secret then registry binding and recalculates routes. A storage/registry split failure is reported as reconciliation-required rather than hidden.

## Routing terms
- **ROUTE CAPABILITY** — one unified routing view: CHAT / SEARCH / CODE / DATA / FILES / PC CONTROL. Functional program paths and native provider/model abilities are not separate route lists. If both deliver the same end-to-end function they share one route; genuinely different functions remain separate.
- **DATA** — the canonical bounded Data Specialist function (bounded input/compute/output with reproducible operation evidence). Generic JSON/structured-text generation does not by itself qualify a provider for DATA. A candidate joins DATA only when its execution path actually implements that bounded function.
- **PREFERRED CANDIDATE** — first persisted candidate in the current calculated adoption order. It is tried first only when still eligible; live health/quota/capability and hard Guard policy can prevent use.
- **FALLBACK CANDIDATES** — later candidates in the same calculated order. This is not a user-managed manual list.
- **Historical / retired: FREE PRIORITY (0–100)** — this control previously biased FREE cloud candidates. It is no longer an active setting.
- **Historical / retired: LOCAL PRIORITY (0–100)** — this control previously biased local candidates. It is no longer an active setting.
- **QUALITY / LATENCY** — not currently exposed as editable ranking controls because no authoritative comparable provider signal is wired. Stored legacy/default fields are not presented as effective policy.
- **PRIVACY / SECRET** — hard Guard policy, not a preference slider. It can exclude cloud execution regardless of routing preferences.
- **RECALCULATE ROUTES** — recomputes and persists candidate order from current eligible candidates and implemented preferences. It does not claim global/model-quality optimization.
- **NOW ROUTING / NOW EXECUTING** — ephemeral read-only observation emitted only across an actual selected inference execution. It disappears when execution ends and grants no authority.

## 2026-09-20 replacement contract

## Cost policy — canonical replacement for legacy routing preference
- The former FREE/LOCAL 0–100 routing-preference controls are retired. They conflated provider tier, local execution and spending policy and did not express the intended cost control.
- User-facing cost control has exactly two independent dimensions:
  1. **Paid-API budget** — a hard ceiling once an authoritative monetary unit and provider cost-accounting path are defined. The existing Guard budget mechanism uses integer `paid_cost` units; those units are not currently established as JPY or another currency for LLM inference. Until that conversion is explicit, PAID LLM execution remains disabled.
  2. **FREE ↔ PAID routing preference** — intended as a soft routing preference only after PAID LLM accounting is trustworthy and spend-authorized. It must never imply that PAID is inherently more capable, and it can never override health, model capability, privacy/secret policy, authority, or the hard budget.
- FREE cloud and Local are both zero-paid-cost candidates for this policy. The future FREE ↔ PAID preference does not mean "suppress free quota" or "prefer Local". Among equally eligible zero-cost candidates, routing continues to use trustworthy availability/quota evidence and deterministic ordering rather than exposing extra preference knobs.
- A PAID provider is not spend-authorized merely because its credential is registered. Runtime selection must have a trustworthy request-cost/accounting path before paid execution can participate. Unknown cost fails closed for paid execution; no guessed price is permitted.
- Existing Guard `paid_cost` / budget reservation is the hard-authority mechanism for effectful work. The LLM routing cost policy must integrate with that accounting concept rather than creating a second contradictory budget authority. Currency/unit conversion must be explicit before a paid provider is enabled.
- Migration rule: replace the legacy preference function end-to-end (schema/service/UI/runtime/tests/docs). Do not keep FREE/LOCAL sliders as compatibility UI and do not silently reinterpret their old numeric values as the new cost/capability slider.

## Unified route namespace
Routing is presented and persisted as one capability view. Program functionality and native model/provider ability are not separate route lists. Overlapping functionality is unified into one route; distinct functionality remains distinct. A candidate joins a route only when its current execution adapter can actually deliver that capability end to end.
## Executable route projection
The Routing UI uses the stable capability inventory below and must distinguish executable from unavailable routes. A specialist/interface contract or provider-native tool does not by itself make a route executable. CHAT is the verified ordinary-chat production route. SEARCH / CODE / DATA / FILES have host-owned execution adapters and explicit signed LibreChat aliases for diagnostic/verification use. `foundation-auto` is the normal Pydantic AI Agent/tool loop: the trusted host may pre-compose already-reviewed bounded grants onto its CHAT request, and the Agent decides which exposed tool is needed. Prompt/model/tool text cannot mint or widen those grants. PC CONTROL remains NOT AVAILABLE. Route detail is one ordered fallback chain; FREE/LOCAL labels are omitted as noise, while PAID remains explicit because it changes cost authority.
## Stable route inventory and provider completeness
The visible route inventory is stable: CHAT / SEARCH / CODE / DATA ANALYSIS / FILES / PC CONTROL. DATA ANALYSIS is the human label for the persisted DATA capability and means bounded calculation/data-processing work, not generic structured text. A route remains visible as NOT AVAILABLE when its end-to-end execution path is not yet wired; UI items are not added/removed merely because current capacity changes.

There is no three-candidate routing limit. Every currently eligible candidate is persisted in ordered fallback state. Runnable FREE cloud capacity is ordered ahead of local compute; Local remains a fallback rather than displacing a usable cloud provider solely because it was discovered earlier. Provider registration and execution eligibility remain distinct: a valid key/card does not enter a route until Foundation has a real execution adapter/model for it.


## Daily agent semantics (2026-09-22)
foundation-auto is not a semantic capability classifier. It is the normal Pydantic AI agent/tool loop. SEARCH/CODE/DATA/FILES settings remain execution/routing/authority concepts and explicit diagnostic aliases. The host decides which tools are exposed; Pydantic AI decides whether an exposed tool is needed.

## Runtime route memory (2026-09-22)
- Displayed PRIMARY/STANDBY order is policy state and stays fixed until explicit route optimization/configuration changes it.
- Runtime selection uses locally recorded outcome/latency plus current capability, health and fresh quota evidence; it must not start from the first displayed provider on every request.
- Runtime observations are updated deterministically on the Foundation host, never by a cloud LLM.
- DOWN/RATE_LIMITED/CREDENTIAL_ERROR/RETIRED are temporary/ineligible execution states and may receive warning/orange UI treatment without reordering the route.
- Near-empty quota evidence expires after its reset evidence becomes stale; stale low quota cannot suppress a recovered provider indefinitely.

## Daily ambient authority clarification — 2026-09-26

The earlier historical statement that ambient AUTO promotion is SEARCH-only
describes the implementation state before a general daily ambient-host-authority
policy was adopted. It is not the target semantic contract.

`foundation-auto` remains semantically CHAT and remains the normal Pydantic AI
Agent/tool loop. The host may pre-compose multiple already-reviewed bounded
grants for a daily request; the Agent then decides which exposed tool, if any,
is needed.

This does not make explicit SEARCH/CODE/DATA/FILES aliases normal user modes,
does not permit prompt-derived scope, and does not grant raw credentials,
protected-resource mutation, unreviewed external effects, or unavailable
capabilities such as unpromoted PC_CONTROL.
