from dataclasses import dataclass
from .core import EffectStatus

@dataclass(frozen=True)
class OperatorActionResult:
    ok:bool; action:str; subject:str; status:str

class OperatorActions:
    """Narrow human-action boundary. Never edits SQLite directly."""
    def __init__(self,guard,work_store=None):
        self.guard=guard; self.work_store=work_store
        self._cancel_observer=None

    def bind_cancel_observer(self, observer):
        """One owner-host callback. No change to Guard cancellation authority."""
        if not callable(observer) or self._cancel_observer is not None:
            raise ValueError('EXACT_CANCEL_OBSERVER_REQUIRED')
        self._cancel_observer=observer

    def _cancel_receipt(self,run_id):
        if self._cancel_observer is None:
            return 'CANCELLED'
        try:
            self._cancel_observer(run_id)
            return 'CANCELLED'
        except Exception:
            # Guard denial/cancellation has already been durably committed.
            # The read-side current-consent boundary must deny access until
            # the independent owner reconciliation is completed.
            return 'CANCELLED_HUMANMODEL_SYNC_PENDING'

    def approve_pending(self,run_id,request_ref):
        """UI/MCP-facing exact pending Guard decision, never a free-form grant."""
        if not run_id or not request_ref:
            return OperatorActionResult(False,'approve',run_id,'STALE_OR_UNBOUND_APPROVAL')
        if not self.guard.approve_pending(run_id,request_ref):
            return OperatorActionResult(False,'approve',run_id,'STALE_OR_UNBOUND_APPROVAL')
        return OperatorActionResult(True,'approve',run_id,'APPROVED')

    def approve_run(self,run_id):
        if not run_id: return OperatorActionResult(False,'approve',run_id,'INVALID')
        self.guard.approve(run_id)
        return OperatorActionResult(True,'approve',run_id,'APPROVED')

    def deny_pending(self,run_id,request_ref):
        if not run_id or not request_ref or not self.guard.cancel_pending(run_id,request_ref):
            return OperatorActionResult(False,'cancel',run_id,'STALE_OR_UNBOUND_APPROVAL')
        return OperatorActionResult(True,'cancel',run_id,self._cancel_receipt(run_id))

    def cancel_run(self,run_id):
        if not run_id: return OperatorActionResult(False,'cancel',run_id,'INVALID')
        self.guard.cancel(run_id)
        return OperatorActionResult(True,'cancel',run_id,self._cancel_receipt(run_id))


    def reconcile_effect(self,effect_id,plan,port):
        """Observe-only reconciliation through Guard's public authority boundary."""
        result=self.guard.reconcile_effect(effect_id,plan,port)
        return OperatorActionResult(result=='VERIFIED_COMPLETE','reconcile',effect_id,result)
