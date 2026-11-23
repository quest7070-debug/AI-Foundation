"""Explicit nonsecret runtime projections through existing FILES/Guard/Work."""
import json
from hashlib import sha256
from pathlib import Path

from .knowledge_lifecycle import _digest, plan_placement, MAX_SOURCE_BYTES
from .orchestration import WorkStatus


def projection_run_id(atom, target, content, *, owner_id):
    """Exact review identity, never a grant or an approval token."""
    return 'klm-projection:' + _digest((owner_id, atom.atom_id, target.__dict__,
                                       sha256(content.encode()).hexdigest()))


def apply_runtime_projection(journal, work, *, atom, target, content, request, guard, port):
    """Update one existing shareable projection with host scopes and approval.

    Other owner writers are UNBOUND. No direct external execute, automatic
    approval, private source publication, canonical write or blind retry.
    """
    from .files_adapter import build_files
    from .core import CanonContract, TaskPlan, EffectStatus
    if (target.system != 'foundation_runtime' or target.role != 'projection'
            or atom.source.privacy != 'shareable' or target.privacy_ceiling != 'shareable'
            or target.scope != atom.source.scope or not request.owner_id
            or request.capability != 'FILES' or not request.file_write_root
            or Path(request.file_write_root).resolve() != Path(target.resource_id).resolve()
            or Path(request.file_read_root).resolve() != Path(target.resource_id).resolve()
            or Path(target.record_id).is_absolute() or '..' in Path(target.record_id).parts
            or not isinstance(content, str) or not 0 < len(content.encode()) <= MAX_SOURCE_BYTES):
        raise PermissionError('EXACT_SHAREABLE_RUNTIME_PROJECTION_REQUIRED')
    files = build_files(request, guard, port)
    execution = files._write
    safe = execution.for_run('klm-review').write_capability.authorize_target(target.record_id)
    execution.protected.validate_write(safe)
    journal.record_atom(atom)
    journal.record_plan(plan_placement(atom, 'runtime_observation', target))
    job = projection_run_id(atom, target, content, owner_id=request.owner_id)
    work.ensure(job, ['owner-update-readback'])
    approved = job in guard.state.approvals or (guard.store is not None
        and hasattr(guard.store, 'is_approved') and guard.store.is_approved(job))
    if not approved:
        if work.load(job)[0].status in {WorkStatus.PLANNED, WorkStatus.WAITING_HUMAN}:
            work.transition(job, 0, (WorkStatus.PLANNED, WorkStatus.WAITING_HUMAN),
                            WorkStatus.WAITING_HUMAN, 'EXACT_OWNER_APPROVAL_REQUIRED')
        if guard.store is not None and hasattr(guard.store, 'request_approval'):
            guard.store.request_approval(job, 'write', safe, 'files-v1', job)
        return {'status': 'WAITING_HUMAN', 'run_id': job}
    observed = files.read(job, safe)  # Missing is not an approved update.
    wanted = sha256(content.encode()).hexdigest()
    plan = TaskPlan(job, 'write', safe, text=content, canon_revision='files-v1',
                    target_precondition=observed, exclusive_target=True, effect_id=job)
    step = work.load(job)[0]
    if step.status is WorkStatus.CANCELLED:
        # Owner cancellation is terminal here, regardless of target revision.
        # A late observation can never reclaim this Work or replay its effect.
        return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
    if step.status in {WorkStatus.RUNNING, WorkStatus.VERIFIED, WorkStatus.FAILED}:
        if sha256(observed.encode()).hexdigest() != wanted:
            return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
        effect = guard.get_effect(job)
        if effect is None or (effect.run_id,effect.target,effect.expected)!=(job,safe,content):
            return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
        if effect.status is not EffectStatus.VERIFIED:
            if guard.reconcile_effect(job,plan,port) != 'VERIFIED_COMPLETE':
                return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
        if not work.transition(
                job, 0, (WorkStatus.RUNNING, WorkStatus.VERIFIED, WorkStatus.FAILED),
                WorkStatus.VERIFIED,
                json.dumps({'sha256': wanted, 'independent_readback': True})):
            return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
        return {'status': 'VERIFIED', 'run_id': job, 'sha256': wanted}
    if target.expected_revision != 'sha256:' + sha256(observed.encode()).hexdigest():
        return {'status': 'TARGET_REVISION_CONFLICT', 'run_id': job}
    if not observed:
        return {'status': 'EMPTY_TARGET_PRECONDITION_UNSUPPORTED', 'run_id': job}
    if not work.claim_not_running(job, 0):
        return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
    try:
        status = guard.execute(plan, CanonContract('foundation-files', 'files-v1'), port, content)
        if status != 'VERIFIED_COMPLETE':
            work.transition(job, 0, WorkStatus.RUNNING,
                            WorkStatus.FAILED, 'OWNER_EFFECT_NOT_VERIFIED')
            return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
        readback = files.read(job, safe)
        if sha256(readback.encode()).hexdigest() != wanted:
            raise ValueError('INDEPENDENT_READBACK_MISMATCH')
        if not work.transition(
                job, 0, WorkStatus.RUNNING, WorkStatus.VERIFIED,
                json.dumps({'sha256': wanted, 'independent_readback': True})):
            return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
        return {'status': 'VERIFIED', 'run_id': job, 'sha256': wanted}
    except Exception:
        # Preserve RUNNING intent and Guard's effect for readback reconciliation.
        return {'status': 'RECONCILE_REQUIRED', 'run_id': job}
