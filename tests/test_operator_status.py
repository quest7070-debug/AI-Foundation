import json,time
from ai_foundation.operator import snapshot
from ai_foundation.human_view import from_snapshot
from ai_foundation.human_renderer import render
from ai_foundation.productization import FoundationConfig

def cfg(tmp_path):
    root=tmp_path/'data'; root.mkdir(); return FoundationConfig(str(root.resolve()))

def test_service_probe_ready_unavailable_and_exception(tmp_path):
    c=cfg(tmp_path)
    def boom(): raise RuntimeError('secret internal failure')
    s=snapshot(c,service_probes={'runtime':lambda:True,'provider':lambda:False,'tool':boom})
    rows={x['name']:x for x in s.services}
    assert rows['runtime']=={'name':'runtime','ok':True,'detail':'ready'}
    assert rows['provider']['detail']=='unavailable'
    assert rows['tool']['detail']=='probe-failed'
    assert 'secret internal failure' not in render(from_snapshot(s),'responsive')

def test_backup_status_valid_and_corrupt_manifest(tmp_path):
    c=cfg(tmp_path); backup=tmp_path/'backup'; backup.mkdir(); manifest=backup/'manifest.json'
    manifest.write_text(json.dumps({'schema_version':1}),encoding='utf-8')
    old=time.time()-120; __import__('os').utime(manifest,(old,old))
    s=snapshot(c,backup_dir=backup)
    assert s.backup['present'] is True and s.backup['schema_version']==1
    assert s.backup['age_seconds']>=119
    manifest.write_text('{broken',encoding='utf-8')
    s=snapshot(c,backup_dir=backup)
    assert s.backup=={'present':False,'age_seconds':None,'schema_version':None}

def test_missing_backup_and_update_stage_are_explicit(tmp_path):
    c=cfg(tmp_path)
    s=snapshot(c,backup_dir=tmp_path/'missing-backup',update_stage=tmp_path/'missing-stage')
    assert s.backup=={'present':False,'age_seconds':None,'schema_version':None}
    assert s.update['staged'] is False and s.update['entries']==0 and s.update['transaction'] is None

def test_update_stage_counts_entries_and_html_escapes_service_name(tmp_path):
    c=cfg(tmp_path); stage=tmp_path/'stage'; stage.mkdir(); (stage/'a').write_text('x'); (stage/'b').mkdir()
    s=snapshot(c,service_probes={'<script>x</script>':lambda:True},update_stage=stage)
    assert s.update['staged'] is True and s.update['entries']==2 and s.update['transaction'] is None
    page=render(from_snapshot(s),'responsive')
    assert '<script>x</script>' not in page and '&lt;script&gt;x&lt;/script&gt;' in page

def test_update_status_uses_transaction_journal_as_authoritative_state(tmp_path):
 from ai_foundation.migration import _write_journal
 c=cfg(tmp_path);_write_journal(c,'APPLYING',backup_dir='x')
 s=snapshot(c,update_stage=tmp_path/'missing-stage')
 assert s.update['transaction']=='APPLYING' and s.update['journal'] and not s.update['staged']
 assert 'UPDATE / APPLYING' in render(from_snapshot(s),'responsive')

def test_snapshot_refuses_to_turn_corrupt_state_into_empty_state(tmp_path):
 from ai_foundation.operator import OperatorReadError
 c=cfg(tmp_path);(tmp_path/'data'/c.guard_db).write_bytes(b'not sqlite')
 import pytest
 with pytest.raises(OperatorReadError): snapshot(c)

def test_applying_update_is_recovering_not_ready(tmp_path):
 from ai_foundation.migration import _write_journal
 c=cfg(tmp_path);_write_journal(c,'APPLYING',backup_dir='x')
 v=from_snapshot(snapshot(c));assert v.state=='RECOVERING'


def test_service_health_is_dependency_specific(tmp_path):
 c=cfg(tmp_path);s=snapshot(c,service_probes={'TOOLHIVE FILES':lambda:True,'TOOLHIVE CODE':lambda:False})
 rows={x['name']:x for x in s.services};assert rows['TOOLHIVE FILES']['ok'] is True and rows['TOOLHIVE CODE']['ok'] is False
