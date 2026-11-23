import importlib.util
import io
import json
from pathlib import Path
import sys
import plistlib

import pytest

sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
spec = importlib.util.spec_from_file_location('publication_host',
    Path(__file__).parents[1]/'scripts/m1_human_model_publish_development.py')
host = importlib.util.module_from_spec(spec)
spec.loader.exec_module(host)


def test_owner_configuration_is_read_back_and_never_overwrites_another_binding(tmp_path):
    path = tmp_path/'binding.json'
    first = {'version':1,'bindings':[{'owner_id':'actual-owner'}]}
    assert host.atomic_create_json(path,first)
    assert not host.atomic_create_json(path,first)
    with pytest.raises(ValueError):
        host.atomic_create_json(path,{'version':1,'bindings':[{'owner_id':'other-owner'}]})
    assert json.loads(path.read_text()) == first


def test_existing_index_inventory_only_allows_admitted_pinned_9b(monkeypatch):
    from ai_foundation import shared_ollama9b_adapter as adapter
    from ai_foundation.local_compute_registry import LocalComputeCandidate
    class Discovery:
        online = False
        def __call__(self):
            return (LocalComputeCandidate(
                "local:ollama-shared9b:general",
                health="ONLINE" if self.online else "UNAVAILABLE",
                model=adapter.MODEL, slot="general", same_host=True),)
    discovery = Discovery()
    monkeypatch.setattr(adapter, "SharedOllama9BDiscovery", lambda: discovery)
    with pytest.raises(RuntimeError, match="EXISTING_PINNED_9B_UNAVAILABLE"):
        host.installed_index_model()
    discovery.online = True
    assert host.installed_index_model() == adapter.MODEL
    # Older local LLM aliases are never eligible as the indexing model.
    assert host.installed_index_model() != "qwen3.5:4b"


@pytest.mark.parametrize('relative',[False,True])
def test_binding_uses_canonical_operator_state_not_actions_working_directory(tmp_path,relative):
    home = tmp_path/'home'; agents = home/'Library/LaunchAgents'; agents.mkdir(parents=True)
    working = tmp_path/'operator'; working.mkdir(); data = working/'state'; data.mkdir()
    config = working/'config.json'
    config.write_text(json.dumps({'data_dir':'state' if relative else str(data)}))
    row = {'ProgramArguments':['python','scripts/operator_server.py','--config',str(config)],
           'WorkingDirectory':str(working)}
    (agents/'dev.quest7070.ai-foundation.operator.plist').write_bytes(plistlib.dumps(row))
    assert host.existing_binding_path(home) == data/'human-model-bindings.prepared.json'
