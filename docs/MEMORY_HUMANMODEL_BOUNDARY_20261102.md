# Working memory and HumanModel owner-question reconstruction boundary

## Primary task

HumanModel's data exist so that an agent can ask **"What would the owner answer?"**
and receive a **provisional reconstruction** from the owner's accumulated
source-backed records. Normal user personalization is one application, not the
definition of HumanModel. This is not a literal message from the owner, a
permanent inferred persona, a consent service or an agent empowered to act
for the owner.

The existing Foundation-authorized answering LLM performs the reconstruction;
HumanModel supplies only authorized data. Keep real user utterances, modeled
answers, contradictions and unknowns distinct. A credible reconstruction
can guide another agent's planning, but only the real owner/Guard can grant
permissions, approve charges or authorize an effect.


## Ownership

Lightweight continuity may remain in the active LLM/client and Foundation.
The owner's judgments, values, enduring priorities, decision history and
personalized interpretation must be referenced from HumanModel.

| Information | Owner | Permitted use |
|---|---|---|
| Current conversation, current task, temporary assumptions, next step | LLM/client working context | Continue the task; do not promote a temporary statement into a permanent user trait. |
| Job/run identity, progress, tool results, approvals, provider/runtime observations | Foundation and their existing stores | Operational continuity and execution authority under their existing contracts. |
| User judgments, accepted/rejected options and reasons, enduring goals/values, exceptions and changes | HumanModel source evidence and approved views | Read relevant current evidence when producing personalized reasoning. |
| A model's interpretation of the person | Request-time derived reasoning | Remain provisional, source-linked and revisable; never replace original evidence or become a hidden permanent profile. |

LibreChat standard Memory/history can provide lightweight continuity. It must
not become a second authoritative store of personality or judgments. Existing
overlapping preference summaries must be reconciled against HumanModel rather
than served as an independent competing personal authority.

## Reasoning flow

The executing LLM interprets the request and uses the host-exposed retrieval
tool when personal evidence is needed. Foundation does not introduce another
semantic mode classifier or a personality inference service.

The flow is:

1. Supply current request and bounded working/task context.
2. The LLM requests relevant HumanModel evidence rather than inventing what
   the owner would value. A task requiring personalized judgment must record
   a retrieval attempt or explicitly state that personal evidence is unavailable.
3. The host binds authenticated owner, approved view, scope, audience and
   destination privacy ceiling. Model text cannot expand these bindings.
4. Read the current authorized HumanModel view. Return source IDs/revisions,
   dates, supersession/dispute information and relevant source content, keeping
   observations, explicit owner decisions and AI hypotheses distinguishable.
5. The currently executing model reasons from those records together with the
   current request. Keep an objective assessment separate from personal fit
   when both are requested. Explain the evidence behind material personalization.
6. Preserve a bounded retrieval receipt for traceability, not another canonical
   personal database. Do not automatically write the resulting interpretation
   or historical conversation back into HumanModel.

Example: when comparing career options, operational memory can retain which
options were already investigated and which step is next. HumanModel supplies
the owner's actual criteria, earlier decisions/rejections, reasons, exceptions
and changes. The executing LLM makes the present comparison; Foundation does
not prescribe a fixed personality or silently recycle a previous recommendation.

## Freshness, privacy and conflicts

- Current explicit user instructions govern the current task. When they differ
  from historical evidence, flag the difference and treat an update as a source
  proposal under HumanModel's existing write/consent process, not an automatic
  overwrite.
- Stale/missing/unapproved views do not authorize personal inference. Preserve
  ordinary objective assistance where possible, and state the limitation or
  ask only for the missing decision criterion when necessary.
- A request-scoped snapshot/cache must retain view/source revision and purpose;
  invalidation must follow changes. Do not retain a stale personality summary
  as a fallback merely because the current view is unavailable.
- Privacy applies to the destination model too. Permission to read a local
  private view is not permission to send it to a cloud model. Disallowed
  evidence remains unavailable to that route; do not silently export it or
  invent substitutes.
- HumanModel provides personal evidence, not execution permission. A historical
  preference cannot override Guard, current approval, billing or tool scope.

## Existing implementation and the remaining connection

Merged #56 introduced `experiments/human_model/foundation_readonly.py`.
Merged #77 aligned the privacy levels with the canonical ledger:
`shareable`, `restricted`, `private`.

The current `read_view` already requires an explicit non-wildcard scope,
`audience=foundation`, an approved fresh view and its privacy ceiling; it opens
the external ledger read-only without creating a DB or falling back to another
location. Returned evidence includes source URI/revision, date, kind and dispute
status. `human_model_ledger.py` also maintains view revision/invalidation and
superseded evidence projection.

The remaining feature work is runtime composition: authenticated host binding,
outbound-model privacy enforcement, a bounded agent-facing retrieval tool,
revision/receipt exposure and the actual ordinary-chat reasoning path. The
existence of the adapter does not prove that this path is already connected.

Acceptance should demonstrate personalized reasoning citing authorized current
HumanModel evidence, a changed criterion appearing after revision, stale/foreign
view denial and a missing-view response that does not fabricate personal facts.
Keep this focused on usable behavior; no additional load/soak test campaign.


## Runtime implementation checkpoint

The ordinary-chat composition and bounded retrieval tool are now implemented
in `human_model_context.py`, `auto_agent.py`, `routed_agent_model.py` and the
Operator host factory. See `HUMANMODEL_CHAT_INTEGRATION_20261102.md` for the
existing adapter reuse, Guard/owner checks, per-turn local-only private policy,
host binding format and synthetic Agent/ledger evidence. This does not claim
that a real personal view has been bound or that the production host has been
restarted onto this code.
