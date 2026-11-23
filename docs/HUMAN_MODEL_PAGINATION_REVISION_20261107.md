# HumanModel: request-local revision-bound evidence pagination

**Parent:** Draft PR #273 at `5a748d8b26ab15e8e43bd2898ee967d000eb3b6f`. Child changes do not modify the parent's HEAD or deployed HumanModel operator.

## Verified defect (synthetic, no private evidence)

The approved HumanModel snapshot reader independently opens a read-only SQLite transaction per page. `HumanModelContext.read(scope, offset)` forwarded offsets without checking that page 2 belonged to the **same view revision** as page 1. If the original evidence was corrected and the owner rebuilt the view between calls, the returned composite could silently combine inconsistent versions.

A new fixed test `tests/test_human_model_pagination_revision.py` reproduced **5 failures / 2 passes** against the exact unmodified parent on the real M1. The code change yielded **7 / 7 passes** on the M1 with exact checked-out source at `c948041f70ef90433babb7af25b76a186def95cd`, without personal data or model inference.

## Ownership and fix

- Preserve `human_model_context(scope, offset)` interface: no schema or model-facing API change.
- The request-scoped `HumanModelContext` keeps at most one **revision + expected next offset** per approved scope; it does not cache record text, expand privacy or implement another canonical store.
- First valid page at offset 0 creates/replaces an anchor only when the adapter returns a bounded, forward-moving next offset. A direct offset without a first page and a nonsequential offset return non-disclosing UNAVAILABLE reasons before reading the source.
- Continuation fetches independently approved source data and compares the new view revision with the original. On revision mismatch, invalid continuation or source failure, fail closed instead of splicing evidence from two view revisions.
- The original Guard admission, owner/scope checks, per-page snapshot/content digests, restricted/private local-only semantics and Cognee backend are unchanged.
- A new first-page read is an explicit restart that may adopt the newly rebuilt revision.
- No deployment, long-running credential, paid inference, Native effects, main merge or local9b worker edits.

## Boundaries and remaining work

This protects **one context's sequential pagination**, not an immutable multi-request snapshot. The same view revision is an owner-provided logical version, not a substitute for a Merkle/content digest across all rows. The existing SQLite adapter validates each returned row's content hash and the source ledger marks affected views stale when evidence changes normally, but unsupported out-of-band DB mutation that leaves the revision unchanged cannot be disproven by this gate alone. A future version should add an adapter-owned view-level digest/cursor token for long-lived cross-request pagination, without trusting model-provided tokens as authority.

Independent focused M1 regression: `5 failed, 2 passed` before; `7 passed` after. Parent PR #273 has already passed its original Foundation CI before this child. The child requires its own full CI verification, and source-only success is not live deployed acceptance.
