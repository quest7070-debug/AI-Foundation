import hashlib
import json
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from ai_foundation.artifact import TEXT_ARTIFACT_MAX_BYTES
from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_execution import CapabilityExecutor
from ai_foundation.capability_request import AttachmentGrant, CapabilityRequest
from ai_foundation.core import GuardState
from ai_foundation.files_adapter import build_files
from ai_foundation.guard import GuardCore
from ai_foundation.protected_resources import ProtectedResources


class DiskPort:
    def __init__(self):
        self.writes = 0
        self.reads = 0
        self.lose_ack = False
        self.corrupt = False

    def execute(self, plan):
        self.writes += 1
        Path(plan.target).write_bytes((plan.text if not self.corrupt else 'wrong').encode('utf-8'))
        if self.lose_ack:
            raise ConnectionError('lost after writing')

    def observe(self, plan):
        self.reads += 1
        return Path(plan.target).read_bytes().decode('utf-8')


@pytest.fixture
def setup(tmp_path):
    output = tmp_path / 'output'
    output.mkdir()
    request = CapabilityRequest('FILES', owner_id='owner',
        file_read_root=str(tmp_path), file_write_root=str(output))
    port = DiskPort()
    guard = GuardCore(GuardState())
    return output, request, port, guard, CapabilityExecutor(None, guard, file_port=port)


def produce(setup, target='report.md', content='結果\n東京\r\n'):
    return json.loads(setup[-1].execute_text_artifact(setup[1], target, content, 'host-run'))


def test_real_guard_disk_output_and_independent_readback(setup):
    content = '結果\n東京\r\n'
    result = produce(setup, content=content)
    assert result == dict(target='report.md', status='VERIFIED_COMPLETE', verified=True,
        utf8_sha256=hashlib.sha256(content.encode()).hexdigest(), utf8_bytes=len(content.encode()))
    assert (setup[0] / 'report.md').read_bytes() == content.encode()
    assert setup[2].writes == 1 and setup[2].reads == 2
    effect = next(iter(setup[3].state.effects.values()))
    assert effect.run_id == 'host-run'


def test_same_target_retry_is_observe_only_and_new_content_cannot_reuse_effect(setup):
    assert produce(setup)['verified']
    assert produce(setup)['verified']
    assert produce(setup, content='different')['status'] == 'ARTIFACT_IDENTITY_CONFLICT'
    assert setup[2].writes == 1


def test_lost_ack_reconciles_without_repeating_write(setup):
    setup[2].lose_ack = True
    first = produce(setup)
    assert first['status'] == 'UNCERTAIN_RECONCILE_REQUIRED'
    assert first['verified'] is False and first['utf8_sha256'] is None
    assert produce(setup)['verified']
    assert setup[2].writes == 1


def test_failed_guard_verification_is_not_a_successful_artifact(setup):
    setup[2].corrupt = True
    result = produce(setup)
    assert result['status'] == 'FAILED_VERIFICATION'
    assert result['verified'] is False and result['utf8_sha256'] is None


@pytest.mark.parametrize('state', ['changed', 'deleted'])
def test_cached_guard_success_requires_current_readback(setup, state):
    assert produce(setup)['verified']
    path = setup[0] / 'report.md'
    if state == 'deleted':
        path.unlink()
    else:
        path.write_text('different', encoding='utf-8')
    result = produce(setup)
    assert result['verified'] is False and result['utf8_sha256'] is None
    assert result['status'] == ('ARTIFACT_READBACK_UNAVAILABLE' if state == 'deleted' else 'FAILED_ARTIFACT_READBACK')
    assert setup[2].writes == 1


def test_host_run_cancellation_is_not_lost_in_effect_identity(setup):
    setup[3].cancel('host-run')
    assert produce(setup)['status'] == 'DENY'
    assert setup[2].writes == 0


@pytest.mark.parametrize('target', ['../escape.md', '/tmp/escape.md'])
def test_escape_rejected_before_effect(setup, target):
    with pytest.raises(PermissionError):
        produce(setup, target)
    assert setup[2].writes == setup[2].reads == 0


def test_symlink_escape_rejected_before_effect(setup, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (setup[0] / 'escape').symlink_to(outside, target_is_directory=True)
    with pytest.raises(PermissionError):
        produce(setup, 'escape/report.md')
    assert setup[2].writes == 0


def test_protected_output_still_rejected(setup):
    setup[-1].protected = ProtectedResources((str(setup[0]),))
    with pytest.raises(PermissionError):
        produce(setup)
    assert setup[2].writes == 0


@pytest.mark.parametrize('target,content', [('x.pdf', 'text'), ('x.py', 'text'),
    ('x.md', 'あ' * (TEXT_ARTIFACT_MAX_BYTES // 3 + 1))])
def test_format_and_utf8_size_limits_precede_effect(setup, target, content):
    with pytest.raises(ValueError):
        produce(setup, target, content)
    assert setup[2].writes == setup[2].reads == 0


def test_read_only_and_attachment_authority_cannot_produce_output(setup):
    for request in [CapabilityRequest('FILES', file_read_root=str(setup[0])),
        CapabilityRequest('FILES', owner_id='owner', attachments=(
            AttachmentGrant('input', 'owner', str(setup[0] / 'input.txt')),))]:
        with pytest.raises(PermissionError):
            setup[-1].execute_text_artifact(request, 'report.md', 'text', 'run')
    readonly = build_files(CapabilityRequest('FILES', file_read_root=str(setup[0])), setup[3], setup[2])
    with pytest.raises(PermissionError):
        readonly.produce_text_artifact('run', 'report.md', 'text')
    assert setup[2].writes == 0


def test_only_authenticated_explicit_write_request_exposes_tool(setup):
    for req in [CapabilityRequest('CHAT', owner_id='owner', file_read_root=str(setup[0])),
        CapabilityRequest('CHAT', file_read_root=str(setup[0]), file_write_root=str(setup[0])),
        CapabilityRequest('CHAT', owner_id='owner', file_read_root=str(setup[0]), file_write_root=str(setup[0]), long_running=True)]:
        agent = AutoCapabilityAgent(TestModel(call_tools=[]), setup[-1], req)
        assert 'create_text_artifact' not in agent.port.agent._function_toolset.tools
        with pytest.raises(PermissionError):
            agent.create_text_artifact('report.md', 'text')
    assert setup[2].writes == 0


def test_agent_uses_write_root_without_inheriting_input_attachments(setup):
    from dataclasses import replace
    req = replace(setup[1], capability='CHAT', attachments=(
        AttachmentGrant('input', 'owner', str(setup[0].parent / 'input.txt')),))
    class RecordingExecutor(CapabilityExecutor):
        def execute_text_artifact(self, request, target, content, run_id):
            assert not request.attachments and not request.attachment_ids
            assert request.file_write_root == str(setup[0])
            return super().execute_text_artifact(request, target, content, run_id)
    executor = RecordingExecutor(None, setup[3], file_port=setup[2])
    agent = AutoCapabilityAgent(TestModel(call_tools=[]), executor, req, run_id='host-run')
    schema = agent.port.agent._function_toolset.tools['create_text_artifact'].function_schema.json_schema
    assert set(schema['properties']) == {'target', 'content'}
    assert json.loads(agent.create_text_artifact('report.md', 'text'))['verified']
    assert not (setup[0].parent / 'report.md').exists()


def test_model_tool_loop_returns_observed_artifact_metadata(setup, monkeypatch):
    from dataclasses import replace
    from pydantic_ai import models
    from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel
    monkeypatch.setattr(models, 'ALLOW_MODEL_REQUESTS', False)
    def model(messages, info):
        returned = [part for message in messages if isinstance(message, ModelRequest)
            for part in message.parts if isinstance(part, ToolReturnPart)]
        if not returned:
            return ModelResponse(parts=[ToolCallPart('create_text_artifact',
                {'target': 'summary.md', 'content': 'observed text'})])
        return ModelResponse(parts=[TextPart(returned[-1].content)])
    agent = AutoCapabilityAgent(FunctionModel(model), setup[-1], replace(setup[1], capability='CHAT'), run_id='host-run')
    result = json.loads(agent.run('Save the summary as a file.'))
    assert result['target'] == 'summary.md' and result['verified']
    assert setup[2].writes == 1


def test_distinct_unbound_agent_requests_do_not_share_effect_ids(setup):
    from dataclasses import replace
    req = replace(setup[1], capability='CHAT')
    agents = [AutoCapabilityAgent(TestModel(call_tools=[]), setup[-1], req) for _ in range(2)]
    assert agents[0]._artifact_run_id != agents[1]._artifact_run_id
    assert all(json.loads(a.create_text_artifact('report.md', 'text'))['verified'] for a in agents)
    assert setup[2].writes == 2


def test_sqlite_restart_reconciles_once_and_preserves_original_recipe(setup, tmp_path):
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.reconciliation_registry import SQLiteReconciliationRegistry
    store = SQLiteGuardStore(tmp_path / 'guard.sqlite3')
    registry = SQLiteReconciliationRegistry(tmp_path / 'recipes.sqlite3')
    executor = CapabilityExecutor(None, GuardCore(store.runtime_state(), store=store),
        file_port=setup[2], reconciliation_registry=registry, file_port_binding='disk')
    setup[2].lose_ack = True
    first = json.loads(executor.execute_text_artifact(setup[1], 'report.md', 'original', 'stable-host-run'))
    assert first['status'] == 'UNCERTAIN_RECONCILE_REQUIRED'
    effect_id = next(iter(store.load().effects))
    recipe = registry.load(effect_id)

    reopened = SQLiteGuardStore(tmp_path / 'guard.sqlite3')
    executor = CapabilityExecutor(None, GuardCore(reopened.runtime_state(), store=reopened),
        file_port=setup[2], reconciliation_registry=registry, file_port_binding='disk')
    conflict = json.loads(executor.execute_text_artifact(setup[1], 'report.md', 'changed', 'stable-host-run'))
    assert conflict['status'] == 'ARTIFACT_IDENTITY_CONFLICT'
    assert registry.load(effect_id) == recipe
    assert json.loads(executor.execute_text_artifact(setup[1], 'report.md', 'original', 'stable-host-run'))['verified']
    assert setup[2].writes == 1
    assert reopened.get_effect(effect_id).expected == 'original'


def test_guard_policy_denial_is_preserved(setup):
    from ai_foundation.core import Decision
    class Policy:
        def authorize(self, plan): return Decision.DENY
    setup[3].policy_boundary = Policy()
    assert produce(setup)['status'] == 'DENY'
    assert setup[2].writes == 0


def test_activity_cleanup_and_content_free_trace_on_failure(setup):
    from ai_foundation.execution_activity import ExecutionActivityRegistry
    from ai_foundation.observability import InMemoryTraceSink, Tracer
    activity = ExecutionActivityRegistry()
    sink = InMemoryTraceSink()
    setup[-1].activity = activity
    setup[-1].tracer = Tracer(sink)
    with pytest.raises(PermissionError):
        produce(setup, '../escape.md', 'do not log this content')
    assert activity.current() == ()
    assert len(sink.events) == 1 and sink.events[0].status == 'ERROR'
    assert sink.events[0].attributes == {'run_id': 'host-run', 'capability': 'FILES'}


def test_existing_observed_guard_remains_replaceable(setup):
    from ai_foundation.instrumentation import ObservedGuard
    from ai_foundation.observability import InMemoryTraceSink, Tracer
    sink = InMemoryTraceSink()
    setup[-1].guard = ObservedGuard(setup[3], Tracer(sink))
    assert produce(setup)['verified']
    assert produce(setup, content='changed')['status'] == 'ARTIFACT_IDENTITY_CONFLICT'
    assert setup[2].writes == 1
    assert len(sink.events) == 1 and sink.events[0].name == 'guard.execute'
