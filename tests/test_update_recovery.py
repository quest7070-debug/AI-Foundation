from pathlib import Path
import pytest
from ai_foundation.migration import inspect_interrupted_update,recover_interrupted_update,UpdateRollbackError
from ai_foundation.productization import FoundationConfig,backup

def setup_backup(tmp_path):
    live=tmp_path/'live';live.mkdir();(live/'trace.jsonl').write_text('old');c=FoundationConfig(str(live.resolve()));b=tmp_path/'backup';backup(c,b);return c,live,b

def test_detects_process_death_after_live_was_quarantined(tmp_path):
    c,live,b=setup_backup(tmp_path);q=tmp_path/'.live.failed-update';live.replace(q)
    s=inspect_interrupted_update(c,b);assert s.status=='RECOVERY_REQUIRED' and s.backup_present and s.quarantine_present and not s.live_present

def test_recovery_restores_backup_without_deleting_forensics(tmp_path):
    c,live,b=setup_backup(tmp_path);q=tmp_path/'.live.failed-update';live.replace(q);(q/'trace.jsonl').write_text('failed-update')
    s=recover_interrupted_update(c,b,tmp_path/'.recovery-stage')
    assert (live/'trace.jsonl').read_text()=='old';assert (q/'trace.jsonl').read_text()=='failed-update';assert s.status=='MANUAL_RECONCILIATION_REQUIRED'

def test_both_live_and_quarantine_refuses_automatic_recovery(tmp_path):
    c,live,b=setup_backup(tmp_path);q=tmp_path/'.live.failed-update';q.mkdir();(q/'evidence').write_text('incident')
    assert inspect_interrupted_update(c,b).status=='MANUAL_RECONCILIATION_REQUIRED'
    with pytest.raises(UpdateRollbackError,match='refused'):recover_interrupted_update(c,b,tmp_path/'.recovery-stage')
    assert (live/'trace.jsonl').read_text()=='old' and (q/'evidence').read_text()=='incident'

def test_backup_exists_but_live_missing_is_recoverable(tmp_path):
    c,live,b=setup_backup(tmp_path)
    import shutil;shutil.rmtree(live)
    assert inspect_interrupted_update(c,b).status=='RECOVERY_REQUIRED'
    recover_interrupted_update(c,b,tmp_path/'.recovery-stage')
    assert (live/'trace.jsonl').read_text()=='old'
