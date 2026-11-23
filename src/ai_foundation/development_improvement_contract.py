"""Host-pinned improvement proposal distinct from the regression-only 9B path.

A measured OSS improvement is not evidence that a current-main fixed test
has regressed. This module renders a *non-runnable* proposal for an explicitly
reviewed feature branch and fixed acceptance test, without manufacturing a
failure or extending the local9B ready-label/Guard authority.

No GitHub Issue, Drive, scheduler, model, filesystem write or authorization
is performed. The returned text intentionally contains NO
```foundation-autodev-task block; existing Issue admission cannot execute it.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
import time

from .development_admission import (
    BenefitReceipt, CostReceipt, HardwareReceipt, HostContract, evaluate,
    _plan,
)
from .development_candidate_registry import reviewed_offline_catalogue

_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_SHA64 = re.compile(r"[0-9a-f]{64}\Z")
_TARGET = re.compile(r"src/ai_foundation/[a-z][a-z0-9_]*\.py\Z")
_TEST = re.compile(r"tests/test_[a-z][a-z0-9_]*\.py\Z")
_BRANCH = re.compile(r"local9b/[A-Za-z0-9_./-]{1,120}\Z")
_DOC = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")


@dataclass(frozen=True)
class HostImprovementScope:
    """Reviewed by the trusted host, never parsed from an Issue or model."""
    candidate_id: str
    base_branch: str
    base_sha: str
    target: str
    acceptance_test: str
    acceptance_sha256: str

    def validated(self, contract: HostContract) -> bool:
        if type(self) is not HostImprovementScope or type(contract) is not HostContract:
            return False
        if (type(self.candidate_id) is not str or
                type(self.base_branch) is not str or
                not _BRANCH.fullmatch(self.base_branch) or
                ".." in self.base_branch or self.base_branch.endswith("/") or
                type(self.base_sha) is not str or
                not _SHA40.fullmatch(self.base_sha) or
                type(self.target) is not str or not _TARGET.fullmatch(self.target) or
                type(self.acceptance_test) is not str or
                not _TEST.fullmatch(self.acceptance_test) or
                type(self.acceptance_sha256) is not str or
                not _SHA64.fullmatch(self.acceptance_sha256)):
            return False
        return (self.candidate_id in reviewed_offline_catalogue()
                and contract.effect == "draft_code"
                and contract.guard_scope == "development:fixed-test"
                and contract.target == self.target
                and contract.test_sha256 == self.acceptance_sha256)


def prepare_nonrunnable_improvement(
    scope, *, contract, cost, benefit, hardware, plan_id,
    plan_digest, drive, source_test_sha256, now=None,
):
    """Check exact host plan, source pins and positive evidence; propose only.

    `source_test_sha256` is an independent host readback of the *existing*
    feature-branch acceptance test bytes, not a value copied from Drive text.
    The trusted caller must separately check branch checkout matches base_sha
    and that the test actually describes the requested positive improvement.
    No claim about baseline failure, Guard ALLOW or 9B completion is made.
    """
    if type(scope) is not HostImprovementScope or not scope.validated(contract):
        return {"status": "HOLD", "reason": "IMPROVEMENT_SCOPE_NOT_REVIEWED"}
    if (type(source_test_sha256) is not str or
            source_test_sha256 != scope.acceptance_sha256 or
            type(plan_id) is not str or _DOC.fullmatch(plan_id) is None or
            type(plan_digest) is not str or _SHA64.fullmatch(plan_digest) is None):
        return {"status": "HOLD", "reason": "PINNED_TEST_OR_PLAN_UNVERIFIED"}
    meta = reviewed_offline_catalogue()[scope.candidate_id]
    # The zero-yen receipt must identify this exact reviewed upstream
    # revision, not an unrelated free product or copied billing assertion.
    if (type(cost) is not CostReceipt or
            cost.proof != meta.repository + "/commit/" + meta.pinned_commit or
            cost.billing != "NOT_APPLICABLE_LOCAL"):
        return {"status": "HOLD", "reason": "SOURCE_COST_IDENTITY_NOT_BOUND"}
    if evaluate(scope.candidate_id, contract, cost, benefit, hardware,
                now=time.time() if now is None else now) != "ADMITTED":
        return {"status": "HOLD", "reason": "CURRENT_IMPROVEMENT_EVIDENCE_NOT_ADMITTED"}
    # Require an identical plan that the genuine existing verifier would
    # generate from the SAME trusted receipts. Never treat a document's text as
    # a license to execute or as proof of independently measured improvement.
    expected = json.dumps(_plan(scope.candidate_id, contract, cost, benefit, hardware),
                          ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if sha256(expected.encode("utf-8")).hexdigest() != plan_digest:
        return {"status": "HOLD", "reason": "PLAN_RECEIPTS_NOT_BOUND"}
    try:
        actual = drive.read(plan_id)
    except Exception:
        return {"status": "HOLD", "reason": "PLAN_READBACK_UNAVAILABLE"}
    if type(actual) is not str or actual != expected:
        return {"status": "HOLD", "reason": "PLAN_READBACK_MISMATCH"}
    evidence = {
        "schema": "foundation-improvement-proposal/v1",
        "status": "REVIEW_REQUIRED_NOT_EXECUTABLE",
        "candidate_id": scope.candidate_id,
        "upstream_repository": meta.repository,
        "upstream_commit": meta.pinned_commit,
        "base_branch": scope.base_branch,
        "base_sha": scope.base_sha,
        "target": scope.target,
        "acceptance_test": scope.acceptance_test,
        "acceptance_sha256": scope.acceptance_sha256,
        "drive_plan_id": plan_id,
        "drive_plan_sha256": plan_digest,
        "metric": benefit.metric,
        "baseline": benefit.baseline,
        "observed": benefit.observed,
        "direction": benefit.direction,
        "measured_proof": benefit.proof,
        "cost_proof": cost.proof,
    }
    payload = json.dumps(evidence, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"))
    if len(payload) > 4096:
        return {"status": "HOLD", "reason": "PROPOSAL_SIZE_UNVERIFIED"}
    # No runnable task block and NO ready label: publication, subsequent
    # approval, and any 9B submission need separate existing host authority.
    return {"status": "REVIEW_REQUIRED", "proposal_sha256":
            sha256(payload.encode("utf-8")).hexdigest(),
            "proposal": payload, "ready_label": False,
            "model_calls": 0, "queue_writes": 0, "issue_writes": 0}
