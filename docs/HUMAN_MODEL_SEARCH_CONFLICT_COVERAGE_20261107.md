# HumanModel ranked search: explicit approved-source coverage

This source-only change is a child of Draft PR #274, which is a child of
Draft PR #273. It does not change task management. GitHub Issues/PR/CI remain
the development task source of truth; Foundation adjudicates execution and
HumanModel supplies owner-scoped judgment/evidence, never task state/authority.

## Observed boundary

HumanModel search may return a ranked subset of an already Guard-approved,
bounded, complete view. Returning an undisputed record does not establish that
no other, disputed originals were present. `NO_MATCH` likewise means no match,
not that the owner's evidence ledger contains no dispute. Search previously
returned records with their own `disputed` flags intact, but did not expose
whether other approved disputed originals were omitted.

## Source fix

Within the existing `HumanModelContext.search()` read/Guard boundary, compute
`retrieval_coverage` from the **canonical admitted snapshot** before any
mutable index response is trusted. This metadata contains only aggregate counts:
`approved_source_count`, `returned_source_count`,
`unreturned_disputed_count`, `exhaustive_for_approved_view`, and fixed
`conflict_adjudication = NOT_PERFORMED`. Never expose omitted private text
or source IDs, and never accept conflict claims from the index.

The scope remains one bounded, complete view. A partial view or unauthorized
scope still produces `UNAVAILABLE` without a coverage report. Exhaustive
means the results include the entire **approved complete bounded view**, not
every possible source outside that view; it is not fact verification or
conflict resolution.

Independent regression: six synthetic no-model tests for omitted disputes,
no-match, complete view, returned disputed records, forged index metadata and
unauthorized scope. The real M1 on exact source commit
`7f62a84b7f1ba78a0942b14a45d19085ac1758dd` passed **20
tests plus 7 subtests** together with the previous pagination and source
integrity regressions. No deployed source, inference route, Native service,
private data or GitHub task authorization changed.

Source-only tests do not certify a new Cognee inference or production chat
acceptance. The PR must stay Draft and receive its own CI.

## Independent before-and-after M1 comparison

- Exact parent source `1a52f7af584c9e10d8c9b88308d17ffa47658401`, with the six new tests unchanged: **5 failed, 1 passed** (expected regression reproduction).
- Exact corrected source `7f62a84b7f1ba78a0942b14a45d19085ac1758dd`: **20 focused tests passed + 7 subtests passed**, including prior #273 original-preservation and #274 page-continuity tests.
- M1 continuation of independent #271 local9B repair was running at the time; this HumanModel source-only change did not evict or alter its lease.
