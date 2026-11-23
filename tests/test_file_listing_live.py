"""Opt-in acceptance against a pinned M1 filesystem workload.

Creates/removes only its own synthetic fixture inside the verified existing mount.
Never provisions, starts, stops or modifies a workload or performs inference.
"""
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('AI_FOUNDATION_FILES_LISTING_LIVE') != '1' and
    os.environ.get('AI_FOUNDATION_FILES_LISTING_ISOLATED') != '1',
    reason='pinned M1 ToolHive workload acceptance is opt-in',
)


def _verify_tool_loop(monkeypatch, thv, mount, server, *, read_only=False):
    import ast
    import json
    from pathlib import Path
    import re
    import subprocess
    import tempfile

    from pydantic_ai import models
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel
    from ai_foundation.auto_agent import AutoCapabilityAgent
    from ai_foundation.capability_execution import CapabilityExecutor
    from ai_foundation.capability_request import CapabilityRequest
    from ai_foundation.core import GuardState
    from ai_foundation.guard import GuardCore
    from ai_foundation.toolhive import ToolHiveFilesystemPort

    expected_image = 'sha256:720393842ef8b0f33713a42e2eebda51ff600756c19d53e1244645ec59496fef'

    def observe_command(argv):
        result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
        if result.returncode:
            raise RuntimeError('existing filesystem workload prerequisite unavailable; no lifecycle action attempted')
        return result.stdout

    assert thv.is_file() and mount.is_dir(), 'existing pinned CLI/mount required'
    assert '0.49.0' in observe_command([str(thv), 'version'])
    status = observe_command([str(thv), 'status', server])
    assert re.search(r'^\s*status:\s*running\s*$', status, re.I | re.M), 'existing workload must already be running'
    identity = observe_command(['docker', 'inspect', '--format', '{{.Image}} {{.State.Running}}', server]).strip()
    assert identity == expected_image + ' true', 'existing workload image/running identity mismatch'
    mounts = json.loads(observe_command(['docker', 'inspect', '--format', '{{json .Mounts}}', server]))
    selected = [m for m in mounts if m.get('Destination') == '/projects']
    assert len(selected) == 1 and selected[0].get('Type') == 'bind', 'expected fixed project bind required'
    assert Path(selected[0]['Source']).resolve() == mount, 'existing mount differs from the approved synthetic fixture root'
    if read_only:
        assert selected[0].get('RW') is False, 'isolated MCP fixture mount must be read-only'

    class RecordingPort(ToolHiveFilesystemPort):
        def __init__(self):
            super().__init__(thv, server, mount)
            self.calls = []
        def _invoke(self, tool, args):
            self.calls.append(tool)
            return super()._invoke(tool, args)
        def execute(self, plan):
            raise AssertionError('observational acceptance must never execute an effect')

    monkeypatch.setattr(models, 'ALLOW_MODEL_REQUESTS', False)
    port = RecordingPort()
    state = GuardState()
    executor = CapabilityExecutor(None, GuardCore(state), file_port=port)
    observed = []
    with tempfile.TemporaryDirectory(prefix='foundation-files-pr183-', dir=mount) as owned:
        fixture = Path(owned)
        # All contents are synthetic; permit the adopted container's runtime UID
        # to traverse this owned fixture through its read-only bind.
        fixture.chmod(0o755)
        allowed = fixture / 'allowed'
        allowed.mkdir()
        (allowed / 'empty').mkdir()
        name = '集計.json'
        (allowed / name).write_text('[3,7,11]', encoding='utf-8')
        (fixture / 'outside.txt').write_text('SYNTHETIC_OUTSIDE_SCOPE', encoding='utf-8')
        (allowed / 'escape').symlink_to(fixture / 'outside.txt')

        def choose_tool(messages, info):
            returned = [p for m in messages if isinstance(m, ModelRequest)
                        for p in m.parts if isinstance(p, ToolReturnPart)]
            if not returned:
                return ModelResponse(parts=[ToolCallPart('list_files', {'target': '.'})])
            if len(returned) == 1:
                listing = returned[-1].content
                rows = listing.splitlines()
                assert '[FILE] ' + name in rows and '[DIR] empty' in rows
                observed.append('listing')
                selected_name = next(row.removeprefix('[FILE] ') for row in rows if row == '[FILE] ' + name)
                return ModelResponse(parts=[ToolCallPart('files', {'target': selected_name})])
            if len(returned) == 2:
                value = json.loads(returned[-1].content)
                assert value == [3, 7, 11], 'real MCP readback differs from seeded fixture'
                observed.append('readback')
                return ModelResponse(parts=[ToolCallPart('data', {'value': value})])
            assert [r.tool_name for r in returned] == ['list_files', 'files', 'data']
            observed.append('data')
            return ModelResponse(parts=[TextPart(returned[-1].content)])

        agent = AutoCapabilityAgent(FunctionModel(choose_tool), executor,
                                    CapabilityRequest(owner_id='fixture-owner', file_read_root=str(allowed), data_operation='json_summary'))
        result = ast.literal_eval(agent.run('フォルダのJSONを見つけ、数値を集計する'))
        assert result['count'] == 3 and result['mean'] == 7
        assert observed == ['listing', 'readback', 'data']
        listing_request = CapabilityRequest('FILES', file_read_root=str(allowed), file_operation='list_directory')
        assert executor.execute(listing_request, 'empty', 'live-empty-directory') == ''
        before_denial = len(port.calls)
        for target in ('..', '../outside.txt', 'escape'):
            with pytest.raises(PermissionError):
                executor.execute(listing_request, target, 'live-denied-list')
        with pytest.raises(PermissionError):
            executor.execute(CapabilityRequest('FILES', file_read_root=str(allowed)), 'escape', 'live-denied-read')
        assert len(port.calls) == before_denial, 'denied target reached the MCP boundary'
        assert port.calls == ['list_directory', 'read_text_file', 'list_directory']
        assert not state.effects

    assert not Path(owned).exists(), 'synthetic fixture cleanup incomplete'
    print(json.dumps({'result': 'FILES_LIST_READ_DATA_LIVE_VERIFIED', 'listing_calls': 2,
                      'read_calls': 1, 'mean': 7, 'denials_before_mcp': 4,
                      'guard_effects': 0, 'fixture_removed': True}))


def test_existing_toolhive_list_read_data_and_scope_denials(monkeypatch):
    if os.environ.get('AI_FOUNDATION_FILES_LISTING_LIVE') != '1':
        pytest.skip('existing production-workload observation is separately opt-in')
    from pathlib import Path
    repo = Path(__file__).resolve().parents[1]
    _verify_tool_loop(monkeypatch, repo / '.tools/toolhive/thv',
                      Path('/tmp/ai-foundation-toolhive').resolve(), 'ai-foundation-fs')


def test_isolated_toolhive_list_read_data_and_scope_denials(monkeypatch):
    if os.environ.get('AI_FOUNDATION_FILES_LISTING_ISOLATED') != '1':
        pytest.skip('isolated workload acceptance is separately opt-in')
    from pathlib import Path
    import re
    server = os.environ['AI_FOUNDATION_FILES_PROBE_SERVER']
    assert re.fullmatch(r'foundation-files-pr183-\d+-\d+', server)
    mount = Path(os.environ['AI_FOUNDATION_FILES_PROBE_ROOT']).resolve()
    mount.relative_to(Path(os.environ['RUNNER_TEMP']).resolve())
    assert mount.name.startswith('foundation-files-pr183-')
    repo = Path(__file__).resolve().parents[1]
    _verify_tool_loop(monkeypatch, repo / '.tools/toolhive/thv', mount, server, read_only=True)
