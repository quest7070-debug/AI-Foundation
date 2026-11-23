# KLM P0–P2 read-only core — source ownership, semantic atoms, no-effect plans

**Parent design:** Draft PR #277, `docs/KNOWLEDGE_LIFECYCLE_MANAGEMENT.md`.
**Implementation task:** Issue #278. **Source only**, no agent/output hook, no new autonomous daemon or production activation.

## Implemented

- `src/ai_foundation/knowledge_lifecycle.py`: versioned `klm-input-semantics/v1`.
- **P0:** exact per-record source pointer (system, ID, row/event identity, revision, scope/privacy, observed time, unverified actor claim) and an explicit domain→original owner registry. GitHub retains code/Issues/PRs; Drive retains personal/cross-project ToDos and plans; HumanModel original evidence retains person judgments; runtime facts remain runtime-owned. Unknown domains have no guessed owner.
- **P1:** meaning atoms are *proposals* tied to immutable original bytes (whole-source SHA256, byte-exact UTF-8 span SHA256, source revision, record ID). Conditions, negation, chronology, speaker attribution and epistemic kind are separate required fields. Inferences cannot become person decisions through an atom. Same source revision with different data and same candidate relation across dates cannot become an automatic merge or asserted supersession. Source and actor **are not authenticated by this pure library**.
- **P2:** per-owner placement `canonical/projection/reference/index/audit` proposals with exact target resource, record, scope, expected revision and privacy ceiling. Wrong canonical owner, privacy downgrade, stale revision and scope drift fail closed. A proposal never grants Guard permission or causes a Drive/GitHub/Person-model write.
- Deterministic bounded `audit_readonly`: source missing only when inventory coverage is independently complete; otherwise `UNKNOWN_COVERAGE`. Exact source revision drift, same-revision changed bytes and privacy drift are surfaced, not silently reconciled.
- Optional SQLite `ReadonlyReceiptJournal`: one idempotency event per owner-specific source/revision/event/scope, plus exact atom/span/meaning hash references and scoped proposed relation links; no original text or inferred personality; 50,000 records per table bound; exact replay is quiet, conflicting replay and orphan links are rejected, symlink paths rejected. This is **not a second job queue or authority system**. Existing `SQLiteWorkStore` remains the executor authority. Storage inventory documented.

## Concrete tests

`tests/test_knowledge_lifecycle.py` includes **54 model-free adversarial pytest cases**: unknown dates, malformed timestamp, UTF-8 multibyte byte offset, stale/tampered original hash, zero-length or excessive/boolean span, duplicate atom IDs, negation, condition/time disambiguation, quoted speaker vs owner, unreviewed inference, cross-owner canonical promotion, true owner vs reference roles, privacy downgrade, cross-scope leak, old revisions, contradicted same-revision observations, incomplete traversal and missing source distinction, receipt exact replay/conflict, excluded private text, symlinked journal, bounded growth, and concurrent exact-replay/capacity serialization, anti-forgery of owner/Guard admission, stored atom identity, orphan placement/relations, and private cross-scope links.

## What this deliberately does *not* certify

No connected Drive Changes reader, authenticated source adapter, Hash receipt from live original source, Cognee inference, LLM semantic validation, owner-approved personal evidence publication, Guard-authorized remote writes, Hatchet KLM handler, scheduled daily/weekly/monthly reconciliation or live M1 launchd cycle is implemented here. Existing sources and source authority remain as-is. Nothing on the normal Pydantic Agent response hot path changes.

The 54 cases establish *shape, non-forgery of exact raw byte spans, provenance, conservative review and no-effect planning*. They do not establish true semantic accuracy or external source completeness. KLM cannot declare `source_verified` merely because a model supplies a plausible SHA256 or actor identity. This requires a trusted, independently readback owner-specific connector. HumanModel Draft PRs #273/#274/#276 are parallel and not deployed by this PR.

## Subsequent separable work

1. Implement owner-authenticated read-only Drive metadata/Changes cursor and full paginated inventory with a declared scan ceiling and independently tested continuation. The existing operator Drive hierarchy and ToDo IDs in `docs/DRIVE_INFORMATION_ARCHITECTURE_20261107.md` must remain stable.
2. Implement GitHub exact resource/commit API observation and registered HumanModel owner-view invalidation without cross-privacy automatic import.
3. Only after P0–P2 has focused + full CI acceptance and independent M1 readback: connect approved events to existing Durable Work under a **new reviewed bounded KLM handler** (current Hatchet allowlist does not contain KLM). First real stage: `DRY_RUN_READ_ONLY`; no local model needed for deterministic audits.
4. Owners/Guard must separately approve each *effect*. If external write outcome is ambiguous, independently read back before retry. Never invent two-phase atomic transaction across GitHub and Drive.
5. Register event-driven/daily/weekly/monthly triggers through an approved existing scheduler and verify unattended M1 readback before claiming autonomous operation.

Do not change #35 Native/Guard, the ongoing local9B #270/#271 autonomous self-development, parallel HumanModel Draft PRs, or user-facing Drive file locations and links.

## Latest Drive operator addendum — 2026-11-07

The connected [KLM operator document](https://docs.google.com/document/d/1AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA/edit) proposes using the **existing consolidated ToDo `Inbox` tab** (verified sheet ID `103` in spreadsheet `12Vuz-C0YtcM9iDSriAUC_s5jtQ1Kt6pB6k70fzlYKu0`) for *non-sensitive references and pending classification states*. It is **not** a grant to copy whole private conversations/audio/judgments into Drive or to overwrite the source owner's record. The current 9B self-development worker consumes authorized **GitHub Issues**, not Drive Inbox rows. The Drive-to-KLM change adapter remains unbuilt.

The operator addendum also proposes **9B self-development first, KLM model inference second**: before initiating any KLM inference, verify no approved unconsumed development Issue, no active 9B worker job and admission through the existing M1 compute lease. These are **not yet activated scheduling rules**; this core performs no inference and does not consume a model slot. Deterministic local audit functions do not need the model.

## Accepted test evidence and exact scope

**M1 CI SOURCE ACCEPTANCE:** [Foundation CI run #42346486457](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42346486457), tested immutable source HEAD `57f9f60ed8fb1f14839208967b80abf46603283b`: **1,686 passed, 15 skipped, 1 warning**. The first isolated run failed exactly one existing storage inventory assertion despite **1,675 passing tests**; the missing `knowledge_lifecycle.py` module filename in the inventory was corrected, and the final full M1 run passed. No production read/write acceptance is claimed.

**Decision: SOURCE_ONLY_CORE_ACCEPTED_NOT_DEPLOYED.** P0-P2 bounded local proposals and SQLite receipts are verified by CI; trusted live source readers, actual extraction accuracy, writes, scheduled unattended M1 operation and operator rollout are not accepted.
