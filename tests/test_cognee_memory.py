import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('cognee_memory', Path(__file__).parents[1]/'experiments/human_model/cognee_memory.py')
memory = importlib.util.module_from_spec(spec); spec.loader.exec_module(memory)


def snapshot(text='この開発では負荷テストより未実装の機能を優先する。', revision=1):
    return {'view_id': 'work', 'scope': 'work', 'view_revision': revision,
            'records': [{'id': 'source-1', 'source_uri': 'test://instruction',
                         'source_revision': str(revision), 'privacy': 'private',
                         'scope': 'work', 'kind': 'instruction', 'content': text,
                         'content_sha256': hashlib.sha256(text.encode()).hexdigest()}]}


def fact():
    return {'subject': 'この開発', 'relation': '優先する', 'object': '未実装の機能',
            'quote': '負荷テストより未実装の機能を優先する'}


def test_quote_must_be_exact_not_a_model_claim():
    row = snapshot()['records'][0]
    assert memory.validate_facts(row, [fact()]) == [fact()]
    with pytest.raises(ValueError):
        memory.validate_facts(row, [{**fact(), 'quote': '検証は不要'}])


def test_changed_source_hash_and_incomplete_views_are_rejected():
    value = snapshot(); value['records'][0]['content'] = '改変'
    with pytest.raises(ValueError): memory.validate_snapshot(value)
    with pytest.raises(ValueError): memory.validate_snapshot({**snapshot(), 'truncated': True})
    with pytest.raises(ValueError): memory.validate_snapshot({**snapshot(), 'omitted_record_ids': ['large']})


def test_correction_privacy_and_scope_change_the_graph_identity():
    original = snapshot(); hashes = {memory.validate_snapshot(original)}
    for field, value in [('source_revision', '2'), ('privacy', 'shareable'), ('scope', 'other')]:
        changed = copy.deepcopy(original); changed['records'][0][field] = value
        hashes.add(memory.validate_snapshot(changed))
    assert len(hashes) == 4


def test_cogx_preserves_source_revision_and_marks_interpretation(tmp_path):
    value = snapshot(); memory.write_archive(value, {'source-1': [fact()]}, tmp_path/'archive')
    nodes = [json.loads(x) for x in (tmp_path/'archive/nodes.jsonl').read_text().splitlines()]
    source = next(x for x in nodes if x['type'] == 'DocumentChunk')
    interpretation = next(x for x in nodes if x['type'] == 'MemoryInterpretation')
    assert source['metadata']['source_revision'] == '1'
    assert interpretation['metadata']['classification'] == 'untrusted_interpretation'
    assert json.loads(interpretation['text'])['quote'] in value['records'][0]['content']


def test_facts_cannot_authorize_actions_or_change_owner(tmp_path):
    altered = {**fact(), 'owner': 'other'}
    with pytest.raises(ValueError):
        memory.write_archive(snapshot(), {'source-1': [altered]}, tmp_path/'archive')


def test_snapshot_rejects_duplicate_or_empty_sources():
    value = snapshot(); value['records'] *= 2
    with pytest.raises(ValueError): memory.validate_snapshot(value)
    with pytest.raises(ValueError): memory.validate_snapshot({'records': []})


def test_source_spans_cover_the_entire_original_without_clipping():
    text = '前提条件\n' + '訂正と適用範囲を残す。'*60 + '\n末尾の例外条件'
    spans = memory.source_spans(text)
    assert ''.join(row['text'] for row in spans) == text
    assert all(text[row['start']:row['end']] == row['text'] for row in spans)
    assert spans[-1]['end'] == len(text)


def test_span_citation_uses_original_text_and_offsets_not_a_model_quote():
    record = snapshot()['records'][0]
    proposed = {'subject':'この開発','relation':'優先する','object':'未実装の機能','source_span_id':0}
    grounded = memory.ground_span_facts(record,[proposed])[0]
    assert grounded['quote'] == record['content'][grounded['span_start']:grounded['span_end']]
    assert grounded['quote'] == record['content']
    with pytest.raises(ValueError): memory.ground_span_facts(record,[{**proposed,'source_span_id':999}])
    with pytest.raises(ValueError): memory.ground_span_facts(record,[{**proposed,'source_span_id':True}])
    with pytest.raises(ValueError): memory.ground_span_facts(record,[{**proposed,'quote':'invented'}])
