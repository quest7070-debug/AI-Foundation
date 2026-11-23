# AI-Foundation 2026-11-08 audit remediation (Draft)

Source report: `Foundation_code_audit_20261108.md` supplied by the operator.
These changes address the eight reproducible main-branch findings, but do not
constitute installed-M1 acceptance or authorize production rollout.

| Finding | Change | Verification |
|---|---|---|
| F01 | Idle KLM defer uses state compare-and-set, never resets a concurrent RUNNING/VERIFIED job | Concurrent pause/claim/verify/defer regression |
| F02 | Durable Work maps known Guard failures/rejections to FAILED and stops dependent steps | Real Guard independent-readback failure |
| F03 | CODE/change runs host-selected tests, not the edited source path; failing baseline does not block repair | Separate source/tests repository |
| F04 | LongRunningAuthority persists DATA backend and versioned envelope; legacy records fail closed if authority cannot be reconstructed | Durable roundtrip |
| F05 | CODE returns machine-verifiable status; long-running wrapper does not promote failed post-write tests | Failed acceptance receipt |
| F06 | Atomic terminal transitions ensure cancellation survives late runner outcome | Cancel/race regression |
| F07 | Drive Changes requests the same rich fields as inventory and fills only truly omitted fields from last observation | Sparse projection roundtrip |
| F08 | Import the existing HostComputeLease implementation and its regression test from PR #227, file blob `10e214c09fdf811a35e23e5cea81944d784199a5` | Import and original lease regression tests |

## Non-goals and constraints

- No paid provider, model installation, Native signal, effect replay, or service restart.
- This is a Draft PR; do not auto-merge or deploy.
- No new workflow database or scheduling/lease plane. The existing shared SQLite
  work store and existing HostComputeLease are reused.
- A Guard write can be independently verified even if later unit tests fail.
  Failed post-test acceptance remains visible as a failure; no rollback is implied.
- Existing grants written with the old authority projection may not be
  reconstructible if their required backend was omitted. Do not infer or mint
  backend authority when reading such records.
- Source copied from PR #227 overlaps the still-open PR #219/#227 work. Reconcile
  provenance and merge order before considering this change for main.

## Required acceptance

1. Review exact branch diff and run focused regression tests.
2. Run Foundation CI; distinguish Linux CI from macOS/M1 and native acceptance.
3. Independently verify exact HEAD and tests. Separate human-gated production
   deployment remains out of scope.
