"""One-shot *host-called* M1 candidate admission; no CLI, scheduler or new authority.

The installed trusted producer provides an immutable reviewed candidate
catalogue, exact offline source observation and fixed benchmark port. The
candidate/model may supply only the identifier. This composes EXISTING
cost, M1 Bridge, HostComputeLease, Drive text, Guard and 9B queue adapters.
It does not install packages, create grants, run a model or merge a PR.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ai_foundation.development_admission import HostContract, evaluate, plan_and_submit
from ai_foundation.development_offline_cost import (
    AuditedOfflinePackage, OfflineObservation, cost_from_pinned_offline_source,
)
from ai_foundation.development_host_evidence import measured_benefit_from_fixed_port
from ai_foundation.development_drive_text_runtime import text_port
from ai_foundation.development_guard_admission import GuardAdmissionPort
from ai_foundation.host_compute_lease import (
    HostComputeBusy, HostComputeLease, HostComputeLeaseError,
)
from local9b_admission_handoff import ExistingApprovedIssueExecutor
from local9b_standing_admission import StandingDelegatedNewIssueExecutor
from local9b_positive_improvement import ReviewedPositiveFeatureExecutor
from m1_development_admission_probe import observe_m1_hardware


class _FixedEvidence:
    """Cost/benchmark identities are pinned for one plan; M1 is reobserved."""
    def __init__(self, candidate, cost, benefit, hardware):
        self.candidate, self._cost, self._benefit, self._hardware = (
            candidate, cost, benefit, hardware,
        )

    def cost(self, candidate):
        if candidate != self.candidate:
            raise ValueError("CANDIDATE_CHANGED")
        return self._cost

    def benefit(self, candidate):
        if candidate != self.candidate:
            raise ValueError("CANDIDATE_CHANGED")
        return self._benefit

    def hardware(self, candidate):
        if candidate != self.candidate:
            raise ValueError("CANDIDATE_CHANGED")
        return self._hardware()


def _bound_owner_ports(candidate_id, catalogue, contract, benchmark_port,
                       guard_port, executor):
    """Reject missing host authority before a lease, token or network lookup."""
    if (type(candidate_id) is not str or type(catalogue) is not dict
            or type(catalogue.get(candidate_id)) is not AuditedOfflinePackage
            or type(contract) is not HostContract
            or type(guard_port) is not GuardAdmissionPort
            or contract not in guard_port.allowed
            or type(executor) not in (
                ExistingApprovedIssueExecutor, StandingDelegatedNewIssueExecutor,
                ReviewedPositiveFeatureExecutor)
            or executor.guard is not guard_port
            or getattr(benchmark_port, "test_sha256", None) != contract.test_sha256):
        return False
    if type(executor) is ExistingApprovedIssueExecutor:
        binding = executor.binding
        return (binding.target == contract.target
                and binding.test_sha256 == contract.test_sha256)
    if type(executor) is ReviewedPositiveFeatureExecutor:
        scope = executor.scope
        return (scope.candidate_id == candidate_id and
                scope.validated(contract) and
                scope.base_branch == "local9b/candidate-ripgrep-search-20261109" and
                scope.target == "src/ai_foundation/literal_code_search.py" and
                scope.acceptance_test == "tests/test_literal_code_search.py")
    return (executor.spec["target"] == contract.target
            and executor.spec["test"] in {
                "tests/test_notification_boundary.py",
                "tests/test_task_result.py",
                "tests/test_question_bridge.py",
            })
    

def admit_trusted_owner_candidate(candidate_id, *, catalogue, observation,
                                   benchmark_port, contract, guard_port,
                                   executor, lease=None):
    """Real M1 orchestration, fail closed; caller owns catalogue and benchmark.

    Exact ordering:
      host registry -> already pinned offline cost -> exclusive host lease
      -> independent five-pair benchmark -> current M1 Bridge observation
      -> Drive-only text store+GET -> plan/readback -> M1 recheck
      -> existing Guard -> existing approved/standing 9B queue.

    Cost/benefit are *measured once* and pinned across Drive I/O; rerunning
    the benchmark there would produce a distinct timestamp/proof and falsely
    reject the unchanged candidate. M1 is reobserved at each Guard boundary.
    The existing worker independently revalidates ready Issue and fixed tests.
    """
    if not _bound_owner_ports(
            candidate_id, catalogue, contract, benchmark_port,
            guard_port, executor):
        return {"status": "HOLD", "reason": "TRUSTED_OWNER_CONTRACT_REQUIRED"}
    if type(observation) is not OfflineObservation:
        return {"status": "HOLD", "reason": "OFFLINE_SOURCE_UNVERIFIED"}
    cost = cost_from_pinned_offline_source(
        candidate_id, catalogue=catalogue, observed=observation)
    if cost is None:
        return {"status": "HOLD", "reason": "COST_NOT_VERIFIED"}
    lease = HostComputeLease() if lease is None else lease
    if type(lease) is not HostComputeLease:
        return {"status": "HOLD", "reason": "CANONICAL_COMPUTE_LEASE_REQUIRED"}
    try:
        with lease.hold(max_wait_s=0) as fd:
            benefit = measured_benefit_from_fixed_port(
                candidate_id, port=benchmark_port)
            if benefit is None:
                return {"status": "HOLD", "reason": "BENEFIT_NOT_VERIFIED"}

            def hardware():
                # Requires the SAME currently held compute lease FD and
                # fresh owner M1 Bridge evidence; never synthesize capacity.
                return observe_m1_hardware(lease_fd=fd)

            initial_hardware = hardware()
            if evaluate(
                candidate_id, contract, cost, benefit, initial_hardware) != "ADMITTED":
                return {"status": "HOLD", "reason": "M1_OR_CANDIDATE_NOT_ADMITTED"}
            try:
                owner_drive, plan_store = text_port()
                owner_drive.probe()  # GET-only, current exact drive.file scope
            except Exception:
                return {"status": "HOLD", "reason": "OWNER_DRIVE_UNAVAILABLE"}
            verifiers = _FixedEvidence(candidate_id, cost, benefit, hardware)
            return plan_and_submit(
                candidate_id, contract=contract, verifiers=verifiers,
                drive=plan_store, guard=guard_port, executor=executor)
    except HostComputeBusy:
        return {"status": "DEFERRED", "reason": "HOST_COMPUTE_LEASE_BUSY"}
    except HostComputeLeaseError:
        return {"status": "HOLD", "reason": "HOST_COMPUTE_LEASE_UNVERIFIED"}
    except Exception:
        # No retries after unknown downstream write/queue effects.
        return {"status": "HOLD", "reason": "HOST_CANDIDATE_EXECUTION_UNVERIFIED",
                "reconciliation_required": True}


def admit_source_reviewed_owner_candidate(candidate_id, *, observation,
                                          benchmark_port, contract, guard_port,
                                          executor, lease=None):
    """Trusted-host entry for the fixed local OSS source registry.

    The registry supplies *only* source metadata. A real separate source
    observation, five-pair benchmark, current M1 lease, owner Drive scope,
    canonical Guard and bounded executor are still indispensable. Unknown
    or merely listed candidate IDs fail closed before any external effect.
    """
    from ai_foundation.development_candidate_registry import (
        reviewed_offline_catalogue,
    )
    return admit_trusted_owner_candidate(
        candidate_id, catalogue=reviewed_offline_catalogue(),
        observation=observation, benchmark_port=benchmark_port,
        contract=contract, guard_port=guard_port, executor=executor,
        lease=lease,
    )


def prepare_reviewed_improvement(
        candidate_id, *, scope, checkout, contract, cost, benefit, hardware,
        plan_id, plan_digest, drive, now=None):
    """Positive-feature plan/readback without reusing a regression approval.

    The original trusted host supplies candidate receipts and an *existing*
    code branch whose acceptance bytes are independently read. Review-stage
    proposals cannot create GitHub tasks, add ready labels or invoke a model.
    """
    from ai_foundation.development_improvement_contract import (
        HostImprovementScope, prepare_nonrunnable_improvement,
    )
    from m1_owner_improvement_source import observed_feature_test
    if (type(candidate_id) is not str or
            type(scope) is not HostImprovementScope or
            candidate_id != scope.candidate_id or
            not scope.validated(contract)):
        return {"status": "HOLD", "reason": "IMPROVEMENT_SCOPE_NOT_REVIEWED"}
    pinned_test = observed_feature_test(scope, checkout)
    if pinned_test is None:
        return {"status": "HOLD", "reason": "FEATURE_BRANCH_SOURCE_UNVERIFIED"}
    return prepare_nonrunnable_improvement(
        scope, contract=contract, cost=cost, benefit=benefit,
        hardware=hardware, plan_id=plan_id, plan_digest=plan_digest,
        drive=drive, source_test_sha256=pinned_test, now=now,
    )
