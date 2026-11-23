# KLM host bindings and authentication handoff — 2026-11-07

Parent: #285, immutable `dc3869fed5b426b15c2b43bebd567e0dcba0ae3f`.
This implements host composition and authentication setup; it does not claim that
unavailable credentials or blocked live inference have already been accepted.

## Native read-only authentication

`klm_drive_auth.py` accepts only an explicitly provided Google *desktop* OAuth
client JSON with fixed Google authorization/token origins. It starts a
127.0.0.1 loopback callback, generates per-attempt state and PKCE S256, requests
only Drive readonly + Sheets readonly with offline refresh, and verifies the
returned scope set. It never accesses the Drive app's or browser's credentials.

The offline grant is stored/read back through existing MacOSKeychain, binding
`klm-drive-readonly-v1`, service `ai-foundation`. The client secret and refresh
token never enter argv, logs, GitHub, SQLite or reports. Access tokens are cached
only in memory, refreshed from Google's fixed token endpoint, and checked for
scope changes. Refresh failure does not open a browser or switch to a different
credential source. No write scope or API enable/billing operation is performed.

Run, once the operator has placed their downloaded desktop client at the private
host path:

```sh
PYTHONPATH=RELEASE/src /opt/homebrew/bin/python3 RELEASE/scripts/klm_drive_authorize.py --client "/Users/yourname/Library/Application Support/AI-Foundation/klm-drive/oauth-client.json"
```

An existing ChatGPT Drive connection is not an exportable desktop OAuth client.
No such explicit Foundation client/binding was found during this work. Creating
one in the operator's Google Cloud project and the browser consent remain a
real external prerequisite; no fake, borrowed or hardcoded third-party client
is substituted. Google Cloud Drive/Sheets APIs must be enabled on that client
project; the code does not silently change a project.

## Existing local 9B handler

`Existing9BKlmHandler` calls only the existing localhost Ollama 11434 service
and existing `qwen3.5:9b` digest
`56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`.
It does not create a daemon, download/switch models, call a cloud endpoint, or
change the development worker/Harness. It requests no tools, keeps thinking
enabled and unloads its own model request with keep_alive=0.

An owned Python request process enforces the absolute deadline (at most 90
seconds for the request, while reserving 22 seconds for original source
readback). A timeout kills only that request process; shared Ollama is never
killed. This bounds the client; it is not proof of instantaneous server-side
cancellation. Existing compute occupancy continues to defer while a model is
loaded. Failed/uncertain work is not automatically replayed by the existing
queue. A real timeout/cleanup acceptance requires an authorized idle host.

Only complete, bounded JSON replies are accepted. Model-selected exact quotes
must occur uniquely in the authenticated original bytes; host-derived UTF-8
spans and Meaning objects go through the unchanged #279 core. Up to 8 proposed
atoms are recorded by the existing hash-only ReadonlyReceiptJournal, in the
same Work DB. No source text or model meaning text is saved in this journal;
the output is an extraction receipt, not a newly authenticated fact/decision
store. Results remain proposed and never grant execution authority.

## Host tick / launchd registration

`scripts/klm_drive_host_tick.py` loads a private host config with the existing
Foundation root, exact five approved roots and owner scope. It resolves the
actual existing work DB from Foundation config, reuses installed approved-Issue
policy/receipts and HostComputeLease, and composes #285's native cycle.
No extra task DB, scheduler engine or credential discovery is added.

The driver may be registered with the existing macOS launchd at StartInterval
900. Unbound auth produces a quiet private DRIVE_AUTH_REQUIRED report and no
Drive/model call. The report is atomically replaced with mode 0600 rather than
building unbounded periodic stdout history. Config/receipt paths are private
and are not stored on Drive. Exact deployment/registration receipts belong in
the later evidence file after real M1 readback.

The optional 11436 owned development backend is legitimately absent between
tasks. Only an actual connection-refused result there is treated as empty.
Timeouts/other failures remain busy, and the shared 11434 service must respond
with no resident model. No memory threshold or extra model eviction is added.

## Current external gates

Read-only M1 observation: shared Ollama 11434 is available and has the exact
existing 9B model; 11436 is absent; no model is resident. Existing development
observer still reports one pending approved item: Native #35 lacks the local9B
finite-task contract. The existing conservative WAIT_DEV_IDLE rule is preserved,
rather than weakening admission just to run KLM. #266/#270/#271 are consumed and
are not replayed. No new native signal or paid request is sent.

Ten focused tests cover no credential borrowing, refresh/cache/scope checks,
real loopback bad-state rejection and PKCE, process deadline termination,
source-quote binding, no raw persistence, late/unverified replies, and Foundation-relative Work DB resolution. These
are model-free tests. Real Drive sync, real 9B extraction, 15-minute authenticated
unattended cycles and server cancellation acceptance remain separate gates.

References: [Google desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Ollama native chat contract](https://github.com/ollama/ollama/blob/main/docs/api.md).

## Actual source and quiet-wait deployment acceptance

Exact code `dd940e66be0c977ce1ea579ae92fb831683b2a7c` passed **123 focused tests plus 2 subtests** on real M1. All five new code/test blobs independently match GitHub. The macOS temp-path assertion was corrected to compare canonical paths; the production DB resolver was not changed for that test fix.

[Foundation CI #42353049281](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42353049281) **SUCCESS: 1,755 passed / 15 skipped / 1 warning / 2 subtests passed** (136.83 seconds). [P02 inventory #42353049282](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42353049282) SUCCESS.

The exact tested code was installed in the private Foundation `klm-drive/releases/<source SHA>` folder. Existing macOS launchd registered `dev.quest7070.ai-foundation.klm-drive`, RunAtLoad + StartInterval 900. Independent readback confirmed interval 900, exit 0, a 0600 report and empty stderr. Stop/bootstrap of only this new agent was tested; its new timestamp again reports DRIVE_AUTH_REQUIRED and exit 0. No prior service/Native/worker was changed.

This is a deployed **authentication-wait entry**, not acceptance of actual KLM work. No Google desktop client was provided/found at the configured or usual download locations; the Keychain binding remains absent. Drive/model calls were zero. Pending development observation remains 1 (#35). No authenticated all-page traversal, real9B extraction, server timeout cleanup or multiple authenticated 15-minute cycles are claimed.

Evidence: `docs/evidence/KLM_HOST_BINDINGS_M1_20261107.json`.
Decision: **SOURCE_AND_QUIET_AUTH_WAIT_SCHEDULE_ACCEPTED_LIVE_KLM_NOT_ACCEPTED**.
Main remains unmerged. The later evidence-only commit does not change deployed code.
