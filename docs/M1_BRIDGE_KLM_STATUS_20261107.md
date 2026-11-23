# M1 development bridge: exact KLM runtime status

**Owner:** existing authenticated GitHub-to-M1 read-only bridge (main).
**Scope:** optional klm-status operation, not the KLM runtime or its release.

## Fixed user request

Create a new owner-authored GitHub Issue with exact title:
"Foundation M1 Bridge: klm-status"

Its entire body is:
"<!-- foundation-m1-bridge: {"version":1,"operation":"klm-status"} -->"

The preexisting GitHub Actions workflow validates original/fresh Issue
author, body and state under the exact repository and runs trusted main
checkout on the existing self-hosted M1 runner. Request bodies cannot add
paths, file reads, commands or dynamic parameters. Bot-authenticated
receipt deduplication is reused.

## Host read-only proof

Only the fixed owner LaunchAgent plist at
~/Library/LaunchAgents/dev.quest7070.ai-foundation.klm-drive.plist
selects the already installed private JSON report and host config.
Report must be a regular owner-owned mode-0600 file below 32 KiB, with
no leaf symlink. The private host config identifies the existing
Foundation Durable Work DB; SQLite is opened mode=ro with
query_only=ON; only KLM VERIFIED work steps are inspected. Fixed
launchctl print metadata for the same service label supplies only
run count, last exit code and run interval (no raw launchctl output). No SQLite
table is created or migrated. All emitted fields use allowlists,
type checks and aggregates: private source, paths, OAuth tokens,
model replies, result refs and raw Issue text are excluded.

Report freshness is explicitly constrained to 2400 seconds. Unknown
or invalid values return UNKNOWN/UNAVAILABLE, never success.
Positive one_noeffect_job_evidenced requires a fresh CURRENT report,
READ_ONLY_VERIFIED inference status, and at least one independently
validated hash-shaped, effect-disabled durable Work receipt updated near
the same report commit (not merely an older verified job).

This is **not** proof of the actual model identity, shared lease release,
post-timeout server unload, multi-cycle continuity or original-source
readback. Work's live operator acceptance must verify those separately.

No model request, Google API access, Native signal or launchd service
operation occurs. The sole external write is the preexisting bridge's
sanitized bot receipt comment on the requesting GitHub Issue.

## Deployment and acceptance

This Draft PR is based on main and independent of all Work KLM PRs
#279 through #297. It changes only the generic bridge, fixed workflow
title allowlist, independent status probe/tests and documentation.
It does not edit Work's klm_drive modules, local 9B handler,
scheduler or LaunchAgent.

It must pass real-M1 Foundation CI and independent blob readback.
Only after an explicitly reviewed main merge may its fixed request
be sent to the M1 bridge. The Work-owned KLM runtime update and
real 9B acceptance remain separate.

**Decision:** SOURCE_ONLY_NOT_MERGED_NOT_LIVE_ACCEPTED.
