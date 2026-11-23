from ai_foundation.human_view import from_snapshot

def test_running_operator_state_comes_from_work_summary_not_notification_attention():
 class S:
  def as_dict(self):return {'ready':True,'waiting_human':0,'effects':{},'attention':[],'work':{'RUNNING':2}}
 assert from_snapshot(S()).state=='RUNNING'

def test_severity_counts_come_from_actual_human_notices():
 from ai_foundation.human_operations import HumanNotice
 class S:
  def as_dict(self):return {'ready':True,'attention':[],'work':{}}
 ns=(HumanNotice(1,'x','1','X','s','d'),HumanNotice(4,'x','2','X','s','d'),HumanNotice(4,'x','3','X','s','d'),HumanNotice(5,'x','4','X','s','d'))
 assert from_snapshot(S(),notices=ns).severity_counts==(1,0,0,2,1)


class Snapshot:
    def __init__(self, value, present=True):
        self.value, self.present = value, present
    def as_dict(self):
        row = {"services": [{"ok": True}], "work": {}, "attention": []}
        if self.present:
            row["ready"] = self.value
        return row

def test_only_boolean_true_certifies_core_readiness():
    for value in ("false", "true", 1, 2, -1, [], {}, [True], {"ready": True}, None):
        view = from_snapshot(Snapshot(value))
        assert view.telemetry.ready is False
        assert view.runtime_health == "UNVERIFIED"
    assert from_snapshot(Snapshot(None, present=False)).telemetry.ready is False

def test_real_boolean_readiness_and_history_are_preserved():
    assert from_snapshot(Snapshot(True)).telemetry.ready is True
    view = from_snapshot(Snapshot(False))
    assert view.telemetry.ready is False
    assert view.runtime_health == "DEGRADED"
