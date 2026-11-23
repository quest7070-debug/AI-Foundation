import importlib.util
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
spec=importlib.util.spec_from_file_location('daily_context_cutover',
    Path(__file__).parents[1]/'scripts/m1_human_model_runtime.py')
runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)


def staged(tmp_path):
    root=tmp_path/'runtime';root.mkdir();state=tmp_path/'state';state.mkdir()
    path=tmp_path/'daily.plist';path.write_bytes(b'original definition')
    (root/'candidate-launchagent.plist').write_bytes(b'candidate definition')
    config={'version':1,'bindings':[]}
    prepared=state/'prepared.json';prepared.write_text(json.dumps(config))
    manifest={'prepared_binding':str(prepared),'active_binding':str(state/'active.json')}
    host={'path':path,'definition':{'Label':'dev.quest7070.ai-foundation.operator'}}
    return root,host,manifest,[8768],{}


def test_failed_live_readback_restores_original_definition_and_binding(tmp_path,monkeypatch):
    prepared=staged(tmp_path);root,host,manifest,_,_=prepared
    calls=[]
    monkeypatch.setattr(runtime,'stage',lambda:prepared)
    monkeypatch.setattr(runtime,'get_json',lambda *args:{'activity':[]})
    monkeypatch.setattr(runtime,'sha',lambda path:runtime.EXPECTED_AGENT)
    monkeypatch.setattr(runtime,'listeners',lambda port:[8768] if port==8768 else [])
    monkeypatch.setattr(runtime,'checked_launchctl',lambda *args:calls.append(args))
    monkeypatch.setattr(runtime,'wait_stopped',lambda *args:None)
    monkeypatch.setattr(runtime,'wait_owned',lambda *args:123)
    monkeypatch.setattr(runtime,'service_pid',lambda label:123)
    def fail(_):raise RuntimeError('LIVE_READBACK_FAILED')
    monkeypatch.setattr(runtime,'live_chat',fail)
    with pytest.raises(RuntimeError,match='LIVE_READBACK_FAILED'):runtime.activate()
    assert host['path'].read_bytes()==b'original definition'
    assert not Path(manifest['active_binding']).exists()
    assert [c[0] for c in calls]==['bootout','bootstrap','bootout','bootstrap']
    assert all('paseo' not in str(c) for c in calls)


def test_busy_daily_operator_is_not_interrupted(tmp_path,monkeypatch):
    prepared=staged(tmp_path);calls=[]
    monkeypatch.setattr(runtime,'stage',lambda:prepared)
    monkeypatch.setattr(runtime,'get_json',lambda *args:{'activity':[{'job_id':'active'}]})
    monkeypatch.setattr(runtime,'checked_launchctl',lambda *args:calls.append(args))
    with pytest.raises(RuntimeError,match='DAILY_OPERATOR_BUSY'):runtime.activate()
    assert calls==[]


def test_failed_readback_restores_both_daily_services(tmp_path,monkeypatch):
    prepared=staged(tmp_path);root,host,manifest,_,_=prepared
    gateway=tmp_path/'gateway.plist';gateway.write_bytes(b'old gateway')
    (root/'previous-gateway-launchagent.plist').write_bytes(b'old gateway')
    (root/'candidate-gateway-launchagent.plist').write_bytes(b'new gateway')
    manifest['gateway']={'plist':str(gateway),'plist_sha256':runtime.EXPECTED_AGENT,
                         'label':'dev.quest7070.ai-foundation.chat-gateway'}
    calls=[]
    monkeypatch.setattr(runtime,'stage',lambda:prepared)
    monkeypatch.setattr(runtime,'get_json',lambda *args:{'activity':[]})
    monkeypatch.setattr(runtime,'sha',lambda path:runtime.EXPECTED_AGENT)
    monkeypatch.setattr(runtime,'listeners',lambda port:[8768] if port==8768 else [])
    monkeypatch.setattr(runtime,'checked_launchctl',lambda *args:calls.append(args))
    monkeypatch.setattr(runtime,'wait_stopped',lambda *args:None)
    monkeypatch.setattr(runtime,'wait_owned',lambda *args,**kwargs:123)
    monkeypatch.setattr(runtime,'service_pid',lambda label:123)
    import gateway_support
    monkeypatch.setattr(gateway_support,'current_csrf',lambda port:'test-only-token')
    def fail(_):raise RuntimeError('LIVE_READBACK_FAILED')
    monkeypatch.setattr(runtime,'live_chat',fail)
    with pytest.raises(RuntimeError,match='LIVE_READBACK_FAILED'):runtime.activate()
    assert gateway.read_bytes()==b'old gateway'
    assert host['path'].read_bytes()==b'original definition'
    assert not Path(manifest['active_binding']).exists()
    assert len(calls)==8
    assert all('paseo' not in str(c) for c in calls)


def test_empty_port_is_not_enough_until_launchd_registration_is_removed(monkeypatch):
    from types import SimpleNamespace
    calls=[]
    states=iter([0,1])
    def run(*args,**kwargs):
        calls.append(args[0]);return SimpleNamespace(returncode=next(states))
    monkeypatch.setattr(runtime.subprocess,'run',run)
    monkeypatch.setattr(runtime,'listeners',lambda port:[])
    monkeypatch.setattr(runtime.time,'sleep',lambda seconds:None)
    runtime.wait_stopped('dev.quest7070.ai-foundation.operator',8766)
    assert len(calls)==2
