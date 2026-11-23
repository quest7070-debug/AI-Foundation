# KLM runtime admission and redundant-work pruning — decision record (2026-11-08)

Canonical source: `quest7070-dev/AI-Foundation`.
Scope: only the KLM GUI-owner tick and its **already leased** local 9B admission.
This document is evidence of a source change, **not** a production acceptance or
authority to deploy, retry historic work, access private source, or change the Guard.

## Evidence / why this was necessary

- Runtime code before this change: `scripts/klm_drive_host_tick.py` rejected
  the presence of **any** `Runner.Worker`, `llama-server`, `llama-cli`,
  `activation` process and **any** loaded Ollama model in either of two ports.
  That equated an idle loaded model or a light GitHub job with active inference.
- Real-M1 fixed read-only #399 observed 1 Runner.Worker, 1 llama-class process
  and 1 resident model while old failed Work remained 3 and retry intent PLANNED
  1. This alone does **not** establish why a KLM due tick deferred; the latest
  report was `NOT_DUE` and not a fresh inference attempt.
- Previous GUI KLM release `4e71e42e` is immutable and remains unchanged until
  a separately reviewed pinned release is APPLIED and independently read back.

## Explicit keep/delete decisions

| Existing predicate or processing step | Decision | Reason / replacement |
|---|---|---|
| GitHub `Runner.Worker` **presence** veto | **REMOVE** | CI process existence does not establish contention or inference demand; CPU pressure check substitutes |
| Ollama `/api/ps` **model residency** veto, two HTTP calls | **REMOVE** | Loaded model is not proof of generating; two potentially failing HTTP probes per candidate are overprocessing |
| `llama-server` / `llama-cli` / generic `activation` **presence** veto | **REMOVE** | May be sleeping/resident; detect sustained CPU and available RAM instead; no speculative GPU-idle assertion |
| Repeated private Keychain `token.available()` call in one tick | **COLLAPSE TO ONE** | Exactly same binding, no write; does not weaken token refresh and OAuth scope checks on actual authenticated reads |
| Read-only M1 bridge's independent `ps` plus two Ollama `/api/ps` snapshots | **REMOVE** | It repeated the obsolete process/residency veto *in the observer*, could mislabel a healthy KLM as `BLOCK_AT_PROBE`, and consumed runner/HTTP work; export only the sanitized verdict from the actual GUI-host report, or `UNAVAILABLE` on old releases |
| Unconditional GitHub development-Issue read at *start of every* Drive tick | **MAKE LAZY** | A Drive-only/NOT_DUE/audit tick does not need development priority for compute it never requests; query only when actual IdleKlmWorker Work is about to run; distinguish `NOT_EVALUATED` from idle |
| Repeated `IntakeQueue(state)` allocation in same host path | **REUSE** | Both retry/9B paths operate on the same existing queue; does not create a new database, worker or timer |
| Host compute gate when no candidate work | **KEEP LAZY** | Existing IdleKlmWorker calls it only after a source candidate and shared lease; no background sampling loop |
| `HostComputeLease.hold(max_wait_s=0)` | **KEEP** | Single-owner Foundation compute arbitration and no stealing live development compute |
| Development readiness check before and after lease | **KEEP** | Fresh ready-Issue / uncertain result evidence can change while waiting for lease; prevents stale permission to run |
| Atomic Work claim, FAILED retry history and source revision/hash/bytes revalidation | **KEEP** | Prevent duplicate effects, source substitution and post-inference source drift; these are safety not redundant work |
| Source re-read before final VERIFIED | **KEEP** | Mandatory TOCTOU guard during asynchronous inference |
| Explicit owner/Guard approval and private-source boundaries | **KEEP** | Never authorize owner writes merely because resource was available |
| 900-second schedule / incremental Drive scan / recurring audits | **KEEP** | Already deployed and used; no extra scheduler or repeated full historical scans added |
| Hard 240s 9B deadline and pinned model identity | **KEEP** | Avoid hanging tasks, accidental model substitution and unbounded generation |

## Replacement resource gate

`src/ai_foundation/klm_compute_admission.py` is called **only after obtaining
the existing compute lease**, not on every Drive poll. It checks:

1. `os.getloadavg()[0]` against `0.85 × os.cpu_count()` logical CPUs. If
   sustained system load reaches that threshold, defer `CPU_PRESSURE`.
   Load average is an imperfect one-minute indicator, not instantaneous CPU%.
2. One bounded macOS `/usr/bin/vm_stat` sample: free + inactive + speculative
   pages must total at least **4 GiB** (do not count purgeable twice). Otherwise
   defer `MEMORY_PRESSURE`. This is a conservative, tunable *admission
   headroom*, not proof the 9B model will fit without swapping.
3. Missing, invalid or timed-out observations defer `RESOURCE_UNKNOWN`.
   This is a fail-closed default, not a false `AVAILABLE`.

The private KLM status report gains only `compute_admission.state` and a
fixed reason code (`AVAILABLE`, `CPU_PRESSURE`, `MEMORY_PRESSURE` or
`RESOURCE_UNKNOWN`), or `NOT_EVALUATED` when no lease-backed check took place.
Development observation is likewise `NOT_EVALUATED` until a candidate worker actually checks development readiness; after that its actual observed fields are reported. Do not infer `complete=true` from a no-work tick.

The fixed read-only M1 bridge returns this same allowlisted verdict from the
stored GUI report; it does not independently poll processes or Ollama. Until
the new GUI release is applied, the bridge truthfully returns `UNAVAILABLE`.
Never include process argv, source text, model names, raw token or personal data.

**Limits:** `vm_stat` is not a GPU inference activity API. An *unmanaged*
external Ollama client may not honor the shared Foundation lease; neither
resident model nor idle load proves that no external GPU inference exists.
Do not claim universal exclusion. A future shared Ollama request coordinator
requires its own design and live acceptance; do not invent one here.

## Acceptance and rollback

1. Synthetic unit tests prove idle light CI/model residency is no longer
   itself a veto, high CPU, low RAM, invalid or timed-out probes defer, and
   no private data is surfaced.
2. Real M1 CI of the exact change must be green; old KLM semantic, source,
   ownership and Native/Guard tests remain enabled.
3. Integrate source to main only after CI. **Do not equate merge with deployment.**
4. Separately pin and deploy the reviewed commit to the KLM-only GUI service
   with the existing rollback contract; keep all other services unchanged.
5. Collect successive due `CURRENT` cycles and evidence of retry-intent
   terminal status, actual 9B VERIFIED and relation/placement results.
6. If resource pressure remains the reason, diagnose measurements before
   lowering thresholds; if a source/auth/Work gate fails, do not bypass it.

**Decision:** relax false-positive resource *presence* checks; retain strong
ownership, lease, development priority and source-revalidation barriers.
