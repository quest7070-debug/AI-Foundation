# KLM GUI-owner lifecycle release v3 — pinned acceptance plan

Status: PREPARED / NOT YET APPLIED (2026-11-08 JST).
Canonical repo: `quest7070-dev/AI-Foundation`.

## Why this cutover
- Installed KLM-only release `369e74a4f8a9f19f369aa182f865b2d8fadb57c0` was accepted as APPLIED (#362); due scan then proved CURRENT / COMPLETE over 33 folders / 114 objects, 900s cadence, no Inbox writes (#385).
- #385 independently found three prior VERIFIED items, three FAILED, twelve older source-hash atoms missing indexed semantic features, three VERIFIED audit Work, and zero relation/placement candidates.
- #388 exact Actions recovery was cancelled after SOURCE_READ_BEGIN and before source-read completion. Exact Keychain-vs-HTTP cause is not attested. GitHub Runner must not fetch owner GUI source or infer a requeue.
- PR #387 and #390 integrated KLM core, source-bound semantic review, one GUI-owner retry intent, and legacy source rehydration to main; PR #390 CI #42430242711: 1,900 PASS / 15 SKIP.

## Immutable release contract
- **Previous installed source:** `369e74a4f8a9f19f369aa182f865b2d8fadb57c0`.
- **New immutable source:** `4e71e42ecc3aa14d740ed4e198c032669b68aba2` (PR #390 merge SHA).
- Single LaunchAgent: `dev.quest7070.ai-foundation.klm-drive`, `StartInterval=900`, existing report/config and owner.
- Git entry/handler/knowledge core/Drive cycle/worker/projection/Input/Auth SHA-1 blob identities embedded in `scripts/m1_klm_final_release.py`. Fetch only the exact commit, reject mutable ref/HEAD drift.
- Require trusted owner-authored exact Issue and independently reread live Issue, actual M1 owner session, exact old installed code and plist, development idle, no active KLM intake, shared compute lease, no active conflicting model and quiescent KLM tick.
- Only source staging and a LaunchAgent script/PYTHONPATH cutover. Preserve exact old plist backup under private permissions; roll back on bootstrap/readback failure. No Guard/Native/Operator/HumanModel effect, Google/Inbox write, paid call, new provider or timer.
- One-shot workflow: `.github/workflows/m1-klm-final-lifecycle-release-v3.yml`; retire promptly after independently verifying APPLIED.

**Owner Issue title:** `Foundation KLM final release: 4e71e42e`

**Exact body:**
```
<!-- foundation-klm-final-release: {"version":1,"release":"4e71e42ecc3aa14d740ed4e198c032669b68aba2","previous_release":"369e74a4f8a9f19f369aa182f865b2d8fadb57c0","scope":"klm-only","intent":"2026-11-08-owner-request"} -->
```

## Subsequent one-item recovery (not part of the release)
After fresh independent `klm-status` proves new service cadence and no unknown active work, owner can create exactly one `Foundation KLM retry one FAILED: 4e71e42e` Issue with source-free staging. Its bot receipt is only `STAGED_ONE_FOR_OWNER_VERIFY`. The existing GUI KLM tick separately authenticates current approved Inbox data, matches revision/hash/raw bytes twice, history-preserving changes only the selected FAILED original to PLANNED, then the existing lease/9B worker may process it on a due CURRENT tick. New old-atom review runs only in an idle window as a separate immutable-original Work.

## Independent exit gates
1. Real M1 CI of final release script + updated one-shot retry and full main regression green.
2. Exact owner release Issue has terminal APPLIED/ALREADY_INSTALLED receipt AND new pinned KLM LaunchAgent status/900s/exit0 verified without unrelated changes.
3. Exact one failure intent reaches `SOURCE_VERIFIED_REQUEUED_ONE`; read back Work transition and previous failure history.
4. Real source-bound 9B has independently VERIFIED Work, new semantic features, owner placement proposal and relation evaluation (zero valid relations may be legitimate). Original source revision/spans are checked separately; model JSON success is not semantic truth.
5. Several due cycles preserve CURRENT complete coverage and 0 unauthorized Inbox/owner writes. No auto-certified human semantic decision.
6. Other owners' write adapters remain UNBOUND until exact owned target/revision, Guard authority, independent readback and explicit approval. No mass historical imports.

Kandev and Desktop Commander were not used.
