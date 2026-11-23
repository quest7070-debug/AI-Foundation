# HumanModel evidence in ordinary chat

## Implemented path

The ordinary `AutoCapabilityAgent` can expose `human_model_context(scope,
offset=0)` when a host binding exists for the server-authenticated owner.
Pydantic AI owns tool selection and scheduling. Foundation creates no semantic
request classifier, personal evidence store or learned personality.

The host factory loads `human-model-bindings.json` from the existing Foundation
data root. Missing configuration leaves the tool disabled. No config, database,
view, private evidence or model is automatically created or imported.

Each read validates owner and the binding's explicit scopes, then calls Guard
preflight before the existing HumanModel-owned source adapter. The adapter
opens only the verified external ledger, read-only, and requires an approved,
fresh `audience=foundation` view with its privacy ceiling. It returns a single
SQLite read-transaction snapshot containing view revision, source URI/revision,
date, kind, dispute status, content hashes and a snapshot digest.

The bounded agent interface returns at most 32 records / approximately 32 KiB
per call with explicit pagination/omission. It neither clips source text into
an apparent complete record nor silently substitutes a personality summary.
The legacy `read_view` list API retains its existing record shape.

Current explicit instructions govern the task. The model is instructed to
distinguish decisions from observations/inferences, cite evidence IDs for
material personalization, report unavailable/incomplete evidence, and treat
retrieved content as data rather than execution authority. Runtime cannot
guarantee the semantic quality of every model's conclusion; source readback
and tool authority remain mechanically enforced.

## Destination privacy

The first version uses a deliberately explicit route policy:

- `restricted` / `private` binding: the **whole bound owner's agent turn**,
  including the initial request and every tool follow-up/fallback, uses the
  canonical router's `local_required=True`. A nonlocal route result is rejected
  before cloud construction. No local route means a visible failure rather
  than private-data cloud fallback. Constructor checks prevent registering a
  private context on an unconfined model adapter.
- `shareable` binding: only shareable rows may be read. Existing ordinary
  eligible routes remain available; no paid provider is added or enabled.

This is not an implicit grant to export private records to a cloud service.
More selective disclosure requires a separately approved shareable view or an
explicit future disclosure contract. It does not arise from a model's claim
that summarizing a private record makes it public.

Host binding changes are explicit policy changes. Do not downgrade/remove a
private-enabled owner's local-only policy while resuming histories that contain
private prior answers without separately addressing those histories. The
feature does not scrub or relabel already stored LibreChat conversations.

## Host configuration example — not installed

```json
{
  "version": 1,
  "bindings": [
    {
      "owner_id": "SERVER_AUTHENTICATED_OWNER",
      "root": "/Volumes/EXTERNAL/HumanModel",
      "view_id": "ALREADY_APPROVED_CURRENT_VIEW",
      "scopes": ["work"],
      "max_privacy": "private"
    }
  ]
}
```

The actual owner must come from the established server identity path, not model
arguments. Root/view/scopes must already exist under HumanModel authority.
No values in this example establish real-owner authentication or view approval.
The tool arguments contain only scope and page offset; they cannot choose an
owner, storage root, executable adapter, view, privacy grant or write action.

The runtime reuses `experiments/human_model/foundation_readonly.py` in a fixed
repository-owned package namespace without changing `sys.path`. A release that
enables this feature must include that owner adapter plus
`human_model_ledger.py` and `storage_location.py`; missing owner code blocks
activation instead of creating an alternate reader or internal-disk fallback.

## Validation and deployment state

Synthetic tests exercise the real Pydantic Agent/tool loop against a real
temporary HumanModel SQLite ledger: current evidence/citation, superseded
decision update, stale-view refusal, missing-view response, owner/scope/Guard
denial, digest corruption, bounded pagination and private local failure with
zero cloud calls. Shareable routing cannot read private evidence. Existing
ordinary-tool/model-routing and legacy read-only adapter regressions remain.

Model responses in these tests are deterministic fixtures: this is proof of
the source/tool/privacy connection, not real-model reasoning quality or actual
private-data use. No real owner binding or production service change has been
performed. M1 source acceptance runs through GitHub CI; runtime activation
remains a separate canonical release/readback step using existing views.

PR #8's source-pinned Native work remains untouched. During its eventual
three-way integration preserve its `work_producer` argument and Native
registration alongside these additive optional context/model arguments. Do
not edit that branch or restart its pinned host to incorporate this feature
while its existing review is pending.

## Real M1 activation checkpoint

Read-only workflow run `41458800852`, source
`d28b42b060a33c8a9db50ccff4694444749e1a17` (PR #116), completed on
2026-11-02 UTC. It found one existing external HumanModel ledger and one
server-side LibreChat owner, but **zero evidence records and zero views**.
No approved nonempty source snapshot exists to bind. The canonical Operator
launch definition identifies installed source without the context module or
binding loader; no binding configuration exists there either. Inspection of
installed files is not proof of what an already running process has loaded.

Consequently real personalization remains blocked. An empty ledger must not
be filled with invented preferences, inferred consent, or an automatic raw
Inbox import merely to make activation pass. HumanModel's existing development
stream owns evidence ingestion and explicit scoped view definition/rebuild.
Once that source exposes a fresh, nonempty Foundation view, recheck readiness,
bind the authenticated owner privately on the host, and integrate #114 through
the canonical release process while preserving concurrent Native work.
Only then verify a real ordinary-chat read and private local routing.

The probe exposes counts/booleans/blocker codes only; it performs no import,
view creation/rebuild, binding write, service restart, model invocation or
Native dispatch. A successful probe run means the diagnosis completed, not
that activation succeeded. Foundation's next independent feature priority
remains usable artifact production; do not replace missing HumanModel source
work with another Foundation personality store or repeated readiness tests.
