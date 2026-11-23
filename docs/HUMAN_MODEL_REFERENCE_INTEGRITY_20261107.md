# HumanModel reference integrity: independent development

## Reconciled baseline

Canonical main: `f7e1b9bc419fbdf40560f3f7fb7d1a9593c598df`.
This branch starts from main, without importing any unrelated Draft branch.

| Path / layer | Implemented | Acceptance / actual limitation |
|---|---|---|
| `human_model_ledger.py` | External SQLite source URI/revision/content hash, kind, unknown observation time, disputed flag, supersession, view invalidation | Source contract tests; new evidence makes views stale until explicitly rebuilt. This is separate from conversational working memory. |
| `foundation_readonly.py` | Read-only transaction, explicit approved view/scope/privacy, bounded pages, revision and snapshot receipt | Existing 8 synthetic adapter contracts pass; not a new private-data import. Superseded rows are excluded by the ledger projection. |
| `human_model_context.py` | Authenticated owner binding, Guard read admission, local-only flag, current source reader, source-bound search output | Existing actual agent-loop tests pass. This PR fixes mutable backend input sharing the canonical comparator. |
| `cognee_bridge.py` / `cognee_memory.py` | Isolated M1 worker, per-snapshot derived cache, grounded spans, post-search current-source revalidation | Prior PR #128 records installed Cognee 1.6.5/local-model acceptance. This change invokes neither Cognee nor inference. |
| `human_model_runtime.py` | Additive context tools and content-free audit over existing daily agent | PR #138 records real daily project-reference calls; #197 records composition with guarded FILES/artifact tools. |
| Draft PR #166 | Additional reviewed private-source admissions and local-only personal chat | Separate extension, not main. Prior live acceptance is recorded in #166; this PR neither imports it nor activates a replacement. |
| Current M1 LaunchAgent | Operator uses pinned `personal-context-5cdad4c9b56c7d63c430` runtime; gateway uses separately pinned daily runtime | Read-only host inspection confirmed installed context still contains the shallow-copy defect. Source changes do not update this runtime. |

No saved Hjarni project notes were available; GitHub source and M1 inspection
were used for the reconciliation. No note or personal profile was created.

## Confirmed defect and correction (P1)

`search()` supplied shallow-copied snapshot data to its backend and constructed
the permitted-record map from that same backend-owned input *after* invocation.
Changing a nested row, appending an invented row, or replacing the list could
therefore pass the supposed original-evidence equality check. Changes to omitted
IDs also leaked into the response. The original snapshot hash could accompany
modified evidence. The same code is present in main, Draft #166, and the installed
M1 context module. This is a boundary defect; no production data corruption or
actual malicious Cognee behavior has been established.

Keep the authorized original snapshot private to the host, derive the permitted
map before calling search, and give the backend a deep copy. Return only rows
equal to the preserved originals. Index ranking still selects original records;
it cannot create evidence, conceal the returned record's disputed flag, replace
unknown dates, expand scope/privacy or grant execution authority. No schema,
tool signature, reader, cache identity or model route changes are needed.

## Independent regression and compatibility evidence

`tests/test_human_model_search_integrity.py` uses a standalone deterministic
backend and synthetic originals, independently of Cognee and any model.
Against unmodified main: 5 tests run, 10 failures (including seven field-mutation
subtests); original-preservation control succeeds. The captured original output
is `evidence/human_model_search_before.txt`.

After correction: focused context/runtime/Cognee tests: **35 passed, 3 skipped,
7 subtests passed**. The skipped contracts require actual Cognee worker runtime;
they do not establish a new real inference result. Existing source adapter:
**8/8 passed**. Existing authenticated owner/Guard/privacy checks, stale view and
correction behavior, real in-process agent tool loop, unchanged ordinary chat,
and local-only failure handling all remain passing.

Real M1 source acceptance on immutable code commit
`6efa13d10823ed60ce74e531c3041f19113cc69f`: **PASS**.
GitHub source bytes were downloaded by commit SHA into a new temporary directory;
no deployed source or configuration was written. The fixed source SHA-256 was
independently equal to the off-host tested file.

| M1 variant | Tests | Result |
|---|---|---|
| Unmodified main | 5 + field subtests | Expected failure: 10 failed assertions/subtests |
| Fixed main | 5 + 7 field subtests | PASS |
| Installed runtime source copied unchanged | 5 + field subtests | Expected failure: 10 failed assertions/subtests |
| Installed runtime source with equivalent correction in a temporary copy | 5 + 7 field subtests | PASS; existing owner/admission checks preserved |
| Existing read-only source adapter | 8 | PASS |

`evidence/human_model_reference_m1_20261107.json` records code/log hashes and
results; it was independently read back from M1 after the run. Regression test
inputs are synthetic. Model calls, paid calls and production changes: **0**.
This accepts the source fix on M1 and its composition with the installed context
module. It does **not** accept a production deployment, a new Cognee worker run,
or a live private-chat answer. Final PR HEAD verification is recorded separately
in the GitHub PR to avoid a self-referential commit hash.

## Remaining work, ordered by effect on evidence continuity

1. **P2: page continuity across view rebuilds.** Offset pagination returns each
   page's revision but does not bind later pages to the first revision. A caller
   must not combine differing revisions as one complete snapshot. Add an explicit
   revision-bound continuation contract and fixed rebuild-between-pages test.
2. **P2: explicit correction-chain provenance.** Current snapshots expose the
   current projection and revision, not the full supersession chain. Design
   source-owned, privacy-filtered lineage rather than exposing private predecessor
   identifiers through a less-private view.
3. **P2: search conflict completeness.** Dispute flags of returned originals are
   preserved, but ranked results are not proof that all conflicting evidence was
   returned. There is no automatic conflict adjudication. Any future relation
   expansion must stay within the same approved source/privacy boundary.
4. **Separate deployment:** preserve Draft #166's owner/admission validation when
   composing a future runtime, stage under its own reviewed hash, then perform
   independent source/audit readback and live acceptance. This PR performs no
   launchd changes, restart, source publication, model operation or main merge.

HumanModel supplies evidence only. Canon, Guard and Human Decision remain
Foundation-owned. PR #248/#268, Issue #270/#271, local9b/Harness/task selection,
Issue #35 and Native production services are unchanged.
