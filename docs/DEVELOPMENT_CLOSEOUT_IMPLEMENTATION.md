# P09 closeout assessment — implementation boundary

Status: **HISTORICAL SOURCE-ONLY P09 CONTRACT; no accepted generic closeout path.**

**2026-11-12 ownership note:** The Paseo task-state assumption in this
source-only proposal applies solely to its old optional integration, not to
current Foundation development. `SYSTEM_ROLE_BOUNDARIES.md` owns current
GitHub / Guard / Harness / local9B task and readback authority. Do not treat
this experimental closeout projection as a new mandatory lifecycle owner.

The existing Paseo task owner remains responsible for task lifecycle and terminal
state. Foundation does not create a second task database, scheduler, cleanup
worker, or task state machine.

## What is implemented

The pure function in src/ai_foundation/development_closeout.py validates six
evidence gates against one exact task, original request, owner scope, task
repository, improvement-target repository, intent revision, source revision,
and Canon revision:

1. Independent verification by a verifier distinct from the producer.
2. A Paseo owner-issued terminal-state readback. The contract uses a normalized
   projection for assessment only; it does not rename or change underlying
   Paseo/Guard state names.
3. Delivery evidence matching the exact requested acceptance level (commit,
   PR, merge, deploy) and a Foundation UI notification receipt. Routine
   NO_CHANGE notification suppression is allowed only when the independently
   verified result remains queryable.
4. An accepted and read-back improvement-target receipt for the exact
   improvement-target repository/revision, separately bound to the task's
   source repository, including purpose, non-goals, dependencies, semantic
   index, acceptance, constraints, failure knowledge, monitoring, authority,
   and rollback references.
5. A complete eight-domain cleanup ledger with an explicit owner, disposition,
   rationale, evidence, and postcheck for every domain.
6. No unresolved questions, approvals, effects, semantics, or required human
   acceptance. A task requiring human acceptance also requires an acknowledged
   Foundation UI notification and its acceptance receipt.

Retained recovery data and explicitly not-applicable domains are valid
dispositions when supported by evidence. UNRESOLVED is always a blocker.
FAILED, BLOCKED, UNCERTAIN and CANCELLED outcomes can never become successful
closeout. NO_CHANGE is a valid terminal result when independently verified and
presented or retained as a queryable result under the no-op notification rule.

## What is not implemented

- No call to Paseo to close a task.
- No notification delivery or Foundation UI projection; only owner-issued
  notification receipts are validated.
- No registration of the permanent improvement target.
- No cleanup/deletion of source, worktrees, sessions, logs, models, databases,
  backups, credentials, or external state.
- No host-side generation, cryptographic verification, or replay protection
  for terminal, notification, handoff, or cleanup receipts.

The current implementation only validates evidence supplied by the existing
owners. Integration must consume real Paseo terminal readbacks and Foundation
UI notification receipts; it must not synthesize them from model output or
treat this assessment as authority to close, delete, merge, deploy, or change a
provider.
