# G1/G2 Multiview Pre-live Audit — 2026-09-19

Perspectives exercised before any real provider credential/API call:
- Security/secrets: Keychain boundary, argv absence, SQLite raw-secret absence, CSRF/origin, response identity isolation.
- Concurrency/races: concurrent observations and duplicate onboarding. A real duplicate-registration race was reproduced immediately and fixed by serializing Settings mutations; regression added.
- Data validation/invariants: provider identity precedence, tier allowlist, quota percentage domain, missing binding, schema tamper.
- Persistence/integrity: SQLite integrity/schema check, Keychain/Registry presence readback, delete partial-failure semantics.
- Failure/recovery: transport failure, HTTP auth/rate/server classification, onboarding rollback, missing secret fail-closed.
- Trust boundaries: provider response cannot mutate registry identity; unsupported/unverified live probe cannot register FREE credentials.
- Filesystem/local host: provider DB is not world-writable under the verified M1 environment; Security.framework Keychain readback already verified.
- UX/operator boundary: password input, no secret in response, CSRF/origin guarded POST, loopback-only server.
- Quota/accounting: missing evidence fails closed; discovered that Registry accepted invalid tiers and out-of-range percentages. Fixed with FREE/PAID allowlist and 0..100 validation.
- Compatibility/operability: fresh install creates Registry automatically; preflight detects corrupt/schema-tampered DB.

Remaining before live FREE API onboarding:
- Provider-specific authoritative quota acquisition/reset semantics.
- Cross-process duplicate onboarding is not yet protected by the in-process Settings lock; if multiple Operator processes are allowed, add a DB/OS-level uniqueness strategy. Current supported operator topology should remain single-process until closed.
- Automated recovery from Registry corruption intentionally does not recreate credentials; backup/restore integration for providers.sqlite should be addressed before production cutover.

## Follow-up closure — 2026-09-19
- Cross-process onboarding mutation is now serialized on the verified Darwin host with an OS `flock` in addition to the in-process lock. A multiprocessing duplicate-registration test proves only one binding survives and the competing registration is rejected.
- `providers.sqlite` is now part of FoundationConfig validation and the productization backup/restore set. A backup/restore readback test proves provider registry bytes are included and restored.
- Full regression after closure: 296 passed, 10 skipped, 1 warning.
- Note: Keychain secret material itself is intentionally not copied into Foundation filesystem backups; restoring provider DB onto a host without corresponding Keychain entries is detected by Settings preflight as missing credentials and fails closed.

## Provider quota evidence research — 2026-09-19
- Groq officially documents response headers where token limit/remaining/reset represent TPM and request limit/remaining/reset represent RPD. Foundation may normalize these two documented windows to percentages, while retaining their source/scope metadata. Missing or malformed either window fails FREE registration closed.
- Mistral officially documents `X-RateLimit-Remaining` for rate monitoring, while exact plan/usage limits live in the Admin Panel; Admin API rate/spend endpoints require an admin key and are Enterprise preview. A normal Mistral API key therefore does not currently provide sufficient authoritative short+long FREE evidence for Foundation's registration rule.
- Mistral API keys are workspace-scoped rather than free/pay-go scoped, so Foundation must not infer FREE tier from key identity.
- OpenRouter free-model limits depend on purchased credits; key limit/reset controls exist but do not by themselves prove a universal free allowance. Keep fail-closed pending a precise authoritative adapter.
- Added source-aware QuotaEvidence policy tests: Groq complete documented headers pass; partial/malformed evidence fails; Mistral short-only evidence cannot satisfy FREE registration.
