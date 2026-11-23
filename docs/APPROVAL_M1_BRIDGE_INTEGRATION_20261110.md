# Approval + M1 bridge integration (2026-11-10)

**Source target:** clean canonical main `aaa1a531`, not a merge of stacked
deployment PR #470 or child #480. This Draft ports only reviewed P3 stdio MCP
transport, LV4 unresolved-case notice fixes, and count-only M1 diagnostic
projection; no Kandev, Desktop Commander, Native signal or model calls.

## Reused owners

- Existing host-authenticated owner decisions and canonical Guard/Operator
  remain the **only** authorization sources. HumanModel is a read-only corpus
  of owner evidence that the existing Agent/LLM may use to reconstruct a
  provisional owner answer; neither its data nor a simulated reply can grant
  authority. The primary-review producer only matches independently recorded
  prior owner decisions to current Guard scope, or escalates to LV4. It is
  **not** a second authorizer. No new approval level or DB.
- `foundation_mcp_stdio.py` default entrypoint exposes only
  `foundation_status`. Read/review/decision tools are code-level **opt-in**
  requiring a trusted host-held `AuthenticatedMcpHost`, exact current
  Guard nonce, caller-bound scope and per-decision owner delegation. An MCP
  client's claimed identity cannot grant this.
- Unresolved HumanModel review projects LV4 **only** when the same current
  Work job remains `WAITING_HUMAN` and the review generation is current.
  Guard denial, stale generation and technical failures do not create owner
  authorization. LV2 STARTED and RESULT remain deduplicated and Web Push
  summaries redact private content.
- The existing M1 bridge `operator-status` reports additional aggregate
  counts: exact pending Guard requests, primary review started/resolved, and
  current LV4 handoff. It does not export refs, task IDs, source text or
  modify Guard. The strict GitHub Issue request vocabulary is unchanged.
- `approval-bridge-readonly-accept.yml` runs real M1 external-process
  stdio discovery/status and negative write tests, with no model or
  production effects. This establishes read-only transport only, **not** a
  write-capable production MCP service.

## Acceptance boundary

Do not report approval/MCP P4 complete until an independently authenticated
**owner-delegated host session** has actually been installed and exercised
against a fresh exact Guard request, its stale/replay and DENY failure modes,
and a real current HumanModel LV2/LV4 notification with independent
Operator/Web Push readback. Production activation requires a separately
authorized release/rollback receipt, preserving `09fdde25` installed
Operator/local9B and original work/Guard state.

## Installed P4 state-root compatibility

The existing M1 runtime-status bridge reported `OWNER_FILE_MISSING` at
`RESULT_DIRECTORY` even though the local9B worker launchd label ran
every 300 seconds with exit code 0. The prior P4 release moved the
installed worker script but intentionally preserved its old queue root
in the trusted LaunchAgent `AI_FOUNDATION_LOCAL9B_STATE_ROOT`.
The legacy main probe assumed `worker.parent/results`, so it cannot
read actual work results after the cutover. Port the two **verified
source-only** fixes and their three fail-closed tests from PR #470 into
this main-based integration: resolve the state root from the *installed*
owner plist, reject traversal/symlinks/unowned directories, never infer
model success from a missing directory. This change is read-only and
does not move or delete existing worker state. New code requires an
independent host readback after deployment.

## 2026-11-10 isolated host-transport acceptance

`m1_approval_scoped_host_canary.py` deliberately does **not** connect to the
installed Operator's Guard database. On the actual Mac owner session it
initializes an ephemeral private SQLite Guard/Work, an explicitly run-bound
owner authorization callback, and a real stdio MCP server. A second process
(`m1_approval_scoped_stdio_e2e.py`) confirms signed-up/current exact request
review, scoped AUTHORIZE and DENY, changed/replayed and foreign-run denial,
and projected LV2 STARTED/RESOLVED + LV4 current unresolved Work. The
subprocess independently validates persisted Guard CAS and durable Work
notifications before the temporary directory is removed. It never invokes
the existing M1 model, launches production software, or changes a live
authorization. Passing this canary proves the **local protocol and
permission-enforcement path**, not that a real account has delegated a
production decision. No production write-capable MCP launch exists yet.

## Owner-issued production grant path — Draft implementation

The existing Operator decision surface now offers **DELEGATE AUTHORIZE VIA MCP**
and **DELEGATE DENY VIA MCP** on a current actionable Guard request only.
The endpoint uses the same loopback Host/Origin/CSRF checks as direct
AUTHORIZE/DENY; it stores one fixed 300-second, one-shot grant in the **existing
Guard DB** (no separate DB or new approval level). Delegation alone is not a
Guard approval. The owner selects the exact decision in the existing UI. MCP
input, clientInfo, LLM text and session ID cannot create a delegation.

The isolated owner-local launcher `m1_owner_delegated_mcp_stdio.py` uses a
fixed trusted owner principal and authenticated in-process token. Its per-tool
authorizer reads only still-current grants, and the precise submit path
atomically consumes the exact reference/decision before the existing Guard
revision CAS. Stale, expired, changed-target, foreign and replayed decisions
fail closed. A new live Operator instance is **not constructed**, preventing
startup Work mutations. An accepted Guard decision is durable but the separate
MCP launcher does not itself re-run an old intake task; work resume retains
its own canonical Operator/worker path.

The M1 canary uses a temporary Guard DB and the real Operator HTTP
CSRF endpoint, then an independent stdio client and the production-path
launcher adapter. It proves dispatch with owner-issued *fixture* scope, not
proof of a real person consenting to a live pending action. Deployment,
owner UI access controls, explicit release and independent production readback
remain separate. The default `foundation_mcp_stdio.py` is still read-only.

## 2026-11-10 installed Operator entrypoint compatibility
The trusted M1 read-only probe returned `OPERATOR_SOURCE_BINDING` with
`UNRECOGNIZED_PYTHON_ENTRY`, proving the installed owner LaunchAgent
uses a Python entrypoint not named as the old two canonical script
basenames. The earlier inventory contract incorrectly rejected valid
versioned/repackaged Operator launchers solely by basename. The new
inventory reads the **one absolute Python file** bound by the fixed
owner-specific installed LaunchAgent, checks ordinary owner/regular
file and not group/world writable, hashes the *actual bytes*, and binds
them into the immutable release scope. This still never executes the
entrypoint and explicitly denies multiple entries, symlinks, relative
paths, `-c`, `-m` and `..`. No host data is returned, no source is
installed, and `release_permitted=false` remains invariant. This
is a read-only diagnosis compatibility fix, not a privilege grant.

## 2026-11-10 production loader evidence and duplicate probe removal
The canonical Operator `scripts/operator_server.py` already creates the owner-bound HumanModel context in `auto_agent_factory`; a second loader would duplicate existing authority. The installed P4 launcher's source must instead be classified by explicit imported/called factory symbols, not a grep for comment/text. `_loader_source_kind` now distinguishes `DIRECT_OPERATOR_SOURCE`, `ADDITIVE_LAUNCHER_SOURCE`, and `UNVERIFIED`. None asserts that a running process loaded those bytes, authorizes a Guard decision or permits a deployment.

The real M1 [run #42718992979](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42718992979) already established an exact owner-bound nonempty View snapshot (one eligible after binding, 4 evidence records), and [run #42718992561](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42718992561) confirmed the fixed project View metadata. Their repeated USB/SQLite inspection held up [run #42723045064](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42723045064) despite the prior lightweight loader probe completing. The redundant project View recheck is removed from this focused acceptance workflow. New source and owner binding diagnostics are still read-only and never imply live process attestation or a release permit.

## In-process HumanModel wiring readback (2026-11-10)
A new read-only `humanmodel_factory_registered` Boolean is emitted under the
existing Operator `/api/human` `development` section. It is set **only**
when this Operator instance's `OpenAICompat` holds the precise source-marked
owner-bound `auto_agent_factory` callback; no host path, owner ID, View ID,
evidence text, tool output, model call or approval authority leaves the host.
The existing M1 `operator-status` projector allowlists only this Boolean
as a tri-state: `true`, `false`, or `null` for old deployed versions.
A true value from the independently PID-bound live HTTP server **after a
reviewed deployment** shows the installed process constructed the intended
callback, but is deliberately **not** proof that HumanModel read completed or
that a Guard production release was authorized. Existing View evidence remains
separately verified. Current installed source on the M1 previously reported
`loader_source_kind=UNVERIFIED`; no live source was changed by this PR.


## Operator-only immutable Guard release scope (2026-11-10)
The read-only M1 P4 inventory originally grouped Operator and local9B,
which cannot serve as a narrowly authorized Operator-only release target.
\`operator_only_release_scope\` now derives an actual
\`ImmutableReleaseScope\` (existing \`GuardReleaseGate\` contract) from
the installed owner-controlled Operator LaunchAgent/source/config, exact
reviewed checkout commit, and five fixed critical Python source hashes.
No path, config, owner, evidence, or private content leaves M1.

Changing the installed plist/source, candidate commit or critical package
changes the immutable scope and invalidates previous request refs.
A dirty checkout or missing fixed owner config fails closed. The scope
only establishes \`OBSERVED\`; rollback bytes are **not yet backed up** and
the result always states \`release_permitted=false\`, owner approval=false
and zero service/Guard/Native writes. Synthetic tests exercise the existing
Guard release gate's WAITING_HUMAN and changed-scope rejection, not live owner
approval. No 9B lease, Native signal or worker state is touched.

The production step after this is a genuine owner-issued Guard approval
for this exact reviewed scope, preserving the old Operator plist/source
and installing the pinned candidate with rollback and PID-bound readback;
neither GitHub CI nor this read-only reviewer can do that effect.


## Operator-only cutover state machine (November 10)
The new src/ai_foundation/operator_release_transaction.py provides an
Operator-only release transaction in the existing CutoverRegistry, with
two independent gates: GuardReleaseGate must return exact APPROVED,
and the trusted host owner release gate must independently confirm the
same scoped request. There is deliberately no live owner-gate provider
or launchctl host adapter in this Draft yet; merely passing MCP JSON,
a Guard request reference, or owner chat text cannot authorize it.

After authorization, a host adapter must back up the exact incumbent
source and plist and independently verify them, stage an immutable
candidate, then recheck both gates and source scope. It journals CUTOVER
before touching a service, switches only the Operator, requires
PID-bound readback including HumanModel factory wiring, and restores
the previous Operator on switch/readback failure. Failure to verify
rollback retains CUTOVER and requires explicit owner recovery.
All new tests are disposable SQLite/fake-host runs. No installed
service, Guard, private View, 9B or Native effect is changed by CI.


## Operator-only private staging source (November 10)
scripts/m1_operator_release_stage.py now implements no-service-effect backup
and pinned candidate staging. It first verifies the exact Operator-only
source/plist/config scope, copies the prior Operator plist and entrypoint, then
copies strictly tracked, owner-owned, nonsymlink candidate source files to a
private scope-named staging directory and verifies a local byte manifest.
Scope drift or corrupt/stale stage fails closed; no restart, Guard mutation,
model or Native dispatch is possible from this staging code. This source runs
only on synthetic temp directories in pull-request acceptance. In particular
a stage result alone cannot authorize a production cutover or prove the
complete old runtime package is recoverable: independent full rollback and
PID-bound host checks are still required by the future installed adapter.


## Fixed Operator launchd adapter (November 10)
scripts/m1_operator_release_host.py now contains a fixed Operator-only
filesystem/launchd adapter. It builds a narrowly validated new Operator plist
from the existing owner config and only the reviewed staged candidate, retains
the exact prior plist mode, checks an idle PID-bound existing HTTP listener,
and performs only the Operator bootout/bootstrap. The post-switch readback
requires the new instance to own TCP 8766 and report the actual registered
HumanModel factory via /api/human. Its independent rollback restores exactly
the prior plist, preserving the old package at its original source path, and
checks old service/PID/HTTP. If the old service is already intact and healthy,
rollback is no-op. The candidate scope now also hashes the exact existing
private config bytes so configuration drift invalidates old approvals.
This adapter deliberately has no CLI/main, GitHub Issues mutation operation,
MCP tool or production owner gate provider. All launchd unit checks use
temporary fixture plist content and never manipulate real M1 services;
authorizing the live owner gate, staging a real host package and performing
the controlled cutover remain separately gated.
