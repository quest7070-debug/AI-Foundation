"""Independent source-boundary regressions; no model or Cognee required."""
import hashlib
import json
import unittest

from ai_foundation.core import Decision
from ai_foundation.human_model_context import HumanModelBinding, HumanModelContext


class AllowRead:
    def preflight(self, plan, canon):
        return Decision.ALLOW


def snapshot():
    row = {'id': 'original-id', 'kind': 'decision', 'scope': 'work',
           'content': 'Original conditional judgment.', 'source_uri': 'synthetic:owner',
           'source_revision': '1', 'observed_at': None, 'privacy': 'private',
           'disputed': 1}
    row['content_sha256'] = hashlib.sha256(row['content'].encode()).hexdigest()
    result = {'view_id': 'approved', 'scope': 'work', 'view_revision': 1,
              'records': [row], 'truncated': False, 'omitted_record_ids': [],
              'next_offset': None}
    result['snapshot_sha256'] = hashlib.sha256(json.dumps(
        result, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return result


class SearchIntegrityTests(unittest.TestCase):
    def context(self, backend):
        return HumanModelContext(
            HumanModelBinding('owner', '/synthetic/HumanModel', 'approved', ('work',), 'private'),
            lambda *args, **kwargs: snapshot(), guard=AllowRead(), run_id='integrity',
            search_backend=backend)

    def test_backend_cannot_mutate_the_canonical_evidence(self):
        for field, value in (
            ('content', 'FORGED_PRIVATE_TEXT'), ('id', 'FORGED_PRIVATE_TEXT'),
            ('scope', 'unapproved'), ('privacy', 'shareable'),
            ('source_revision', '999'), ('disputed', 0), ('observed_at', '2099-01-01')):
            with self.subTest(field=field):
                def backend(source, query):
                    source['records'][0][field] = value
                    return {'records': source['records']}
                result = json.loads(self.context(backend).search('owner', 'work', 'semantic-query-without-literal-match'))
                self.assertEqual(result['status'], 'UNAVAILABLE')
                self.assertNotIn('FORGED_PRIVATE_TEXT', json.dumps(result))
                self.assertFalse(result['execution_authority'])

    def test_backend_cannot_add_an_authorized_looking_record(self):
        def backend(source, query):
            source['records'].append({**source['records'][0], 'id': 'FORGED_PRIVATE_TEXT'})
            return {'records': source['records']}
        result = json.loads(self.context(backend).search('owner', 'work', 'semantic-query-without-literal-match'))
        self.assertEqual(result['status'], 'UNAVAILABLE')
        self.assertNotIn('FORGED_PRIVATE_TEXT', json.dumps(result))

    def test_backend_cannot_replace_the_authorized_record_list(self):
        def backend(source, query):
            source['records'] = [{**source['records'][0], 'content': 'FORGED_PRIVATE_TEXT'}]
            return {'records': source['records']}
        result = json.loads(self.context(backend).search('owner', 'work', 'semantic-query-without-literal-match'))
        self.assertEqual(result['status'], 'UNAVAILABLE')

    def test_unchanged_original_retains_dispute_uncertainty_and_source_receipt(self):
        context = self.context(lambda source, query: {'records': source['records']})
        result = json.loads(context.search('owner', 'work', 'semantic-query-without-literal-match'))
        self.assertEqual(result['status'], 'AVAILABLE')
        self.assertEqual(result['retrieval_engine'], 'cognee==1.6.5')
        self.assertEqual(result['records'], snapshot()['records'])
        self.assertEqual(result['snapshot_sha256'], snapshot()['snapshot_sha256'])
        self.assertIsNone(result['records'][0]['observed_at'])
        self.assertEqual(result['records'][0]['disputed'], 1)
        self.assertFalse(result['execution_authority'])

    def test_approved_literal_fast_path_does_not_call_untrusted_backend(self):
        calls = []
        def unexpected_backend(source, query):
            calls.append(query)
            raise AssertionError('unnecessary backend call')
        result = json.loads(self.context(unexpected_backend).search('owner', 'work', 'judgment'))
        self.assertEqual(result['status'], 'AVAILABLE')
        self.assertEqual(result['retrieval_engine'], 'approved-literal-v1')
        self.assertEqual(calls, [])
        self.assertEqual(result['records'], snapshot()['records'])

    def test_index_does_not_gain_authority_or_replace_snapshot_metadata(self):
        def backend(source, query):
            source['view_revision'] = 999
            source['omitted_record_ids'].append('index-only-id')
            return {'records': source['records'], 'execution_authority': True}
        result = json.loads(self.context(backend).search('owner', 'work', 'semantic-query-without-literal-match'))
        self.assertEqual(result['view_revision'], 1)
        self.assertEqual(result['omitted_record_ids'], [])
        self.assertFalse(result['execution_authority'])


if __name__ == '__main__':
    unittest.main()
