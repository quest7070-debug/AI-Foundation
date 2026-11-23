"""Directory discovery stays inside the existing observational FILES boundary."""
import json
from pathlib import Path
from subprocess import CompletedProcess

import pytest
from pydantic_ai.models.test import TestModel

from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import AttachmentGrant, CapabilityRequest
from ai_foundation.core import GuardState
from ai_foundation.files_adapter import build_files
from ai_foundation.guard import GuardCore
from ai_foundation.toolhive import ToolHiveFilesystemPort


def request(root):
    return CapabilityRequest('FILES', owner_id='owner', file_read_root=str(root), file_operation='list_directory')


class ListingPort:
    def __init__(self): self.calls = []
    def observe(self, plan):
        self.calls.append(plan)
        assert plan.action == 'list_directory'
        return '[FILE] note.txt\n[DIR] reports'
    def execute(self, plan): raise AssertionError('listing must not execute an effect')


def test_list_then_read_discovery_uses_normalized_host_root_without_effects(tmp_path):
    (tmp_path / 'note.txt').write_text('OBSERVED_NOTE')
    state = GuardState()
    class Port(ListingPort):
        def observe(self, plan):
            if plan.action == 'read': return Path(plan.target).read_text()
            return super().observe(plan)
    port = Port()
    executor = CapabilityExecutor(None, GuardCore(state), file_port=port)
    assert '[FILE] note.txt' in executor.execute(request(tmp_path), '.', 'listing')
    assert port.calls[0].target == str(tmp_path.resolve())
    assert executor.execute(CapabilityRequest('FILES', file_read_root=str(tmp_path)), 'note.txt', 'read') == 'OBSERVED_NOTE'
    assert not state.effects


@pytest.mark.parametrize('target', ['../outside', '/etc'])
def test_listing_escape_is_denied_before_port(tmp_path, target):
    port = ListingPort()
    files = build_files(request(tmp_path), GuardCore(GuardState()), port)
    with pytest.raises(PermissionError): files.list_directory('run', target)
    assert port.calls == []


def test_listing_symlink_escape_is_denied_before_port(tmp_path):
    root = tmp_path / 'allowed'; root.mkdir()
    other = tmp_path / 'outside'; other.mkdir()
    (root / 'link').symlink_to(other, target_is_directory=True)
    port = ListingPort()
    with pytest.raises(PermissionError):
        build_files(request(root), GuardCore(GuardState()), port).list_directory('run', 'link')
    assert not port.calls


def test_attachment_or_repository_alone_cannot_grant_directory_discovery(tmp_path):
    grant = AttachmentGrant('f', 'owner', str(tmp_path / 'upload.txt'))
    for authority in ({'attachments': (grant,)}, {'repo_root': str(tmp_path)}, {}):
        with pytest.raises(ValueError):
            CapabilityRequest('FILES', owner_id='owner', file_operation='list_directory', **authority)


@pytest.mark.parametrize('operation', ['write', 'search_files', 'directory_tree', '', None, []])
def test_unsupported_files_operation_is_not_authority(operation, tmp_path):
    with pytest.raises(ValueError):
        CapabilityRequest('FILES', file_read_root=str(tmp_path), file_operation=operation)


def test_non_files_capability_cannot_carry_listing_operation(tmp_path):
    with pytest.raises(ValueError):
        CapabilityRequest('CHAT', file_read_root=str(tmp_path), file_operation='list_directory')


def test_agent_exposes_listing_only_for_explicit_general_read_root(tmp_path):
    class NoExec:
        def execute(self, *args): raise AssertionError('construction cannot execute')
    grant = AttachmentGrant('f', 'owner', str(tmp_path / 'upload.txt'))
    for authority in ({}, {'repo_root': str(tmp_path)}, {'attachments': (grant,)},
                      {'attachments': (grant,), 'file_read_root': str(tmp_path)}):
        agent = AutoCapabilityAgent(TestModel(call_tools=[]), NoExec(), CapabilityRequest(owner_id='owner', **authority))
        assert 'list_files' not in agent.port.agent._function_toolset.tools
    agent = AutoCapabilityAgent(TestModel(call_tools=[]), NoExec(), CapabilityRequest(owner_id='owner', file_read_root=str(tmp_path)))
    tool = agent.port.agent._function_toolset.tools['list_files']
    assert set(tool.function_schema.json_schema['properties']) == {'target'}


def test_real_pydantic_agent_calls_host_bound_listing(tmp_path):
    port = ListingPort()
    state = GuardState()
    executor = CapabilityExecutor(None, GuardCore(state), file_port=port)
    agent = AutoCapabilityAgent(TestModel(call_tools=['list_files']), executor,
                                CapabilityRequest(owner_id='owner', file_read_root=str(tmp_path)))
    assert 'note.txt' in agent.run('作業フォルダには何がある？')
    assert len(port.calls) == 1 and not state.effects


def test_attachment_mode_cannot_switch_to_directory_browsing_even_with_root(tmp_path):
    grant = AttachmentGrant('f', 'owner', str(tmp_path / 'missing-upload'))
    with pytest.raises(ValueError, match='attachment mode'):
        CapabilityRequest('FILES', owner_id='owner', attachments=(grant,),
                           file_read_root=str(tmp_path), file_operation='list_directory')


def test_toolhive_listing_maps_only_the_fixed_readonly_mcp_tool(tmp_path, monkeypatch):
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return CompletedProcess(argv, 0, json.dumps({'content': [{'type': 'text', 'text': '[FILE] 日本語.txt'}]}), '')
    monkeypatch.setattr('ai_foundation.toolhive.subprocess.run', run)
    port = ToolHiveFilesystemPort('/pinned/thv', 'host-files', tmp_path)
    files = build_files(request(tmp_path), None, port)
    assert files.list_directory('run', '.') == '[FILE] 日本語.txt'
    argv, options = calls[0]
    assert argv[:4] == ['/pinned/thv', 'mcp', 'call', 'list_directory']
    assert argv[argv.index('--server') + 1] == 'host-files'
    assert json.loads(argv[-1]) == {'path': '/projects/.'}
    assert options['timeout'] == 30 and len(calls) == 1


@pytest.mark.parametrize('result', [
    {'isError': True, 'content': [{'type': 'text', 'text': 'PRIVATE_FAILURE'}]},
    {'isError': 'false', 'content': [{'type': 'text', 'text': 'PRIVATE_FAILURE'}]},
    {}, {'content': []}, {'content': 'PRIVATE_FAILURE'},
    {'content': [{'type': 'image', 'data': 'PRIVATE_FAILURE'}]},
    {'content': [{'type': 'text', 'text': None}]},
    {'content': [{'type': 'text', 'text': '界' * 11000}]},
])
def test_invalid_or_oversized_listing_is_not_success_or_partial_output(tmp_path, monkeypatch, result):
    port = ToolHiveFilesystemPort('/pinned/thv', 'host-files', tmp_path)
    monkeypatch.setattr(port, '_call', lambda *args: result)
    with pytest.raises(RuntimeError) as error:
        build_files(request(tmp_path), None, port).list_directory('run', '.')
    assert 'PRIVATE_FAILURE' not in str(error.value)


def test_empty_directory_is_a_valid_empty_text_observation(tmp_path, monkeypatch):
    port = ToolHiveFilesystemPort('/pinned/thv', 'host-files', tmp_path)
    monkeypatch.setattr(port, '_call', lambda *args: {'content': [{'type': 'text', 'text': ''}]})
    assert build_files(request(tmp_path), None, port).list_directory('run', '.') == ''


def test_list_non_directory_fails_before_mcp(tmp_path, monkeypatch):
    (tmp_path / 'file.txt').write_text('body')
    port = ToolHiveFilesystemPort('/pinned/thv', 'host-files', tmp_path)
    monkeypatch.setattr(port, '_call', lambda *args: pytest.fail('MCP must not be called'))
    with pytest.raises(NotADirectoryError):
        build_files(request(tmp_path), None, port).list_directory('run', 'file.txt')


def test_port_mount_is_a_second_independent_listing_scope(tmp_path, monkeypatch):
    mount = tmp_path / 'mount'; mount.mkdir()
    port = ToolHiveFilesystemPort('/pinned/thv', 'host-files', mount)
    monkeypatch.setattr(port, '_call', lambda *args: pytest.fail('MCP must not be called'))
    with pytest.raises(ValueError, match='outside ToolHive mount'):
        build_files(request(tmp_path), None, port).list_directory('run', '.')


def test_agent_discovers_reads_then_analyzes_observed_file_with_real_tool_loop(tmp_path, monkeypatch):
    import ast
    from pydantic_ai import models
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel

    monkeypatch.setattr(models, 'ALLOW_MODEL_REQUESTS', False)
    name = '集計-20261104.json'
    (tmp_path / name).write_text('[3,7,11]')
    calls = []

    def mcp(tool, args):
        calls.append((tool, args))
        if tool == 'list_directory':
            assert args == {'path': '/projects/.'}
            text = '[FILE] ' + name
        else:
            assert tool == 'read_text_file' and args == {'path': '/projects/' + name}
            text = (tmp_path / name).read_text()
        return {'content': [{'type': 'text', 'text': text}]}

    port = ToolHiveFilesystemPort('/fixture/thv', 'fixed-files', tmp_path)
    monkeypatch.setattr(port, '_call', mcp)
    def model(messages, info):
        returned = [p for m in messages if isinstance(m, ModelRequest)
                    for p in m.parts if isinstance(p, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart('list_files', {'target': '.'})])
        if len(returned) == 1:
            observed_name = returned[-1].content.removeprefix('[FILE] ')
            return ModelResponse(parts=[ToolCallPart('files', {'target': observed_name})])
        if len(returned) == 2:
            return ModelResponse(parts=[ToolCallPart('data', {'value': json.loads(returned[-1].content)})])
        assert [r.tool_name for r in returned] == ['list_files', 'files', 'data']
        assert ast.literal_eval(returned[-1].content)['mean'] == 7
        return ModelResponse(parts=[TextPart(returned[-1].content)])

    state = GuardState()
    agent = AutoCapabilityAgent(FunctionModel(model), CapabilityExecutor(None, GuardCore(state), file_port=port),
                                CapabilityRequest(owner_id='owner', file_read_root=str(tmp_path), data_operation='json_summary'))
    assert ast.literal_eval(agent.run('フォルダのJSONを探して数値を集計して'))['mean'] == 7
    assert len(calls) == 2 and not state.effects


def test_discovered_outside_name_does_not_gain_read_authority(tmp_path):
    root = tmp_path / 'scope'; root.mkdir()
    (tmp_path / 'private.txt').write_text('PRIVATE_CONTENT')
    port = ListingPort()
    executor = CapabilityExecutor(None, None, file_port=port)
    executor.execute(request(root), '.', 'list')
    with pytest.raises(PermissionError):
        executor.execute(CapabilityRequest('FILES', file_read_root=str(root)), '../private.txt', 'read')
    assert len(port.calls) == 1


def test_agent_listing_method_cannot_mint_root_when_not_exposed():
    class NoExec:
        def execute(self, *args): raise AssertionError('no grant, no port call')
    agent = AutoCapabilityAgent(TestModel(call_tools=[]), NoExec(), CapabilityRequest())
    with pytest.raises(ValueError): agent.list_files('.')
