# KLM Google setup: minimize operator work — 2026-11-07

Parent #292 at immutable `d34090167abd6940eaf33e37b11bfd15259c9f20`.

## Operator path

A desktop launcher named **KLM_Google認証.command** runs the new
`ai_foundation.klm_auth_setup` from a separately pinned helper release.
It does not update the currently registered KLM host worker or the scheduler.

If no own native grant/client exists, it opens a local Japanese guide with fixed
official Google links for the two required APIs and Desktop-app OAuth client.
The operator completes Google-side project/app setup if needed and downloads
the Google client JSON to normal Downloads **after starting the helper**.
No file rename, copy, path input, token paste, terminal command or separate
scheduled-worker restart is required.

Only new, owner-owned, stable regular files matching Google export names
`client_secret*.json` / `credentials*.json` are considered. Symlinks, older
downloads, unrelated names, oversize, growing and invalid clients are ignored
or rejected. Multiple valid new clients stop for clarification rather than
silently selecting an account/project. A validated private 0600 copy is published
exclusively under the existing KLM runtime. No original download is deleted.

The existing #292 PKCE/loopback consent and Keychain provider are reused.
After consent, exact five approved Drive root metadata reads and existing Inbox
readback must succeed before requesting one tick of the **existing** launchd
entry. Failed API/account/scope checks do not trigger that tick. This is a read
probe, not all-page inventory/model/unattended acceptance.

Already configured own client skips the guide/download step. An existing own
grant skips unnecessary consent; an expired/revoked refresh response can reopen
consent once without manual Keychain deletion. The old grant remains until the
new valid grant is saved by existing #292 logic.

## Limits and storage

This is a user-started, at most 20-minute download wait plus the existing
five-minute consent wait. A private flock prevents duplicate setup windows.
No permanent watcher, second scheduler, task DB, paid API, model call or browser
credential extraction is added. The local HTML contains no credential values.
Temporary import files are 0600 and cleaned. One private result report is
overwritten; it states that unattended KLM is still unaccepted.

Google Cloud project/app creation, API enabling, and Google account consent
cannot be completed by a background token provider. The guide links to official
screens and does not claim that first-time setup is a fixed number of clicks.
Billing setup and app publication are not automatically changed.

## Verification / delivery

Nine model-free tests cover freshness/stability, unrelated/old/link rejection,
validated exclusive private import, automatic download-to-consent progression,
existing-client reuse, no resumption on failed readback, fixed action order and
one-consent expired-own-grant recovery. Local stdlib tests passed.
Real M1 CI, launcher syntax and Desktop placement/readback are recorded after
they actually complete; the helper is **not launched for OAuth** during preparation.

M1 bridge was consulted first: its accepted operations are read-only diagnostics,
not Desktop writes/browser launch. Source/testing use GitHub; placing the exact
launcher on Desktop needs the last-resort authorized host file path. Do not add
an unsupported bridge operation or widen its authority for this task.

References:
- [Google client setup](https://developers.google.com/workspace/guides/create-credentials)
- [Enable required APIs](https://developers.google.com/workspace/guides/enable-apis)

## Actual prepared M1 entry

Immutable `d76a0857837f831536d3ec53ed8f46a0e1eca602` passed [real-M1 Foundation CI #42354041422](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42354041422): **1,764 passed / 15 skipped / 1 warning / 2 subtests passed** (134.50 seconds). [P02 #42354041451](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42354041451) also SUCCESS.

The validated helper release was installed privately and independently matched the GitHub helper/launcher Git blobs. M1 Desktop **KLM_Google認証.command** exists, executable 0755, passes native Bash syntax, and its configured Python import resolves to that exact pinned helper release. The actual default Downloads directory binding was checked. The existing scheduled worker/service remains on its prior release; only the separate helper alias and Desktop entry were prepared.

**No OAuth, browser launch, Keychain change, model request or Google project action was started.** Nine new setup tests are model-free. Cloud-side first-time project/app/API configuration and user consent remain human steps, whose count depends on existing Google configuration. The user need not rename/move the JSON, paste paths/tokens or issue a worker restart command.

Evidence: `docs/evidence/KLM_AUTH_HELPER_PREPARED_M1_20261107.json`.
Decision: **DESKTOP_ENTRY_PREPARED_NOT_AUTHORIZED**.
Later evidence-only commits do not change the tested/placed code. No main merge.
