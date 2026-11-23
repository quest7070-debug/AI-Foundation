# M1 Host Compute Lease — cooperative admission

Status: **Independent Draft source proposal, split from research PR #202; not deployed
as a globally enforced host policy.** No model launch, forced unload, original
storage mutation, provider/payment change, Native signal, or PR merge.

## Existing runtime: what we keep

Foundation already routes its local model slots through **llama-swap**
(\`LlamaSwapExecution\`), without needing a new model scheduler.
An independent shared Ollama on :11434 supports other existing clients,
including the local Qwen3.5-4B planner. These services MUST NOT be forcibly
stopped to create a large-model test slot.

The historical \`local-general\` policy aspires to 9B, but that is not evidence
the configured llama-swap slot has a valid artifact on this host. The real 9B
Ollama test used a SHA-verified *separate* inactive internal-APFS candidate.
Do not conflate these bindings or silently promote a 2B/4B fallback.

## Implemented cooperative lease

\`src/ai_foundation/host_compute_lease.py\` offers a per-UID, **OS-released**
\`fcntl.flock\` held for the duration of cooperating local compute.
The canonical lock is at
\`<real login HOME>/Library/Application Support/AI-Foundation/host-compute/compute.lock\`.
It does not honor a caller-controlled HOME override, follows no symlink for
the lock file, requires a private owned 0700 parent/0600 regular file, and
blocks on demand only within a bounded interval.

\`scripts/host_compute_lease.py run --max-wait-seconds N -- COMMAND...\`
execs a command under the **same lock descriptor**, with no orphan lock-keeper
process. Nonzero exit is used for contention (75) or invalid lock state (76),
never a fabricated CI pass. An inherited descriptor can be reused for
nested Foundation inference calls *only when its inode and owner match the
actual canonical lock*. The underlying OS frees the lock on exit/crash.

Current participating paths in PR #202 source:
- Foundation \`llama-swap\` \`chat()\` and \`chat_payload()\`: acquire during
  the HTTP exchange, release afterwards. Existing model selection unchanged.
- \`GuardedInferenceService\`: resource lock busy/error returns
  \`LOCAL_RESOURCE_DEFERRED\` and does not mark a model unhealthy or fall
  through to paid/cloud routes.
- 9B no-replay experimental continuation: hold one lease around the entire
  bounded trial; *also* retains the strict, independent macOS RAM/CI/swap
  pre-admission. No new 9B calls have been made.
- Foundation CI's resource-heavy unit-test step: bounded lease wait.
- Development-autonomy daily local Ollama 4B planner command and the local
  HumanModel synthetic Ollama smoke command: bounded lease wait.

## What this does NOT enforce

**File locks are cooperative**. An independent Ollama client or an unrelated
GitHub Actions workflow does not follow this lock automatically. In particular,
the updated Foundation CI lease currently protects the main pytest step,
**not** the entire multi-step CI job or all self-hosted workflows. CI may still
install dependencies, compile or exercise other probes outside this lease.
A participating request must additionally check actual provider/CI state,
unified-memory admission and storage locality before loading a large model.

Thus, a PASS from the lock alone does **not** mean 9B is safe on the M1.
The separate \`host_capacity_admission.py\` is an intentionally conservative
source-only check: \`free+inactive+speculative\` physical pages are only an
**optimistic upper bound** for reclaimable memory. In a real M1 check that
upper bound was ~2.86 GB against a declared 9B+overhead+reserve need of
~9.77 GB. It correctly DEFERRED the 9B run, without model invocation.

## Current acceptance and remaining milestones

1. Lock contracts: separate FDs and subprocesses conflict, release on crash,
   reject symlink and unsafe permissions, support bounded wait and nested
   inherited-FD reentry.
2. Real M1 Foundation CI: verify full suite, including new lock integration
   and \`LOCAL_RESOURCE_DEFERRED\` behavior. No production source adoption
   before successful readback and review.
3. Expand participation to **every** local-compute-producing M1 workflow and
   existing Ollama client. Validate cross-workflow contention with a real
   **synthetic no-model job**, not by inducing paging on 9B.
4. For reliable whole-CI-run exclusivity, integrate the admission at the
   self-hosted runner job boundary after reviewing the runner ownership
   and cancellation semantics. Step-scoped locking alone is insufficient.
5. Use llama-swap as the single Foundation slot lifecycle owner and persist
   a bounded model-residency plan under host authority. Do not add a new
   Foundation-owned general model scheduler.
6. Only re-evaluate 9B host placement after physically safe capacity and
   resource coordination are measured. If not feasible on 16GiB M1, keep
   deferred; assess another *existing* suitably provisioned host separately
   without changing LOCAL_ONLY role/capability authority.

No complete 9B performance A/B is claimed. Both FV05-01 plain and schema
answers are frozen; the other four original requests remain NOT_RUN.
