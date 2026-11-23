# Agent boundary

AgentPort is a replaceable execution/reasoning boundary. Agents may interpret instructions, reason, and propose tool work, but they do not own Canon, Privacy, Authority/Approval, Budget, external Effect state, credentials, or Verification. Those remain Guard responsibilities.

The first adapter targets Pydantic AI v2. Pydantic AI is MIT licensed and its stable v2 line is suitable as an adapter dependency, not as architectural authority. Pin an exact tested version before production integration. Agent tools that can create external effects must be exposed through Guard-controlled ports rather than handed unrestricted credential-bearing clients.

## Verified implementation
Pydantic AI slim is pinned to 2.44.0. A real library E2E uses its TestModel through PydanticAgentPort. The default AgentPort construction exposes no tools; model output therefore remains a proposal and cannot create an external effect. Effect-capable tools must be added later only as Guard-mediated wrappers.

## Guard-mediated effect gateway
GuardedToolGateway is the first effect-capable agent-facing boundary. It constructs a TaskPlan and delegates execution to GuardCore; it has no direct filesystem/MCP write path. Unit tests prove canon mismatch and high-impact approval stop execution. A live M1 E2E proves Gateway -> Guard -> ToolHive -> real MCP write -> independent readback -> durable VERIFIED.

A real Pydantic AI function-tool E2E now calls GuardedToolGateway. TestModel-generated tool arguments are accepted only when they match the bound canon revision; otherwise Guard returns WAITING_HUMAN and the effect count remains zero. This exposed an important property: model-generated authority fields must not be trusted as authority. Future production wrappers should bind canon/run identity outside model-controlled arguments rather than asking the model to supply them.

## Host-bound authority
BoundGuardedWriteTool removes run_id, canon_revision and paid_cost from the model-visible callable signature. Trusted host code binds those values before tool registration; the model sees only target and content. A real Pydantic AI function-tool test verifies the resulting Effect uses the trusted run/canon values and reaches VERIFIED.

## Bound authority tool schema
BoundAgentTools removes run_id and canon_revision from model-visible tool parameters. These values are injected from trusted execution context outside the model. Real Pydantic AI TestModel execution confirms the model-visible write schema contains only target/content and the resulting durable Effect uses the trusted bound run identity. A direct TestModel-to-real-filesystem E2E is intentionally not claimed because TestModel synthesizes arbitrary target/content values; the already-verified real MCP gateway E2E covers the downstream boundary independently.

## Target capability binding
ScopedAgentTools adds a host-bound WriteCapability. The model still sees only target/content, but the trusted host binds an allowed target root. Canon/run identity and target scope are therefore outside model authority. Parent traversal and absolute paths outside the bound root fail before Guard/ExecutionPort and create no Effect. This complements, rather than replaces, Guard policy and ToolHive mount/path isolation.

## Read versus effect capabilities
CapabilityAgentTools separates observational read from effectful write. Read is root-scoped and calls ExecutionPort.observe without creating durable Effect state; write remains root-scoped and must cross Guard, producing durable Effect/Verification state. Model-visible schemas contain only read(target) and write(target, content); run/canon/scope stay host-bound. This is the baseline capability shape for future specialists.

## Pydantic capability flow E2E
Real Pydantic AI TestModel runs now cover read-only, write-only, and read-then-write tool selection. Relative model targets resolve inside the host-bound capability root; absolute/traversal escapes remain denied. Read creates no durable Effect; write alone crosses Guard and reaches VERIFIED. The read-then-write run therefore records only the write Effect.

## Generic compute and first specialist
COMPUTE operations are not model-selected authority. FixedComputeTool binds an approved operation (currently summarize) in host code and exposes only payload to the model. A real Pydantic Agent test confirms this path. TextAnalysisSpecialist is the first narrow specialist boundary proof and consumes this capability rather than owning execution authority.

## Run and effect identity
One Agent run may own multiple external Effects. run_id remains trusted parent authority/cancellation identity; effect_id is a separate host-generated per-effect durable identity. Model-visible tools do not accept either field. Guard effect state, claims and budget reservations use effect_id, while run-level approval/cancellation continue to use run_id. Regression tests cover two writes in one run and same-effect replay idempotency.

## Protected local-model control plane
Developer/Agent authority must treat the local model control plane as outside its mutable workspace. This is an environment capability boundary, not a prompt instruction.

The protected set covers four mutation classes:
1. model weights / model caches;
2. model registration and runtime manifests, including llama-swap configuration;
3. training / fine-tuning / LoRA-style actions;
4. active-model load, switch, replace or registration actions.

Developer may use/read a selected model through the inference boundary, but may not obtain FILES write scope rooted in a protected model/runtime tree. Model-visible tool arguments cannot expand this boundary. Any future trusted administrative model-management workflow must be a separate host-authorized capability rather than reusing Developer FILES authority.


## Daily-use tool selection

Pydantic AI owns the ordinary semantic tool-selection loop. The trusted host constructs the run-specific tool set from existing grants, and the model can call only that set. Foundation does not classify the user request into SEARCH/CODE/DATA/FILES before the Agent runs. Those names remain internal authority/execution boundaries.

A scope-free daily CHAT may expose observational SEARCH when a live SEARCH route exists. DATA and CODE tools are exposed only when the trusted request already carries the corresponding bounded operation/repository grant. FILES is exposed only when the trusted request already carries either a bounded file-read root or owner-verified attachment grant(s). These are distinct authority forms: an attachment grant authorizes only the resolved attachment and is never promoted into a directory/root grant. Tool choice never creates or expands any of these grants. Explicit capability modes remain debug/verification paths and continue to execute through the same host-bound capability executor.

## CODE execution clarification — 2026-09-23

A trusted CHAT request may carry a host-authorized repository grant while remaining semantically CHAT. When that grant exists, the Pydantic AI Agent may receive the CODE tool and choose it from natural language. The model-visible CODE call does not contain repository-root authority or durable Effect identity; those remain host-bound.

A CODE change is one host-controlled transaction boundary: authorize target -> protected-resource validation -> read -> pre-change TestPort verification -> Guard-mediated write -> durable effect/readback verification -> post-change TestPort verification. Guard `VERIFIED` proves the external write/readback effect, not that tests passed; code verification is reported separately. A failed post-test does not erase or silently roll back an already verified write.

ToolHive filesystem RW transport is not authorization. Repository containment, ProtectedResources, Guard/Cedar and host-granted scope remain the authority boundary. Explicit capability aliases are diagnostic/verification paths; normal daily-use semantic tool selection remains Pydantic AI through `foundation-auto`.

## FILES execution clarification — 2026-09-23

FILES has two host-authorized read paths. General file-area access uses a bounded absolute `file_read_root` and `ScopedFileExecution`; exact uploaded-file access uses owner-scoped `AttachmentGrant` objects resolved from trusted attachment IDs. The latter does not mint `file_read_root`, expose the host path to the model, or authorize sibling files.

```foundation-semantic
{"source":"src/ai_foundation/file_execution.py","subject":"src/ai_foundation/file_execution.py::CLASS::ScopedFileExecution@15:0","subject_kind":"SYMBOL","claim_kind":"bounded_file_read_boundary","purpose":"execute general FILES reads only within the trusted host-authorized bounded absolute file_read_root","ownership":"the trusted host owns the read root; the Agent/model may select a read only inside that already granted scope","rationale":"keep general file-area access bounded without allowing model-visible paths or tool choice to create or widen filesystem authority","failure_semantics":"requests without a valid bounded root or outside the granted root fail closed and do not gain FILES authority","side_effects":"NONE","change_impact":"changes must preserve host-bound root containment and must not let model/tool output create or widen file authority","evidence":["tests/test_file_execution.py","tests/test_files_adapter.py"]}
```

```foundation-semantic
{"source":"src/ai_foundation/capability_request.py","subject":"src/ai_foundation/capability_request.py::CLASS::AttachmentGrant@9:0","subject_kind":"SYMBOL","claim_kind":"exact_attachment_authority","purpose":"represent owner-scoped exact uploaded-file authority resolved from a trusted attachment identity","ownership":"the trusted host resolves and owns the attachment grant; the Agent/model cannot create an attachment identity, host path, sibling-file or directory grant","rationale":"allow exact uploaded-file access without promoting an attachment into general filesystem authority","failure_semantics":"absence of an owner-verified exact attachment grant does not authorize attachment access and the grant never widens to sibling or directory authority","side_effects":"NONE","change_impact":"changes must preserve exact-resource owner scope and must not promote attachment authority into root, sibling-file or write authority","evidence":["tests/test_attachment_capability_reuse.py","tests/test_vision_capability_contract.py"]}
```

The Pydantic AI Agent may receive the FILES tool only when one of those authority forms is already present on the trusted request. The model-visible FILES call cannot establish a root, attachment ownership, write scope, Effect ID or protected-resource authority. A request carrying neither root nor verified attachment fails closed.

FILES write remains a separate host authority. Natural-language write intent and ToolHive filesystem RW transport do not create it.

## Daily ambient host authority — 2026-09-26

The normal `foundation-auto` daily-use request may carry multiple pre-authorized,
host-bound capabilities while remaining semantically `CHAT`. This is host
composition, not semantic request classification. Pydantic AI decides which of
the already exposed tools to use.

The owner's daily-use policy is permissive only inside boundaries already
established and verified by Foundation:

- observational SEARCH may be available when its live route is eligible;
- the canonical AI Foundation repository may be available through the existing
  bounded CODE repository grant;
- bounded DATA and promoted contained COMPUTE backends may be available through
  their existing host-selected operations/profiles;
- bounded FILES read authority may be available only for host-selected roots or
  owner-verified attachments;
- other promoted observational capabilities may be ambient only when their
  existing host grant is independently bounded and does not widen authority.

Ambient composition MUST NOT expose raw credentials or secret values to the
Agent/model, grant access outside an already reviewed resource boundary, or
convert an unpromoted/high-authority capability into daily authority.

External or destructive mutation remains a separate effect authority. Existing
Guard/Cedar, ProtectedResources, approval, durable Effect, reconciliation and
independent verification rules continue to apply. The presence of an Agent tool
does not itself authorize bypassing those boundaries.

Prompt text, model output and tool output MUST NOT create, select, expand or
replace ambient authority. Explicit capability aliases remain
debug/verification paths and are not the normal mechanism for obtaining these
daily grants.

Do not introduce a Foundation semantic pre-router or a second generic grant
framework for this policy. Reuse `CapabilityRequest`, existing host composition,
existing bounded grants and adopted OSS boundaries. A new authority abstraction
requires evidence that these existing mechanisms cannot represent the required
boundary.

```foundation-semantic
{"source":"src/ai_foundation/capability_request.py","subject":"src/ai_foundation/capability_request.py::CLASS::CapabilityRequest@18:0","subject_kind":"SYMBOL","claim_kind":"host_authority_envelope","purpose":"carry trusted request-scoped host authority and already reviewed bounded capability grants into Agent execution without semantic pre-routing","ownership":"the trusted host owns CapabilityRequest authority; prompt text, model output and tool output cannot create, select, expand or replace its grants","rationale":"reuse one host-owned authority envelope and existing bounded grants instead of creating a second generic grant framework or semantic mode switch","failure_semantics":"missing required host authority remains unavailable and unpromoted or high-authority capabilities are not exposed merely from request or model intent","side_effects":"NONE","change_impact":"changes must preserve host ownership, request-scoped bounded grants and the prohibition on model/prompt/tool-output authority expansion","evidence":["tests/test_capability_request.py","tests/test_capability_composition.py"]}
```

## VISION daily-use authority — 2026-09-27

VISION follows the same Agent-first daily-use rule as the other observational capabilities, with a stricter attachment precondition. `foundation-auto` remains semantically CHAT at the signed outer boundary. When the trusted host has already resolved owner-authorized image attachment grants and a usable VISION execution path exists, the run-specific Pydantic AI tool set may expose VISION and the Agent may select it from natural language. The model-visible VISION call cannot create an attachment ID, owner, filesystem path, trusted root, route, credential or capability authority.

Attachment authority remains exact-resource authority and is never promoted into directory authority. Raw symlinks are rejected before path resolution in the attachment handoff and again before VISION backend invocation. Client-supplied URL/path/base64 content remains non-authoritative.

The production browser actual-pixel acceptance passed through this `foundation-auto` Agent-selected path. The explicit `foundation-vision` identity remains a diagnostic/verification alias and is not required for ordinary user interaction.
