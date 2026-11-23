# Legacy Responsibility Retirement Matrix

Status: REQUIRED = Foundation owns behavior; DELEGATED = replaceable selected boundary owns implementation below Foundation; OBSOLETE = deliberately not carried forward; UNRESOLVED = classification/evidence incomplete. Absence is never OBSOLETE by default.

| Legacy | Responsibility | Target | Class | Retirement gate |
|---|---|---|---|---|
| MultiLLM | provider onboarding/credentials | Settings/credential | REQUIRED | implemented; real provider credential-gated |
| MultiLLM | health/quota routing/failover | ComputeRouter/Settings | REQUIRED | H3 failover 3/3; cloud BLOCKED |
| MultiLLM | local-only privacy | Guard/ComputeRouter | REQUIRED | privacy tests |
| MultiLLM | chat-facing compatibility | daily-use entry | REQUIRED | Foundation OpenAI-compatible chat entry is the live LibreChat caller path through Guard/ComputeRouter; model discovery, normal chat and streaming have production readback. Multi-turn is test-backed; title generation and attachment transport remain separately gated |
| MultiLLM | web research/search | Tool/Specialist | DELEGATED | selected implementation + guarded E2E |
| MultiLLM | media bridge | external specialist/tool | DELEGATED | not part of Foundation routing authority; preserve only as a replaceable external capability if a real caller requires it |
| MultiLLM | LibreChat/admin UI | presentation | DELEGATED | presentation remains replaceable and outside Foundation authority; current containers may remain during caller migration |
| Automation Hub | durable recovery/no duplicate | DurableWork/Guard | REQUIRED | restart + real effect evidence |
| Automation Hub | approval/input/cancel | Guard/TaskIntake | REQUIRED | H3 + broader flow |
| Automation Hub | failed-work retry semantics | runtime/work | REQUIRED | explicit retry-safe classification added; effectful FAILED requires reconciliation before retry |
| Automation Hub | question context/stale-answer rejection | TaskIntake | REQUIRED | durable context digest binds answer to job/step/question/intake; drift returns CONTEXT_CHANGED |
| Automation Hub | scheduler/lease/redelivery | durable runtime | DELEGATED | external Hatchet is now production-composed through Foundation's explicit long-running producer/worker boundary; official native-bound credential bootstrap, real isolated SEARCH/DATA/CODE execution/readback and queued-work worker stop/restart recovery are proven. Foundation/Guard retains authority, effect idempotency and verification; ordinary Operator/chat is not an ambient scheduler |
| Automation Hub | Hub-specific integrations | external producers | DELEGATED | Foundation source has no :8787 dependency; legacy Hub authority :8787 is now down after verified Echo/Foundation migration, so retained producer integrations must target their own replaceable boundary rather than restoring Hub authority |
| AI Home Server | model inventory | Local Compute | DELEGATED | llama-swap /v1/models live readback proven |
| AI Home Server | load/switch/exclusion | Local Compute | DELEGATED | two real cached models load/switch; concurrency backpressure; TTL unload/reload proven |
| AI Home Server | failed-switch rollback | Local Compute | DELEGATED | deliberately broken model fails while healthy model remains recoverable; live readback proven |
| AI Home Server | backend health | Local Compute | DELEGATED | llama-swap inventory/runtime readback integrated; failure path fails closed |
| AI Home Server | inference authority | Foundation routing | REQUIRED | legacy runtime stopped; live Operator targets llama-swap; current-backend H3 LIVE 3/3 regenerated |
| AI Home Server | standalone job queue | Foundation runtime | OBSOLETE | no supported caller uses AIHS jobs |
| HumanConsole | decision/status/notice IA | Human Decision Surface | REQUIRED | responsive + live readback; Foundation-native human projection added for replaceable clients |
| HumanConsole | remote/mobile authentication | access boundary | REQUIRED | staged HTTPS gateway end-to-end live after Operator refresh: unauth 401, forged Host 400, bad Origin 403, login 204, authenticated Foundation human readback 200; native-Keychain production startup boundary implemented on non-conflicting port 8793; Tailscale/Let's Encrypt TLS identity verified and native-Keychain credentials provisioned; production launchd + authenticated read-only human projection live on 8793; remote mutations intentionally not exposed; remote-device validation/cutover remain |
| HumanConsole | push delivery | notification boundary | REQUIRED | Foundation-native projection/storage + pinned pywebpush + native Keychain VAPID boundary implemented; one-shot 0600 legacy import completed; real FCM send accepted 1/1 with no expiry and both Foundation/legacy stores retained 1 subscription; device-visible receipt still requires client confirmation |
| HumanConsole server (:8790) | legacy human web authority | none | OBSOLETE | Foundation remote/human surface replaces server authority; retire via H4/H5 |
| HumanConsole mobile push client/subscription | notification presentation client | replaceable client over Foundation Push | REQUIRED | existing migrated subscription proves transport continuity; do not delete client/subscription until Foundation-native enrollment or deliberate client retention is decided |
| Echo dedicated HumanConsole-named Android client | Echo presentation client over Foundation Echo gateway :8788 | separate Echo client responsibility | REQUIRED | package name is legacy but authority is Foundation :8788 after rollback/re-cutover evidence; do not restore Automation Hub :8787 merely because the client retains the old package name |
| M1Remote | remote-control product | outside | OBSOLETE | never migrate |
| Concept OS | all semantics | independent | OBSOLETE | never migrate |

## Next execution order
1. HumanConsole :8790 server cutover/rollback/re-cutover is VERIFIED and no longer blocks migration. Remaining HumanConsole-named mobile/Echo presentation clients are separate responsibilities; device-visible Foundation Push remains a client-confirmation gate, not a reason to restart :8790.
2. Keep the live LibreChat/Foundation daily-use chat path verified while resolving the remaining SEARCH specialist mapping, attachment/media transport, title readback and historical LibreChat runtime-location cleanup.
3. H4/H5 per ready responsibility: real entry redirect, authoritative readback, actual rollback/readback, re-cutover.
4. H6 daily use; H7 removal only when all rows are REQUIRED-complete, DELEGATED-proven, or explicitly OBSOLETE.
