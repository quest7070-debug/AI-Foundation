# Cognee integration — 2026-11-03 JST

## Destination and ownership

Cognee 1.6.5 supplies extraction, derived-graph persistence and retrieval.
SQLite remains the authority for original evidence, revisions, privacy,
disputes and corrections. Personal judgments are read from HumanModel;
Foundation does not maintain a competing personality store. The LLM serving
the current turn reasons over the permitted originals. Hindsight is an
alternative candidate, not a second engine automatically installed alongside it.

The extraction model selects integer IDs from complete ordered source spans.
The host copies original text and exact offsets itself. Generated relationships
remain untrusted interpretations: valid source offsets do not establish
semantic truth, consent, owner identity or approved personal facts. Automation
reports are not treated as the owner speaking. No proposal is automatically
promoted into the approved HumanModel ledger.

## Connected route

AutoCapabilityAgent exposes human_model_search(scope, query) only when its
owner-bound HumanModel context has an explicit host-configured backend.
Owner, source root, view and privacy ceiling are never model arguments.
Existing Guard authorization and a fresh approved-source read precede search.
Private-bound turns retain local-only routing.

Each derived graph is partitioned by the complete permitted snapshot, scope,
privacy ceiling, revision, engine, adapter revision and model. Physical graph
directories are immutable because Cognee stores absolute database paths.
After retrieval the source is read again; changed or stale views reject the
result. Only unchanged original records from the permitted snapshot return.

The worker calls Cognee extract_content_graph through the local compatible
JSON-output endpoint, validates its response, imports standard COGX without
vector indexing, and uses Cognee graph traversal and Japanese-aware lexical
retrieval. Cross-process search explicitly reopens the authorized named dataset.
No semantic-vector or paraphrase-quality improvement is claimed. A complete
snapshot is bounded to 32 records / 32 KiB; larger views require explicit
partitioning, never silent truncation.

## Host placement and confinement

GitHub Actions prepares pinned Cognee software on the existing external
HumanModel volume, then copies only its installed dependency set into
~/Library/Application Support/HumanModel/runtimes/cognee-1.6.5.
Originals, SQLite databases, derived graphs and private logs stay external.
The internal software receipt records dependency hash and Python version.
Foundation never imports Cognee into its service process.

The worker uses macOS Seatbelt with TCP access limited to the one selected endpoint
and writes limited to its private workspace. Provider keys, proxies and the
service environment are not inherited; timeout kills the worker process group.
Python audit checks additionally restrict TCP connects. An optional Unix-IPC
probe is diagnostic only, disabled by default: both profiles passed, so no
network-policy relaxation was adopted as a timeout fix. Fixed phase labels
provide diagnostics without recording source text or model responses.

No model weights are installed or downloaded and there is no paid/cloud
fallback. Current 9B weights are absent; the historical local-general alias
and role policy are not an installed-model inventory. There is no 9B recovery
or installation prerequisite. The acceptance workflow uses existing installed
Ollama models by default; --canonical-input is an explicit opt-in for a future
host where that model is actually installed. It never activates a model.

Project-source publication explicitly selects existing qwen3.5:4b, or 2b when
4b is absent, for the replaceable Cognee index only. This does not change
Foundation's general inference router or the LLM serving the output turn.
The worker confines TCP to its selected local endpoint. Acceptance alone does
not write enabled.json. The separate owner-authorized publication command
enables the project index only after source-grounded graph readback succeeds.

An optional explicitly managed tools/cognee-1.6.5/enabled.json can select the
backend, but model/endpoint compatibility must first be validated for the
intended production route. Backend configuration does not approve source
views, bind a LibreChat owner, deploy an Operator release or restart Native.

## Verification and remaining work

M1 run [41526709739](https://github.com/quest7070-dev/AI-Foundation/actions/runs/41526709739)
passed the current synthetic extraction -> graph -> separate-process search:
90.41 seconds build, 7.67 seconds search, one grounded interpretation.
No Raw read, production mutation, new model download or Native dispatch occurred.
Full latest-revision M1 acceptance [41527757843](https://github.com/quest7070-dev/AI-Foundation/actions/runs/41527757843)
also passed: approved-source Guard readback, stale-view rejection, corrected
source readback, plus one real Raw draft extracted into four interpretations
and retrieved in a separate process (38.81s build / 7.12s search). Raw originals
and approved production ledger were unchanged; the Raw is not approved personal
evidence. This used the existing small acceptance model. The canonical 9B route
has separate real-host acceptance [41529651535](https://github.com/quest7070-dev/AI-Foundation/actions/runs/41529651535);
its outcome must be checked independently, never inferred from the small-model run.

Local focused source checks pass 26 tests covering original grounding,
owner/scope isolation, forged-source denial and actual agent tool scheduling.
An optional existing-Cognee contract runs the complete extraction interface
against synthetic local HTTP fixtures for both fixed endpoints, then graph persistence, a separate
search worker and changed-snapshot rejection. It does not test model quality.

The earlier raw failure was exact-quote generation; span IDs remove generated
quotes and preserve exact host-owned offsets. Timeout diagnosis also moved
software off the external volume. A later smoke success does not prove all
earlier intermittent stalls are eliminated; complete acceptance succeeded on the small-model route; live source / owner / Operator readiness remains a separate requirement.

The previous read-only readiness audit found zero approved ledger records and
views, alongside separate Raw preservation receipts. Original materials exist,
but Raw drafts are not approved personal evidence. Live personalization still
requires a current approved view, owner binding,
and formal Operator deployment / chat readback. None is fabricated by a green
test. Existing Native/Operator services, signals and Guard decisions remain
outside this change.

## Upstream source

Cognee v1.6.5 Git tree: 37f788bd287750e10d7610173e5332b3843f6ebd.
Relevant modules: infrastructure/llm/extraction/knowledge_graph/extract_content_graph.py,
modules/migration/sources/cogx_archive.py, modules/retrieval/lexical_retriever.py.
The old divergent #39 branch is not imported or merged.

## Explicit project-source publication

development_sources.py preserves two exact user messages supplied in this
development conversation. Their scope is ai-foundation-development; the view
is foundation-development-instructions. Unknown message event dates and
conversation IDs stay unknown. They are project instructions, not an inferred
personality or an authorization to perform effects.

The publication command first verifies the single real server-side LibreChat
owner and existing external Operator data directory, backs up the existing
ledger, then publishes those two bounded originals. It refuses conflicting
sources, scopes, views or host configurations and reuses identical records.
Raw reports and paired-answer-source-review/1 files are not approval inputs.
The saved review file contained unreviewed LLM answer comparisons, not owner
approval, so none of its alleged personal claims is promoted.

Source and Cognee readback precede index enablement and prepared host binding creation.
Bindings require local-only handling of private context. Configuration writes
use exclusive creation compatible with the external filesystem and never
replace a different binding. The final context is reconstructed through the
same production loader and queried again. Aggregate diagnostics report the
installed Operator's actual integration state separately: a prepared binding
does not imply the running service has loaded this feature. No service restart,
Native dispatch or active immutable-release replacement is performed.

The prepared binding is human-model-bindings.prepared.json in the existing
Operator state directory. The active binding filename is untouched. Promotion
requires reviewed runtime integration and a working local-only output route;
it must not implicitly force ordinary chat into a missing historical 9B slot.

Adapter grounded-spans-v3 rejects malformed model interpretations per record
and records their count. Authorized originals remain indexed and searchable;
invalid relationships are not persisted. Inference transport/server failures
and invalid source snapshots still fail. An actual Cognee cross-process test
covers invalid typed span IDs, zero accepted interpretations, retained original
retrieval and changed-snapshot refusal.
