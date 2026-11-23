import importlib.util
from pathlib import Path
import json
import pytest

spec=importlib.util.spec_from_file_location('activation_probe',Path(__file__).parents[1]/'scripts/m1_human_model_activation_readiness.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


def test_empty_ledger_cannot_be_promoted_by_a_single_account():
    report={'ledger_candidates':1,'ledger':{'evidence_count':0,'eligible_nonempty_views':0},
            'identity':{'single_server_owner':True},'runtime':{}}
    out=probe.blockers(report)
    assert 'NO_HUMANMODEL_EVIDENCE' in out and 'APPROVED_NONEMPTY_VIEW_NOT_UNIQUE' in out
    assert 'SERVER_OWNER_NOT_UNIQUE' not in out


def test_approved_data_does_not_imply_installed_runtime():
    report={'ledger_candidates':1,'ledger':{'evidence_count':4,'eligible_nonempty_views':1,'source_snapshot_verified':True},
            'identity':{'single_server_owner':True},'runtime':{}}
    assert probe.blockers(report)==['CANONICAL_RELEASE_REQUIRES_CONTEXT_INTEGRATION']


def test_volume_selection_requires_existing_verified_external_ledger(tmp_path):
    volumes=tmp_path/'Volumes';volume=volumes/'USB';ledger=volume/'HumanModel/ledger/human_model.sqlite3'
    ledger.parent.mkdir(parents=True);ledger.write_bytes(b'synthetic')
    info=lambda p:{'Internal':False,'BusProtocol':'USB','MountPoint':str(p)}
    assert probe.existing_ledger_roots(volumes,mounted=lambda _:True,info=info)==[volume/'HumanModel']
    assert probe.existing_ledger_roots(volumes,mounted=lambda _:False,info=info)==[]
    assert probe.existing_ledger_roots(volumes,mounted=lambda _:True,info=lambda p:{'Internal':True})==[]


def test_owner_probe_returns_no_identity_values(monkeypatch):
    def run(args,**kwargs):
        assert args[1:5]==['exec','chat-mongodb','mongosh','--quiet']
        assert '_id:1' in args[-1] and 'email' not in args[-1]
        return type('CP',(),{'stdout':json.dumps({'count':1,'owner':'a'*24})})()
    monkeypatch.setattr(probe.subprocess,'run',run)
    assert probe.inspect_owner('docker')=={'single_server_owner':True}


def test_missing_launch_agent_cannot_be_called_context_ready(tmp_path):
    state=probe.inspect_installed_runtime(tmp_path)
    assert state["loader_source_kind"] == "UNVERIFIED"
    assert all(value is False for value in state.values() if type(value) is bool)


def test_explicit_project_binding_selects_its_view_among_multiple_private_views(tmp_path,monkeypatch):
    import importlib
    import sys
    from ai_foundation.human_model_context import HumanModelBinding,_source_reader
    sys.path.insert(0,str(Path(__file__).parents[1]/'experiments/human_model'))
    from human_model_ledger import Ledger
    root=tmp_path/'HumanModel';directory=root/'ledger';directory.mkdir(parents=True)
    path=directory/'human_model.sqlite3';ledger=Ledger(path)
    try:
        for scope,privacy in [('private','private'),('project','shareable')]:
            ledger.add(source_uri='fixture:'+scope,source_revision='1',kind='observation',
                       scope=scope,privacy=privacy,content=scope+' source')
            ledger.define_view(view_id=scope,purpose=scope,audience='foundation',
                               allowed_scopes=[scope],max_privacy=privacy)
        ledger.rebuild_view(view_id='private');ledger.rebuild_view(view_id='project')
    finally:ledger.close()
    reader=_source_reader(Path(__file__).parents[1])
    module=importlib.import_module(reader.__module__.rsplit('.',1)[0]+'.storage_location')
    monkeypatch.setattr(module,'validated_ledger_path',lambda _,**kwargs:path)
    binding=HumanModelBinding('owner',str(root),'project',('project',),'shareable')
    report=probe.inspect_ledger(root,binding)
    assert report['view_count']==2 and report['eligible_nonempty_views']==1
    assert report['source_snapshot_verified']
    assert probe.inspect_ledger(root)['eligible_nonempty_views']==2



def test_unrelated_mounted_volume_never_invokes_diskutil(tmp_path):
    volumes = tmp_path / 'Volumes'
    unrelated = volumes / 'UnrelatedUSB'
    unrelated.mkdir(parents=True)
    candidate = volumes / 'Candidate'
    ledger = candidate / 'HumanModel/ledger/human_model.sqlite3'
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b'synthetic')
    inspected = []
    def info(path):
        inspected.append(path.name)
        if path == unrelated:
            raise RuntimeError('diskutil on unrelated mount must not be called')
        return {'Internal': False, 'BusProtocol': 'USB', 'MountPoint': str(path)}
    assert probe.existing_ledger_roots(
        volumes, mounted=lambda _: True, info=info
    ) == [candidate / 'HumanModel']
    assert inspected == ['Candidate']


def test_diskutil_failure_on_candidate_stays_fail_closed(tmp_path):
    import subprocess
    volumes = tmp_path / 'Volumes'
    ledger = volumes / 'Candidate/HumanModel/ledger/human_model.sqlite3'
    ledger.parent.mkdir(parents=True)
    ledger.write_bytes(b'synthetic')
    def failed_info(path):
        raise subprocess.CalledProcessError(1, ['diskutil', 'info'])
    with pytest.raises(subprocess.CalledProcessError):
        probe.existing_ledger_roots(volumes, mounted=lambda _: True, info=failed_info)



@pytest.mark.parametrize("running,returncode,expected", [
    ("true", 0, "CONTAINER_RUNNING_QUERY_FAILED"),
    ("false", 0, "CONTAINER_STOPPED"),
    ("secret-owner", 0, "DOCKER_INSPECT_UNAVAILABLE"),
])
def test_owner_failure_diagnostic_is_one_fixed_readonly_bit(monkeypatch,running,returncode,expected):
    import subprocess
    def run(args,**kwargs):
        assert args==["docker","inspect","--format","{{.State.Running}}","chat-mongodb"]
        assert kwargs["capture_output"] is True and kwargs["check"] is False
        return subprocess.CompletedProcess(args,returncode,running,"PRIVATE-SECRET-STDERR")
    monkeypatch.setattr(probe.subprocess,"run",run)
    state=probe._owner_service_state("docker")
    assert state==expected
    assert "PRIVATE" not in state


def test_owner_failure_diagnostic_timeout_is_unavailable(monkeypatch):
    import subprocess
    def run(args,**kwargs):
        raise subprocess.TimeoutExpired(args,8)
    monkeypatch.setattr(probe.subprocess,"run",run)
    assert probe._owner_service_state("docker")=="DOCKER_INSPECT_UNAVAILABLE"


@pytest.mark.parametrize("daemon_rc,daemon_stdout,expected", [
    (0, "28.0.1", "CONTAINER_UNAVAILABLE_DAEMON_OK"),
    (1, "", "DOCKER_DAEMON_INACCESSIBLE"),
    (0, "", "DOCKER_DAEMON_INACCESSIBLE"),
])
def test_missing_mongodb_vs_inaccessible_daemon_are_distinct(monkeypatch,daemon_rc,daemon_stdout,expected):
    import subprocess
    seen=[]
    def run(args,**kwargs):
        seen.append(args)
        if args[1]=="inspect":
            return subprocess.CompletedProcess(args,1,"","PRIVATE-SECRET")
        assert args == ["docker","info","--format","{{.ServerVersion}}"]
        return subprocess.CompletedProcess(args,daemon_rc,daemon_stdout,"PRIVATE-SECRET")
    monkeypatch.setattr(probe.subprocess,"run",run)
    assert probe._owner_service_state("docker")==expected
    assert len(seen)==2



def test_renamed_operator_binding_uses_actual_owner_config_without_name_guess(tmp_path):
    import os
    import plistlib
    home=tmp_path
    script=home/'immutable/p4/renamed_operator_live.py'
    script.parent.mkdir(parents=True)
    script.write_text('exact installed owner script')
    data=home/'Foundation'
    data.mkdir()
    config=home/'foundation-config.json'
    config.write_text(json.dumps({'data_dir':str(data)}))
    plist=home/'Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist'
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({
        'Label':'dev.quest7070.ai-foundation.operator',
        'ProgramArguments':['/usr/bin/python3','-B',str(script),'--config',str(config)]}))
    assert probe.installed_paths(home)==(script,data.resolve())
    (data/'human-model-bindings.json').write_text(
        json.dumps({'version':1,'bindings':[]}))
    observed=probe.inspect_installed_runtime(home)
    assert observed['operator_source_identified'] is True
    assert observed['existing_binding_config'] is True


def test_operator_binding_without_config_never_infers_data_root(tmp_path):
    import plistlib
    home=tmp_path
    script=home/'immutable/p4/renamed_operator_live.py'
    script.parent.mkdir(parents=True)
    script.write_text('source')
    plist=home/'Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist'
    plist.parent.mkdir(parents=True)
    plist.write_bytes(plistlib.dumps({
        'Label':'dev.quest7070.ai-foundation.operator',
        'ProgramArguments':['/usr/bin/python3',str(script)]}))
    assert probe.installed_paths(home) is None
    record=probe.inspect_installed_runtime(home)
    assert record['operator_source_identified'] is True
    assert record['existing_binding_config'] is False


def test_operator_binding_rejects_malicious_python_or_stale_plist(tmp_path):
    import plistlib
    home=tmp_path
    script=home/'immutable/p4/renamed_operator_live.py'
    script.parent.mkdir(parents=True)
    script.write_text('source')
    plist=home/'Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist'
    plist.parent.mkdir(parents=True)
    for args in (
        ['/usr/bin/python3','-c',str(script),'--config','/tmp/any.json'],
        ['/usr/bin/python3',str(script),str(script),'--config','/tmp/any.json'],
        ['/usr/bin/python3','../fake.py','--config','/tmp/any.json'],
    ):
        plist.write_bytes(plistlib.dumps({
            'Label':'dev.quest7070.ai-foundation.operator',
            'ProgramArguments':args}))
        assert probe.installed_paths(home) is None



def test_loader_source_requires_import_and_real_call(tmp_path):
    script=tmp_path/"renamed_operator_live.py"
    script.write_text("# build_human_model_context + install_legacy_agent_factory\n"
                      "def main():\n  pass\n")
    assert probe._loader_source_kind(script)=="UNVERIFIED"
    script.write_text("from ai_foundation.human_model_context import build_human_model_context\n"
                      "def main():\n  return build_human_model_context(None)\n")
    assert probe._loader_source_kind(script)=="DIRECT_OPERATOR_SOURCE"
    script.write_text("from ai_foundation.human_model_runtime import install_legacy_agent_factory\n"
                      "def main():\n  return install_legacy_agent_factory()\n")
    assert probe._loader_source_kind(script)=="ADDITIVE_LAUNCHER_SOURCE"
    script.write_text("from ai_foundation.human_model_context import build_human_model_context\n"
                      "def main():\n  return 42\n")
    assert probe._loader_source_kind(script)=="UNVERIFIED"
