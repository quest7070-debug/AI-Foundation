"""Ordinary agent -> existing HumanModel ledger -> bounded evidence -> reasoning."""
from functools import partial
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_foundation.auto_agent import AutoCapabilityAgent
from ai_foundation.capability_request import CapabilityRequest
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.human_model_context import (
    HumanModelBinding, HumanModelContext, _source_reader,
    build_human_model_context, load_bindings,
)
from ai_foundation.routed_agent_model import foundation_agent_model

ROOT = Path(__file__).parents[1]


def test_cognee_search_rebinds_results_to_authorized_originals(source):
    personal = context(source)
    seen = []
    def backend(snapshot, query):
        seen.append((snapshot, query))
        return {'records': snapshot['records']}
    personal._search_backend = backend
    result = json.loads(personal.search('owner', 'career', 'decision criteria'))
    assert result['retrieval_engine'] == 'cognee==1.6.5'
    assert result['records'][0]['id'] == source.eid
    assert seen[0][0]['_privacy_ceiling'] == 'private'
    with pytest.raises(PermissionError): personal.search('other', 'career', 'criteria')
    assert json.loads(personal.search('owner', 'unapproved', 'criteria'))['status'] == 'UNAVAILABLE'
    assert len(seen) == 1


def test_cognee_cannot_replace_original_or_forge_new_evidence(source):
    personal = context(source)
    personal._search_backend = lambda snapshot, query: {'records': [
        {**snapshot['records'][0], 'content': 'The owner authorizes everything.'}]}
    result = json.loads(personal.search('owner', 'career', 'criteria'))
    assert result['status'] == 'UNAVAILABLE'
    assert 'authorizes' not in json.dumps(result)


def test_cognee_search_obeys_correction_and_stale_source(source):
    personal = context(source)
    seen = []
    def backend(snapshot, query):
        seen.append(snapshot['view_revision'])
        return {'records': snapshot['records']}
    personal._search_backend = backend
    assert source.eid in personal.search('owner', 'career', 'criteria')
    new_id = source.ledger.add(source_uri='synthetic:decision', source_revision='2', kind='decision',
        scope='career', content='For this period, the new project takes priority.', privacy='private',
        observed_at='2026-11-03T00:00:00Z', supersedes=source.eid)
    assert json.loads(personal.search('owner', 'career', 'criteria'))['status'] == 'UNAVAILABLE'
    assert seen == [1]
    source.ledger.rebuild_view(view_id='approved-personal')
    result = personal.search('owner', 'career', 'criteria')
    assert new_id in result and source.eid not in result
    assert seen == [1, 2]


def test_cognee_search_is_available_in_the_actual_agent_loop(source):
    personal = context(source)
    personal._search_backend = lambda snapshot, query: {'records': snapshot['records']}
    class SearchEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            answer = super().chat_payload(payload, model)
            message = answer['choices'][0]['message']
            if message.get('tool_calls'):
                call = message['tool_calls'][0]['function']
                call.update(name='human_model_search', arguments='{"scope":"career","query":"decision criteria"}')
            return answer
    endpoint = SearchEndpoint(); router = Router()
    model = foundation_agent_model(router, lambda _: pytest.fail('private cloud call'), endpoint,
                                   local_required=True)
    a = AutoCapabilityAgent(model, object(), CapabilityRequest(owner_id='owner'),
                             human_model_context=personal)
    assert source.eid in a.run('Use my decision criteria.')
    assert router.calls == [True, True]
    tool = next(t for t in endpoint.payloads[0]['tools'] if t['function']['name'] == 'human_model_search')
    assert set(tool['function']['parameters']['properties']) == {'scope', 'query'}


@pytest.fixture
def source(tmp_path):
    volumes = tmp_path / 'Volumes'
    root = volumes / 'USB' / 'HumanModel'
    (root / 'ledger').mkdir(parents=True)
    reader = _source_reader(ROOT)
    owner_module = reader.__module__.rsplit('.', 1)[0]
    Ledger = importlib.import_module(owner_module + '.human_model_ledger').Ledger
    ledger = Ledger(root / 'ledger' / 'human_model.sqlite3')
    eid = ledger.add(source_uri='synthetic:decision', source_revision='1', kind='decision',
                     scope='career', content='Predictable evenings matter more than a higher title.',
                     privacy='private', observed_at='2026-11-02T00:00:00Z')
    ledger.define_view(view_id='approved-personal', purpose='synthetic personalized reasoning',
                       audience='foundation', allowed_scopes=['career', 'creative'])
    ledger.rebuild_view(view_id='approved-personal')
    read = partial(reader, volumes_dir=volumes, mount_check=lambda p: p == str(volumes / 'USB'))
    yield SimpleNamespace(root=root, ledger=ledger, reader=read, eid=eid)
    ledger.close()


def context(source, privacy='private', guard=None):
    binding = HumanModelBinding('owner', str(source.root), 'approved-personal', ('career', 'creative'), privacy)
    return HumanModelContext(binding, source.reader, guard=guard or GuardCore(GuardState()), run_id='personal-test')


class Router:
    settings = None
    def __init__(self, cloud=False): self.calls=[]; self.cloud=cloud
    def choose(self, function, *, exclude=(), local_required=False):
        self.calls.append(local_required)
        kind = 'CLOUD' if self.cloud else 'LOCAL'
        if 'route' in exclude or (local_required and self.cloud):
            return SimpleNamespace(binding=None)
        return SimpleNamespace(binding='route', kind=kind, execution_slot=None, model='synthetic')


class ReasoningEndpoint:
    """Synthetic model behavior, real Pydantic scheduling and source reads."""
    def __init__(self, fail_followup=False): self.payloads=[]; self.fail_followup=fail_followup
    def chat_payload(self, payload, model=None):
        self.payloads.append(payload)
        returns=[row for row in payload['messages'] if row['role']=='tool']
        if not returns:
            message={'tool_calls':[{'id':'read-personal', 'type':'function',
                      'function':{'name':'human_model_context','arguments':'{"scope":"career"}'}}]}
        else:
            if self.fail_followup: raise RuntimeError('local route unavailable')
            data=json.loads(returns[-1]['content'])
            if data['status']=='UNAVAILABLE': text='Personal evidence is unavailable; no personal claim.'
            elif not data['records']: text='No approved matching evidence.'
            else:
                row=data['records'][0]
                text=row['content']+' [HumanModel:'+row['id']+'@'+str(data['view_revision'])+']'
            message={'content':text}
        return {'model':'synthetic', 'choices':[{'message':message}]}


def agent(source, *, privacy='private', endpoint=None, router=None):
    personal=context(source, privacy)
    endpoint=endpoint or ReasoningEndpoint()
    router=router or Router()
    cloud_calls=[]
    def cloud(binding):
        cloud_calls.append(binding)
        return SimpleNamespace(invoke_for_function=lambda binding,payload,function: json.dumps(endpoint.chat_payload(payload)))
    model=foundation_agent_model(router, cloud, endpoint, local_required=personal.local_required)
    result=AutoCapabilityAgent(model, object(), CapabilityRequest(owner_id='owner'),
                               human_model_context=personal, run_id='personal-test')
    return result, personal, endpoint, cloud_calls, router


def test_actual_agent_tool_loop_reads_current_decision_and_returns_source_reference(source):
    a, personal, endpoint, cloud_calls, router=agent(source)
    out=a.run('Compare these options against my decision criteria.')
    assert source.eid in out and 'Predictable evenings' in out
    assert cloud_calls==[] and router.calls==[True, True]
    tools=endpoint.payloads[0]['tools']
    schema=next(t['function']['parameters'] for t in tools if t['function']['name']=='human_model_context')
    assert set(schema['properties'])=={'scope','offset'}
    assert personal.receipts[0]['view_revision']==1
    assert set(personal.receipts[0])=={'view_revision','snapshot_sha256'}


def test_changed_judgment_is_not_served_from_personality_cache(source):
    a, personal, *_=agent(source)
    assert 'Predictable evenings' in a.run('Use my decision criteria.')
    new=source.ledger.add(source_uri='synthetic:decision', source_revision='2', kind='decision',
        scope='career', content='For this period, the new project takes priority.', privacy='private',
        observed_at='2026-11-02T01:00:00Z', supersedes=source.eid)
    assert json.loads(personal.read('owner','career'))['status']=='UNAVAILABLE'
    source.ledger.rebuild_view(view_id='approved-personal')
    answer=a.run('Use my revised criteria.')
    assert new in answer and source.eid not in answer and 'new project takes priority' in answer
    assert personal.receipts[-1]['view_revision']==2


def test_private_followup_never_falls_back_to_cloud(source):
    a, personal, endpoint, cloud_calls, router=agent(source, endpoint=ReasoningEndpoint(fail_followup=True))
    with pytest.raises(RuntimeError, match='no eligible agent compute'):
        a.run('Use my personal decision evidence.')
    assert len(endpoint.payloads)==2 and cloud_calls==[]
    assert all(router.calls)
    assert personal.receipts


def test_private_context_cannot_register_on_unconfined_model(source):
    model=foundation_agent_model(Router(), lambda _:None, ReasoningEndpoint())
    with pytest.raises(PermissionError, match='host-confined'):
        AutoCapabilityAgent(model, object(), CapabilityRequest(owner_id='owner'), human_model_context=context(source))


def test_only_shareable_records_can_reach_cloud_route(source):
    eid=source.ledger.add(source_uri='synthetic:shareable',source_revision='1',kind='observation',
        scope='career',content='Shareable synthetic project fact.',privacy='shareable',observed_at='2026-11-02T02:00:00Z')
    source.ledger.rebuild_view(view_id='approved-personal')
    a, personal, endpoint, cloud_calls, router=agent(source,privacy='shareable',router=Router(cloud=True))
    answer=a.run('Use authorized evidence.')
    assert eid in answer and source.eid not in answer
    assert len(cloud_calls)==2 and not any(router.calls)
    serialized=json.dumps(endpoint.payloads)
    assert 'Predictable evenings' not in serialized and source.eid not in serialized


def test_host_owner_guard_and_scope_are_checked_before_source_read(source):
    personal=context(source)
    with pytest.raises(PermissionError): personal.read('foreign','career')
    assert json.loads(personal.read('owner','*'))['reason']=='SCOPE_NOT_APPROVED'
    assert json.loads(personal.read('owner','career',offset=-1))['reason']=='PAGE_OUT_OF_RANGE'
    denied=context(source,guard=GuardCore(GuardState(cancellations={'personal-test'})))
    assert json.loads(denied.read('owner','career'))['reason']=='GUARD_READ_NOT_AUTHORIZED'
    with pytest.raises(PermissionError,match='owner'):
        AutoCapabilityAgent(foundation_agent_model(Router(),lambda _:None,ReasoningEndpoint(),local_required=True),
            object(),CapabilityRequest(owner_id='foreign'),human_model_context=personal)


def test_corrupt_evidence_is_not_returned_as_personal_fact(source):
    source.ledger.db.execute('UPDATE evidence SET content=? WHERE id=?',('corrupt replacement',source.eid))
    source.ledger.db.commit()
    raw=context(source).read('owner','career')
    assert json.loads(raw)['status']=='UNAVAILABLE'
    assert 'corrupt replacement' not in raw and str(source.root) not in raw


def test_malformed_approved_view_never_reaches_agent_or_source_receipts(source):
    personal = context(source)
    original = personal._reader
    valid = original(str(source.root), view_id='approved-personal',
                     scope='career', max_privacy='private',
                     max_records=32, max_bytes=32768, offset=0)
    baseline = valid['records'][0]
    for malformed in (
        [baseline],
        {**valid, 'records': [None]},
        {**valid, 'records': [{**baseline, 'content': None}]},
        {**valid, 'records': [{**baseline, 'id': ''}]},
    ):
        personal._reader = lambda *args, _malformed=malformed, **kwargs: _malformed
        answer = personal.read('owner', 'career')
        assert json.loads(answer)['reason'] == 'APPROVED_CURRENT_VIEW_UNAVAILABLE'
        assert 'Predictable evenings' not in answer
        assert not personal.receipts


def test_snapshot_is_bounded_and_pagination_is_explicit(source):
    for i in range(36):
        source.ledger.add(source_uri='synthetic:page:'+str(i),source_revision='1',kind='observation',
            scope='creative',content='Synthetic '+str(i),privacy='private',observed_at=f'2026-11-02T00:00:{i:02d}Z')
    source.ledger.rebuild_view(view_id='approved-personal')
    personal=context(source)
    first=json.loads(personal.read('owner','creative'))
    second=json.loads(personal.read('owner','creative',offset=first['next_offset']))
    assert first['status']=='PARTIAL' and len(first['records'])==32
    assert len(second['records'])==4 and second['next_offset'] is None
    assert not ({r['id'] for r in first['records']} & {r['id'] for r in second['records']})


def test_missing_host_config_disables_tool_without_creating_a_store(tmp_path):
    path=tmp_path/'human-model-bindings.json'
    assert build_human_model_context(path,'owner',repository_root=ROOT,
                                    guard=GuardCore(GuardState()),run_id='test') is None
    assert not path.exists() and list(tmp_path.iterdir())==[]


def test_config_binds_exact_owner_and_cannot_supply_executable_adapter(tmp_path,source):
    path=tmp_path/'host.json'
    row={'version':1,'bindings':[{'owner_id':'owner','root':str(source.root),'view_id':'approved-personal',
                                'scopes':['career'],'max_privacy':'private'}]}
    path.write_text(json.dumps(row))
    assert build_human_model_context(path,'foreign',repository_root=ROOT,
                                    guard=GuardCore(GuardState()),run_id='test') is None
    bound=build_human_model_context(path,'owner',repository_root=ROOT,
                                   guard=GuardCore(GuardState()),run_id='test')
    assert bound.local_required and bound.scopes==('career',)
    row['bindings'][0]['adapter_module']='untrusted'
    path.write_text(json.dumps(row))
    with pytest.raises(ValueError): load_bindings(path)
    path.write_text('{"version":1,"version":1,"bindings":[]}')
    with pytest.raises(ValueError): load_bindings(path)


def test_router_cannot_send_private_context_to_a_nonlocal_result(source):
    class BrokenRouter(Router):
        def choose(self,*args,**kwargs):
            return SimpleNamespace(binding='cloud',kind='CLOUD')
    a, _, _, cloud_calls, _=agent(source,router=BrokenRouter())
    with pytest.raises(PermissionError,match='local'):
        a.run('Use HumanModel.')
    assert not cloud_calls


def test_unknown_view_reports_unavailability_instead_of_personality_fallback(source):
    source.ledger.db.execute('DELETE FROM model_sources')
    source.ledger.db.execute('DELETE FROM model_views')
    source.ledger.db.commit()
    a, personal, _, cloud_calls, _=agent(source)
    answer=a.run('Use my decision history.')
    assert answer=='Personal evidence is unavailable; no personal claim.'
    assert not personal.receipts and not cloud_calls


def test_ordinary_chat_without_a_binding_does_not_register_personal_retrieval():
    class Ordinary:
        def chat_payload(self,payload,model=None):
            assert 'human_model_context' not in [tool['function']['name'] for tool in payload.get('tools',())]
            return {'choices':[{'message':{'content':'ordinary answer'}}]}
    endpoint=Ordinary()
    model=foundation_agent_model(Router(),lambda _:None,endpoint)
    a=AutoCapabilityAgent(model,object(),CapabilityRequest(owner_id='unbound'))
    assert a.run('Explain this ordinary topic.')=='ordinary answer'


def test_oversized_record_is_explicitly_omitted_without_partial_raw_text(source):
    source.ledger.add(source_uri='synthetic:large',source_revision='1',kind='observation',
        scope='creative',content='UNRETURNED_PERSONAL_TEXT'*3000,privacy='private',observed_at='2026-11-02T02:00:00Z')
    source.ledger.rebuild_view(view_id='approved-personal')
    result=json.loads(context(source).read('owner','creative'))
    assert result['status']=='PARTIAL' and result['records']==[] and result['omitted_record_ids']
    assert 'UNRETURNED_PERSONAL_TEXT' not in json.dumps(result)


def test_literal_humanmodel_search_has_no_model_or_extra_persistent_index(source):
    personal = context(source)
    called = []
    personal._search_backend = lambda *_: called.append(True)
    assert personal.search_available is True
    result = json.loads(personal.search('owner', 'career', 'Predictable evenings'))
    assert result['status'] == 'AVAILABLE'
    assert result['retrieval_engine'] == 'approved-literal-v1'
    assert result['records'][0]['id'] == source.eid
    assert called == []
    assert result['execution_authority'] is False


def test_literal_search_no_backend_owner_scope_and_stale_view(source):
    personal = context(source)
    result = json.loads(personal.search('owner', 'career', 'Predictable'))
    assert result['status'] == 'AVAILABLE'
    assert json.loads(personal.search('owner', 'career', 'not present'))['status'] == 'NO_MATCH'
    with pytest.raises(PermissionError):
        personal.search('foreign', 'career', 'Predictable')
    source.ledger.add(source_uri='synthetic:revision2', source_revision='2',
                      kind='decision', scope='career', content='Revised decision.',
                      privacy='private', observed_at='2026-11-03T01:00:00Z',
                      supersedes=source.eid)
    assert json.loads(personal.search('owner', 'career', 'Predictable'))['status'] == 'UNAVAILABLE'
    source.ledger.rebuild_view(view_id='approved-personal')
    assert json.loads(personal.search('owner', 'career', 'Predictable'))['status'] == 'NO_MATCH'
    assert json.loads(personal.search('owner', 'career', 'Revised decision'))['status'] == 'AVAILABLE'



def test_literal_search_marks_synthetic_inference_for_review(source):
    source.ledger.add(source_uri='synthetic:proposal', source_revision='1',
                      kind='inference', scope='career',
                      content='SYNTHETIC REVIEW HYPOTHESIS ONLY',
                      privacy='private', observed_at='2026-11-12T00:00:00Z')
    source.ledger.rebuild_view(view_id='approved-personal')
    result = json.loads(context(source).search(
        'owner', 'career', 'SYNTHETIC REVIEW HYPOTHESIS'))
    assert result['status'] == 'AVAILABLE'
    assert result['requires_evidence_review'] is True
    assert result['interpretations_are_personal_facts'] is False
    assert result['retrieval_coverage']['conflict_adjudication'] == 'NOT_PERFORMED'


def test_agent_question_gets_provisional_owner_reconstruction(source):
    """The existing local Agent answers a synthetic agent question using real approved view bytes."""
    class OwnerProxyEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            supplied = json.dumps(payload, ensure_ascii=False)
            assert 'Would you prioritize a promotion over your evenings?' in supplied
            assert 'Predictable evenings matter more than a higher title.' in supplied
            assert source.eid in supplied
            assert '[HumanModel:' + source.eid + ']' in supplied
            assert 'Copy a supplied citation token verbatim' in supplied
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': ('Simulation (not owner approval): I would prefer predictable '
                            'evenings over a title. [HumanModel:' + source.eid + ']')
            }}]}

    a, personal, endpoint, cloud_calls, router = agent(source, endpoint=OwnerProxyEndpoint())
    result = a.answer_owner_question(
        'Would you prioritize a promotion over your evenings?', scope='career')
    assert result['status'] == 'SIMULATED_PROVISIONAL'
    assert 'Simulation' in result['answer'] and source.eid in result['answer']
    assert result['candidate_evidence_ids'] == [source.eid]
    assert result['view_revision'] == 1
    assert result['owner_statement_verified'] is False
    assert result['execution_authority'] is False
    assert result['needs_review'] is False
    assert len(endpoint.payloads) == 1
    assert not endpoint.payloads[0].get('tools')  # another agent cannot invoke host tools
    assert cloud_calls == [] and router.calls == [True]
    assert len(personal.receipts) == 3  # selected page, pinned check, answer readback



def test_owner_question_refuses_revoked_source_before_inference(source):
    a, personal, endpoint, _, _ = agent(source)

    def denied(*args, **kwargs):
        raise PermissionError('synthetic Guard revocation')

    personal.read = denied
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'APPROVED_VIEW_UNAVAILABLE'
    assert 'answer' not in result
    assert not endpoint.payloads


def test_owner_question_refuses_revocation_during_inference(source):
    # Owner-answer reconstruction has no callable tools. The normal test
    # endpoint exercises the unrelated agent tool loop, so use a pure answer.
    class AnswerOnlyEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': 'Simulation: predictable evenings matter.'
            }}]}

    a, personal, endpoint, _, _ = agent(source, endpoint=AnswerOnlyEndpoint())
    original_read = personal.read
    calls = []

    def read_with_revoke(*args, **kwargs):
        calls.append(True)
        # One approved evidence page and initial snapshot read succeed;
        # then the owner revokes access before the answer is handed off.
        if len(calls) == 3:
            raise PermissionError('synthetic Guard revocation')
        return original_read(*args, **kwargs)

    personal.read = read_with_revoke
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'VIEW_CHANGED_DURING_SIMULATION'
    assert 'answer' not in result
    assert len(endpoint.payloads) == 1
    assert len(calls) == 3


def test_owner_question_rejects_model_requested_tool_in_tool_free_simulation(source):
    # The normal endpoint attempts to call human_model_context. Owner-answer
    # mode intentionally exposes no tools, and must not raise a raw runtime
    # exception or execute the attempted request.
    a, personal, endpoint, _, _ = agent(source)
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'OWNER_SIMULATION_INVALID_TOOL_REQUEST'
    assert 'answer' not in result
    assert endpoint.payloads
    assert len(personal.receipts) == 2  # only approved evidence + source recheck


def test_owner_question_model_runtime_error_does_not_leak_private_exception(source, monkeypatch):
    a, personal, endpoint, cloud_calls, _ = agent(source)
    def failed_adapter(_self, _request):
        raise RuntimeError('SYNTHETIC_PRIVATE_OWNER_TEXT_IN_ADAPTER_ERROR')
    monkeypatch.setattr('ai_foundation.auto_agent.PydanticAgentPort.run', failed_adapter)
    outcome = a.answer_owner_question('Predictable evenings?', scope='career')
    assert outcome == {
        'status': 'UNAVAILABLE',
        'reason': 'OWNER_SIMULATION_RUNTIME_UNAVAILABLE',
        'execution_authority': False,
        'owner_statement_verified': False,
    }
    assert not endpoint.payloads and not cloud_calls
    assert len(personal.receipts) == 2
    assert 'SYNTHETIC_PRIVATE' not in repr(outcome)


def test_owner_question_refuses_fabricated_evidence_reference(source):
    class UnsupportedCitation(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': 'Simulation: invented fact. [HumanModel:invented-id]'
            }}]}

    a, _, endpoint, _, _ = agent(source, endpoint=UnsupportedCitation())
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'UNSUPPORTED_EVIDENCE_CITATION'
    assert result['citation_failure_kind'] == 'UNKNOWN_EVIDENCE_ID'
    assert result['source_scan_complete'] is True
    assert result['evidence_selection_complete'] is True
    assert result['omitted_records'] == 0
    assert 'answer' not in result
    assert len(endpoint.payloads) == 1


def test_owner_question_accepts_exact_view_revision_citation(source):
    class RevisionCitation(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': ('Simulation: current source. [HumanModel:'
                            + source.eid + '@1]')
            }}]}

    a, _, _, _, _ = agent(source, endpoint=RevisionCitation())
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'SIMULATED_PROVISIONAL'
    assert result['cited_evidence_ids'] == [source.eid]
    assert result['needs_review'] is False


def test_owner_question_rejects_stale_view_revision_citation(source):
    class StaleCitation(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': ('Simulation: obsolete source. [HumanModel:'
                            + source.eid + '@999]')
            }}]}

    a, _, _, _, _ = agent(source, endpoint=StaleCitation())
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'UNSUPPORTED_EVIDENCE_CITATION'
    assert result['citation_failure_kind'] == 'VIEW_REVISION_MISMATCH'
    assert result['source_scan_complete'] is True
    assert result['evidence_selection_complete'] is True
    assert result['omitted_records'] == 0
    assert 'answer' not in result



def test_owner_question_rejects_malformed_evidence_marker(source):
    class MalformedCitation(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': 'Simulation: invalid reference [HumanModel:' + 'x' * 257 + ']'
            }}]}

    a, _, _, _, _ = agent(source, endpoint=MalformedCitation())
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'UNSUPPORTED_EVIDENCE_CITATION'
    assert result['citation_failure_kind'] == 'MALFORMED_MARKER'
    assert result['source_scan_complete'] is True
    assert result['evidence_selection_complete'] is True
    assert result['omitted_records'] == 0
    assert 'answer' not in result


def test_owner_question_missing_citation_requires_review(source):
    class UncitedResponse(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': 'Simulation: I prefer predictable evenings.'
            }}]}

    a, _, endpoint, _, _ = agent(source, endpoint=UncitedResponse())
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'OWNER_ANSWER_WITHOUT_SOURCE_CITATION'
    assert 'answer' not in result
    assert result['candidate_evidence_ids'] == [source.eid]
    assert result['citation_reference_status'] == 'NO_CITATIONS'
    assert result['source_scan_complete'] is True
    assert result['evidence_selection_complete'] is True
    assert result['omitted_records'] == 0
    assert result['execution_authority'] is False
    assert len(endpoint.payloads) == 1


def test_agent_question_refuses_unknown_scope_and_empty_data_without_inference(source):
    a, _, endpoint, cloud_calls, _ = agent(source)
    unknown = a.answer_owner_question('What would I say?', scope='forbidden')
    empty = a.answer_owner_question('What would I say?', scope='creative')
    assert unknown['reason'] == 'SCOPE_NOT_APPROVED'
    assert empty['reason'] == 'NO_OWNER_EVIDENCE'
    assert not endpoint.payloads and not cloud_calls


def test_agent_question_never_inherits_a_write_or_external_search_route(source):
    personal = context(source)
    endpoint = ReasoningEndpoint()
    model = foundation_agent_model(
        Router(), lambda _: pytest.fail('no cloud'), endpoint, local_required=True)
    a = AutoCapabilityAgent(model, object(),
        CapabilityRequest(owner_id='owner', repo_root=str(ROOT)),
        human_model_context=personal)
    result = a.answer_owner_question('What would I authorize?', scope='career')
    assert result['reason'] == 'READ_ONLY_CHAT_REQUIRED'
    assert not endpoint.payloads and not personal.receipts


def test_owner_reconstruction_small_corpus_fallback_preserves_later_pages(source, monkeypatch):
    personal = context(source)
    rows = [
        {'id': f'approved-{i}', 'kind': 'observation',
         'content': f'owner source fact number {i}', 'disputed': False}
        for i in range(3)
    ]
    calls = []

    def paged_read(owner_id, scope, *, offset=0):
        assert owner_id == 'owner' and scope == 'career'
        calls.append(offset)
        if offset == 0:
            records, next_offset, status = rows[:2], 2, 'PARTIAL'
        else:
            assert offset == 2
            records, next_offset, status = rows[2:], None, 'AVAILABLE'
        return json.dumps({'status': status, 'records': records,
                           'next_offset': next_offset, 'view_revision': 1,
                           'snapshot_sha256': 'a' * 64, 'omitted_record_ids': []})

    monkeypatch.setattr(personal, 'read', paged_read)
    # No lexical keyword overlap; small-corpus fallback must include every
    # authorized page, rather than silently dropping the final record.
    result = personal.reconstruction_evidence('owner', 'career', 'Unrelated?')
    assert result['status'] == 'AVAILABLE'
    assert [row['id'] for row in result['records']] == [
        'approved-0', 'approved-1', 'approved-2']
    assert result['scanned_records'] == 3
    assert result['coverage_complete'] is True
    assert result['omitted_records'] == 0
    assert calls == [0, 2, 0]



def test_owner_reconstruction_accepts_distinct_page_digests_same_revision(source, monkeypatch):
    # Each approved page's digest covers its own bounded slice, not the
    # complete view. The original first-page digest is checked again below.
    personal = context(source)
    offsets = []

    def paged_read(owner_id, scope, *, offset=0):
        assert (owner_id, scope) == ('owner', 'career')
        offsets.append(offset)
        row = {'id': f'owner-statement-{offset}', 'content': f'view {offset}',
               'kind': 'observation', 'disputed': False}
        return json.dumps({'status': 'PARTIAL' if offset == 0 else 'AVAILABLE',
                           'records': [row], 'next_offset': 1 if offset == 0 else None,
                           'view_revision': 1, 'snapshot_sha256': ('a' if offset == 0 else 'b') * 64,
                           'omitted_record_ids': []})

    monkeypatch.setattr(personal, 'read', paged_read)
    result = personal.reconstruction_evidence('owner', 'career', 'Unrelated?')
    assert result['status'] == 'AVAILABLE'
    assert [row['id'] for row in result['records']] == [
        'owner-statement-0', 'owner-statement-1']
    assert result['coverage_complete'] is True
    assert offsets == [0, 1, 0]


def test_agent_question_pages_complete_view_before_reconstruction(source):
    # The oldest owner preference must remain findable behind 32 newer rows.
    for i in range(32):
        source.ledger.add(source_uri='synthetic:additional:' + str(i),
                          source_revision='1', kind='inference' if i == 31 else 'observation', scope='career',
                          content='Independent statement ' + str(i),
                          privacy='private', observed_at='2026-11-12T00:00:00Z')
    source.ledger.rebuild_view(view_id='approved-personal')

    class PagedEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            content = json.dumps(payload, ensure_ascii=False)
            assert 'Predictable evenings matter' in content
            assert 'Independent statement 31' not in content
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': ('Simulation: I prioritize predictable evenings. '
                            '[HumanModel:' + source.eid + ']')}}]}

    a, personal, endpoint, _, _ = agent(source, endpoint=PagedEndpoint())
    result = a.answer_owner_question(
        'Why do predictable evenings matter to my decisions?', scope='career')
    assert result['status'] == 'SIMULATED_PROVISIONAL'
    assert result['candidate_evidence_ids'] == [source.eid]
    assert result['scanned_records'] == 33 and result['source_scan_complete'] is True
    assert result['coverage_complete'] is False
    assert result['evidence_selection_complete'] is False
    assert result['omitted_records'] == 32 and result['needs_review'] is True
    assert result['omitted_uncertain_records'] == 1
    assert len(endpoint.payloads) == 1
    assert len(personal.receipts) == 4  # two pages + initial recheck + final recheck


def test_agent_question_scans_beyond_four_pages_without_exporting_bulk(source):
    for i in range(128):
        source.ledger.add(source_uri='synthetic:overflow:' + str(i),
                          source_revision='1', kind='observation', scope='career',
                          content='Observation ' + str(i),
                          privacy='private', observed_at='2026-11-12T00:00:00Z')
    source.ledger.rebuild_view(view_id='approved-personal')

    class ScanningEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            content = json.dumps(payload, ensure_ascii=False)
            assert 'Predictable evenings matter' in content
            assert 'Observation 127' not in content
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': ('Simulation: I value predictable evenings. '
                            '[HumanModel:' + source.eid + ']')}}]}

    a, personal, endpoint, _, _ = agent(source, endpoint=ScanningEndpoint())
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'SIMULATED_PROVISIONAL'
    assert result['scanned_records'] == 129
    assert result['candidate_evidence_ids'] == [source.eid]
    assert result['source_scan_complete'] is True
    assert result['coverage_complete'] is False
    assert result['evidence_selection_complete'] is False
    assert result['omitted_records'] == 128 and result['needs_review'] is True
    assert len(endpoint.payloads) == 1
    assert len(personal.receipts) == 7  # five pages, initial check, final check

    # Large scopes with no lexical grounding must not silently fabricate
    # owner behavior or call the LLM with arbitrary first-page evidence.
    unrelated = a.answer_owner_question('Zqxw unfamiliar criterion?', scope='career')
    assert unrelated['reason'] == 'NO_RELEVANT_OWNER_EVIDENCE'
    assert len(endpoint.payloads) == 1


def test_owner_answer_refuses_repeated_evidence_id_before_inference(source):
    """A duplicated source record must not count as independent owner evidence."""
    a, personal, endpoint, _, _ = agent(source)
    original = personal.read

    def repeated(owner, scope, *, offset=0):
        page = json.loads(original(owner, scope, offset=offset))
        if page.get('records'):
            page['records'].append(dict(page['records'][0]))
        return json.dumps(page)

    personal.read = repeated
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'CORPUS_IDENTITY_CONFLICT'
    assert not endpoint.payloads


@pytest.mark.parametrize('invalid', [None, 123, {'text': 'fabricated'}])
def test_owner_answer_refuses_nontext_evidence_before_inference(source, invalid):
    a, personal, endpoint, _, _ = agent(source)
    original = personal.read

    def malformed(owner, scope, *, offset=0):
        page = json.loads(original(owner, scope, offset=offset))
        if page.get('records'):
            page['records'][0]['content'] = invalid
        return json.dumps(page)

    personal.read = malformed
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'CORPUS_RECORD_INVALID'
    assert not endpoint.payloads


def test_agent_question_refuses_a_changed_view_during_response(source):
    class ChangingEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': 'Simulated answer from stale data.'}}]}
    a, personal, endpoint, _, _ = agent(source, endpoint=ChangingEndpoint())
    # Inject an independently observed changed snapshot at the second host
    # readback; do not mutate a main-thread SQLite connection from the model
    # callback's worker thread.
    original = personal.read
    calls = 0
    def reread(owner, scope, *, offset=0):
        nonlocal calls
        calls += 1
        value = json.loads(original(owner, scope, offset=offset))
        if calls == 3:
            value['view_revision'] += 1
        return json.dumps(value)
    personal.read = reread
    result = a.answer_owner_question('What would I answer?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'VIEW_CHANGED_DURING_SIMULATION'
    assert 'answer' not in result
    assert len(endpoint.payloads) == 1
    assert calls == 3


@pytest.mark.parametrize(('route', 'query'), [
    ('literal', 'Predictable evenings'),
    ('no_match', 'absent evidence'),
    ('cognee', 'decision criteria'),
])
def test_search_refuses_changed_source_between_read_and_return(source, route, query):
    """Revalidate Guard and exact View before hits, NO_MATCH, or Cognee results."""
    personal = context(source)
    if route == 'cognee':
        personal._search_backend = lambda snapshot, _: {'records': snapshot['records']}
    original_read = personal.read
    calls = 0

    def changed_read(owner, scope, *, offset=0):
        nonlocal calls
        calls += 1
        snapshot = json.loads(original_read(owner, scope, offset=offset))
        if calls == 2:
            snapshot['view_revision'] += 1
        return json.dumps(snapshot)

    personal.read = changed_read
    result = json.loads(personal.search('owner', 'career', query))
    assert calls == 2
    assert result == {
        'source': 'HumanModel', 'status': 'UNAVAILABLE',
        'reason': 'SEARCH_SOURCE_CHANGED', 'execution_authority': False,
    }
    assert source.eid not in json.dumps(result)


def test_host_builder_restores_exact_current_guard_collection_consent(tmp_path, source, monkeypatch):
    import ai_foundation.human_model_context as hm
    from ai_foundation.core import CanonContract
    from ai_foundation.human_model_collection_guard import GuardCollectionConsent

    guard = GuardCore(GuardState())
    binding = HumanModelBinding(
        'owner', str(source.root), 'approved-personal', ('career',), 'private')
    consent = GuardCollectionConsent(
        authenticated_owner='owner', binding=binding, guard=guard,
        canon=CanonContract('human-model-test', 'current-test-revision'))
    path = tmp_path / 'human-model-bindings.json'
    path.write_text(json.dumps({'version': 1, 'bindings': [{
        'owner_id': binding.owner_id, 'root': binding.root,
        'view_id': binding.view_id, 'scopes': list(binding.scopes),
        'max_privacy': binding.max_privacy,
    }]}))
    observed = []

    def inert_reader(root, **kwargs):
        observed.append(kwargs)
        return {'status': 'synthetic-only'}

    monkeypatch.setattr(hm, '_source_reader', lambda _: inert_reader)
    bound = hm.build_human_model_context(
        path, 'owner', repository_root=ROOT, guard=guard,
        run_id='synthetic', collection_consent=consent)
    assert bound.binding == binding
    bound._reader('synthetic-root', view_id='approved-personal', scope='career')
    assert len(observed) == 1
    callback = observed[0]['collection_current']
    assert callback.__self__ is consent
    assert callback.__func__ is GuardCollectionConsent.active_digest

    with pytest.raises(PermissionError, match='trusted host collection consent'):
        hm.build_human_model_context(
            path, 'owner', repository_root=ROOT, guard=GuardCore(GuardState()),
            run_id='synthetic', collection_consent=consent)
    assert len(observed) == 1


@pytest.mark.parametrize(("route", "query"), [
    ("literal", "Predictable evenings"),
    ("no_match", "absent evidence"),
    ("semantic", "decision criteria"),
])
def test_search_stale_source_rejected_for_literal_no_match_and_semantic(source, route, query):
    """#607 recovery: stale hits and stale NO_MATCH never represent the owner."""
    personal = context(source)
    if route == "semantic":
        personal._search_backend = lambda snapshot, _: {"records": snapshot["records"]}
    original_read = personal.read
    calls = 0

    def changed_read(owner, scope, *, offset=0):
        nonlocal calls
        calls += 1
        snapshot = json.loads(original_read(owner, scope, offset=offset))
        if calls == 2:
            snapshot["view_revision"] += 1
        return json.dumps(snapshot)

    personal.read = changed_read
    response = json.loads(personal.search("owner", "career", query))
    assert response == {
        "source": "HumanModel",
        "status": "UNAVAILABLE",
        "reason": "SEARCH_SOURCE_CHANGED",
        "execution_authority": False,
    }
    assert calls == 2


# Owner-answer lifecycle acceptance beyond one-shot syntax-only citation success.
# These use a disposable real SQLite Ledger and the existing Agent pipeline;
# no real owner records, new model, network, cloud or execution authority.
def test_owner_answer_lifecycle_correction_stale_then_new_cited_source(source):
    active = {'id': source.eid, 'content': 'Predictable evenings matter more'}
    class CitedSourceEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            wire = json.dumps(payload, ensure_ascii=False)
            assert active['id'] in wire and active['content'] in wire
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': 'Simulation: current decision. [HumanModel:' + active['id'] + ']'
            }}]}

    a, personal, endpoint, cloud_calls, _ = agent(
        source, endpoint=CitedSourceEndpoint())
    first = a.answer_owner_question('Evenings or higher title?', scope='career')
    assert first['status'] == 'SIMULATED_PROVISIONAL'
    assert first['cited_evidence_ids'] == [source.eid]
    assert first['owner_statement_verified'] is False
    assert len(endpoint.payloads) == 1 and cloud_calls == []

    replacement = source.ledger.add(
        source_uri='synthetic:decision', source_revision='2', kind='decision',
        scope='career', content='Now a higher title matters more than evenings.',
        privacy='private', observed_at='2026-11-13T00:00:00Z',
        supersedes=source.eid)
    # Updating an original invalidates every derived View. Never use the
    # stale projected preference or rerun the model before View rebuild.
    stale = a.answer_owner_question('Evenings or higher title?', scope='career')
    assert stale['status'] == 'UNAVAILABLE' and 'answer' not in stale
    assert len(endpoint.payloads) == 1

    source.ledger.rebuild_view(view_id='approved-personal')
    active.update(id=replacement, content='Now a higher title matters more')
    current = a.answer_owner_question('Evenings or higher title?', scope='career')
    assert current['status'] == 'SIMULATED_PROVISIONAL'
    assert current['cited_evidence_ids'] == [replacement]
    assert source.eid not in current['candidate_evidence_ids']
    assert source.eid not in json.dumps(endpoint.payloads[-1])
    assert current['view_revision'] > first['view_revision']
    assert current['execution_authority'] is False
    assert current['owner_statement_verified'] is False
    assert len(endpoint.payloads) == 2 and cloud_calls == []


def test_owner_answer_lifecycle_real_revision_change_before_return_is_withheld(source):
    class CitedSourceEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': 'Simulation: old preference. [HumanModel:' + source.eid + ']'
            }}]}

    a, personal, endpoint, cloud_calls, _ = agent(
        source, endpoint=CitedSourceEndpoint())
    previous_read = personal.read
    calls = 0

    def host_read_with_correction(owner_id, scope, *, offset=0):
        nonlocal calls
        calls += 1
        if calls == 3:
            # Actual Ledger mutation in the host readback thread, not a
            # fabricated JSON revision or cross-thread SQLite mutation.
            source.ledger.add(
                source_uri='synthetic:decision', source_revision='2',
                kind='decision', scope='career',
                content='New preference supersedes the earlier decision.',
                privacy='private', observed_at='2026-11-13T00:00:00Z',
                supersedes=source.eid)
            source.ledger.rebuild_view(view_id='approved-personal')
        return previous_read(owner_id, scope, offset=offset)

    personal.read = host_read_with_correction
    result = a.answer_owner_question('Evenings or title?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'VIEW_CHANGED_DURING_SIMULATION'
    assert 'answer' not in result and 'cited_evidence_ids' not in result
    assert result['execution_authority'] is False
    assert len(endpoint.payloads) == 1 and calls == 3
    assert cloud_calls == []


def test_owner_answer_disputed_inference_requires_review_not_owner_authority(source):
    suspect_id = source.ledger.add(
        source_uri='synthetic:unverified-hypothesis', source_revision='1',
        kind='inference', scope='career',
        content='Career promotion may always take priority: an uncertain hypothesis.',
        privacy='private', observed_at='2026-11-13T00:00:00Z',
        disputed=True)
    source.ledger.rebuild_view(view_id='approved-personal')

    class CitesInference(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            assert suspect_id in json.dumps(payload, ensure_ascii=False)
            return {'model': 'synthetic', 'choices': [{'message': {
                'content': 'Simulation: uncertain hypothesis. [HumanModel:' + suspect_id + ']'
            }}]}

    a, _, endpoint, cloud_calls, _ = agent(
        source, endpoint=CitesInference())
    answer = a.answer_owner_question('Career promotion priority?', scope='career')
    assert answer['status'] == 'SIMULATED_PROVISIONAL'
    assert answer['cited_evidence_ids'] == [suspect_id]
    assert answer['needs_review'] is True
    assert answer['conflict_adjudication'] == 'NOT_PERFORMED'
    assert answer['citation_reference_status'] == 'MATCHED_IDS_ONLY'
    assert answer['owner_statement_verified'] is False
    assert answer['execution_authority'] is False
    assert len(endpoint.payloads) == 1 and cloud_calls == []


def test_owner_reconstruction_reports_safe_model_failure_without_owner_answer(source):
    class FailedLocalEndpoint(ReasoningEndpoint):
        def chat_payload(self, payload, model=None):
            self.payloads.append(payload)
            raise RuntimeError("SYNTHETIC_PRIVATE_OWNER_CONTENT_MUST_NOT_LEAK")
    a, personal, endpoint, cloud_calls, router = agent(
        source, endpoint=FailedLocalEndpoint())
    result = a.answer_owner_question('Predictable evenings?', scope='career')
    assert result['status'] == 'UNAVAILABLE'
    assert result['reason'] == 'OWNER_SIMULATION_ROUTE_UNAVAILABLE'
    assert result['model_failure_phase'] == 'initial'
    assert result['model_failure_code'] == 'MODEL_EXECUTION'
    assert result['model_attempts'] == 1
    assert result['owner_statement_verified'] is False
    assert result['execution_authority'] is False
    assert 'answer' not in result
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(result)
    assert len(endpoint.payloads) == 1
    assert cloud_calls == []
    assert router.calls == [True, True]
    assert len(personal.receipts) == 2  # read + revision recheck, no answer readback


