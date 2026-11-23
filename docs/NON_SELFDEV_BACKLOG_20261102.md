# Non-self-development audit and implementation queue — 2026-11-02 JST

## Scope and authority

Owner request: comprehensively investigate and advance Foundation outside the
ongoing self-development mechanism, in importance order; minimize Desktop
Commander use and use GitHub for M1 validation/application.

Baseline: `main` at `301cd4ec0a96b9a95990a6f6110a24574680234b`.
Evidence sources: repository tree, all 137 canonical Python source modules,
`END_GOAL.md`, `BOUNDARIES.md`, `SOURCE_RELATIONSHIP.md`, `ROADMAP.md`,
`PROGRAM_COMPLETION_2026-09-27.md`, the full-system verification matrix,
convergence handoff, runtime/operations and storage inventories, open Issues
and all 14 open PR file lists observed at audit time. Source inventory and
focused inspection are not a claim of repository-wide runtime acceptance or
a deep security audit.

The September reconstruction completion remains valid. Earlier roadmap prose
about missing licenses, nonexistent schema v2 or already-closed Hatchet/DR
gates is superseded by its later closure records. Do not reopen those gates
as new work. Concept OS owns its opportunity/review semantics; HumanModel
experiments are separately developed clients, not Foundation's semantic core.

Concurrent work excluded: Native/Guard one-shot execution (#8/#109/#35),
Muse research (#55), HumanModel (#80/#81/#86/#95/#96), Job identity/API
(#18/#23) and Kandev governance (#6/#7). None of the changed attachment/push
modules are changed by those open PRs (including historical #5 and UI #1).

## Active feature queue

Prioritize previously unavailable useful behavior over maintenance, load testing,
soak testing, benchmark expansion or further hardening of already accepted paths.
The completed attachment/notification repairs below are historical delivered
work, not the order for future feature development.

| Priority | Feature | Concrete next action |
|---|---|---|
| 1 | PDF / Office input | Complete the existing LibreChat standard parser -> owner-scoped Foundation input connection; inspect the dedicated real-M1 probe, then address only a failure in that actual feature path. |
| 2 | Usable history / memory context | Keep lightweight task/conversation continuity in LLM/client/Foundation; retrieve judgments and personalization from HumanModel approved views. Follow MEMORY_HUMANMODEL_BOUNDARY_20261102.md; connect the existing read-only adapter with authenticated owner/privacy/revision instead of creating a competing personality store. |
| 3 | Useful generated artifacts | Establish one real export/download path using the existing ArtifactPort and standard producer, with a concrete host-owned destination and a format validator. No ambient arbitrary write authority. |
| 4 | Cross-chat continuation / supervision | Integrate the existing Job/API work when its owner PRs converge; do not build another Job store or interfere with the Native self-development stream. |

Existing regression checks still run where required. A failure in an unrelated
load test is a small maintenance item, not a reason to expand this workstream
into load/soak/performance infrastructure. The HTTP overload test correction
already made is bounded and stops there; no additional load campaign is planned.

## Historical audit order and disposition

Order considers actual data/correctness impact, daily-use reach, dependencies,
independent acceptance cost and collision with existing work. A future feature
is not more urgent merely because its implementation is absent.

| Order | Area | Current evidence / disposition | Next bounded action and acceptance |
|---|---|---|---|
| 1 | Attachment concurrency and snapshot integrity | **REPRODUCED DEFECT; FIXED IN THIS BRANCH.** A second acquire overwrote the first lease; one release allowed cleanup while another reader was active. Re-resolving changed upstream text also replaced the active snapshot. | Independent per-reader markers, process/thread-local release ownership, content-addressed snapshots, kernel-serialized publication/maintenance. Test separate objects, threads, independent process, stale markers, cleanup, ENOSPC and old-format leases. M1 CI required before runtime promotion. |
| 2 | Durable notification deduplication | **REPRODUCED DEFECT; FIXED IN THIS BRANCH.** Lexical truncation evicted a newly delivered low-sort key, so the next poll resent it. Duplicate projection rows also sent the same notice twice. | Retain delivery order with the same 2,048-key bound; serialize read/send/persist across processes; unique private atomic temp files; preserve legacy JSON lists and retry-after-failure. Test reverse lexical order, restart, duplicate projection and kernel ownership during send. |
| 3 | Partial multi-device notification delivery | **VERIFIED SOURCE GAP; FIXED IN FOLLOW-UP SLICE.** Previously `WebPushTransport.deliver` reported one success while another subscription failed, and `PushDispatch` marked the whole notice seen. The follow-up persists per-target opaque acknowledgements and globally settles only once current subscriptions are delivered or confirmed expired. Device-visible P07/P09 remain unverified. | Per-subscription acknowledgement is implemented behind the existing transport with opaque subscription/key fingerprints and bounded retention. A-success/B-failure/restart tests retry only B; 404/410 retires only an unchanged subscription. Physical receipt remains separate. No credentials or endpoint strings in public evidence. |
| 4 | Non-image document input | **EXPLICIT FUTURE CAPABILITY**, not a regression of accepted image/VISION. Current FILES attachment path reads UTF-8 with replacement; it is not PDF/Office parsing. | First follow `LIBRECHAT_V088_STANDARD_FIRST_MIGRATION.md`: evaluate existing owner-scoped LibreChat/RAG extracted text (`LibreChatAttachmentLookup` already consumes `doc.text`) before adding a parser. Coordinate the attachment-consumption seam with #8; only a demonstrated residual gap justifies an OSS-backed bounded read-only DocumentPort. Require owner-bound provenance, bytes/pages/output/time limits, unsupported/encrypted/malformed errors, no network and no automatic model download. Do not implement a homegrown PDF/Office parser. |
| 5 | User-facing durable jobs across chats | **ALREADY IN PROGRESS**, #18/#23; do not create a second Job store/API. | Review ownership/revision/idempotency and status/approval/resume/result return after those PRs converge. Keep task lifecycle separate from scheduler delivery. |
| 6 | Authenticated supervision from daily-use clients | **EXISTING IMPLEMENTATION + PENDING DESIGN/ACCEPTANCE.** #8 records loopback Host/Origin/CSRF versus unfinished independent Operator identity. | Reuse the selected server-derived identity adapter and negative tests; do not silently promote browser fields into identity or replace the pending signed Native decision. |
| 7 | Knowledge/context retrieval as a generic capability | **FUTURE ADAPTER WORK**; Concept OS/HumanModel own semantic interpretation and source truth. | First specify generic owner/privacy-filtered retrieval provenance and revision/expiry; consume the existing client projects' approved views. Avoid a new vector DB, semantic classifier or Foundation-owned user model without an actual integration requirement. |
| 8 | Artifact production | **BOUNDARY BASELINE**, `artifact.py` delegates create/validate to ArtifactPort; a concrete document/export execution path is not established by that protocol. | Define the host-approved destination and independent format/content validator for one actual artifact type, then compose an existing OSS producer. No ambient write grant. |
| 9 | External component version compatibility | **POST-COMPLETION PRODUCTIZATION**, matrix LT42 remains partial. Current-host bootstrap/update/rollback are already proven. | Capture exact existing images/tools and test one isolated version transition plus rollback/readback. Do not update production Docker/LibreChat/ToolHive/model runtimes merely for an audit. |
| 10 | Backup, restore, update and storage lifecycle | **BASELINE CLOSED** on current M1; new lock/snapshot surfaces inventoried in this branch. | On any real future schema/state-format change, add restore and rollback evidence at that change. Never invent schema v2 just to fill a roadmap row; preserve old attachment snapshots until their existing owner cleanup expires them. |
| 11 | Routing, provider recovery and local compute | **BASELINE PRESENT; CONCURRENT NATIVE BRANCH CHANGES.** Quota recovery remains fresh-observation-bound; paid/unknown routes cannot be enabled by this queue. | Fix only a new observed ordinary-chat defect with a payload-representative test. No local model installation, paid probing or runtime route-policy reordering. Cohere 429 is external state, not a feature implementation task. |
| 12 | Research/MCP/DATA/CODE orchestration | **BASELINE ACCEPTED**, with ongoing Muse work. | Preserve one agent/tool loop and host-owned scopes. Extend only for a concrete missing adapter/schema/result contract; do not duplicate ToolHive, Hatchet, Cedar or Pydantic AI. |
| 13 | Traceability, evaluation and observability | **BASELINE PRESENT** (`observability`, `instrumentation`, `run_report`, deterministic evaluation). Development Intelligence extension belongs to the concurrent development stream. | Add bounded correlation/evidence only for a real missing non-development journey. Do not persist raw prompts, secret payloads or unbounded results for convenience. |
| 14 | PC_CONTROL | **ACCEPTED BLOCKED** on upstream signing; #106 is a candidate investigation, not adopted backend authority. | A later conforming-backend evaluation must verify release identity/signature and bounded snapshot/readback before any action. No ad-hoc signing, TCC bypass or implicit desktop authority. No Commander used in this work. |
| 15 | FILES write | **INTENTIONALLY UNAVAILABLE** pending a concrete narrower write use case. | Obtain a concrete destination/use case and bind that existing scoped write boundary; do not enable arbitrary chat writes. Artifact destinations can be evaluated independently. |
| 16 | Linux/Windows/native credential adapters and other media | **PORTABILITY / FUTURE**, current production target remains Darwin/arm64. | Pick an actual deployment or media need before implementing. The new kernel lock helper deliberately requires POSIX flock rather than silently running unlocked. |

## Implemented slice and limits

- Source changes in the first slice are limited to `attachment_handoff.py`,
  `push_dispatch.py` and a small standard-library `filesystem_lock.py` adapter.
  The follow-up also extends the existing `webpush_transport.py`. No dependency,
  workflow, billing, credential, model or Native execution change.
- New lock files contain no payload. Retain their stable inode while any
  participating process runs; deleting a live lock file splits ownership.
- The attachment `acquire`/`release` calling contract is unchanged. Each
  successful acquire must still be released on the calling process/thread.
  Process liveness recovers abandoned persisted leases; malformed markers
  remain protected. Old content/meta/lease files remain readable/cleanable.
- Both new and old maintenance implementations must **not** run concurrently
  against the same handoff root: old cleanup does not understand per-reader
  markers. Runtime promotion requires the existing owner to drain old uses,
  replace all participating consumers/maintenance, then perform readback.
- Push is still at-least-once: a process death after provider acceptance and
  before durable per-target commit can duplicate that target. The follow-up
  records provider acceptance per subscription, not device-visible receipt.
  Acknowledgement cache loss/eviction can duplicate delivery; corrupt state
  fails closed. New subscriptions/rotated keys observed during a pending
  delivery keep it pending. Physical Android receipt remains unverified.
- No production service restart/cutover, private-data import, new provider,
  Desktop Commander invocation or model installation was performed.

## Validation and continuation

The two initial reproductions returned: active second-reader attachment was
deleted (`True`); newest low-sort notification resent (`1`). The changed
code must make both outcomes false/zero. Focused tests include the existing
attachment/ENOSPC/10,000-file cleanup, push, WebPush and writer inventory
regressions, plus independent process and ordering tests. Record the exact
GitHub head and M1 CI outcome in the PR; source tests are not production E2E.

After M1 validation of the first two implementation slices, continue with
order 4 while retaining the explicit collision
boundaries above. Do not auto-label this queue as a Native-ready task.


### Source and CI checkpoint

- First slice #110, source head `58ef951f3e93c16d39c91257d3b06e01895d8017`:
  self-hosted M1 Foundation CI #41442504543 **SUCCESS** — 1,433 passed,
  10 skipped, one warning; additional external-mount synthetic contracts:
  10 tests, OK. P02 inventory #41442504610 **SUCCESS**.
- Follow-up #111, runtime source head `56b2ca41658787df093c5a1acdde3b60e5efe034`:
  combined local regression **69 passed**; all four changed runtime modules
  and this audit were independently read back from GitHub. Its separate M1
  CI #41443751181 is separately queued at this checkpoint and is not
  replaced by the parent result. Earlier #41443103051 was cancelled when
  the final all-expired-recipient fix superseded it.
- The next input integration must reuse standard LibreChat/RAG ownership
  first. `paseo_document_reader.py` in #8 reads public HTTPS HTML/text with
  DNS/size limits; it is not a PDF/Office attachment extractor. Do not treat
  the similar name as proof that non-image attachment parsing exists.

Final expiry regression: when every subscription returns 404/410, the notice
remains pending until a valid recipient exists; it is not silently settled.


## Continuation: standard document input

Parent #110 is merged as `90af83721712fcd11295b9ed772b13702f538523`.
The next slice implements order 4's verified adapter gap and a dedicated M1
standard-parser probe. See `STANDARD_DOCUMENT_HANDOFF_20261102.md` for exact
upstream source pins, unchanged ownership, synthetic acceptance and explicit
browser/OCR limitations. Standard extraction is reused; no Foundation parser,
model installation, private upload or cloud fallback is introduced.


## Ordinary-chat HumanModel connection checkpoint

PDF/Office slice #112 and notification slice #111 have passed their separate
M1 checks and are merged. The next implementation connects the current ordinary
Agent to the existing HumanModel read-only adapter, with host owner binding,
Guard preflight, source revisions/hashes and private local-only routing.
See `HUMANMODEL_CHAT_INTEGRATION_20261102.md`. Real owner/view activation remains
explicit and is not inferred from a successful synthetic test. No additional
load/soak campaign or private source import is part of this slice.
