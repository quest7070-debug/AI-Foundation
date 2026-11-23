# Foundation development frontends: single authority, minimal OSS integration

**Owner:** existing Foundation Harness / Guard / Canon. **Date:** 2026-11-11.

## Architecture and non-duplication

| Responsibility | Existing implementation | Adoption decision |
|---|---|---|
| Job, role, source approval, independent tests and Draft delivery | `HarnessRoleRuntime`, existing development host, Guard and Canon | **KEEP**; no second scheduler, router, model manager or PR publisher |
| Codex OSS with shared local 9B | `src/ai_foundation/codex_oss9b_port.py` → existing `HostBoundHarnessAgent` | Optional **source integration**, not live accepted |
| Exact Codex binary/9B eligibility | `scripts/m1_codex_oss9b_host_admission.py` → existing `HostComputeLease` and `klm_compute_admission` | **KEEP** the shared compute lock, immutable CLI/model SHA and CPU/RAM admission |
| macOS kernel isolation | `scripts/m1_codex_oss9b_seatbelt_probe.py` | **KEEP** fixed WAN denial / only local Ollama; host must verify actual descendant boundary |
| OpenCode offline CLI and synthetic host stdio | **PR #512** `opencode_isolated_cli`, `opencode_live_stdio` | **REUSE**, do not create another adapter here |
| OpenCode Console Free and other external models | **PR #512** exact-model gate and account review; **PR #478** free service registry / durable attempts | **HOLD** until current account-specific no-charge proof and Guard release; distinct development lease, no 9B lock while remote models run |
| Other evaluated OSS | ToolHive/Hatchet/Cedar existing; ripgrep #481; KLM discovery via LLMPerks | Keep own existing owners and acceptance evidence; no speculative duplicate daemons |
| Google Jules | Retired by #512 | **DO NOT DISPATCH** |

Codex OSS (Apache-2.0 upstream `openai/codex`) and OpenCode are **execution frontends**, not billing or provider grants. Ollama is a local model provider; a public Free model is a separate account-bound cloud route. Existing 4B experiments do not carry over to this 9B-first development path.

## Small runtime contract

- Trusted host selects role and exact CLI binding. The Codex adapter constructs only `sandbox-exec -f <reviewed-profile> <pinned-codex> exec --ephemeral --oss --local-provider ollama --model qwen3.5:9b --sandbox read-only --skip-git-repo-check <trusted-instruction>`. This has no credential fallback, provider selection by model output, session archive, tool/write grant or global user Codex home.
- Host independently checks installed CLI SHA-256 `61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70`, local 9B digest `56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90`, real active load, **existing shared compute lease**, CPU/memory pressure, host kernel egress denial and owner data isolation. This check is necessary, **not** permission to publish work.
- Only existing Harness/CODE local reviewer, fixed tests, Guard/Canon and Draft PR issuer can accept output. No new runner, receipt database or repeating model task is introduced by this PR. Free external requests continue to use PR #512/#478's separate durable attempt ledger, exact-model egress, owner account grant and no-charge conditions.

## Immutable evidence / failures

- PR #512 [M1 #42927600915](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42927600915): OpenCode **2.2.5** pinned ARM64 Docker offline public fixture and native host stdio **synthetic** accepted; **0 external provider calls**, **0 billing attestation**. Existing accepted built-image ID `sha256:2dfbc55b78a637e2bd078743df89922847e50671348df0c8f2b7f1657351c4d4`.
- PR #627 [M1 #42952429511](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42952429511): pinned Codex CLI read-only `exec --help` under Seatbelt and cached prior OpenCode image `run --help` under Docker network-none succeeded without a model. Startup samples **99ms vs 922ms** are *not comparable* due to native macOS vs Linux VM.
- PR #627 [M1 #42948963564](https://github.com/quest7070-dev/AI-Foundation/actions/runs/42948963564): a separate **consumed** fixed public Codex→9B task **timed out at 180s**. Independent private receipt `BLOCKED / CONSUMED_UNVERIFIED`. It must never be replayed; deleting its one-off GitHub source does **not** remove, amend or authorize the host receipt. Whether the model received/partially processed the request remains unknown. There is **no accepted Codex real-9B completion**.
- Owner's actual OpenCode v2.2.5 read-only budget record was **one selected 49-model $0 policy** (`coverage=models picked=True`), **not** the intended entire-workspace All-spend $0. PR #512 rightly refuses that as blanket no-charge evidence; current Billing/Go state remains unattested. Existing PR #512 remains fail closed for provider calls. Jules remains retired.
- CI in this Draft validates **only** the optional role binding, pinned local admission and kernel policy; all model-free. The main/full suite, installed Operator, existing 9B worker and KLM deployment are not changed.

## Future acceptance (existing routes only)

1. For **local Codex**, use a *new* source-bound public task identity only after real host admission and strict egress/timeout diagnosis. Do not resurrect the consumed one-shot script or manufacture a successful reply.
2. For **OpenCode**, reuse #512's real pinned native offline CLI and host stdio. Before any Console request, independently read effective selected-account $0 workspace policy, auto-recharge, Go Extra Usage, selected Free model/origin and Guard release. On 402/403/429, stop without paid fallback or retry.
3. Accept productivity improvements only on independently verified **completed** edit→test→review→Draft work with a measured provider, cost=$0 and exact source/host readback. Do not compare CLI help startup time as developer throughput.

**Never:** merge `main` by this work, use Kandev, start 4B/a second 9B, kill an existing Ollama/user job, introduce cloud billing risk, emit a Native signal, or create duplicate background queues/servers.


## Ownership correction (2026-11-11)

The official DSH→OpenCode ACP staging, host-only dynamic candidate ordering, and free-model/Guard integration are maintained **only in OpenCode owner Draft [PR #512](https://github.com/quest7070-dev/AI-Foundation/pull/512)**. Removed the earlier duplicated `dsh_opencode_acp.py` and focused test from Codex PR #627. This PR exclusively owns Codex OSS → local 9B role, pinned Seatbelt and existing lease. No ACP or cloud model work runs here.
