# Bounded text artifact generation

Scope: ordinary product capabilities, separate from Paseo Native development.
Audit basis: main `6bd2d7982f4480a1eb6bab054a09cb2e8beda2e9` and the open-PR
inventory read on 2026-11-04 JST. PR #8 was independently inspected at
`e3e6db1f5154cc14f1ae682d3b9b7ca4d8e10d22`; its source, installed releases,
signed contracts and Native attempts are outside this change.

## Selection from unfinished areas

| Area | Evidence at audit | Development decision |
| --- | --- | --- |
| Artifact generation and receipt | `artifact.py` only defines the generic create/validate protocol; `AutoCapabilityAgent` exposes file reads, while `CapabilityRequest.file_write_root` and Guard-backed `ScopedFileExecution.write` already exist | Implement the missing bounded text-output adapter and Agent tool using existing owners |
| Download into the original conversation | No product artifact delivery adapter was found in the source tree; a relative output target is not a download URL | Keep delivery explicitly unaccepted; inspect LibreChat's existing authenticated file-serving contract before connecting it |
| PDF/Office input | Main includes `STANDARD_DOCUMENT_HANDOFF_20261102.md`, attachment lookup and the document parser probe | Preserve that implementation; parser/browser acceptance is distinct from output generation |
| Personal judgment and memory | Open PR #166 contains owner-approved local-only HumanModel references and records actual M1 chat evidence | Avoid a second memory store or competing reference integration |
| Research handoff | Open PRs #55/#145/#149 cover Muse intake, evidence-gated delivery state and File Provider reading | Avoid duplicate dispatch/state mechanisms |
| Native self-development | Open PRs #175/#178 cover the existing failed attempt, Guard transport and exact release cessation | Keep this product-capability patch independent of the active Native recovery scope |

## Existing boundaries reused

The host must supply an authenticated `owner_id`, absolute `file_read_root`,
and an explicit `file_write_root` nested inside it. The Agent exposes
`create_text_artifact(target, content)` only for that envelope. Read-only,
attachment-only, anonymous and long-running chat contexts do not expose it.
Direct method calls recheck the same requirements. Attachment grants are not
copied into the output request.

`CapabilityExecutor.execute_text_artifact` constructs the existing FILES
adapter. `BoundFiles` uses its **write** execution for both target resolution
and readback, including when the write root is narrower than the read root.
Existing path confinement, protected-resource checks, Guard policy/privacy,
cancellation, durable effects, target leasing and reconciliation remain in
force. No filesystem writer, scheduler, registry, model or format-rendering
engine is introduced.

Supported output is UTF-8 `.txt`, `.md`, `.csv`, `.tsv` and `.json`, limited to
1 MiB of encoded text. An extension does not attest syntax or document quality.
Only a `VERIFIED_COMPLETE` Guard result followed by matching current readback
returns `verified=true`, a relative target, `utf8_sha256` and `utf8_bytes`.
These describe observed text, not binary file format validation, file metadata,
user delivery or the existence of an authenticated download URL.

One normalized target has one effect identity per host run. Run identity stays
the host run, preserving cancellation and approval lookup. Changed content
cannot replace an existing effect or its reconciliation recipe. A repeated
ambiguous write reaches the existing observe-only Guard reconciliation path;
it does not mint a new effect. A cached Guard success is rechecked against the
current file, so subsequent change/deletion cannot produce a fresh success
claim. Without a host run ID, each Agent instance receives a distinct identity;
cross-process recovery requires the caller to preserve the real host run ID.

## Validation and promotion

Initial adapter focused verification: 60 passed across text artifacts, FILES scope,
existing generic artifacts/computer action, Agent selection and capability
execution. Tests use actual temporary files and the real Guard; restart tests
reopen the existing SQLite Guard and reconciliation stores. A deterministic
Pydantic-AI FunctionModel exercises tool selection through file creation and
the returned metadata, with external model requests disabled.

Additional cases cover lost acknowledgements, cached-result mutation/deletion,
content identity conflicts, original host-run cancellation, policy denial,
protected resources, traversal/symlink escape, encoded-size limits, read-only
and attachment-only requests, inherited attachment isolation and content-free
activity/trace cleanup.

Effect identity is read through the existing Guard boundary's read-only
`get_effect` accessor, including `ObservedGuard`; the artifact adapter does
not depend on Guard storage/state implementation attributes.

The existing self-hosted M1 Foundation CI collects this test file. CI success
is source/fixture acceptance only. Production composition currently grants no
file-write root: `capability_factory.py` is unchanged. This patch does not
activate production output writes, publish files, create a download endpoint,
restart services, invoke a model/provider, add models, send a Native signal,
merge main or modify another open PR.

## Backend concurrency and restart continuation

The owner deferred LibreChat integration on 2026-11-04 JST. No response export,
file registration, download route or LibreChat patch is included in this
continuation. Delivery remains deferred; current work stays in the existing
artifact/FILES/Guard backend.

The earlier adapter's identity lookup and reconciliation-recipe registration
were not one transaction. Eight simultaneous requests reproduced one real
file write but a recipe containing a losing request's different text. A
second reproduction cached PLANNED in one Guard instance while another
instance completed the same durable effect; the stale reader returned
EFFECT_STATE_CONFLICT instead of observing the current VERIFIED result.

The adapter now uses the existing `exclusive_file_lock` around identity
lookup, recipe registration, Guard execution and current readback. The lock
inode sits beside the normalized target with a SHA-256-derived `.lock` name;
overlapping host scopes share it and independent targets remain concurrent.
This is supported-host metadata, not another effect lease or scheduler. Its
empty inode is retained to avoid split-inode locking and symbolic links are
rejected by the existing no-follow lock primitive. Target directories must
already be host-provisioned. This is a single-host transaction boundary, not
a distributed lock or OS containment claim.

Guard execution now reads current durable effect state before deciding
between execution and reconciliation, instead of preferring an older
in-memory phase. Existing policy, cancellation, claims, leases and effect
verification remain enforced.

Validation adds ten regression scenarios: simultaneous matching requests,
conflicting text, overlapping scopes, independent targets, cached phase
refresh, separate OS processes, retained/no-follow lock inode, protected and
read-only refusal before creating lock metadata, and a child
process exiting immediately after the real file write. Recovery reopens
SQLite, waits for the existing claim to expire if needed and verifies the
file without another write. Latest focused artifact/FILES/Guard/store/trace
verification: **139 passed**. The existing full M1 CI independently checks
the source revision; no production activation is implied.
