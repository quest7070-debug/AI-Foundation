# LibreChat v0.8.8 Patch Reconciliation

Status: ACCEPTED CANDIDATE / PRODUCTION UNCHANGED
Date: 2026-10-07
Upstream source: LibreChat v0.8.8, commit e8f3be08623663d4ad7f7241e693c94469b63bb0

## Decision

Adopt LibreChat v0.8.8 standard ownership first. Do not line-rebase the v0.8.7 patches.

### DELETE / HOLD

- History Recall patch: DO NOT PORT initially. Accept and test v0.8.8 standard Memory first. Re-open only on measured cross-conversation recall gap.
- Custom attachment ownership/provenance: DELETE. v0.8.8 already resolves owner-scoped request files and exposes currentRequestAttachments separately from history/agent context.
- Old VISION attachment plumbing: DELETE where v0.8.8 standard request/current attachment provenance closes the requirement. VISION authority remains Foundation-owned.
- Any duplicate Memory, Projects, Schedules, MCP catalog, Web/File Search or programmatic-tool product subsystem in Foundation: DO NOT ADD without demonstrated residual gap.

### KEEP — minimal Foundation adapter

- Exact final serialized-body HMAC at the Foundation custom-endpoint transport boundary.
- Foundation owner, authorized current-request attachment IDs, outer capability/scope/long-running metadata bound into the HMAC contract.
- Fail closed until standard attachment authority has finalized.
- Auxiliary Foundation model calls fail down to CHAT with empty scope, no attachments and longRunning=false.
- Non-Foundation endpoints receive no Foundation signing authority.

## v0.8.8 adapter shape

1. initializeAgent creates a request-local mutable signing context; it is not global state.
2. Provider configuration captures that object by reference while preserving the standard LibreChat transport.
3. LibreChat performs its standard owner/file authorization and derives currentRequestAttachments.
4. Only then are attachment IDs copied into the request-local signing context and ready=true set.
5. finalRequestTransform hashes the exact serialized body, adds HMAC headers, and delegates to the already-selected standard fetch.
6. Standard SSRF, allowed-address, proxy, redirect and timeout transport behavior therefore remains underneath the adapter.
7. Foundation getOptions calls without a primary agent signing context are treated as auxiliary and receive only CHAT/no-scope/no-attachment authority.

No new AsyncLocalStorage, global request map, second attachment database or prompt-derived authority is introduced.

## Evidence

- Adapter focused Docker test: 5/5 PASS.
  - exact final body is signed and delegated;
  - pre-finalization request fails closed;
  - concurrent user/request contexts remain isolated;
  - auxiliary calls downgrade to CHAT/no-scope/no-attachments;
  - non-Foundation endpoint receives no signing context.
- LibreChat packages/api build: PASS.
- Foundation focused compatibility regression:
  tests/test_librechat_signing_contract.py
  tests/test_final_fetch_transport.py
  tests/test_chat_gateway.py
  tests/test_capability_factory.py
  tests/test_openai_compat.py
  => 47 passed.
- Production LibreChat remained ai-foundation/librechat:v0.8.7-vision-candidate-tdzfix and HTTP 200 during candidate work.

## Dependency security gate

The exact v0.8.8 dependency set reports 22 npm advisories: 6 low, 6 moderate, 9 high, 1 critical.
The critical/high runtime-relevant set includes proxy-addr, @modelcontextprotocol/sdk, compression and sharp.
A non-force package-lock-only npm audit fix removes the critical advisory and reduces high advisories from 9 to 5. The remaining five high entries are the same Tailwind build-tool chain (tailwindcss -> chokidar/fast-glob/micromatch/braces) and require a Tailwind 4 semver-major change according to npm audit. Do not use npm audit fix --force.

Production promotion remains blocked until:
- the non-force security-lock candidate passes build/regression;
- residual Tailwind advisories are classified as build-time/non-runtime for the pruned production image or upstream resolves them;
- isolated runtime acceptance passes CHAT and attachment/signature negative paths;
- production switch is separately admitted with immediate rollback.
