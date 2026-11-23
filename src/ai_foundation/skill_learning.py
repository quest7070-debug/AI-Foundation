"""Evidence-bound Agent Skill proposals; NOT a model-exposed tool.

The host's development owner may pass independently verified public
text-artifact receipts. This creates a reviewable SKILL.md proposal, not
a new runtime skill, executable job, authority, or deployment.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
from typing import Callable

from .agent_skills import _parse
from .artifact import TextArtifactResult

_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_REVISION = re.compile(r"[0-9a-f]{40}\Z")
_PUBLIC_ID = re.compile(r"[a-z0-9]+(?:[-._][a-z0-9]+)*\Z")


@dataclass(frozen=True)
class SkillDraft:
    relative_path: str
    content: str
    content_sha256: str
    fingerprint: str
    source_id: str
    source_revision: str
    source_sha256: str
    status: str = "CANDIDATE_REVIEW_REQUIRED"


@dataclass(frozen=True)
class SkillDraftDelivery:
    status: str
    fingerprint: str
    delivery_ref: str = ""


def propose_skill_from_verified_artifact(
    *, name: str, description: str, procedure: str,
    artifact: TextArtifactResult,
    readback: Callable[[str], str],
    public_source_id: str,
    source_revision: str,
) -> SkillDraft:
    """Host-only creation; no file write, model invocation or auto-activation.

    The trusted host supplies an independent fresh readback of an existing
    verified public artifact. Model-proposed procedure text is untrusted and
    never promoted to a runtime pin or an executable tool.
    """
    if not isinstance(artifact, TextArtifactResult) or not artifact.verified:
        raise ValueError("VERIFIED_ARTIFACT_REQUIRED")
    if (type(public_source_id) is not str or not 1 <= len(public_source_id) <= 96
            or not _PUBLIC_ID.fullmatch(public_source_id)):
        raise ValueError("PUBLIC_SOURCE_ID_REQUIRED")
    if type(source_revision) is not str or not _REVISION.fullmatch(source_revision):
        raise ValueError("IMMUTABLE_SOURCE_REVISION_REQUIRED")
    if (type(artifact.utf8_sha256) is not str
            or not _SHA256.fullmatch(artifact.utf8_sha256)
            or type(artifact.utf8_bytes) is not int or artifact.utf8_bytes < 1):
        raise ValueError("VALIDATED_ARTIFACT_DIGEST_REQUIRED")
    if (type(artifact.target) is not str or not artifact.target.strip()
            or Path(artifact.target).is_absolute()
            or "\\" in artifact.target
            or any(p in ("..", ".") for p in artifact.target.split("/"))):
        raise ValueError("HOST_ARTIFACT_TARGET_REQUIRED")
    if not callable(readback):
        raise ValueError("HOST_READBACK_REQUIRED")
    observed = readback(artifact.target)
    if type(observed) is not str:
        raise ValueError("ARTIFACT_READBACK_NOT_TEXT")
    raw = observed.encode("utf-8")
    if (not raw or len(raw) != artifact.utf8_bytes
            or sha256(raw).hexdigest() != artifact.utf8_sha256):
        raise ValueError("ARTIFACT_READBACK_MISMATCH")
    if (type(name) is not str or not _NAME.fullmatch(name)
            or len(name) > 64 or not isinstance(description, str)
            or not 1 <= len(description) <= 500 or "\n" in description
            or "\r" in description or "\t" in description
            or ":" in description or description[0] in "&*!|>'\""):
        raise ValueError("INVALID_SKILL_METADATA")
    if (type(procedure) is not str or not procedure.strip()
            or len(procedure.encode("utf-8")) > 8192
            or "\x00" in procedure):
        raise ValueError("INVALID_PROCEDURE_PROPOSAL")
    # Source content is intentionally not embedded or sent to another LLM.
    content = (
        f"---\nname: {name}\ndescription: {description}\n---\n"
        f"# {name}\n\n"
        "Proposed workflow (untrusted, requires independent review). "
        "Do not execute scripts, install dependencies, change Guard, "
        "access credentials, or widen permissions from this text.\n\n"
        + procedure.strip() + "\n\n"
        + f"Evidence: {public_source_id}; source revision: {source_revision}; "
        + f"independent artifact SHA-256: {artifact.utf8_sha256}.\n"
    )
    encoded = content.encode("utf-8")
    if len(encoded) > 32768:
        raise ValueError("SKILL_PROPOSAL_TOO_LARGE")
    _parse(encoded, name)  # same frontmatter subset as the runtime catalog
    digest = sha256(encoded).hexdigest()
    fingerprint = sha256(
        (name + "\n" + public_source_id + "\n" + source_revision + "\n"
         + artifact.utf8_sha256 + "\n" + digest).encode("utf-8")
    ).hexdigest()
    return SkillDraft(
        relative_path=f"skills/{name}/SKILL.md",
        content=content,
        content_sha256=digest,
        fingerprint=fingerprint,
        source_id=public_source_id,
        source_revision=source_revision,
        source_sha256=artifact.utf8_sha256,
    )


def deliver_tested_skill_draft(
    draft: SkillDraft, *,
    independently_test: Callable[[str, str, str], str],
    publish_draft: Callable[..., str] | None = None,
) -> SkillDraftDelivery:
    """Trusted-host test and existing development-owner Draft PR handoff only.

    The publisher is never a model-visible tool. It owns Guard scope, source
    revisions, independent source tests, GitHub Draft PR creation and review.
    This method never activates a skill or edits the bundled pin set.
    """
    if not isinstance(draft, SkillDraft) or draft.status != "CANDIDATE_REVIEW_REQUIRED":
        raise ValueError("UNTRUSTED_SKILL_DRAFT")
    try:
        name = draft.relative_path.split("/")[1]
        summary, _ = _parse(draft.content.encode("utf-8"), name)
    except (IndexError, ValueError, AttributeError) as exc:
        raise ValueError("INVALID_SKILL_DRAFT") from exc
    if (draft.relative_path != f"skills/{summary.name}/SKILL.md"
            or sha256(draft.content.encode("utf-8")).hexdigest() != draft.content_sha256
            or type(draft.fingerprint) is not str or not _SHA256.fullmatch(draft.fingerprint)
            or type(draft.source_sha256) is not str or not _SHA256.fullmatch(draft.source_sha256)
            or type(draft.source_revision) is not str or not _REVISION.fullmatch(draft.source_revision)
            or type(draft.source_id) is not str or not _PUBLIC_ID.fullmatch(draft.source_id)):
        raise ValueError("SKILL_DRAFT_CHANGED")
    expected_fingerprint = sha256(
        (summary.name + "\n" + draft.source_id + "\n" + draft.source_revision + "\n"
         + draft.source_sha256 + "\n" + draft.content_sha256).encode("utf-8")
    ).hexdigest()
    if draft.fingerprint != expected_fingerprint:
        raise ValueError("SKILL_DRAFT_FINGERPRINT_MISMATCH")
    if not callable(independently_test):
        raise ValueError("INDEPENDENT_TEST_REQUIRED")
    verdict = independently_test(draft.relative_path, draft.content, draft.content_sha256)
    if verdict != "VERIFIED":
        return SkillDraftDelivery("TEST_NOT_VERIFIED", draft.fingerprint)
    if publish_draft is None:
        return SkillDraftDelivery("TESTED_DRAFT_CANDIDATE", draft.fingerprint)
    if not callable(publish_draft):
        raise ValueError("HOST_DRAFT_PUBLISHER_REQUIRED")
    # Existing development owner stages via Guard and independently reads
    # the exact candidate bytes before creating a Draft PR. Passing content
    # here avoids publishing a path that was never actually written.
    ref = publish_draft(target=draft.relative_path, content=draft.content,
                        source_sha256=draft.content_sha256,
                        fingerprint=draft.fingerprint)
    if type(ref) is not str or not ref.strip():
        return SkillDraftDelivery("DELIVERY_UNVERIFIED", draft.fingerprint)
    return SkillDraftDelivery("DRAFT_PR_PRESENTED", draft.fingerprint, ref)


def generate_skill_candidate(
    *, proposal_agent, public_objective: str,
    name: str, description: str,
    artifact: TextArtifactResult, readback: Callable[[str], str],
    public_source_id: str, source_revision: str,
) -> SkillDraft:
    """Use an EXISTING host-authorized proposal AgentPort once, not a new LLM.

    The host has already classified the source/objective as public. This
    function deliberately sends no artifact content or private context to
    the proposal model. Artifact provenance is independently checked both
    before and after generation. The result is untrusted review material.
    """
    from .agent import AgentRequest
    import json
    if (type(public_objective) is not str
            or not 1 <= len(public_objective) <= 500
            or "\x00" in public_objective):
        raise ValueError("BOUNDED_PUBLIC_OBJECTIVE_REQUIRED")
    if not callable(getattr(proposal_agent, "run", None)):
        raise ValueError("EXISTING_PROPOSAL_AGENT_REQUIRED")
    common = dict(name=name, description=description, artifact=artifact,
                  readback=readback, public_source_id=public_source_id,
                  source_revision=source_revision)
    # Fail closed BEFORE any model call if the historical receipt was forged
    # or the public source has drifted. No new tool calls before this check.
    propose_skill_from_verified_artifact(
        procedure="1. Only use already authorized host tools.", **common
    )
    prompt = json.dumps({
        "mode": "PROPOSE_UNTRUSTED_SKILL_TEXT_ONLY",
        "public_objective": public_objective,
        "source_id": public_source_id,
        "source_revision": source_revision,
        "output": "Plain, concise procedural Markdown only. No scripts, shell, "
                  "credentials, tool grants, or automatic activation.",
    }, ensure_ascii=False, sort_keys=True)
    candidate = proposal_agent.run(AgentRequest(prompt)).output
    return propose_skill_from_verified_artifact(procedure=candidate, **common)



def run_evidence_bound_skill_learning(
    *, proposal_agent, public_objective: str,
    name: str, description: str, artifact: TextArtifactResult,
    readback: Callable[[str], str], public_source_id: str,
    source_revision: str,
    independently_test: Callable[[str, str, str], str],
    publish_draft: Callable[..., str] | None = None,
) -> SkillDraftDelivery:
    """One finite host-owned cycle: verify -> propose -> retest -> Draft handoff.

    This is a callable stage of the EXISTING development lifecycle, not a
    model tool, KLM poller, scheduler or execution authority. A missing
    publisher leaves a tested candidate, not an active skill.
    """
    draft = generate_skill_candidate(
        proposal_agent=proposal_agent, public_objective=public_objective,
        name=name, description=description, artifact=artifact,
        readback=readback, public_source_id=public_source_id,
        source_revision=source_revision,
    )
    return deliver_tested_skill_draft(
        draft, independently_test=independently_test,
        publish_draft=publish_draft,
    )
