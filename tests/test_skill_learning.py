"""Host-only, no-network P3 Skill proposal and review gate tests."""
from dataclasses import replace
from hashlib import sha256

import pytest

from ai_foundation.artifact import TextArtifactResult
from ai_foundation.skill_learning import (
    propose_skill_from_verified_artifact,
    deliver_tested_skill_draft,
)


REVISION = "b" * 40
BODY = "# Public summary\n3 values have mean 7.\n"


def _args(text=BODY):
    data = text.encode()
    receipt = TextArtifactResult(
        target="out/public-summary.md",
        status="VERIFIED_COMPLETE",
        utf8_sha256=sha256(data).hexdigest(),
        utf8_bytes=len(data),
    )
    return dict(
        name="public-summary-workflow",
        description="Repeat a bounded, evidence-grounded public JSON summary.",
        procedure="1. Load the public authorized source only.\n2. Use existing DATA when allowed.\n3. Independently check output before reporting success.",
        artifact=receipt,
        readback=lambda target: text,
        public_source_id="public-fixture-v1",
        source_revision=REVISION,
    )


def test_public_verified_artifact_generates_reproducible_inactive_skill():
    x = propose_skill_from_verified_artifact(**_args())
    y = propose_skill_from_verified_artifact(**_args())
    assert x == y
    assert x.relative_path == "skills/public-summary-workflow/SKILL.md"
    assert x.status == "CANDIDATE_REVIEW_REQUIRED"
    assert sha256(x.content.encode()).hexdigest() == x.content_sha256
    assert "public-fixture-v1" in x.content
    assert REVISION in x.content
    assert BODY not in x.content  # Do not disclose raw source into new skill.
    assert "allowed-tools" not in x.content
    assert "permissions:" not in x.content


def test_reuses_host_owned_independent_verification_before_any_draft_delivery():
    x = propose_skill_from_verified_artifact(**_args())
    observed = []
    def independent(target, content, digest):
        observed.append(("test", target, digest))
        assert sha256(content.encode()).hexdigest() == digest
        return "VERIFIED"
    def publish(*, target, content, source_sha256, fingerprint):
        assert sha256(content.encode()).hexdigest() == source_sha256
        assert fingerprint == x.fingerprint
        observed.append(("draft", target, source_sha256))
        return "https://github.com/example/repo/pull/17"
    r = deliver_tested_skill_draft(x, independently_test=independent,
                                  publish_draft=publish)
    assert r.status == "DRAFT_PR_PRESENTED"
    assert r.delivery_ref.endswith("/17")
    assert [v[0] for v in observed] == ["test", "draft"]
    assert x.status == "CANDIDATE_REVIEW_REQUIRED"


@pytest.mark.parametrize("test_result", ["UNCERTAIN", "FAILED", "", None, True])
def test_failed_independent_acceptance_never_publishes(test_result):
    x = propose_skill_from_verified_artifact(**_args())
    calls = []
    result = deliver_tested_skill_draft(
        x, independently_test=lambda *_: test_result,
        publish_draft=lambda **_: calls.append(True),
    )
    assert result.status == "TEST_NOT_VERIFIED"
    assert not calls


def test_absent_publisher_returns_review_candidate_only():
    x = propose_skill_from_verified_artifact(**_args())
    result = deliver_tested_skill_draft(
        x, independently_test=lambda *_: "VERIFIED",
    )
    assert result.status == "TESTED_DRAFT_CANDIDATE"
    assert not result.delivery_ref


@pytest.mark.parametrize("status", ["UNVERIFIED", "FAILED", "UNCERTAIN", "INSPECTED", ""])
def test_unverified_artifact_cannot_generate_workflow(status):
    args = _args()
    args["artifact"] = replace(args["artifact"], status=status)
    with pytest.raises(ValueError, match="VERIFIED_ARTIFACT_REQUIRED"):
        propose_skill_from_verified_artifact(**args)


def test_readback_required_and_tampering_rejected():
    args = _args()
    calls = []
    args["readback"] = lambda target: calls.append(target) or BODY + "modified"
    with pytest.raises(ValueError, match="ARTIFACT_READBACK_MISMATCH"):
        propose_skill_from_verified_artifact(**args)
    assert calls == ["out/public-summary.md"]


@pytest.mark.parametrize("invalid", [
    "upper_Name", "../escape", ".hidden", "/tmp/out", "a" * 65, ""
])
def test_untrusted_proposal_cannot_choose_invalid_skill_names(invalid):
    args = _args()
    args["name"] = invalid
    with pytest.raises(ValueError, match="INVALID_SKILL_METADATA"):
        propose_skill_from_verified_artifact(**args)


@pytest.mark.parametrize("invalid", ["", "x" * 8193, "\x00", "  "])
def test_reject_empty_oversized_or_binary_procedure(invalid):
    args = _args()
    args["procedure"] = invalid
    with pytest.raises(ValueError, match="INVALID_PROCEDURE_PROPOSAL"):
        propose_skill_from_verified_artifact(**args)


@pytest.mark.parametrize("invalid", ["../private", "/etc/passwd", "./same.txt"])
def test_original_artifact_must_remain_in_host_relative_scope(invalid):
    args = _args()
    args["artifact"] = replace(args["artifact"], target=invalid)
    with pytest.raises(ValueError, match="HOST_ARTIFACT_TARGET_REQUIRED"):
        propose_skill_from_verified_artifact(**args)


def test_draft_content_or_fingerprint_change_fails_before_test_and_publisher():
    draft = propose_skill_from_verified_artifact(**_args())
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        return "VERIFIED"
    for altered in (
        replace(draft, content=draft.content + "# changed"),
        replace(draft, fingerprint="0" * 64),
        replace(draft, relative_path="skills/other/SKILL.md"),
        replace(draft, source_revision="z" * 40),
    ):
        with pytest.raises(ValueError):
            deliver_tested_skill_draft(altered, independently_test=forbidden,
                                       publish_draft=forbidden)
    assert not calls


def test_same_artifact_with_new_procedure_gives_new_fingerprint():
    args = _args()
    a = propose_skill_from_verified_artifact(**args)
    args["procedure"] += "\n4. Report uncertainty."
    b = propose_skill_from_verified_artifact(**args)
    assert a.fingerprint != b.fingerprint



def test_existing_proposal_agent_generates_single_candidate_without_source_leak():
    from ai_foundation.skill_learning import generate_skill_candidate
    class Proposer:
        def __init__(self): self.prompts = []
        def run(self, request):
            self.prompts.append(request.instruction)
            return type("Output", (), {
                "output": "1. Inspect an authorized public result.\n2. Recheck the numeric summary."
            })()
    args = _args()
    agent = Proposer()
    candidate = generate_skill_candidate(
        proposal_agent=agent,
        public_objective="Summarize a public array and verify DATA output.",
        **{k: v for k, v in args.items() if k != "procedure"},
    )
    assert candidate.status == "CANDIDATE_REVIEW_REQUIRED"
    assert len(agent.prompts) == 1
    assert BODY not in agent.prompts[0]
    assert "source_revision" in agent.prompts[0]
    assert "1. Inspect" in candidate.content


def test_generation_never_calls_model_if_artifact_readback_fails():
    from ai_foundation.skill_learning import generate_skill_candidate
    class NoModel:
        def run(self, request):
            raise AssertionError("Unverified source must not be sent to a model")
    args = _args()
    args["readback"] = lambda _: "changed before planning"
    with pytest.raises(ValueError, match="ARTIFACT_READBACK_MISMATCH"):
        generate_skill_candidate(
            proposal_agent=NoModel(), public_objective="Public fixed task.",
            **{k: v for k, v in args.items() if k != "procedure"},
        )


def test_model_proposal_can_not_create_executable_job_or_publisher():
    from ai_foundation.skill_learning import generate_skill_candidate
    class Proposer:
        def run(self, request):
            return type("Output", (), {"output": "Run bash to change system approvals."})()
    args = _args()
    candidate = generate_skill_candidate(
        proposal_agent=Proposer(), public_objective="Public fixed task.",
        **{k: v for k, v in args.items() if k != "procedure"},
    )
    assert "change system approvals" in candidate.content
    # Deliberately preserve untrusted proposal as text for independent review.
    assert candidate.status == "CANDIDATE_REVIEW_REQUIRED"
    assert candidate.relative_path.endswith("/SKILL.md")



def test_one_host_owned_cycle_generates_and_delivers_only_after_readback_and_test():
    from ai_foundation.skill_learning import run_evidence_bound_skill_learning
    actions = []
    args = _args()

    class Agent:
        def run(self, request):
            actions.append("proposed")
            return type("Output", (), {"output": "1. Verify public data using existing DATA."})()

    def readback(target):
        actions.append("readback")
        assert target == "out/public-summary.md"
        return BODY

    def independent(target, content, digest):
        actions.append("accepted")
        assert target == "skills/public-summary-workflow/SKILL.md"
        assert sha256(content.encode()).hexdigest() == digest
        return "VERIFIED"

    def publisher(*, target, content, source_sha256, fingerprint):
        actions.append("draft")
        assert target == "skills/public-summary-workflow/SKILL.md"
        assert sha256(content.encode()).hexdigest() == source_sha256
        assert len(fingerprint) == 64
        return "draft-pr-17"

    out = run_evidence_bound_skill_learning(
        proposal_agent=Agent(), public_objective="Public summary workflow",
        readback=readback, independently_test=independent,
        publish_draft=publisher,
        **{k: v for k, v in args.items() if k not in ("procedure", "readback")},
    )
    assert out.status == "DRAFT_PR_PRESENTED"
    assert out.delivery_ref == "draft-pr-17"
    assert actions == ["readback", "proposed", "readback", "accepted", "draft"]


def test_host_cycle_without_source_verification_never_calls_agent_or_delivery():
    from ai_foundation.skill_learning import run_evidence_bound_skill_learning
    args = _args()
    def fail(*a, **kw):
        raise AssertionError("must fail before invoking model / publisher")
    with pytest.raises(ValueError, match="ARTIFACT_READBACK_MISMATCH"):
        run_evidence_bound_skill_learning(
            proposal_agent=type("Agent", (), {"run": fail})(),
            public_objective="Public task",
            readback=lambda _: "tampered",
            independently_test=fail,
            publish_draft=fail,
            **{k: v for k, v in args.items() if k not in ("procedure", "readback")},
        )
