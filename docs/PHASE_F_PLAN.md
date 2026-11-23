# Phase F — Productization plan

## Human-operable product gate

Phase F must not close with only backend APIs, scripts and runbooks.

It must provide a minimal operator surface sufficient to inspect and operate Foundation-level concerns such as runtime/provider/tool status, waiting-human decisions, failures/UNCERTAIN states, evidence/reconciliation, configuration and credential presence, and backup/restore/update status.

This is deliberately a minimal Foundation operator surface. The full daily-use Human Decision experience belongs to Phase G; presentation clients remain replaceable and must not become authority boundaries.


Goal: make the verified foundation installable, recoverable, operable and portable without weakening A–E boundaries or touching existing production systems during preparation.

## F1 Configuration and host readiness
- Versioned config schema with path confinement and fail-closed unknown versions.
- Explicit host capability report; unsupported native-secret platforms remain unavailable rather than silently downgraded.
- Configuration contains references/paths only, never raw secrets.

## F2 Backup, restore and disaster recovery
- Consistent SQLite backups through SQLite backup API, not blind live-file copy.
- Trace/configurable state backup with SHA-256 manifest.
- Restore verifies every artifact before writing destination state.
- DR drill must prove restored Guard/work state is readable and no effect is replayed blindly.

## F3 Install/update/migration
- Reproducible bootstrap for supported host; preflight before mutation.
- Versioned state migrations with backup-before-migrate, explicit rollback boundary and readback.
- Historical Phase-F rule: update preparation did not mutate the then-existing MultiLLM/Automation Hub/AI Home Server/HumanConsole/M1Remote systems before Phase-H migration gates. Later cutover evidence is authoritative for current runtime state.

## F4 Portability
- macOS M1 is first verified production host.
- Linux/Windows adapters are explicit capability gaps until real-host verified; never claim portability from mocks alone.
- OS-specific secret storage stays behind the common boundary.

## F5 Supply chain/licensing
- Produce dependency inventory from installed/pinned environment, record licenses and source/version evidence where available.
- Fail release review on unknown/high-risk licensing or unpinned critical runtime dependencies; do not invent license conclusions.

## F6 Operator UX/documentation
- One preflight/status surface: config validity, DB readability, secret-store availability, containment/runtime readiness, backup freshness and current version.
- Runbooks: install, update, backup, restore, recovery, rollback, credential rotation and incident handling.
- Human approval remains required for production apply, deletion, spending and actual outbound communication.

## Exit gate
A supported host can be installed/configured, backed up, restored and recovered using documented procedures; update/migration has rollback evidence; dependency/licensing review is recorded; unsupported platforms fail explicitly; full regression plus real-host DR/readback passes.

## F6 implementation evidence — 2026-09-18
Implemented a minimal, replaceable Foundation Operator Surface: read-only status/attention snapshot, loopback-only HTML/HTTP surface, narrow Guard-backed approve/cancel actions, and observe-only UNCERTAIN reconciliation boundary. Focused tests cover real HTTP, durable approval, malformed/unknown action rejection, security headers, duplicate action idempotency, raw-secret non-disclosure, XSS-shaped durable input, and real SQLite UNCERTAIN -> observe-only reconciliation -> VERIFIED -> attention cleared. Focused result: 14 passed. F6 is not closed until full regression passes and remaining status requirements (notably runtime/provider/tool and backup/update freshness) are represented or explicitly delegated to another F gate.

## Phase F exit gate — CLOSED for Darwin/arm64 M1, 2026-09-18
Phase F closes only when the supported host is installable/configurable/recoverable and the minimal Operator Surface can show the Foundation states a human must act on without bypassing Guard/verification boundaries. Backup/restore/update state, runtime/provider/tool readiness and credential presence must be human-visible without exposing raw secrets. Full regression and real-host DR/readback must pass. Unsupported platforms and unresolved supply-chain/license evidence remain explicit rather than being hidden by a nominal release status.
