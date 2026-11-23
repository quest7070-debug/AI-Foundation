# Operator-only owner SSH release entrypoint (Draft PR 522)

This is source-ready work, not proof of production deployment. The sole
production target is the LaunchAgent named
'dev.quest7070.ai-foundation.operator'. Never restart local9B, KLM or Native.

## Existing mechanisms reused

- 'operator_only_release_scope': immutable read-only fingerprints for the
  exact installed Operator plist/source/config and reviewed candidate commit.
- 'GuardReleaseGate': an exact, revision-bound 'production_deploy' pending
  request in the existing Guard database, never an automatic approval.
- Existing authenticated Operator approval UI: the actual Guard decision issuer.
- 'FixedOperatorHost': private old-source/plist backup, pinned candidate
  staging, fixed launchd switch, PID-bound HTTP readback, and rollback.
- 'OperatorOnlyCutover': requires both exact Guard approval and a distinct
  interactive owner-SSH confirmation before doing anything to services.

The new 'scripts/m1_operator_release_cli.py' is a direct Mac owner-SSH
terminal tool, not an MCP endpoint, GitHub Actions workflow, generic remote
shell, Native dispatcher, or model executor.

## Owner-local usage

Use the *already authenticated owner's M1 SSH session with a TTY*
('ssh -tt'). Check out the exact independently reviewed and accepted full
Draft PR commit in a clean owner-owned working tree; do not run an unreviewed
moving branch. From the repository root:

~~~sh
export PYTHONPATH="$PWD/src:$PWD"
HEAD_SHA='<exact-reviewed-and-accepted-40-character-commit>'
python3 -m scripts.m1_operator_release_cli inspect --expected-head "$HEAD_SHA"
~~~

'inspect' is read-only and must report 'OBSERVED_NO_EFFECT'. It refuses a
dirty tracked checkout, missing fixed Operator bindings and wrong source
commit or owner identity.

The owner host now independently resolves the current **canonical
source-policy snapshot**, instead of trusting a user/LLM-provided revision.
It freshly queries the authenticated GitHub repository's `refs/heads/main`,
verifies that commit is already available locally and is an ancestor of
the reviewed release candidate, checks the active Canon declarations, and
hashes the fixed relevant Canon/Guard/Cedar source documents under the
versioned `canon-source/v1:` namespace. If the live remote revision cannot
be verified, request/apply both fail closed. A source-policy revision does
**not** imply a running Operator has that policy installed, nor does it
replace the exact owner Guard authorization.

~~~sh
python3 -m scripts.m1_operator_release_cli canon-check \
  --expected-head "$HEAD_SHA"
python3 -m scripts.m1_operator_release_cli request \
  --expected-head "$HEAD_SHA"
~~~

`request` recomputes the current source revision immediately before creating
the exact pending approval; `apply` independently recomputes it again before
checking the owner-approved Guard request. Any change to the policy content
since owner approval is a hard stop before staging or launchd effects.
No arbitrary `github-main:...` or human-invented Canon revision is
accepted as authority.

Type the displayed 'REQUEST <scope-prefix>' confirmation in the owner's TTY.
This makes a *pending* release Guard request and returns an exact 'run_id',
'request_ref' and 'scope_ref', **not** permission to deploy. The owner must
then use the existing authenticated Operator UI to approve that exact
pending request. Do not write an approval directly into SQLite, replay an
old approval, or use CI to perform the decision.

After the exact request is genuinely approved, from the same reviewed
checkout and owner SSH session:

~~~sh
python3 -m scripts.m1_operator_release_cli apply \
  --expected-head "$HEAD_SHA" \
  --run-id '<returned-run-id>' \
  --request-ref '<returned-request-ref>'
~~~

'apply' first confirms the exact approved Guard request and immutable scope.
Unapproved, stale, or changed scope exits BLOCKED before host construction.
The separate 'APPLY <scope-prefix>' TTY confirmation binds scope/run/ref for
the existing transaction. It backs up old plist+source, verifies staged
candidate, switches *only* the Operator launchd label, verifies the new
PID-bound '/api/human' registered HumanModel factory, and rolls back on
failure. It never touches the 9B worker, Work queue or Native.

## Acceptance and recovery restrictions

- An approval cannot be inferred from this chat, an Issue, a scope ref, a
  green PR CI or successful SSH authentication alone.
- The current Canon revision is an independent authority requirement. If it
  cannot be checked, do not call 'request'.
- Any installed source, config, candidate or plist drift changes the scope;
  abandon the prior ref and require a newly approved request.
- A missing genuine TTY, wrong M1 UID, missing existing Guard DB or authority
  marker, invalid backup or changed source fails closed.
- Failed launchctl/PID/readback triggers the existing rollback transaction;
  failed rollback verification must be treated as manual recovery required.
- Never auto-retry an interrupted cutover. Reconcile the durable registry
  and old backup first.
- A live in-process HumanModel-factory marker is *only* wiring evidence.
  Independently verify the owner-bound HumanModel View and actual Guard/Work
  state before claiming complete installed P4.
- Draft PR remains Draft; no automatic main merge or live host mutations
  occur as a consequence of source editing or CI.

No Mac production write or Guard authorization has been performed by
creating these files.


## 2026-11-10 real-M1 rollback investigation and safer next attempt

Owner's direct terminal receipt for the first approved release attempt:
- `m1-operator` registry transitioned PREPARED 21:44:25 JST ->
  CUTOVER 21:53:11 JST -> ROLLED_BACK 21:53:17 JST.
- Independently inspected old installed plist byte-for-byte equal to backup,
  restored PID-bound /api/human responds, no activity, and private staged
  backup/candidate remains hash-verified. New definition is NOT installed.
- Initial CLI printed `{"status":"BLOCKED","reason":"OperatorHostDenied"}`.
  Owner stderr last update was 21:51:12, before cutover; its
  sqlite3.OperationalError class alone cannot establish this failure's cause.
  A narrow launchd unified-log predicate showed no matching bootout/bootstrap
  keywords. Failure's exact fixed host code was unfortunately not preserved.
- The transaction's original host exception was not an independently
  verified post-switch HumanModel-readback result. No evidence supports
  attributing this specific rollback to 9B, ToolHive, or SQLite.
- Do not retry the first release run, reuse its approval, alter existing
  Guard rows, clear the private recovery backup or restart 9B/KLM/Native.

This patch adds a read-only *preflight* operation:

~~~sh
python3 -m scripts.m1_operator_release_cli preflight \
  --expected-head '<new-reviewed-40-character-commit>'
~~~

It checks the current immutable source/installed identity, existing
operator-only release registry status, installed LaunchAgent registration,
live launchd-PID-to-port ownership, /api/human reachability, and empty
activity. It does **not** touch existing Guard approval state, stage, launch,
approve or write a plist. `preflight_ok` is a current-time observation,
**not** a guarantee that macOS bootout/bootstrap will succeed, or permission
to deploy. A ROLLED_BACK predecessor is acceptable only for assessing current
readiness; the old approval still cannot be replayed.

When a future separately approved transaction fails, CLI now prints only
an **allowlisted fixed OperatorHostDenied code** such as
`OPERATOR_BOOTOUT_REJECTED`, `OPERATOR_BOOTSTRAP_REJECTED`, or
`OPERATOR_BUSY_OR_NOT_PID_BOUND`. Unknown exception text, OS stderr,
private paths, config contents and credentials never leave this channel.
The fixed failure code is for a *new* attempted change only; it cannot
retroactively determine the earlier failure. The apply entrypoint now independently requires that the durable release
registry is still PREPARED with the **same run ID and request reference**.
A ROLLED_BACK, CUTOVER, VERIFIED, missing or mismatched predecessor is rejected
*before* the owner prompt or any Guard or service modification; a stale
Guard approval never permits a retry. A new code commit changes the
immutable release scope, so any subsequent production request requires a
fresh independent Canon check and a new exact owner Guard approval.


## Second real-M1 failed bootstrap and transactional race hardening

The owner performed a second, independently approved exact Operator-only release at
`77fd84c1b50a6538b3cd527e1b8ea8f70ed148ae` (new release scope
`f7f157c3d98aa130ac4937b0a0ffe1afd2ca8760063c0d1a6c8ac03205ab1f6c`).
Its failure was `OPERATOR_BOOTSTRAP_REJECTED` and the owner then verified:
- `ROLLED_BACK` for the exact scope; old plist restored, new plist absent
- existing launchd label registered and PID bound to port 8766, /api/human HTTP 200
- candidate interpreter, script, working directory, owner config present
- candidate plist passes `plutil -lint`, so no evidence of a static plist parse issue

In `FixedOperatorHost.switch_operator`, the fixed error occurs only after
`bootout` returns zero and the new plist is installed, when `bootstrap`
returns nonzero. The host did not record that exact macOS return code or
stderr, so this alone does **not** establish the cause. Independent examples
of macOS launchd teardown latency are documented in
https://github.com/headroomlabs-ai/headroom/issues/1289 and
https://github.com/openclaw/openclaw/issues/84630. Those reports show
`bootout` success before complete label removal can cause transient
`bootstrap` error 5 (`Input/output error`). This matches the vulnerable
old code sequence, but remains a **hypothesis**, not a proven owner-host cause.

Repair on this Draft branch only:
1. After a successful `bootout`, wait for two consecutive absent
   `launchctl print gui/<uid>/<fixed-label>` observations (at most 60
   observations at 0.25 s intervals) **before** swapping the plist.
2. Permit at most 10 `bootstrap` attempts **only** if previous stderr
   matches the exact transient `5: Input/output error` or
   `37: Operation already in progress` launchd responses and the label
   remains unregistered. All other errors and already-registered labels
   fail immediately; never repeat bootout just to retry.
3. Apply the same bounded teardown wait and narrowly scoped bootstrap
   retry to an authorized transaction's rollback. Rollback remains
   mandatory and independently verified.
4. Add fixed, path-free failure codes `OPERATOR_BOOTOUT_SETTLE_TIMEOUT`
   and `ROLLBACK_BOOTOUT_SETTLE_TIMEOUT` plus fixture-only tests for
   ordering, timeouts, recognized transient/permanent errors and rollback.
   No code path automatically issues/reissues a Guard approval.
5. No production services, 9B, KLM, Native, or owner Guard data are
   changed by this code patch. Previous approved runs remain consumed
   and **must not** be applied again.

A successful CI means only that the fixed failure paths passed isolated
tests. Any further production attempt requires a **new reviewed pinned SHA**,
fresh independent Canon verification (do not conflate source Git SHA with
runtime Canon authority), new owner Guard `production_deploy` approval,
exact owner terminal confirmation, and live post-switch PID-bound readback.


## Bootstrap diagnostic refinement (no extra authorization)

Before any future owner-approved release, the revised host explicitly classifies
three local bootstrap failure outcomes into fixed, privacy-safe denial codes:
`*_LABEL_PRESENT` (the label is still registered and must not be replaced),
`*_RETRY_EXHAUSTED` (transient 5/37 persisted through the bounded attempts),
and `*_PERMISSION` (macOS reports a permission denial). Unrecognized
launchctl output continues to report generic `*_BOOTSTRAP_REJECTED`.
The exact macOS command output, paths, environment and secrets are never
exported into chat or GitHub. These codes apply to the *next* attempt only
and do not establish which condition caused the historical failure.

## 2026-11-10 Canon source binding (no live service change)

New `m1_operator_release_canon.py` derives the source-policy digest from
the fresh remote canonical main and a fixed set of owner/release-relevant
Guard/Cedar/Canon policy source bytes. `canon-check` is read-only.
`request` binds the verified `canon-source/v1:` token to the existing
Guard pending request, not to a new authority DB. `apply` refuses old
Git-SHA-only approvals or policy changes before the owner prompt.

This is strictly a verified *source* Canon snapshot; independent installed
runtime-policy readback remains required after a successful real switch.
The owner must still authorize the exact request through the existing
authenticated UI and separately confirm `APPLY` in an interactive TTY.
This change creates no approval and does not restart Operator, 9B, KLM or Native.
