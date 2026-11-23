"""Operator-only cutover state machine. No production launcher or owner grant issuer.

The host must supply a separately authenticated owner release gate and
fixed, owner-validated filesystem/launchd adapter. No MCP JSON, PR value,
or opaque request ref can act as an owner approval by itself.
"""
from dataclasses import dataclass
from .release_gate import ImmutableReleaseScope


class ReleaseDenied(RuntimeError):
    pass


class ManualRecoveryRequired(RuntimeError):
    pass


@dataclass(frozen=True)
class ReleaseResult:
    status: str
    scope_ref: str
    operator_only: bool
    guard_approved: bool


class OperatorOnlyCutover:
    """Stage/backup/readback/rollback with two independent authorization gates.

    The concrete host adapter must implement: current_scope_ref,
    backup_prior, verify_backup, stage_candidate, verify_candidate,
    switch_operator, readback_operator, rollback_operator, verify_rollback.
    No such live adapter is installed or called from PR CI.
    """

    def __init__(self, release_gate, host, owner_gate=None):
        self.gate = release_gate
        self.host = host
        self.owner_gate = owner_gate

    def _authorized(self, scope, run, request_ref):
        row = self.gate.verify(scope, run, request_ref)
        if (type(row) is not dict or row.get("status") != "APPROVED"
                or row.get("ok") is not True
                or row.get("approved") is not True
                or row.get("scope_ref") != scope.scope_ref):
            raise ReleaseDenied("EXACT_GUARD_RELEASE_APPROVAL_REQUIRED")
        if self.owner_gate.verify_exact_release(scope, run, request_ref) is not True:
            raise ReleaseDenied("HOST_OWNER_RELEASE_AUTHORITY_REQUIRED")

    def execute(self, scope, run, request_ref):
        if not isinstance(scope, ImmutableReleaseScope) or scope.path != "m1-operator":
            raise ReleaseDenied("OPERATOR_ONLY_SCOPE_REQUIRED")
        if self.owner_gate is None:
            raise ReleaseDenied("TRUSTED_OWNER_RELEASE_GATE_UNAVAILABLE")
        if self.host.current_scope_ref() != scope.scope_ref:
            raise ReleaseDenied("RELEASE_SCOPE_CHANGED")
        self._authorized(scope, run, request_ref)
        self.host.backup_prior(scope)
        if self.host.verify_backup(scope) is not True:
            raise ReleaseDenied("PRIOR_PACKAGE_BACKUP_UNVERIFIED")
        self.host.stage_candidate(scope)
        if self.host.verify_candidate(scope) is not True:
            raise ReleaseDenied("PINNED_CANDIDATE_UNVERIFIED")
        if self.host.current_scope_ref() != scope.scope_ref:
            raise ReleaseDenied("RELEASE_SCOPE_CHANGED_DURING_STAGE")
        self._authorized(scope, run, request_ref)
        # A durable interrupted-cutover state precedes any service effects.
        self.gate.registry.transition(scope.path, "PREPARED", "CUTOVER")
        try:
            self.host.switch_operator(scope)
            if self.host.readback_operator(scope) is not True:
                raise ReleaseDenied("PID_BOUND_OPERATOR_READBACK_FAILED")
            # A verified service is NOT accepted until its durable release
            # receipt is committed. Failure here must restore the old service.
            self.gate.registry.transition(scope.path, "CUTOVER", "VERIFIED")
        except BaseException:
            try:
                self.host.rollback_operator(scope)
                if self.host.verify_rollback(scope) is not True:
                    raise ManualRecoveryRequired("ROLLBACK_NOT_VERIFIED")
                self.gate.registry.transition(scope.path, "CUTOVER", "ROLLED_BACK")
            except BaseException as exc:
                raise ManualRecoveryRequired("OWNER_MANUAL_RECOVERY_REQUIRED") from exc
            raise
        return ReleaseResult("VERIFIED", scope.scope_ref, True, True)
