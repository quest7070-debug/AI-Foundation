# G1/G2 Pre-live Audit

> Superseded note (2026-09-20): this pre-live audit records the earlier quota-gated onboarding design. Current semantics are authoritative in SETTINGS_SEMANTICS.md and PHASE_G_PLAN.md: validated FREE credentials may register when quota is not machine-readable; unknown quota is never fabricated or treated as capacity proof. — 2026-09-19

## Gate result
NOT YET CLEARED for live provider credentials.

## Verified in this audit
- Focused provider/settings/security suite: 28 passed.
- Adversarial additions: raw secret absent from SQLite bytes; concurrent observations preserve DB operation; unknown binding cannot execute; untrusted provider response body cannot mutate provider/binding identity.
- Full regression after additions: 277 passed, 10 skipped, 1 warning.
- Existing real-M1 Keychain save/load/delete readback remains the native-secret evidence.

## Remaining blockers before live API
1. CLOSED 2026-09-19: Keychain persistence now calls macOS Security.framework directly (Keychain Services) rather than passing the secret to `/usr/bin/security` argv. Real-M1 isolated-service save/available/load/delete readback passed.
2. CLOSED 2026-09-19: Settings deletion now removes Keychain first and Registry second; failed secret deletion retains Registry, while post-secret DB failure is surfaced as reconciliation-required.
3. CLOSED 2026-09-19: duplicate raw credentials are detected by in-memory digest comparison against Keychain-loaded registered bindings; no digest is persisted.
4. PARTIAL 2026-09-19: Provider Registry now has SQLite integrity/schema preflight plus Keychain-binding presence readback. Corrupt/missing-secret states fail readiness. Automated repair remains intentionally absent; recovery must not invent credentials.
5. LiveProviderProbe intentionally cannot satisfy FREE short+long quota evidence yet.

Live credential E2E argv blocker is closed. Blockers 2–4 should still be closed before calling G1 production-ready; blocker 5 is required for FREE onboarding.
