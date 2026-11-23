# HumanModel lifecycle management — source-backed contract and acceptance (2026-11-10)

**State:** code-audited design, staged no-effect implementation only. This document does not authorize importing private data, minting a person judgment, installing a model, widening a Guard grant, resetting a consent state or deploying to M1.

## 1. Definition

**Primary purpose:** HumanModel is the **owner's data corpus used to reconstruct how the owner would answer questions from other agents**. The existing Foundation-authorized reasoning model reads appropriate records and produces a provisional owner-perspective response. HumanModel is not an independent personality agent, a fixed classification, a pretrained copy of the owner, an execution authority or a data-management project for its own sake. Its success criterion is the usefulness and fidelity of those question→simulated-answer interactions, not the number of stored records or green retrieval tests.

The corpus retains what the owner actually said, decided or rejected, including source identity, conditions, historical changes, contradictory evidence and uncertainty. The answering agent must separate an actual owner statement from **its own simulation**; even convincing simulated first-person speech never counts as a new owner instruction, agreement, Guard authorization or consent. If evidence is absent, stale, contradictory or insufficient, it must say what cannot be reconstructed instead of inventing a stable personality.

All source/consent, audit, revision, and privacy infrastructure below is **supporting machinery for this answering purpose**, not a competing top-level objective. Existing authenticated owner data and the existing Agent/LLM are reused; no second model, profile database or special permanent persona is needed. A question may originate from a trusted orchestration agent, but only host-admitted scopes are readable and the question text cannot become a new grant. The newly implemented `AutoCapabilityAgent.answer_owner_question(question, scope=...)` is an opt-in, read-only CHAT entry point: it scans current Guard-approved source pages, selects at most 12 question-relevant original records / 24 KiB for the existing host-selected model, reports omitted coverage, returns a `SIMULATED_PROVISIONAL` answer and checks the current source revision before delivery. A complete scan is not a claim that the selected evidence is semantically exhaustive; unavailable, changed, unapproved or out-of-bounds reads are denied. This is source code, **not proof of an installed live E2E path**.

Its *management plane* covers the entire chain: governed source registration → complete bounded intake → provenance and actor authentication → source and privacy validation → deterministic record matching → evidence candidates and (where needed) semantic proposals → authenticated publication → View invalidation and reconstruction → read-only retrieval → current decision review → audit/correction/erasure/recovery. Retrieval is only one consumer.

Distinct owners:
- Source of conversation, audio, email, Drive docs: each original application remains authoritative.
- HumanModel original **evidence ledger** and purpose-scoped View definitions: existing `experiments/human_model/human_model_ledger.py` on validated external USB volume.
- HumanModel event / proposal verification and mutation: an authenticated **HumanModel-owner-side** writer, not `HumanModelContext.read()`, not KLM's derived journal and not an LLM.
- Foundation Guard/Canon, cost, capability, LV1–LV5, execution approval, irreversible effects: existing Foundation authority. History of user preferences is **not** equivalent to Guard consent.
- KLM: source checks, source-bound relation/placement proposals, retries and audit; never an unauthenticated HumanModel writer.
- Cognee, proposed FTS5/RapidFuzz, DeepSeek Harness, 9B and other LLMs: optional derived retrieval/extraction. None can grant publication or execution authority.

## Owner-reconstruction acceptance (the product outcome)

An authenticated host agent asks a natural-language question, chooses an already
authorized purpose/scope, and receives a provisional answer **from the owner's
point of view** with relevant evidence references. The observed user-facing
value is whether the response reproduces the owner's specific decision criteria,
exceptions, changing mind and unknowns, rather than how many events were
collected or what a data audit counted. A successful source read alone is not
an accepted simulated answer.

Use an owner-reviewed, private held-out set of question/actual-owner-answer
pairs to evaluate fidelity and failure to overstate certainty; avoid using the
same source rows as both test target and answer evidence. Report exact-answer
agreement, reason/exception preservation, appropriate abstention and false
claims of owner approval separately. Test synthetic contradictions, revoked
evidence and stale views without importing private source into CI. Do not call
a simulated answer a verified owner utterance or enable an execution effect from
it. The current source test exercises wiring and denials, **not** real owner
fidelity or a deployed agent-to-agent endpoint.

## 2. Actual repository inventory (implemented code is not proof of live operations)

| Area | Existing source | Source audit / gap |
|---|---|---|
| Source identity, owner and revision | `src/ai_foundation/knowledge_lifecycle.py`; `klm_drive_work.py` | KLM source pointers/receipts are implemented. Not universal HumanModel data intake. |
| Evidence ledger | `experiments/human_model/human_model_ledger.py` | `evidence`, `change_log`, `model_views`, `model_sources`; SQLite version/hash/scope/privacy and append-like correction. Ledger has no authenticated actor/consent event schema. |
| Mount isolation | `storage_location.py`, `scripts/human_model_ssd_provision.py` | Strict external-volume placement. No internal fallback. |
| Explicit source publication | `development_sources.py`, `project_reference_sources.py`, `m1_human_model_publish_development.py` | Fixed project sources and selected owner instructions, **not** generic chat/Drive/feedback ingestion or continuous collection. |
| Decision events | `decision_events.py`, `DECISION_EVENTS.md` | Three Concept OS transitions recorded as Ledger events. `actor='user'` is **a claimed string**, not authenticated owner identity; no general-purpose trusted decision writer. |
| Hypothesis/contestation | `hypothesis_engine.py`, `temporal_comparison.py`, `proposal_evaluation.py` | Evidence-bound provisional comparisons; no general owner adjudication, retirement or downstream dependency cascade. |
| Current view | `Ledger.rebuild_view`, `foundation_readonly.py` | Global stale invalidation on add; current non-superseded rows are projected. Important: disputed `evidence` and `kind='inference'` are **not excluded** by the current projection. **View inclusion is not user agreement or a factual truth claim.** |
| Host-bound read/search | `src/ai_foundation/human_model_context.py`, `human_model_runtime.py`, `auto_agent.py`, `cognee_bridge.py` | Authenticated owner/bound scope/Guard, 32 records / 32KiB per page, optional Cognee; prior live project-source read exists. No arbitrary personal evidence write API. |
| Exception review | `human_model_primary_review.py`, `host_question_review.py`, `primary_review_events.py` | Exact delegation + current view + Guard revalidation; no new approval. Full trusted host producer and real live cycle still separately gated. |
| Ongoing quality and recovery | `m1_human_model_activation_readiness.py`, `human_model_ledger_verify.py`, KLM audits | Read-only SQLite checks and status exist. No continuous end-to-end owner consent, correction/erasure propagation, restoration rehearsal, coverage and SLAs. |
| Source material scope | `docs/MEMORY_HUMANMODEL_BOUNDARY_20261102.md`, `CONCEPT_OS_INTEGRATION.md`, `KNOWLEDGE_LIFECYCLE_MANAGEMENT.md` | No blanket import of private raw; no personality promotion; maintain explicit source owners. |

## 3. Supporting data-management constraints and gaps (subordinate to answering questions)

Codes: **EXISTS** = implementation exists in source, not guaranteed deployed. **PARTIAL** = partial or only specific experimental sources. **GAP** = no accepted end-to-end path.

| ID | Management responsibility | Present | Required contract / gap |
|---|---|---|---|
| HM01 | Trusted source registry / owner | PARTIAL | Explicit connector, permitted corpus, owner/scope/privacy, source ID/revision, completeness evidence; source application owns originals |
| HM02 | Incremental intake / replay / checkpoints | PARTIAL | Authenticated changes + rescan, no lost pagination; no auto bulk-import of private chats |
| HM03 | Actor provenance / impersonation defense | GAP | Authenticated principal outside the text; distinguish owner, other person, assistant, tool, quoted actor and unknown |
| HM04 | Original text span / citation / event time | PARTIAL | Exact source-span hashes/offset, message ID when available, observed vs captured vs effective times; never invented IDs/dates |
| HM05 | Owner consent to collect / purpose / expiry | GAP | Trusted acquisition grant bound to source and scope; separate from permission to export or act |
| HM06 | Ingest integrity / duplicate identity / same-revision conflict | EXISTS | Existing `Ledger.add` exact URI+revision+digest, fail-closed conflict; richer cross-source comparisons are proposals |
| HM07 | Meaning eligibility / non-HumanModel classification | PARTIAL | Keep transient job memory, external research, assistant suggestions and private secrets out of owner-judgment authority |
| HM08 | Exact correction/supersession | EXISTS | Append new evidence with `supersedes`, stale Views; extend authenticated withdrawal/rectification |
| HM09 | Valid-time/conditional applicability | GAP | Valid-from/to and conditions are evidence claims, not silently overwritten present-tense preferences |
| HM10 | Dispute / contradiction / unresolved authority | PARTIAL | Preserve both claims, evidence IDs, producer, uncertainty; no forced model convergence |
| HM11 | Explicit owner's decisions / delegations | PARTIAL | Trusted identity + exact target/revision/action; DecisionEvent actor string alone never proves consent |
| HM12 | Hypothesis lineage and multi-producer dissent | PARTIAL | Separate proposals from accepted evidence and keep unsupported/contradictory outcomes |
| HM13 | Publication to purpose-bound View | EXISTS | Only authenticated owner-side writer may publish; projection freshness and scope/privacy bounds do not imply owner approval per record |
| HM14 | View invalidation and dependent derived indexes | PARTIAL | On input, consent, correction, privacy or owner changes invalidate all affected View/index/cache and provenance-derived links |
| HM15 | Completeness / source drift / stale checkpoint | GAP | Check source owner independent revision, cursor and omission; mark partial rather than claim current/global coverage |
| HM16 | Bounded exact/non-LLM search | PARTIAL | Existing read, proposed FTS5 with short-keyword fallback; RapidFuzz proposal-only; optional Cognee not default |
| HM17 | Sharing restrictions and secret/PII policy | PARTIAL | Guard + original privacy grants; optional scanners provide findings, not permission to send |
| HM18 | Primary-review/Canon/Guard revalidation | EXISTS | Exact decision prior evidence, current generation and distinct permission; live authenticated producer acceptance remains |
| HM19 | User correction / contest / review interface | GAP | Existing LV1–LV5 and Operator/MCP for owner approvals, no duplicate approval DB or new levels |
| HM20 | Notification / audit / tracing | PARTIAL | Content-free receipts for accepted/rejected/revoked publication, stale, review, broken dependencies; no log of raw private source |
| HM21 | Backup, integrity, disaster recovery | PARTIAL | Restore generations and actual independent readback including revoked state, no silent fallback disk |
| HM22 | Erasure, revocation, retention and propagation | GAP | Authenticated delete/forget request path, derived index purge, source-owner delete obligations and verifiable receipts; cannot assume immutable ledger is exempt |
| HM23 | Source export / scope mobility / owner separation | GAP | Portable evidence manifest without default export of raw private data, new owner grants required |
| HM24 | Maintenance schedule / stalled states / resources | PARTIAL | Reuse existing KLM clock/Work; deterministic owner checks run without 9B, semantic work waits under existing lease |
| HM25 | Quality and regression / false convergence | PARTIAL | Synthetic Japanese negation, amount/date change, third-party quote, actor spoof, conflicting views, stale source, deletion, crash/restart, owner-separated reads; distinct CI vs M1 live |
| HM26 | Privacy/risk event response | GAP | Block disclosed or uncertain View, record fixed reason codes, notify within existing levels and route to owner-corrective operation |

**No unsubstantiated feature completion**: Source code shows a function; production-ready claims require the host, current owner, real source, exact release and independent readback.

## 4. Management states — do NOT overload current Ledger status or grant authority

Use a versioned *management observation and intent* contract first; convert into schema only after backward compatibility review.

Input/record lifecycle:
- `DISCOVERED` → `SOURCE_VERIFIED` (independent source read, authenticated actor/provenance and exact revision) → `ELIGIBLE` (purpose/consent/privacy satisfied) → `STAGED` (no-effect candidate).
- `STAGED` → `PUBLISHED_EVIDENCE` only by the existing owner-authorized writer; exact direct user utterances may be published as source evidence **without pretending semantic interpretation is verified**.
- `STAGED` → `SEMANTIC_PROPOSAL` only where meaning really needs interpretation; proposals remain explicitly provisional. `SEMANTIC_PROPOSAL` → `OWNER_CONFIRMED` **only on authenticated owner decision** for personal claim/consent, not a model's confidence.
- A `PUBLISHED_EVIDENCE` may acquire states `DISPUTED`, `SUPERSEDED`, `WITHDRAWN`, `ERASURE_PENDING`, `ERASURE_VERIFIED`, but the exact source owner is responsible for permitted raw erasure. Existing `supersedes` chain remains authoritative until a reviewed migration adds dedicated event facts.
- Current View lifecycle: `DEFINED` → `STALE` → `RECONSTRUCTED` → `INDEPENDENTLY_VERIFIED` → `SERVABLE`; any source, owner, consent, privacy, revision or erasure change forces `STALE`. `SERVABLE` means valid retrieval, **not** that every row was user-endorsed.
- Any unknown/foreign principal, ambiguous actor, revoked consent, missing source range, conflicting revision, incomplete pagination or unresolved effects: `UNAVAILABLE` / `WAITING_HUMAN` / `RECONCILE_REQUIRED` with a fixed reason, never force 'approved' and never run a cloud inference to decide authority.

Do not persist these proposed state strings as a new authority source until the owner writer path, schema migration, rollback and readback are accepted. Use existing Guard and source-owner state.

## 5. Required minimal data contract

Source evidence (trusted host metadata where available):
```text
source: system, native resource ID, record/message ID, source revision, exact span/digest
origin: authenticated owner/principal binding (if verified), actor_claim, actor_proof_state
time: observed_at, captured_at, effective_from/to (if source-backed), timestamp_quality
use: purpose, scope, privacy ceiling, collection grant, source completeness
evidence: existing evidence_id, kind, disputed, supersedes
interpretation: proposal producer/revision, support & contradiction IDs, no truth authority
publication: owner-side signed/verified intent, expected source & view revision, no-effect receipt
```
Unknown fields remain UNKNOWN; never infer an authenticated speaker from `source_uri`, `actor='user'`, prose, an LLM response or an unsigned chat export.

Avoid duplicating originals in GitHub/KLM: only source refs, hashes, revisions, status codes and nonidentifying counters outside authorized HumanModel storage. Do not share raw private data to debug CI.

## 6. Delegation and 9B queue policy

**Model-free by default**: source hash/revision and actor-proof checks, consent/permission lookups, exact duplicate/supersession, current-view invalidation, privacy filters, FTS5 retrieval, drift/checkpoint verification, deterministic relation audits, backup integrity and readback; no 9B lease needed.

**Not decided by a lexical OSS alone**: new conditional preferences, sarcasm, negation, two statements whose meanings differ despite similarity, cultural or contextual interpretation. Route as a *provisional* meaning task to an accepted local model or allowed free/sanitized route. No implicit cloud fallback for private raw.

**Owner exception**: only an unresolved authority/personal decision whose prior explicit evidence and Guard permissions cannot be matched reaches existing LV4; ordinary code fixes remain autonomous; no new confirmation popups or extra LV categories.

## 7. Dependency order, build scope and acceptance

**P0 — No-model integrity audit, no mutation**
- Add an owner-side, read-only verifier over the **existing** Ledger/View that reports only integer counts and fixed reason codes. Check projection of disputed/inference rows, superseded evidence, revision/privacy/scope and content hashes, stale Views. No raw output, DB migration, owner elevation or new daemon.
- Acceptance: synthetic fixtures and no-op repeat result, corrupt hash, wrong scope, inferred View row, correction, stale/rebuild, partial coverage and no content in receipts; live host observation separately.
- Rationale: identify unsafe management states before making a writer or assuming model accuracy.

**P1 — Authenticated intake and source/actor/consent verification**
- Reuse KLM's existing source pointer + authenticated source client / cursor. Add a narrow typed event contract and owner-side ingestion intent using the current HumanModel store, **not** a second personality DB. Prove user vs assistant quote vs external source. Only fixed explicit owner source intake initially; expand connectors after independent coverage receipt.
- Acceptance: actor-forgery test, same-revision conflict, source deletion/change during process, replay and crash resume; zero private text in runtime events.

**P2 — Owner-controlled update / withdraw / conflict / expiry**
- Extend the same Ledger-owner write path with version-bound approval and corrections. Validate no privacy downgrade, no fabricated time range, no automatic promotion of `kind='inference'`. Track dependencies for revoked, superseded or disputed evidence. Model_VIEW selection must never imply approval.
- Acceptance: independent source reread before/after, stale View and derived cache invalidation, corrections do not destroy audit, unauthorized writers rejected, deletion propagation tested without claiming erased originals when source owner has not erased.

**P3 — Read side search and right evidence**
- Implement proposed in-memory FTS5 + bounded ID/short-query fallback against only current approved complete Views. RapidFuzz optional and proposal-only. Preserve actual record identity, privacy and owner/current-revision checks.
- Acceptance: exact ID, two-character Japanese, negative wording/amount/date difference, source changes during search, partial page recognized as partial; baseline Cognee remains optional.

**P4 — Lifecycle service composition without new daemon**
- Extend existing KLM 15-minute tick/Work for deterministic audits, delta checks, expired intents and orphaned projections. Never acquire local9B lease for deterministic work. New semantic proposals enter only the already accepted deferred inference queue. Existing Guard/Operator notifies owner only for actionable exceptions.
- Acceptance: multiple unattended M1 ticks, simulation of shutdown/restart and stale underlying source, prove no 9B call or extra model residency, changes appear in existing Operator audit.

**P5 — Restore, erasure and whole-system acceptance**
- Restore from versioned encrypted owner-authorized backup with independent source identity readback, demonstrate delete/revoke propagation to approved Views and derived caches and prevent stale snapshot resurrection.
- Acceptance: exact owner/principal and revision, default-deny after revocation, bounded storage/retention, zero silent paid route, zero leaked private source, no merge/deploy without separately reviewed release.

P0 may be delivered source-only as a Draft; P1–P5 are **not** claims of implementation or live acceptance.

## 8. Non-goals / out-of-scope

No 4B reintroduction; no second HumanModel canonical store, graph database, standalone lifecycle scheduler or new permission hierarchy; no automatic profile convergence, "personality scoring", clinical inference, default private chat import, automatic owner decision from personal history, forced local model stop or cloud secret/Raw transmission. Reuse existing DeepSeek Harness for permitted *semantic proposals only*, not to control management authority.

Related: `docs/DETERMINISTIC_PRIVACY_HUMANMODEL_ADOPTION_PLAN_20261110.md` (Draft PR #566), `docs/KNOWLEDGE_LIFECYCLE_MANAGEMENT.md` (KLM), `docs/HUMAN_ESCALATION_POLICY_2026-10-06.md` (Human-by-exception), Issue #402 (approval), Issue #562 (9B resource contention).


## 9. Implementation stage update — 2026-11-10 (Draft #607, source-only)

**P0 (implemented, not deployed):** human_model_management_audit.py checks the existing SQLite Ledger/View using a bounded read transaction and emits aggregate counters + fixed statuses. It now additionally identifies malformed host admission proof links and withdrawn evidence that somehow re-enters a current view. A clean structural receipt is intentionally named STRUCTURE_OK_SOURCE_UNVERIFIED: it neither independently authenticates the source nor proves owner consent.

**P1 (staging contract implemented, not host-connected):** human_model_source_admission.py defines exact HostCollectionGrant and TrustedSourceSnapshot DTOs, requires the trusted host's current authenticated owner, current consent verifier and reader, checks exact source identity/revision/content SHA, refuses assistant/quoted/foreign/unknown actors, and rereads the current source and consent. The first implementation admits only PRIVATE, kind=observation, from authenticated direct owner utterances; no personal decision or general-purpose effect approval is minted. This is a **library**, not a new authenticated source connector. The host must not take a model-generated DTO as proof.

**P2a (source-only owner writer implemented, not production accepted):** human_model_owner_publication.py explicitly initializes an optional human_source_admissions table **inside the existing HumanModel external SQLite database**; routine construction of Ledger never initializes it. The owner-side publish function requires an existing prepared schema, current host verifier/reader and exact source snapshot; the evidence, proof and change_log are inserted in one transaction with View stale invalidation. A replay with the same source+revision+proof is idempotent; a legacy unattested matching row cannot be silently retroactively claimed. Proof metadata is host-asserted, not cryptographic source attestation. The function has no HTTP surface and is not bound to the daily Operator, KLM, Drive, chat input or model tool call. Real owner auth/consent service and migration acceptance **remain blockers**.

**P2b (withdrawal serving exclusion implemented, not physical erasure):** the owner-side withdrawal function requires a fresh trusted owner action verifier and exact bound evidence ID. It marks the admission WITHDRAWN, invalidates Views and appends a change_log entry atomically. The existing Ledger.rebuild_view skips withdrawn admission rows whenever the optional admission table exists; legacy ledgers without the table keep previous behavior. Identical-revision publish replay cannot reactivate a withdrawn source. This is a **source-service denial** and does not prove raw deletion from the original chat application, backups, cached old context, or external graph workspaces; physical erasure and revoke-event subscription remain P5.

**Verification:** P0 CI for the earlier Draft head completed successfully. Newer P1/P2 commits require their own full CI completion, M1 owner-adapter binding and separate real database migration approval before deployment. All added tests use disposable SQLite with entirely synthetic source text and fake trusted-host callbacks; they cannot certify live authentication. The owner ID/consent digests in local SQLite are stable evidence pointers, not proof of a cryptographic signature.

**Remaining sequence:** P1 native host adapter + per-source owner consent and completeness acceptance → P2 versioned correction and dependable withdrawal event ingestion + independent old-index purge → P3 complete per-owner FTS5 search → P4 KLM deterministic audit wiring → P5 backup/restore/revocation/erasure independent M1 E2E. Keep Draft until these are individually accepted. No 4B model, DSH/Codex model run, paid provider, raw-data GitHub upload, new daemon, Native signal or main merge has been introduced by these code changes.


> **Current-source correction (2026-11-12):** Earlier P0–P5 Draft/verification language below is historical staging evidence, not a declaration that current main lacks these source files. Owner-answer source code from PRs #746, #750, #752 and #755 has since been merged. This does **not** establish actual owner MCP credentials, the approved M1 host Agent factory, live private-source fidelity, collection consent, or production E2E. Those remain separately gated and unverified.

## 10. Explicit correction acceptance extension

P2 additionally implements an exact correction hook in the existing owner-side publisher: the caller supplies the **prior attested evidence ID**, a newly authenticated direct owner source, and a **separate current host verifier** for the exact correction action. Text resemblance or LLM output never chooses the old evidence. The writer verifies prior same-scope/private/active evidence belongs to the current authenticated owner, accepts one successor, stores the new source's proof and supersedes pointer in one SQLite transaction, and invalidates all Views. Replays are idempotent; a second competing successor and corrections to withdrawn or foreign-scope evidence are refused. Existing original evidence remains for audit and the next View rebuild excludes the superseded predecessor.

This does **not** establish that the corrected utterance is a final accepted personal preference; the inserted kind is still observation. A real host/owner correction event source (source-app UI, authenticated direct owner action, or approved exact decision event) is not connected, and cannot be inferred from the candidate text. General decision updates, retention/expiry rules, superseding an unattested legacy row, and revocation propagation into old Cognee workspaces remain unaccepted. M1 source-owner independent readback and migration/rollback authorization remain required.


## 11. Guard-backed consent / changed-source reconciliation / no-model retrieval (2026-11-10)

**Existing Guard approval reused, NOT a new approval authority:** src/ai_foundation/human_model_collection_guard.py calculates an opaque target from the exact owner, bound external root, View, original source record ID/URI/revision/digest, collection purpose, privacy, consent ID and consent revision. The existing durable Guard store's is_approved_for(run_id, action='human_model_collect', target, Canon revision, effect_id) must match, and current Guard preflight must not deny or wait. Source content and private resource identifiers are not copied to the Guard approval target. Old run-only approvals cannot pass, nor can a model-created claimed consent. Synthetic tests exercise the **real existing OperatorActions.approve_pending** and SQLiteGuardStore, and prove the host-only publisher refuses without that exact consent. This remains an optional host-produced API; no actual owner acceptance or live account data has been used. Existing deployment must still supply server-authenticated identity, source-owned current data and an explicit user collection request. A successful Guard check here is a local collection permit only, NOT cloud disclosure or general personal claim.

**Changed-source fail closed:** human_model_owner_publication.py now implements owner-bound reconcile_attested_source_revision: independently reread the source through a trusted host port; if identity, actor, revision, completeness or content digest does not match (including source unavailable), atomically mark the evidence-admission proof STALE, invalidate all Views and append a source_stale receipt. Legacy originals stay unchanged; Ledger.rebuild_view excludes all non-ACTIVE host-admitted rows (STALE and WITHDRAWN). Replay of a stale/withdrawn same revision is forbidden; a separately accepted corrected/new revision must be used. The structural auditor counts source_stale and rejects accidental reentry into a current View. This helper is **not** yet connected to source-app change notifications or the live KLM 15-minute tick; independent M1 source reconciliation and durable dispatch remain P4 acceptance.

**No-model search path:** HumanModelContext.search() now uses bounded, exact-ID and literal substring retrieval over an already authenticated/Guard-approved **complete, current** 32-record/32-KiB snapshot, with a second independent current read. A literal match bypasses the optional model-backed Cognee backend even when it is installed; on no literal match Cognee remains an optional semantic search backend as before, and without Cognee a literal NO_MATCH is returned. A partial View cannot be classified as NO_MATCH. Inference/disputed results remain marked non-factual review candidates, never implied user approval. Tests cover 2-character Japanese, negation/changed-date differences, revision race, partial visibility, source ID and configured-Cognee bypass. No FTS index is built at current bound: a synthetic 32-row container benchmark (Linux x86-64, NOT M1) measured median approx 0.011 ms for literal scan vs 1.342 ms for building and querying a fresh FTS5 trigram index. FTS5 is deferred pending **accepted complete multi-page retrieval** and evidence of material speedup, avoiding new persistent personal index and extra M1 work.

**Critical unmet revocation coupling:** cancelling a Guard collection consent after a source was published does not itself guarantee instant invalidation of previously published evidence. The owner must explicitly withdraw the admission, or the source-owner change check must mark it STALE; an event-driven bridge to Guard cancellation and all old derived/cached contexts is required before any production write/collection activation. A clean P0 structural audit does not prove consent currently remains valid. Do not deploy the writer or infer actual owner authorization based only on synthetic Guard tests. This gap is P2/P4 and the private-data fail-closed release gate.


## 12. Proven Guard cancellation -> bounded local revocation helper

The existing owner-side publisher now exposes reconcile_cancelled_collection_consent() for an **already cancelled**, exact Guard collection run. It must be passed the server-authenticated owner and a read-only current canonical Guard cancellation verifier; no model/source text can assert cancellation. Matching HumanModel admissions are found using the existing stored consent-run SHA-256 and owner-binding digest, marked WITHDRAWN atomically, all Views invalidated and revocation audit events appended. Replay is idempotent, foreign owner cannot bulk revoke other owners, and the original private evidence is not claimed to be physically erased. Synthetic integration tests use SQLiteGuardStore + existing OperatorActions' exact user-approved consent action followed by actual Guard cancellation.

This is **not** connected to every production Operator cancellation yet. Before enabling the owner writer or automatic collection, production must connect authenticated cancellation observation to this helper, ensure stale cached results are not served between cancellation and invalidation, and independently verify derived-graph/cache purge. Real account auth and initial collection permission are also not accepted. The per-record consent proof here is intentionally narrow pilot scope. The production user experience should eventually use a bounded, explicit source/purpose grant that can cover **future separately authenticated owner utterances**, while preserving individual provenance checks and bulk revocation; do not demand redundant per-message prompts, but also do not infer opt-in from chat content.


## 2026-11-12 — Agent-to-HumanModel answer route (follow-up implementation)

The primary outcome remains **an agent asking what the owner would answer**.
The existing `AutoCapabilityAgent.answer_owner_question` now selects relevant
original records across all reachable pages of an approved source View rather
than truncating a complete owner's data to the first 32/128 records. It uses
Guard-checked read-only source paging, a small deterministic exact-keyword /
Japanese-bigram candidate pass, and at most 12 current records / 24 KiB for
the *existing host-selected model*. Missing lexical relevance in a large
corpus, missing/omitted data, an invalid page cursor, a changed revision,
or the current 4096-offset ceiling cause an explicit unavailable response.
A complete **scan** does not establish that the selected evidence is
semantically exhaustive or that the simulation matches the actual owner.

The existing authenticated `AuthenticatedMcpHost` and opt-in
`MCPStdio` accept `human_model_answer(question, scope)` **only when** a
trusted host supplies the same-owner/same-binding `AutoCapabilityAgent`
factory, registers the exact HumanModel tool scope, and independently
authorizes that session for this personal read. The default public
`foundation_status` MCP process still **does not expose** this tool.
The response carries a labeled provisional answer, evidence IDs, current
revision and no execution/consent authority; the underlying original records
remain host-local. Private owner data cannot be sent through an unconfined
model. This adds no listener, new source collector, new AI provider, permanent
personality copy or duplicate Guard.

**Implementation checkpoint, not live acceptance:** synthetic integration
tests cover the real approved external-ledger read adapter, host Guard checks,
local-model route, MCP scope denial and original-data minimization. The
production owner Host has **not** been configured here with a trusted
answer-agent factory or a newly authorized session; this source change does
not silently activate an external agent's access to private data. Real M1
owner binding and owner-reviewed answer-fidelity measurement remain distinct
deployment/quality gates.

### Owner-adjudicated answer-fidelity evaluator (source only; 2026-11-15)

`ai_foundation.human_model_fidelity.evaluate_owner_answer_fidelity` accepts only
fixed, bounded **owner-reviewed labels**; an independently authenticated
owner-side review authority must pass exact trusted review digests separately.
An LLM's answer, a JSON declaration of `reviewed_by=owner`, or the source
corpus alone never authenticates a reference answer. No question, actual owner
answer, generated text, evidence ID, private path, review reference or digest
appears in the returned aggregate. The evaluator distinguishes exact/partial/
wrong agreement, preserved reasons and exceptions, uncertainty, justified or
unjustified abstention, unsupported owner assertions, valid citations and
fabricated owner approvals. Unreviewed dimensions remain explicitly unrated.

It never calls a model, edits the owner ledger, enables an execution effect or
sets `representative_fidelity_verified=true`: that requires actual independent
owner-labeled held-out examples and acceptance of representativeness. Until
the owner-side evidence capture/review interface is connected, this is a
**source-ready evaluation primitive**, not live fidelity evidence. The
existing owner-only local 9B cited provisional technical E2E remains separate.
