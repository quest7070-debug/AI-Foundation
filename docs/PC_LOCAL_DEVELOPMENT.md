# PC-local development

The installed owner command is `~/foundation`. Registration, implementation,
fixed acceptance and durable readback run on M1 without a GitHub Issue or CI
round trip for each task. GitHub is used to install a reviewed CLI release and,
separately, for optional delivery.

New owner-reviewed tasks use the existing repository at
`~/Develop/AI-Foundation`, independently of the installed CLI checkout.
Prepare a clean committed baseline on a local feature branch containing the
target source and an independent fixed test. The owner-private review document
under the existing data root, `development/reviews/<ticket-id>.json`, pins the
commit, source/test hashes, public source/instruction hashes and instruction.
The schema and privacy checks remain those in
`m1_strata_owner_ticket_admission.reviewed_contract`; a model or MCP caller
cannot choose a path, command, test or model through a run request.

The reviewed `model` field selects existing compute policies:

| Value | Execution |
| --- | --- |
| `auto` | Available authenticated Strata first for the exact reviewed public initial prompt; otherwise approved shared M1 9B. |
| `m1` | Approved shared M1 9B only. |
| `strata` | Strata only; no M1 fallback. |

Run the existing owner commands:

```sh
~/foundation admit <ticket-id>
~/foundation status <ticket-id>
~/foundation run <ticket-id>
~/foundation status <ticket-id>
```

Registration stores one immutable contract in the existing private manifest.
Each task gets an isolated local Git worktree and uses existing Guard/Work and
fixed acceptance. Later changes to the reviewed source require review before
the first claim. Capacity waits do not consume Work or force model termination.
Verified, failed and source-review-required tasks are not new work.

The CLI accepts successful M1 and Strata receipts only under the selected
policy and exact durable readback. No publication occurs in this loop.
The historical CLI `deliver` adapter is restricted to its original r2 ticket;
other IDs return DELIVERY_TICKET_REVIEW_REQUIRED, rather than publishing r2.
Owner-scoped generic Draft delivery remains separate from local implementation.

Existing installed tickets retain their original source binding and compute
policy. This change does not migrate, reset or re-run them.

## Authenticated request-to-reviewed-ticket handoff (source implementation)

With the trusted local-development MCP launcher enabled, `development_request(ticket_id, instruction)` saves a bounded request in the existing Work database. This is not execution permission and is never a CHAT intake. The owner-side review must pin the exact original instruction, local committed source, independent fixed test and public/nonsecret egress claim using the existing owner-private review document. A changed instruction requires a new reviewed request; MCP arguments cannot manufacture that review.

`development_admit(ticket_id)` then checks that private review against the saved instruction SHA, fixed owner checkout and installed data root, uses the existing admission lock/manifest, and reloads the port with the same Guard. It runs no model or test. Missing review remains REVIEW_REQUIRED. Once admitted, `development_run(ticket_id)` uses the existing Strata/M1 CODE path; local acceptance and optional owner-approved Draft delivery retain their existing rules. Repeated admission reads the existing ticket, including terminal receipts, without re-admitting or executing it. Cancelled requests stay cancelled.

The request record closes after admission while preserving its immutable payload. No new database, scheduler, listener, paid route, model policy or automatic source/test reviewer is added. Source CI and synthetic tests do not prove installed MCP exposure or a new real CODE task. The deployed tunnel must independently advertise the tools and complete a fresh task before generic ChatGPT/Muse development is accepted.

## Optional M1 review-candidate preparation (unsigned, no execution)

After a real `development_request(ticket_id, instruction)` has saved a WAITING_HUMAN
request, an authorized M1 owner can run the reviewed local helper:

```bash
python3 scripts/m1_development_review_candidate.py <exact-ticket-id>
```

The helper reads **only** that exact owner Work request with SQLite read-only
mode, requires one explicit `src/ai_foundation/*.py` target in the saved
instruction, and picks one existing Git-tracked `tests/test_*.py` file
(either explicitly named in the instruction or the conventional matching test
name). It verifies exact locally committed source and test bytes, and stores an
idempotent 0600 candidate under
`DATA_ROOT/development/review_candidates/<ticket-id>.json`.

**This is not an accepted owner review.** The candidate uses
`review=UNREVIEWED_CANDIDATE`, does not occupy
`DATA_ROOT/development/reviews/`, includes no public egress authorization,
and cannot pass `reviewed_contract` or `development_admit` as-is. The owner
still has to inspect the actual source, verify fixed-test correctness and
public/private scope, choose the compute role, and independently create an
exact approved 0600 review document. Ambiguous paths, a missing tracked test,
a dirty checkout, cancelled requests or a changed candidate all stop without
admission. This deliberately leaves arbitrary natural-language task
decomposition and independent test design as separate work.

No model calls, GitHub inner-loop operations, Work mutations, source edits,
new scheduler or automatic review-signing are performed.

## Owner-approved CODE wake exception (2026-11-16)

The general "MainPC absence does not authorize automatic wake" rule in the
historically evidence-pinned `LOCAL_MODEL_ROLE_POLICY.md` remains valid: an
ordinary failed route or offline PC never by itself grants a startup effect.
The later explicit owner authorization in ACTIVE `SYSTEM_ROLE_BOUNDARIES.md`
permits one **ticket-scoped** exception, without modifying that immutable
HumanModel project-reference document.

Only an exact host-reviewed, READY, PUBLIC_NONSECRET Strata/auto CODE ticket,
using the existing M1 owner `wake-desktop.py`, may issue one bounded,
persisted wake intent **before** a Work claim after the host independently
observes that MainPC is unreachable. Status/list, non-reviewed/cancelled/
completed tickets, missing credentials or wrong model, and M1-only/private
work never wake the PC. A consumed/uncertain wake intent is not replayed.
No always-on daemon, global automatic wake, forced model restart, paid
fallback or expansion of the Guard/MCP authority is implied.

This clarification is a run-time interpretation of the 2026-11-16 explicit
owner decision; it does not re-pin or reclassify any earlier shareable project
evidence and does not itself prove a physical wake has occurred.


## Owner review in the existing Operator

The owner-local Operator exposes **CODE 開発依頼の審査** at
`/development/review`. Enter one existing request ID, preview its exact saved
instruction and committed source/fixed test, select the existing compute policy,
then explicitly confirm source scope, independent test correctness and public
nonsecret content. All values are escaped and preview content is returned only
through the existing Host/Origin/CSRF-protected POST surface.

Confirmation is bound to that server's exact preview. It rechecks Work state,
commit and source/test bytes, applies the existing sensitive-input scan, and
exclusively saves the existing immutable 0600
`development/reviews/<ticket-id>.json` contract. Changed source, cancellation,
missing confirmation or a conflicting prior review is rejected. Preview is
read-only. No review is inferred from an unsigned candidate or an AI answer.

This action saves owner review only. It performs no tests, admission, model call
or execution and does not claim that an already-fixed request needs to run.
The existing `development_admit` and `development_run` remain separate. Only an
actual new authorized task with independent acceptance and readback proves the
generic CODE loop; source/UI tests do not substitute for it.


## Withdrawing an obsolete unadmitted request (2026-11-17)

The existing `/development/review` preview offers an explicit owner withdrawal action. A signed current preview, CSRF token and unchecked-by-default confirmation are required. Under the same admission lock, withdrawal rejects any already admitted ticket and atomically cancels only the unchanged REVIEW_REQUIRED development contract in the existing Work store. The original request payload and any saved owner review remain available as evidence. No execution, model call, Guard approval, or cancellation of admitted work occurs. This allows already repaired requests to be retired without rerunning them as an artificial end-to-end test.

## Fast reviewed CODE continuation (2026-11-17, source feature)

The existing **owner-local, opt-in MCP development launcher** may additionally expose
`development_continue(ticket_id)`. This is a convenience for *already owner-reviewed*
requests, not a second admission authority or an unattended arbitrary code executor.

For one immutable host-owned ticket, the original MCP principal must have all three
explicit scopes: `development_continue`, `development_admit`, and
`development_run`. The current host owner authorizer must independently accept
that exact ID. A not-yet-admitted request first invokes the **unchanged**
`m1_strata_owner_ticket_admission.admit`: a present immutable owner-local
review, fixed baseline SHA, unchanged source and independent test bytes, private
storage admission, original Guard, and existing manifest lock are still required.
The newly admitted task then runs through the original host lease, Harness,
Guard, Work one-shot claim, and fixed tests. Non-ready, cancelled, source-drifted,
failed, busy and consumed tickets are **not** rearmed.

If an independently accepted local task reaches `VERIFIED_LOCAL`, the caller's
**separate** `development_deliver` permission and original manifest's
`allow_draft_delivery=true` opt-in are rechecked at that instant before the
existing Draft-only publisher may be invoked. Without both, the change stays
local. Neither completion nor Draft publication authorizes main merge, installed
M1 cutover, billing, new providers, extra M1 resident models, owner decisions,
nor arbitrary commands. `development_status` and `development_list` remain
strictly observational.

**Automation boundary:** an authorized ChatGPT/Muse caller can advance one
previously reviewed or *owner-scope-delegated* task with one MCP call and use
subsequent calls for durable state readback. Unreviewed requests without an
active exact owner scope still stop at `REVIEW_REQUIRED`. The installed finite standing-delegation/main-regression
worker is the only currently permitted reviewless autonomous task path; expanding
it to arbitrary files or releasing this new tool requires an explicit host-bound
standing policy and independent installed-runtime acceptance. Source CI does not
prove this feature is installed.


## Bounded autonomous CODE cycle (2026-11-17, source feature)

An opted-in owner-local MCP host may expose `development_cycle()` without
arguments. This **advances at most one** existing owner-authorized development
ticket per invocation. A calling AI may repeat the cycle when a previous
receipt is terminal; it never needs to choose or fabricate a ticket ID.

The host must independently authorize `development_cycle` and
`development_list` for that session. For every candidate it must independently
grant `development_status` and `development_run` for the exact ticket ID.
An unadmitted request is selectable only with either an owner-private 0600
ticket review **or** an existing, owner-activated 0600 standing CODE scope
that matches the exact tracked source/test pair. The session still needs
that ticket's `development_admit` and `development_continue` authorities.
Neither the review file nor the scope is itself permission to bypass exact
source/test, public-egress, Guard, lock, storage or one-shot Work checks.

The cycle skips requests with neither an individual review nor a valid
current owner scope, plus cancelled, source-drifted, failed, already
verified and running tickets; an unsupported or changed review fails
closed. It returns a bounded `NO_ELIGIBLE_TICKET` summary with an unsigned-review
count if no eligible work exists. No model call, work claim or machine wake
occurs on that path. A ready ticket uses the existing Strata-first optional
MainPC or single shared9B policy; the host's resource lease serializes local
inference. On `VERIFIED_LOCAL`, optional Draft publication still requires
the separate exact `development_deliver` authorization *and* the original
owner manifest opt-in. There is no main merge, deployment, new provider,
paid call or new scheduler. The installed five-minute worker is not
automatically granted this new MCP scope by source code alone.

This is an **on-demand bounded autonomous step**, not a claim of an always-on
agent. A real production release must separately install the integrated
source and verify tool exposure, exact owner scope, one new CODE execution
receipt and readback in the existing Operator.

## Owner-once bounded ordinary CODE delegation (2026-11-19, Draft source)

This supersedes only the old requirement to review **each ordinary, in-scope
public CODE request individually**. A trusted M1 owner must enable the scope
once in the *existing Operator* `/development/review` page under Origin+CSRF
protection and an explicit unchecked confirmation. No MCP JSON request, model
suggestion, copied source, GitHub issue or new app can create this consent.
**Until the owner actively enables it on the installed release, it is OFF.**

The 0600 `development/scope-delegation.json` is private, validated strictly
on each selection, and carries a fresh random generation for every re-enable.
The owner chooses either **M1 shared 9B only** (no remote egress) or **Strata
first with M1 fallback** (explicitly authorizes outgoing *public* source only),
and separately opts in/out of independently verified **Draft-only** delivery.
Neither selection enables cloud billing, payment, extra models, main merging,
deployment, root shell effects or service restarts. Tests and local acceptance
still run under the original bounded Work lease and Guard.

The existing single-file tracked `src/ai_foundation/<module>.py` paired with
a tracked `tests/test_<module>.py` must be unambiguously named in the request,
read from a clean exact committed baseline and hashed before admission.
Operator/Guard/MCP, identity, secret, HumanModel, security, storage, release,
billing and other protected source modules never qualify; they retain exact
per-ticket owner review. The sensitive-value detector also rejects suspected
private instruction/source/test content, but it is **not a universal privacy
proof**. Strata routing remains restricted to the exact public candidate and
the existing host-pinned free local model.

`development_cycle()` may now select an individually reviewed request **or**
a request matched against this private owner grant. The existing independent
`m1_strata_owner_ticket_admission` and immutable manifest persist the exact
source/test, owner scope digest and Work ticket; no model or test executes during
the grant activation itself. A revoked or changed grant immediately blocks
**future** code and Draft claims through the same host port; it does not erase
a running effect or replay terminal Work. A later enable rotates the grant
generation so older queued claims stay revoked. All original source drift,
uncertain effects, failure-history retention, fixed-test acceptance and owner
consent for production/Guard changes remain.

**Completion:** deploy only after Draft CI, exact owner Guard release consent
and independent M1 installed-source/readback verification. Then activate the
scope in the existing owner Operator UI and verify one genuinely new, harmless
CODE request through admission, local test, immutable readback and optional
Draft. The CI of this Draft is not installation or scope activation.

## Smartphone owner release over the existing private Tailnet (2026-11-19, Draft source)

**Why:** the owner must be able to approve and cut over a Foundation release
from the phone without opening a terminal on the Mac. This is integrated into
the **existing** native-Keychain/Tailscale HTTPS human gateway (port 8793),
not a separate dashboard, listener, Guard authority, account or database.

When an actual installed M1 UID 501 gateway loads these source changes with a
configured exact `.ts.net` DNS host, the existing overview offers a
**スマホから本番切替** link to `/release`. A deployment may explicitly disable
this route with `FOUNDATION_REMOTE_MOBILE_RELEASE_ENABLED=0`.
Do **not** use Tailscale Funnel, an Internet/public reverse proxy, forwarded
client identity or a LAN bypass for a production release.

For every GET/POST, the gateway uses bounded native
`tailscale status --json` and `tailscale whois --json <peer-ip>` responses
to require the originating **untagged, unshared Tailscale device** to belong
to the same user ID as the owner M1. Only the configured `.ts.net` HTTPS
Host is accepted. Release POST additionally requires an exact HTTPS Origin,
a same-owner-node/phase/commit/scope/run/ref-bound 5-minute HMAC token
derived from the existing Keychain remote session secret, one typed phrase,
and a checked explicit confirmation. Any failed identity, source,
origin, token or review readback **denies** the action.

The owner sees three distinct mobile confirmation screens:
**1. Guard request → 2. exact pending Guard AUTHORIZE → 3. cutover/rollback
and PID-bound readback**. The phone never directly edits the Guard DB,
launchd plist or a repo: it calls the existing trusted
`m1_operator_release_cli.run` logic with a Tailscale owner-confirmed
challenge callback and reuses the canonical Guard's
`OperatorActions.approve_pending` for the exact same release request.
Only a pre-staged, clean, immutable
`~/.ai-foundation-tunnel-sources/<sha>` owner checkout is eligible.
The old terminal CLI retains its TTY confirmation by default.
An uncertain network result must be observed via the persisted registry:
the phone browser must **not** retry a service effect blindly.

**Limitations / first deployment:** this is Draft code until independently
accepted and installed. The current remote gateway process is a separate
service and is **not** restarted by the current Operator-only cutover;
deploying a new Operator source package alone does not prove the phone
route is running. Before claiming mobile acceptance, the existing gateway
must be refreshed through its separately approved, owner-controlled
service lifecycle and its loaded module/source/PID and physical phone
Tailnet identity verified. Initial trust enrollment and the first release
must use an already authenticated owner entry (e.g. existing owner M1
session from a phone SSH app) rather than treating GitHub CI as the owner.
No self-issued Guard approval, paid API, inference, wake or automatic
production cutover is created here.


### Tailscale Serve 8454 and gateway-owner acceptance (2026-11-19 follow-up #1502)

The owner added tailnet-only Tailscale Serve port 8454 to route to the existing
HTTPS gateway 127.0.0.1:8793 without changing the default 443->8080 mapping.
The owner also finished the existing Operator-only release for exact scoped
candidate 685e6880 with Guard approved and release result VERIFIED. The
gateway is a separate service and does not reload as part of that cutover.

Existing responsive dashboard APIs were missing from the old gateway GET
allowlist. The existing fast-CSRF endpoint was implemented but not installed
in the Operator launch entrypoint, forcing expensive root-page reads for each
smartphone mutation. The follow-up adds those routes and the missing hook.

Owner authentication through Serve (as opposed to direct Tailscale peer IP):
- Trust Serve identity headers ONLY after a separately authorized gateway
  lifecycle actually binds 127.0.0.1, NOT the old 0.0.0.0 listener.
- Set FOUNDATION_REMOTE_SERVE_OWNER_ENABLED=1 only on that loopback-bound
  installed gateway. Invalid bind+opt-in combinations fail on startup.
- Require an actual loopback peer and one exact Tailscale-User-Login header.
  Validate it against the currently Running M1 Tailscale status Self.UserID
  and matching User[UserID].LoginName. Missing, tagged, mismatched,
  malformed, duplicate and inactive identities fail closed.
- Preserve exact HTTPS Origin, allowed .ts.net Host, short-lived owner-bound
  HMAC and confirmation, canonical Guard release checks, PID readback and
  rollback. Do not trust generic forwarded IPs, Funnel or public ingress.

Two distinct production gates remain: (1) review/stage the new #1502 exact
source and obtain a NEW owner Guard request and Operator-only release; (2)
apply a separately owner-authorized gateway service source/bind/env update
with existing plist/source backup, PID/source/port readback and rollback.
Operator-only cutover does not change the gateway. Physical Android Serve
identity and one actual theme/owner-action readback remain required.


### One-time owner gateway bootstrap — replace routine release CLI

Current PR #1502 exact Guard run release-59a238b6b90d10e6aabb7b7e
remains pending; a previously attempted apply was blocked before effects.
No second Operator request or reused approval may be forged.

After source-only CI/M1 staged acceptance of Draft PR #1503, the M1 owner
starts scripts/m1_mobile_gateway_bootstrap.py exactly once from the
immutable private checkout. This command itself does not confer Guard
permission; an interactive UID501 owner session is mandatory.

1. Check exact prior PR1502 source/scope/run/ref and prompt for the
   existing APPLY 4ebdd05052882b58 confirmation once.
2. Wait for genuine existing Operator UI AUTHORIZE via Tailnet 8454, then
   call existing owner release CLI with exact Guard verify, backup,
   launchd effect and PID-bound readback or rollback.
3. Discover the real dev.quest7070.ai-foundation.remote-gateway
   LaunchAgent, verify TLS/ports/script/source, active PID and HTTP health.
   Never touch separate human-review gateway or other Serve mappings.
4. Ask the M1 owner for a distinct GATEWAY <scope[:16]> local confirmation;
   make a NEW immutable Guard production_deploy request for the gateway.
   Wait for its separate owner AUTHORIZE from the same private phone UI.
5. Recheck exact Canon, approved gateway Guard request and source.
   Back up the original plist with owner-only permissions, update only
   the 8793 gateway to a pinned staged source, bind 127.0.0.1 and set
   FOUNDATION_REMOTE_SERVE_OWNER_ENABLED=1. Verify launchd PID owns the
   loopback port and HTTPS /health works. Roll back to the exact old
   service on uncertain verification.

Thus the initial migration has one terminal launch and up to two local
typed owner confirmations, but two distinct smartphone Guard approvals;
no generic remote shell, new account or paid API is introduced.
Future routine releases use /release on the existing private 8454 HTTPS
surface (Guard request -> owner authorize -> apply -> verified readback).

CI/staging success is NOT a running service. Physical Android owner
identity and at least one real /release action readback are required before
claiming production mobile completion.
