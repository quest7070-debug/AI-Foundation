from pathlib import Path
from types import SimpleNamespace
import pytest
from ai_foundation.capability_composition import build_capability_composition

def test_shared_composition_binds_exact_host_roots_and_servers(tmp_path):
 repo=tmp_path/'repo';repo.mkdir();thv=repo/'.tools/toolhive/thv';thv.parent.mkdir(parents=True);thv.write_text('x')
 tools=tmp_path/'tools';tools.mkdir();data=tmp_path/'data';data.mkdir()
 workspace=tmp_path/'trusted-workspace';workspace.mkdir()
 c=SimpleNamespace(toolhive_server='files-server')
 x=build_capability_composition(repo_base=repo,data_root=data,config=c,inference='i',guard='g',reconciliation_registry='r',env={'AI_FOUNDATION_TOOLHIVE_ROOT':str(tools),'AI_FOUNDATION_TOOLHIVE_REPO_SERVER':'repo-server','AI_FOUNDATION_REPO_ROOT':str(workspace)},thv_path=thv)
 assert x.file_port.server=='files-server' and x.repo_port.server=='repo-server'
 assert x.executor.file_port is x.file_port and x.executor.repo_port is x.repo_port
 assert x.tool_root==tools.resolve() and x.repo_root==workspace.resolve()
def test_shared_composition_fails_closed_without_runtime(tmp_path):
 with pytest.raises(RuntimeError):build_capability_composition(repo_base=tmp_path,data_root=tmp_path,config=SimpleNamespace(toolhive_server='x'),inference=None,guard=None,reconciliation_registry=None,env={},thv_path=tmp_path/'missing')


def test_shared_composition_registers_only_observational_browser_tools(tmp_path):
 repo=tmp_path/'repo';repo.mkdir();thv=repo/'.tools/toolhive/thv';thv.parent.mkdir(parents=True);thv.write_text('x')
 tools=tmp_path/'tools';tools.mkdir();data=tmp_path/'data';data.mkdir()
 x=build_capability_composition(repo_base=repo,data_root=data,config=SimpleNamespace(toolhive_server='files'),inference='i',guard='g',reconciliation_registry='r',env={'AI_FOUNDATION_TOOLHIVE_ROOT':str(tools),'AI_FOUNDATION_BROWSER_SERVER':'playwright'},thv_path=thv)
 grant=x.executor.mcp_registry._grants['browser-main']
 assert grant.server=='playwright'
 assert grant.allowed_tools==frozenset({'browser_console_messages','browser_network_request','browser_network_requests','browser_snapshot','browser_take_screenshot','browser_wait_for'})
 assert 'browser_navigate' not in grant.allowed_tools
 assert 'browser_tabs' not in grant.allowed_tools
 assert 'browser_run_code_unsafe' not in grant.allowed_tools


def test_shared_composition_registers_minimal_compute_tool_only(tmp_path):
 repo=tmp_path/'repo';repo.mkdir();thv=repo/'.tools/toolhive/thv';thv.parent.mkdir(parents=True);thv.write_text('x')
 tools=tmp_path/'tools';tools.mkdir();data=tmp_path/'data';data.mkdir()
 x=build_capability_composition(repo_base=repo,data_root=data,config=SimpleNamespace(toolhive_server='files'),inference='i',guard='g',reconciliation_registry='r',env={'AI_FOUNDATION_TOOLHIVE_ROOT':str(tools),'AI_FOUNDATION_COMPUTE_SERVER':'jupyter'},thv_path=thv)
 grant=x.executor.mcp_registry._grants['compute-main']
 assert grant.server=='jupyter'
 assert grant.allowed_tools==frozenset({'execute_code'})
 assert 'connect_to_jupyter' not in grant.allowed_tools
 assert 'restart_notebook' not in grant.allowed_tools


def test_composition_registers_duckdb_data_grant_without_widening_baseline(tmp_path,monkeypatch):
 from ai_foundation.capability_request import CapabilityRequest
 from ai_foundation.capability_composition import build_capability_composition
 from pathlib import Path
 repo=tmp_path/'repo';repo.mkdir();root=tmp_path/'toolhive';root.mkdir();thv=repo/'.tools/toolhive/thv';thv.parent.mkdir(parents=True);thv.write_text('')
 class Config: toolhive_server='files'
 composition=build_capability_composition(repo_base=repo,data_root=tmp_path,config=Config(),inference=None,guard=None,reconciliation_registry=None,env={'AI_FOUNDATION_TOOLHIVE_ROOT':str(root),'AI_FOUNDATION_DATA_SERVER':'duckdb-server'},thv_path=thv)
 grant=composition.executor.mcp_registry._grants['data-duckdb']
 assert grant.server=='duckdb-server'
 assert 'query' in grant.allowed_tools and 'save_query' not in grant.allowed_tools and 'execute_code' not in grant.allowed_tools
 assert CapabilityRequest('DATA',data_operation='json_summary').data_backend==''


def test_shared_composition_recreates_missing_ephemeral_files_root(tmp_path):
 repo=tmp_path/'repo';repo.mkdir();thv=repo/'.tools/toolhive/thv';thv.parent.mkdir(parents=True);thv.write_text('x')
 tools=tmp_path/'reboot-cleared'/'toolhive';data=tmp_path/'data';data.mkdir()
 x=build_capability_composition(repo_base=repo,data_root=data,config=SimpleNamespace(toolhive_server='files-server'),inference='i',guard='g',reconciliation_registry='r',env={'AI_FOUNDATION_TOOLHIVE_ROOT':str(tools)},thv_path=thv)
 assert tools.is_dir()
 assert x.tool_root==tools.resolve()



def test_installed_composition_never_binds_code_to_immutable_release_by_default(tmp_path):
 repo=tmp_path/'candidate';repo.mkdir()
 data=tmp_path/'private-data';data.mkdir()
 thv=tmp_path/'thv';thv.write_text('synthetic')
 from types import SimpleNamespace
 config=SimpleNamespace(toolhive_server='files-server')
 out=build_capability_composition(
     repo_base=repo,data_root=data,config=config,
     inference=None,guard=None,reconciliation_registry=None,
     env={'AI_FOUNDATION_TOOLHIVE_ROOT':str(tmp_path/'ephemeral-files')},
     thv_path=thv)
 assert out.file_port is not None
 assert out.repo_port is None and out.repo_root is None
 assert out.executor.repo_port is None
 with pytest.raises(ValueError,match='distinct'):
  build_capability_composition(
      repo_base=repo,data_root=data,config=config,
      inference=None,guard=None,reconciliation_registry=None,
      env={'AI_FOUNDATION_REPO_ROOT':str(repo)},thv_path=thv)
 with pytest.raises(ValueError,match='distinct'):
  build_capability_composition(
      repo_base=repo,data_root=data,config=config,
      inference=None,guard=None,reconciliation_registry=None,
      env={'AI_FOUNDATION_REPO_ROOT':str(tmp_path)},thv_path=thv)
