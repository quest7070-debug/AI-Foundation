# Local Model Role Policy

Status: ACTIVE ROLE CONTRACT — reconciled with the owner's single-9B / optional-Strata policy; not an installed-model inventory
Updated: 2026-11-15

## Current owner policy

M1 uses **one local LLM: the approved 9B**. CHAT, local development, private reasoning and independent verification are work roles sharing that model and the existing compute lease, not separate model-residency requirements. Do not install or keep Ornith, Granite, 4B or a VISION model resident to fill historical slots. Independent review requires separately checked evidence; it does not require a second resident model. This policy does not claim that any configured artifact, endpoint or VISION capability is installed or accepted.

For exact host-reviewed PUBLIC_NONSECRET work with existing egress and role admission, prefer the available, authenticated, capable MainPC Strata route for coding, public text analysis/summarization/planning, public error triage and preliminary public code review. HumanModel, private KLM/context, secrets, data-sensitivity decisions, error recovery and final independent M1 acceptance remain on the same-host M1 boundary. A remote-local model is still another host and cannot receive LOCAL_ONLY data. Public CHAT may use an already-online M1 9B when fresh comparative completion evidence proves it materially faster; missing evidence retains Strata-first. CODE remains Strata-first within its admitted scope.

MainPC is optional. Absence, authentication failure or a failed request does not block independent M1 work or authorize automatic wake, model loading, process eviction, payment or a new scheduler. Reuse the existing admitted free routes and M1 fallback: current routing prefers online M1 for public CHAT when MainPC is absent, existing admitted free routes for public CODE when MainPC is absent, and online M1 after a failed Strata attempt in either function. Preserve within-task exclusion and explicit failure when no eligible capacity exists.

The single-local-LLM rule does not limit the number of already-authorized browser/external AI routes. Independent external tasks may overlap where existing host, privacy, no-charge and resource admission permit; local 9B and heavy M1 work retain their shared resource gates. Do not convert this policy into an unconditional external-egress grant or a new parallel runtime.

Current source owners are `model_work_roles.py`, `compute_routing.py` and `inference_service.py` under `src/ai_foundation/`. Public Strata roles were merged in [#1163](https://github.com/quest7070-dev/AI-Foundation/pull/1163); optional-MainPC fallbacks in [#1215](https://github.com/quest7070-dev/AI-Foundation/pull/1215) supersede the conflicting Draft #1193. Source merge is separate from installed configuration, live capacity and caller E2E evidence. No model or capability is admitted merely by this document.


## Development execution preference — 2026-11-15

Continue implementation through the existing PC-side Foundation development path wherever admitted capacity is available. Use authenticated MainPC Strata first for reviewed public implementation; retain M1 for private work, recovery and final independent acceptance. GitHub remains source storage and delivery, with bootstrap transport only when the connected MCP lacks the necessary operation. Keep validation proportional to the change: focused regression checks and real installed-path acceptance; run broader checks only when required by affected contracts or an unresolved failure. Do not rerun already verified work or add standing maintenance for its own sake. MainPC remains optional under the fallback rules above.

## Historical role-slot proposal and host observations — superseded

The following 2026-10-07 proposal and 2026-11-03 inventory note are retained as dated history, not the current M1 model roster, replacement requirement, installed inventory or routing authority. The current owner policy above takes precedence over every slot/count statement below.

Local models are stable capability slots, not a collection to minimize by model count. Replacement requires slot-specific evaluation and must preserve fallback and independent-review semantics.

### Purposes

Local compute has two purposes. First, it is last-resort inference insurance: after eligible free/cloud CHAT routes fail or exhaust, local-general remains the terminal CHAT standby. LOCAL_ONLY policy may require local compute earlier and never widens to cloud merely because local capacity is unavailable. Second, specialist slots perform dedicated local work even when cloud capacity exists.

### M1 slots

- local-general = Qwen3.5-9B: CHAT / GENERAL PURPOSE; terminal CHAT insurance and general LOCAL_ONLY inference.
- local-code-agent = Ornith-1.5-9B: CODE GENERATION / DEVELOPMENT AGENT specialist; local implementation/agent work and development-capability insurance. It does not become the normal Foundation CODE tool topology merely because it can code.
- local-code-review = Granite-4.2-8B: independent CODE REVIEW / re-evaluation specialist. Independence from the code-agent slot is intentional; do not consolidate both roles into one model solely to save storage or RAM.
- local-vision = Qwen2.5-VL-3B-Instruct: IMAGE ANALYSIS / VISION; current local VISION primary and authorized LOCAL_ONLY image path.

### Replacement

Foundation routes stable slots; model names are replaceable implementation details. A replacement must pass slot-specific real-host A/B evidence plus required protocol/tool/vision behavior. Newer release or aggregate benchmark alone is insufficient.

local-general may gain VISION only after measured image quality, latency, stability and LOCAL_ONLY acceptance. Retiring local-vision remains a separate decision because multimodal consolidation must not reduce CHAT-insurance reliability.

Remote/main-PC models supplement M1 insurance; they do not erase it. The PC has an independent power/network/runtime failure domain. Remote models use the same semantic slots or explicitly narrower host-owned roles.

Known-bad local bindings enter bounded cooldown and fall through only to another genuinely capable authorized binding. Exhaustion is explicit. No incompatible substitution, paid fallback, authority widening or remote-machine lifecycle authority is implied.

### Main-PC accepted specialist — 2026-10-07

`local:mainpc-strata:code-agent` is an accepted remote-local specialist backed by Strata on the direct-link Main PC. Current observed runtime model is `qwen3.8-flash-next-coder-iq1_m` (text-only, context 32768). Its role is stronger optional CODE/development-agent local compute. It is not the sole terminal fallback and does not remove the M1 Ornith code-agent insurance or Granite independent-review slot. Host wake/power management is external to Foundation inference authority.

### Current M1 inventory correction — 2026-11-03

The historical local-general -> Qwen3.5-9B mapping describes an intended role;
it does not prove installed weights. Current host verification found the
configured 9B artifact absent and the alias unloaded after upstream launch
failure. Do not infer availability from /v1/models alias advertisement alone.
9B restoration or installation is not a prerequisite for HumanModel source
publication, owner binding, or the existing-model Cognee pilot. No new model
installation is authorized. Existing Ollama candidates must be verified through
actual local inventory; project indexing does not replace Foundation's general
inference routes or select the output LLM.

