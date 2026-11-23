# Knowledge Lifecycle Manager (KLM) — source-owned input semantics and ongoing reconciliation

Status: **READ-ONLY DRIVE CAPTURE / SEMANTIC EXTRACTION DEPLOYED; REMAINING LIFECYCLE NOT ACCEPTED**. Updated 2026-11-08 JST.
Repository: `quest7070-dev/AI-Foundation` is the canonical source for implementation/specification. This document is not authority to ingest private histories, grant write permissions, migrate files, deploy, or change Native/Guard behavior.

## Decision and scope

Add a *Foundation-coordinated, input-side* knowledge lifecycle service, with normal Agent output unchanged. Its remit is: (1) source capture; (2) evidence-grounded multi-atom semantic decomposition; (3) source ownership and placement planning; (4) duplicate/contradiction/revision mapping; (5) authorized per-owner writes/readback; and (6) change-driven and periodic audits, reclassification and corrective proposals.

Do **not** create a competing universal fact/personal profile database, a pre-Agent semantic router, a separate general grant framework or a second unreviewed LLM. The normal Pydantic AI agent reasons and selects already-granted tools. KLM creates asynchronous, bounded intake/reconciliation jobs via existing Durable Work; agents never mint scope or effect authority. Reuse Guard/Cedar/CapabilityRequest/ExecutionPort/verification/owner evidence. Do not put this synchronous service on the everyday response hot path.

## Ownership contracts

| Domain | Original/canonical owner | KLM role |
|---|---|---|
| Human judgments, experiences, accepted/rejected options, reasons, exceptions and changing preferences | HumanModel original evidence ledger + approved views | source-bound proposal / relation / audited derived reference, never silent promotion |
| Life/project plans, ToDo, document references, inventories | Their specific Drive docs/sheets or another established owner | normalize row/section identities, propose verified per-owner updates |
| AI-Foundation code, specs, tests, PR/Issue/CI evidence | GitHub repository and specific commits/PRs | read GitHub state, provide proposed changes through bounded development/PR workflow |
| M1 runtime truth, execution progress, approvals, actual deployment | Runtime owner and existing Foundation/Guard stores | observe; NEVER equate green CI/merged PR with deployed or live acceptance |
| Chat conversation history and attachments | Source application, e.g. LibreChat Mongo for original chat | read only with explicit source-owner approval; not automatic personal evidence |
| External publications/opportunity discovery | Authoritative origin and domain-specific collection | derive cited facts or candidates, not personal preference |

Different copies serve roles: `canonical`, `operational_projection`, `reference`, `derived_index`, `audit`. Canonical ownership is per-domain / per-record (possibly per-field), not a global "GitHub always wins" ranking. KLM stores **links/proposals/receipts**, not new independent source truth.

No bulk import of old conversations/audio/private Raw; no inference-to-personality promotion; no reinterpretation of a user decision as approval for an external effect. Distinguish verified input actor from untrusted document text/model output.

## Semantic unit contract v0 (proposed)

```json
{
  "schema_version":1,
  "atom_id":"source-bound-stable-id",
  "source_ref":{"system":"gdrive|github|humanmodel|chat|other","resource_id":"...","revision":"...","span":{"type":"text|row|cell|event","start":0,"end":10},"content_sha256":"...","actor_claim":"source-authenticated-or-unknown","observed_at":null,"captured_at":"..."},
  "meaning":{"entity_id":"...","subject":"...","predicate":"...","object":"...","kind":"observation|decision|instruction|outcome|inference|question|quote","modality":"assertion|intention|conditional|hypothetical|unknown","polarity":"positive|negative","condition":null,"valid_from":null,"valid_until":null},
  "relations":[{"type":"supports|contradicts|supersedes|refines|depends_on|same_as_candidate|derived_from|preserves_goal|changes_priority","target_atom_id":"...","status":"proposed|verified"}],
  "assessment":{"source_verified":true,"semantic_status":"proposed|reviewed|unresolved","missing_fields":[]},
  "privacy":{"owner":"host-bound","scope":"host-bound","ceiling":"private|restricted|shareable"},
  "placements":[{"system":"...","resource_id":"...","role":"canonical|projection|reference|index|audit","write_status":"proposed|applied|verified|blocked"}]
}
```

Unknown time, speaker, modality or evidence must remain unknown. Source spans and hashes are host-derived and independently compared; never accept LLM-generated exact quote, actor ID, authority, source revision or proof. Verified `same_as` and `supersedes` require additional evidence beyond approximate similarity. A source revision must identify a *specific row/section/event*, not an entire changing sheet.

Store `sources`, `semantic_atoms`, `relations`, `placements`, `source_checkpoints`, `write_operations`, `audit_findings`, `policy_versions` as *minimal link/proposal/receipt state* in a confined KLM SQLite store. Do not duplicate HumanModel's person evidence or Foundation durable work into competing authority. Explicit retention/lifecycle and private-content limits apply.

## Processing

1. **Capture**: authenticate source-side owner, fetch bounded source revision, calculate id/hash and exact range, record ingestion lease/checkpoint.
2. **Decompose**: use existing local Agent/Cognee-derived extraction as *untrusted semantic proposals*; preserve conditions, negation, qualifiers, quoted speakers, original phrasing, time.
3. **Resolve**: exact id/hash dedup first; bounded scope-aware search for neighboring atoms; mark new, duplicate, refinement, condition change, historical supersession, conflict, or unresolved. Preserve dissent rather than force one world model.
4. **Plan**: policy registry maps semantic domain and record role to source owner(s). Verify existing revision, allowed write boundaries, propagation direction and review requirement. One atom may require multiple destinations with different roles.
5. **Apply**: only existing owner-authorized Guard-mediated writes. Commit each destination independently with persistent intent + effect idempotency key, expected revision and readback. No assumed distributed transaction across Drive and GitHub.
6. **Verify**: independently reload the affected record, compare identity/revision/content and mark `VERIFIED`, `UNCERTAIN`, `RECONCILE_REQUIRED` or `BLOCKED`. Never blindly retry unknown write outcomes.
7. **Maintain**: invalidated dependencies/meaning interpretations become candidates for bounded review. Source data remains intact; repair links and projections before any physical move/deletion.

The existing `HumanModelContext` is read-only. HumanModel new-original publication must go through its own owner-approved process; KLM does not create writer authority by adding a method to the reader.

## Continuous reconciliation

- Event-driven per source: changed GitHub commits/PR/CI, Drive revision/row changes, HumanModel evidence additions/view revisions, runtime observations.
- Daily: deterministic delta checks (ids, versions, hashes, orphan links, incomplete writes), no model if nothing changed.
- Weekly: review semantic conflicts, classification candidates, active personal decisions and active projects.
- Monthly: bounded complete source-inventory traversal and migration candidates, with explicit pagination completeness receipts; do not assume partial listing is comprehensive.
- After schema/policy/model upgrades or explicit user corrections: impact-graph invalidation and comparison of new hypothesis vs previous hypothesis; no silent retroactive rewrite of historical decisions.

Audit classes: `MISSING_SOURCE`, `STALE_PROJECTION`, `OWNER_CONFLICT`, `SEMANTIC_CONTRADICTION`, `TIME_SCOPE_CONFLICT`, `WRONG_PLACEMENT`, `REVISION_MISMATCH`, `PRIVACY_SCOPE_MISMATCH`, `PARTIAL_WRITE`, `UNKNOWN_COVERAGE`.
Repairs R0 index/link rebuild; R1 derived classification correction; R2 owner-authorized projection refresh; R3 interpretation hypothesis only; R4 person decision approval from explicit source; R5 source ownership change, physical move or deletion requiring separately reviewed authority. Never delete human originals as generic cleanup.

## Performance / runtime

No whole-corpus inference on each chat turn. Delta/hash first; candidate retrieval second; LLM meaning check only on ambiguous/changed subsets. Batch or bounded queues under the existing job/lease system; preserve local-only privacy and no paid fallback. Daily chat returns normally while ingestion and audits run separately; user-facing changes that depend on a write wait for verified effects. Abort on partial inventory and conflicting source revision.

## OSS assessment (decision as of 2026-11-07)

- **Reuse Cognee already integrated**: source-linked graph extraction/retrieval is available in an existing isolated worker; keep its graph **derived**, not personal Canon. No new deployment required for design phase. Do not assume unreleased Cognee roadmap features are already present.
- **Graphiti** (getzep/graphiti, Apache-2.0): technically relevant bitemporal graph and invalidation semantics, but introducing Neo4j/FalkorDB + overlapping graph authority and potentially new model dependencies before benchmark is premature. **Candidate for isolated read-only comparison only**, never automatic installation or production switch.
- **OpenMetadata** (open-metadata/OpenMetadata): metadata catalog and lineage are relevant but large data-platform overhead for the current small personal multi-owner use; **defer**.
- **RapidFuzz** (MIT): optional CPU-only candidate for near-duplicate blocking. It does not prove semantic equivalence and is unnecessary before measurable missing recall. **No dependency added**.

OSS acceptance gate: baseline Cognee v1.6.5 + existing local models on same evidence set vs candidate, with accuracy on conditional/negative/temporal contradiction, provenance correctness, runtime/memory, no paid calls, no graph ownership duplication. Record the winner based on measurements, not attractiveness of architecture.

## Rollout / acceptance

P0: register source owners, existing Drive inventory and authority directions; **read-only** exact source map.
P1: semantic atom contract and 20+ hand-labeled adversarial example tests (quotation, negation, conditional, temporality, inference vs decision, duplicates, unknown date). Original hash/span and actor must not be forgeable.
P2: non-effectful multi-target placement plans with objective diff receipts; review HumanModel PR #273/#274 revisions and production compatibility before source-wide pagination.
P3: isolated per-owner writes via Guard + independently verified readback; partial update and concurrency recovery.
P4: daily/weekly/monthly reconciliation and bounded reparations with audit ledger.
P5: real M1 / Drive / GitHub / authorized HumanModel source acceptance, source-completeness checks, manual gate for consequential personal decisions.

Pass criteria: zero unauthorized effects; zero automatic inferred-personality approvals; original trace for all accepted atoms; zero duplicate effects on replay; no mixed-source-revision accepted pages; detected mismatches never rewritten as certainty; no ordinary-chat input latency dependence. Semantic accuracy thresholds must be measured using real labeled samples and accepted before automation promotion.

## Dependencies / non-goals

Respect the independent HumanModel integrity work in Draft PR #273 and child #274, **SOURCE_ACCEPTED_NOT_DEPLOYED**. Do not merge or deploy them implicitly. Keep Native Issue #35, 9B/Harness, current model slots, operator service and private source imports unchanged. This document is for a dedicated review/implementation sequence, not license to rewrite running jobs.

Drive folder structure and bounded existing-file move plan: `docs/DRIVE_INFORMATION_ARCHITECTURE_20261107.md`.

## Automation execution wiring — reviewed proposal (2026-11-07)

**Drive capture and bounded 9B extraction are deployed.** Issue #355 records KLM-only release `71a74d9bb065585a368167c34139263e7e59cc7c` applied to the existing 900-second LaunchAgent. Fresh read-only Issue #359 reports CURRENT / COMPLETE, 33 folders, 113 objects, 3 validated no-effect receipts / VERIFIED steps, 13 LaunchAgent runs, last exit 0, and NO_INPUT. The private report was 20 seconds old. These observations do not attest the current service source HEAD, atom count, FAILED details, semantic correctness, independent end-to-end completion or every historical unattended cycle. Other owner writes and the lifecycle extensions below are not production-accepted.

### Trigger, runner, queue (no competing scheduler)

- A bounded **intake hook** receives owner-approved new-source events from the existing chat/attachment owner. Publish only authenticated source pointer, revision, origin type and purpose. Receiving a message does not imply consent to import private conversation history or promote a human decision.
- A **GitHub event adapter** accepts trusted Issue/PR/push/CI event metadata and fetches current API state independently before treating the event as fact. Reuse existing GitHub Actions/event integrations for dispatch where they are independently authorized; do not repurpose development workflow task contracts as KLM write authority.
- A **Drive incremental watcher** polls Drive Changes with a persistent per-owner page token on the M1 host using separately approved credentials and bounded scopes; suggested *starting interval* 15 minutes, subject to actual API quota. Detect file updates from metadata, then enumerate changed document sections and sheet row IDs without bulk private content caching. Full listing/pagination evidence is needed before declaring scan complete.
- HumanModel receives **approved source/view revision invalidation notifications** from its owner. KLM may not call the read-only context adapter as a write interface; privacy/owner binding is host-controlled.
- An existing **M1 launchd-managed invocation** may tick reconciliation/inbox processing; the invoker holds no model authority and must not spawn a second orchestrator. A durable idempotent job record is enqueued to existing Foundation Durable Work; no unbounded new daemon/task database. Prefer existing Hatchet orchestration for genuinely approved long-running Foundation workflows *after* adding a bounded KLM-specific handler: the current generic Hatchet worker allow-list does not support KLM and must not be bypassed.
- Use lease/claim and retry classification of Durable Work. Duplicate event key = `source-owner|resource-id|revision|event-kind|scope`; downstream effect idempotency additionally includes target owner/resource/expected revision and plan revision. No arbitrary source text or authority in queue payload.

### Work stages and run states

```
SOURCE_EVENT -> SOURCE_VERIFIED -> SOURCE_SNAPSHOT_PINNED
 -> NO_CHANGE (terminal) | SEMANTIC_PROPOSALS -> RELATIONS_RESOLVED
 -> PLACEMENTS_PLANNED -> READ_ONLY_REVIEWED
 -> (GUARD_APPROVED -> PER_OWNER_EFFECT -> INDEPENDENT_READBACK)*
 -> VERIFIED / NEEDS_HUMAN / BLOCKED / UNCERTAIN_RECONCILE_REQUIRED
```

The source revisions and job checkpoints must persist across host restarts. Crashes between remote effect and local receipt require readback/reconciliation before any retry. An entry in a Drive planning ledger is not evidence that Foundation deployed a service or installed its credentials.

### Minimum recurring jobs, after activation

| Trigger | Suggested initial cadence | KLM behavior | Effect policy |
|---|---|---|---|
| trusted source intake | immediate enqueue, not synchronous chat | snapshot, decompose changed bounded spans, dedup, link, plan | read-only initially |
| GitHub authorized change event | on change | compare exact PR/Issue/CI/main/run identities | projections only after Guard |
| Drive change cursor | every 15 minutes | verify token/cursor, gather changed IDs then row/section delta | metadata/read-only initially |
| daily sweep | daily | missed delta, expired source view, broken link, partial/uncertain effect audit | no destructive repair |
| weekly semantic sweep | weekly | bounded contradiction, time-scope, classification drift on changed/high-priority atoms | interpretation proposals only |
| monthly inventory | monthly | paginated source inventory, orphan references and wrong-placement proposals | no bulk move/deletion |
| owner correction / policy upgrade | event-driven | invalidate dependent derived conclusions and reevaluate affected graph | approval for changing person judgments |

No assumption of real-time delivery where connector/event access is absent. Record `DISCONNECTED`, `STALE`, `PARTIAL_COVERAGE` or `BACKLOGGED` rather than silently claiming completeness. Default to UTC durable timestamps and explicit local timezone in presentation.

### Resource budgets and backpressure

Bound queue depth, per-source fetches, tokens/semantic atoms and time per tick; deterministic first, Cognee retrieval second, LLM only if needed. Use installed local inference model selected through existing route; do not depend on absent 9B weights, paid fallback or new model installation. Coalesce changes to the same resource while retaining every raw event revision receipt. If inference is unavailable, leave an indexed pending job and continue deterministic audits, never manufacture a semantic result. Keep normal chat output non-blocking; confirmed user-facing writes may wait for verified effect. Support operator pause, re-enable, status visibility, unreadable/denied source reporting and no-change quiet operation.

### Activation sequence and evidence

1. **DRY_RUN_READ_ONLY**: one synthetic source and live metadata-only source; assert no external writes and exact source/owner/position readback.
2. **BOUNDED_AUTO_INTAKE**: one user-approved real source/scope; verify conditional/negative/quoted utterance extraction, source revision change and idempotent resume.
3. **AUDIT_SCHEDULED**: activate Drive/GitHub/HumanModel checks only after obtaining each host's native approved credentials and durable cursor; demonstrate unattended tick, restart and no-change checks on real M1.
4. **CONTROLLED_PROJECTIONS**: Guard-reviewed idempotent write to non-personal derived Drive tracking record, independent readback, simulate partial network failure and reconcile.
5. **LIMITED_REPAIR**: allow R0/R1 and specific R2 projection updates within scoped owner grants; require explicit owner decision for R4, approval for ownership migrations/deletion (R5). Record rollback plan, delta evidence and true runtime deployment version.

No automatic 24h production operation is claimed until an unattended M1 cycle and persistent source receipts are independently verified. Existing work/CI and private-personal-model PRs are separate and must remain undisturbed.


## Remaining lifecycle implementation and acceptance — 2026-11-08 JST

This section is the current acceptance record; earlier design descriptions are goals, not evidence of operation.

| Stage | Implemented on the KLM development branch | Acceptance / remaining gap |
|---|---|---|
| P1 | Failure phase + exception type + source hash receipts; explicit one-ID retry with fresh revision/hash/bytes validation and append-only failure history; repeated identical failures require review | The 3 historical FAILED items have NOT been inspected or retried. The status bridge does not expose their identities/hashes/errors. Real 9B semantic accuracy and source-span readback remain unaccepted. |
| P2 | SQLite derived semantic fingerprints, indexed neighbour retrieval, same-information/support/contradiction/qualifier/revision/reinterpretation candidates, explicit dependency invalidation; boundary checks; append-only UNRESOLVED review history | Exact matching only, not complete natural-language equivalence. Legacy hash-only atoms need source-authenticated rehydration. No automatic equivalence, contradiction, replacement or owner decision confirmation. |
| P3 | Model domain proposal -> host-validated owner mapping -> durable placement candidate. Existing exact placement plans retained. Isolated shareable runtime projection update uses existing FILES scope, exact-plan Guard approval, target revision check, Guard effect, independent readback, Durable Work and observe-only reconciliation | Runtime projection writer is an explicit host callable, not enabled by the periodic service. Drive/GitHub/HumanModel effect bindings remain UNBOUND. No personal/shared original writes, moves or deletion. Empty/missing update targets are unsupported. This is not completed multi-owner production wiring. |
| P4 | Existing 15-minute host tick calls deterministic daily/ISO-week/calendar-month audit Work; no new timer. Monthly paginated Drive rescan reuses native cycle checkpoints. Audits expose legacy feature gaps, orphan links, unresolved reviews and failed intake | Audit Work VERIFIED means local checks completed, not that all findings were repaired or remote targets inspected. Remote source/placement liveness and semantic weekly drift review remain unbound. Interrupted RUNNING claims require reconciliation, never automatic reset. |
| P5 | Synthetic regression covers approved runtime update/readback, replay suppression, ambiguous effect recovery, revision conflict, privacy boundary, incremental candidates, dependency changes, retry history and monthly rescan | A mocked inference is not real 9B. New code is not deployed. Live Drive -> 9B -> relationships -> placement -> audit and live approved projection update remain unaccepted until independent M1 evidence exists. |

No graph database, scheduler, daemon, provider/router, grant system or configuration key was added. Meaning fingerprints and review candidates live in the existing SQLite journal; explicit dependencies retain original evidence. Candidate-window overflow fails explicitly rather than certifying partial recall. Model output domain is untrusted and never authorizes an effect. The model's original source position/hashes remain host-derived. Historical originals, successful Work, receipts and old interpretations are retained.

**Stopping conditions:** Only the fixed read-only M1 bridge operations are currently exposed through GitHub. Its klm-status receipt cannot provide historical failures or invoke the new code. The existing release path is pinned to one old/new SHA and cannot deploy a new branch by changing Issue text. Desktop Commander returned MONTHLY USAGE EXHAUSTED; do not retry or reconnect. Kandev is prohibited. No new release/approval route or Native/Guard/Operator change is introduced to bypass these limits.

**Shortest next execution:** Complete existing M1 PR CI against the new immutable head; restore an authorized direct M1 execution route or separately review a concrete KLM-only release plan with rollback. Read exact current service SHA, FAILED identities/revisions/source hashes and journal counts without source text. Retry only one selected source-bound failure, verify source bytes/spans/atom IDs independently, inspect semantic labels separately from JSON syntax, then accept the new lifecycle chain. Enable an isolated nonsecret runtime projection through an existing owner-granted FILES/Guard binding, approve its exact run identity, update and independently read back VERIFIED. Keep all other owner writers UNBOUND until their target, existing authority and recovery plan are concrete.

**Explicit Decision:** Existing read-only Drive synchronization and prior three source-bound no-effect Work receipts are observed. New lifecycle code may be accepted as implemented/tested only after its checks pass. Historical failed-item recovery, semantic accuracy, new release deployment, continuous lifecycle operation, other-owner effects and KLM-wide completion are NOT ACCEPTED.


## Legacy source rehydration — 2026-11-08 (implementation, not deployment)

Independent M1 bridge Issue #385 observed **12 source-bound legacy atoms without new indexed
semantic features** from the 3 preserved VERIFIED KLM Work steps. Relation and placement
candidate counts were both zero; this is not evidence that the new relation/placement
engine failed, but evidence that it has not processed those historical sources.

The bounded `LegacyRehydrateQueue` selects at most one previously VERIFIED Inbox
source with exactly one old source SHA and missing indexed features. It creates a
**separate** `klm-legacy-review:<intake_id>` Durable Work step, without touching its
original VERIFIED receipt or old atoms. The approved Inbox row is authenticated
and reread by the existing GET-only adapter, and its current revision, SHA and
raw bytes must match the old source before the shared existing 9B handler can
propose new, independently indexed meaning and relation candidates.

This queue is only consulted if the already installed 900-second host tick
returns CURRENT and the primary PLANNED intake worker returned NO_INPUT.
Development priority, shared HostComputeLease, occupancy checks and bounded
deadline are identical. Never process legacy work if an active intake is waiting;
never retry an uncertain RUNNING or failed/cancelled legacy review automatically.
The old source/interpretation is immutable; different new semantic atoms are
**proposals**, not silent corrections of historical truth. No new scheduler,
model route, credential, personal record import or owner-write effect is added.

Independent acceptance still requires a future **explicit SHA-pinned KLM-only
release** and a real M1 due cycle that returns a validated
`klm-legacy-source-review` receipt with source integrity, and follow-up
semantic accuracy review. Source merge/CI alone do not count as acceptance.


## GUI-owner retry intent handoff — source bound (2026-11-08)

Independent Issue #385 found three historical FAILED inputs, three old VERIFIED
inputs, twelve legacy hash-only atoms without feature vectors, and zero relation
or placement reviews. Issue #388's run reached SOURCE_READ_BEGIN and was then
cancelled by the exact three-minute GitHub Action limit, before any original
Work status change. The root within the owner's Keychain-vs-Google request is
not yet isolated.

The reviewed recovery Action must only stage one fixed `klm-source-verified-retry`
Durable Work intent; it does not fetch Google source or attempt 9B under a
non-GUI Runner. The already-authorized GUI KLM service reads the source and
retries **one original FAILED step** on its next 900-second tick, preserving
failure history, source identity and replay suppression. Prior WAITING_HUMAN,
FAILED or uncertain RUNNING intent is not silently reset; provenance and
owner effects remain unchanged. Public receipts contain only aggregates.
Live source-verified retry acceptance requires a future SHA-pinned KLM-only
release and independent Work readback.


## Host-local semantic review completion (source contract, 2026-11-17)

`klm_relation_review.py` supplies the missing explicit decision path for indexed
relation candidates. It is a host-only callable, not a new MCP tool, scheduler,
source reader or grant mechanism. An authenticated host binds the actual owner,
one exact scope, the current Canon, the existing Guard and a trusted source
adapter. The adapter `read_current(atom_id) -> SemanticAtom` must independently
reread the original source revision/bytes and reconstruct the indexed meaning;
caller JSON or an LLM assertion cannot implement this boundary.

1. Select the existing exact `review_key` and explicitly decide `REJECT`
   (`relation_kind=""`) or `ACCEPT` with one existing relation kind. Direction
   is the candidate's saved `before_id -> after_id`; do not infer direction from
   the sorted review-key digest. No bulk or automatic semantic decision exists.
2. Call `request_relation_review(journal, guard=guard, read_current=reader,
   review_key=key, decision=decision, relation_kind=kind,
   authenticated_owner=owner, scope=scope, canon=canon, run_id=fresh_run)`.
   It verifies both current source atoms and stages only the existing durable
   Guard pending request. `relation_review_intent(...)` previews its exact opaque
   owner/scope/source/decision binding without creating any authorization.
3. The existing Operator pending-request UI uses its unchanged exact
   `OperatorActions.approve_pending(run_id, request_ref)`. A run-only historical
   grant, changed owner/scope/decision/Canon, cancellation or unbound store fails.
4. Call `resolve_relation_review` with the same arguments. It independently
   checks exact durable approval, current source/meaning pins, candidate identity
   and cancellation again before the atomic local commit and separate readback.

Original UNRESOLVED candidate rows remain immutable. A bounded immutable
`klm_relation_dispositions` receipt in the same Work DB records each decision;
only accepted decisions insert/promote an exact local relation to
`owner_verified`. This is a reviewed derived relationship, never source truth,
external write permission or execution authority. `RelationProposal` remains
untrusted/proposed-only. An exact repeat is read-only; changed decisions conflict
and require a separately designed supersession process, not an overwrite.
Unresolved counts and reason buckets exclude completed dispositions consistently;
older schemas without the additive table retain their original counts. Known
later source revisions remain candidates for the existing revision audit.

This source contract does not claim live review of the 92 candidates, deployment,
or supply an authenticated source adapter where none is installed. Missing source
access/owner decisions remain blockers; never construct synthetic approvals to
make those counts disappear.


### Native source proof for relation review (source contract, 2026-11-17)

The host can bind `NativeKlmReviewReader(journal, authenticated_owner=owner,
scope="drive-inbox", inbox=NativeInboxReader(OwnerInboxHTTP(existing_token)))`
as `read_current` in the existing request/resolve functions. For the already
approved public-research root, pass the existing owner-bound
`KlmLlmperksReader` with `scope="drive-public-research"` instead. Reuse the
same native token/config as `klm_drive_host_tick`; this does not discover
credentials, request OAuth scopes, register a tool or read anything at import.

The reader maps each atom to exactly one saved `klm_drive_intake` pointer with
the same owner, source, record, revision and privacy. It then uses the original
bounded native adapter to refetch metadata and current bytes. Current revision,
canonical byte SHA, exact span SHA and unchanged indexed proposal fingerprints
must all match. Missing/ambiguous legacy provenance, unsupported source kinds,
unavailable historical revisions or changed source fail with fixed categories.
No caller URL or supplied cached raw bytes can substitute for this refetch.

Only a fresh immutable proof from the exact owner/scope-bound reader instance
can satisfy this branch of the review verifier. Generic callbacks must still
return the original SemanticAtom contract and cannot pass serialized/native
proofs. Inbox grid limits and the research app-root/content digest checks remain
owned by their existing adapters. Each request and each resolve performs new
native reads; no proof cache, model call or source-text persistence is added.

This verifies source freshness and the identity of the saved semantic proposal.
Legacy meanings are hashes and cannot be reconstructed or independently
re-extracted without another reviewed process. A successful native proof does
not assert semantic accuracy, owner approval or completion of the 92 live
reviews. Actual source access and the existing exact Guard decision are still
required on the host.

## Installed owner relation review (2026-11-17)

The existing Operator `/klm/review` lists unresolved candidates in bounded pages. Native preview reads the exact saved before/after source spans; it verifies provenance, not semantic accuracy. The owner explicitly chooses ACCEPT with a relation kind or REJECT and confirms that the sources were reviewed. The CSRF-protected save action requests the exact existing Guard approval, approves only that explicit owner decision, then resolves after a fresh native source read. Failed approval, changed source, or missing historical provenance leaves the candidate unresolved. GET and preview never approve or write a disposition.

The host binds review authority to a fingerprint of the installed review contract files, rechecked on each operation. This is an installed-runtime Canon pin, not a claim that GitHub main was freshly observed; routine review has no GitHub dependency. Source changes require an Operator restart. Existing private Work/Guard stores remain authoritative. On older Work schemas, only an approved resolve with StorageAdmission may ask the existing receipt journal to add its disposition table. No new database or source-text archive is introduced. Deployment alone does not decide the remaining real candidates or establish HumanModel accuracy.

