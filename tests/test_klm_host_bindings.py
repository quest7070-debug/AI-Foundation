import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib import parse, request, error

from ai_foundation.klm_drive_auth import (BINDING, SCOPES, ReadonlyGoogleToken,
                                         authorize, load_desktop_client, save_grant)
from ai_foundation.klm_9b_handler import Existing9BKlmHandler, bounded_request, _source_candidates, _classification_schema, MODEL
from ai_foundation.knowledge_lifecycle import ReadonlyReceiptJournal


class Store:
    def __init__(self):
        self.values = {}
    def available(self, key):
        return key in self.values
    def load(self, key):
        return self.values[key]
    def save(self, key, value):
        self.values[key] = value


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.client = {'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'test-only',
                       'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
                       'token_uri': 'https://oauth2.googleapis.com/token'}
        self.client_path = self.root / 'client.json'
        self.client_path.write_text(json.dumps({'installed': self.client}))
        self.store = Store()
        self.grant = {'scope': ' '.join(sorted(SCOPES)), 'refresh_token': 'test-refresh'}

    def test_no_auth_uses_no_other_native_binding_or_external_request(self):
        self.store.save('other-application', 'unrelated-token')
        provider = ReadonlyGoogleToken(self.store, exchange=lambda x: self.fail('unbound request'))
        self.assertFalse(provider.available())
        with self.assertRaisesRegex(RuntimeError, 'DRIVE_AUTH_REQUIRED'):
            provider()
        self.assertEqual(self.store.load('other-application'), 'unrelated-token')

    def test_refresh_exact_scopes_cache_and_expiry_without_persisting_access_token(self):
        save_grant(self.store, self.client, self.grant)
        calls = []
        now = [100]
        def exchange(fields):
            calls.append(fields)
            return {'access_token': 'test-access', 'expires_in': 600}
        token = ReadonlyGoogleToken(self.store, exchange=exchange, clock=lambda: now[0])
        self.assertEqual(token(), 'test-access')
        self.assertEqual(token(), 'test-access')
        self.assertEqual(len(calls), 1)
        self.assertNotIn('test-access', self.store.load(BINDING))
        now[0] += 600
        token()
        self.assertEqual(len(calls), 2)

    def test_write_scope_or_missing_offline_grant_is_rejected(self):
        for grant in [dict(self.grant, scope=self.grant['scope'] + ' https://www.googleapis.com/auth/drive'),
                      dict(self.grant, refresh_token='')]:
            with self.assertRaises((ValueError, PermissionError)):
                save_grant(self.store, self.client, grant)
        self.assertFalse(self.store.available(BINDING))

    def test_desktop_config_must_be_explicit_and_google_owned(self):
        self.assertEqual(load_desktop_client(self.client_path)['client_id'], self.client['client_id'])
        self.client_path.write_text(json.dumps({'installed': dict(self.client, token_uri='https://example.invalid/token')}))
        with self.assertRaises(ValueError):
            load_desktop_client(self.client_path)

    def test_host_driver_resolves_real_foundation_relative_db_config_without_creating_a_db(self):
        import runpy
        host = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'scripts/klm_drive_host_tick.py'))
        db = self.root / 'work.db'
        config = {'data_dir': str(self.root), 'work_db': 'work.db'}
        with self.assertRaisesRegex(ValueError, 'EXISTING_WORK_DB_REQUIRED'):
            host['existing_work_db'](config, self.root)
        self.assertFalse(db.exists())
        db.touch()
        self.assertEqual(host['existing_work_db'](config, self.root), db.resolve())

    def test_real_loopback_pkce_rejects_wrong_state_and_saves_native_grant(self):
        captured = {}
        threads = []
        def browser(url):
            params = parse.parse_qs(parse.urlsplit(url).query)
            captured['params'] = params
            redirect = params['redirect_uri'][0]
            def callbacks():
                try:
                    request.urlopen(redirect + '?state=wrong&code=wrong', timeout=2)
                except error.HTTPError as exc:
                    captured['wrong_status'] = exc.code
                with request.urlopen(redirect + '?' + parse.urlencode({'state': params['state'][0], 'code': 'test-code'}), timeout=2) as reply:
                    captured['right_status'] = reply.status
            t = threading.Thread(target=callbacks)
            threads.append(t)
            t.start()
            return True
        def exchange(fields):
            captured['fields'] = fields
            return self.grant
        result = authorize(self.client_path, self.store, open_browser=browser, exchange=exchange, timeout=3)
        for t in threads:
            t.join(3)
        self.assertEqual(result['status'], 'READONLY_GRANT_SAVED_AND_READ_BACK')
        self.assertEqual((captured['wrong_status'], captured['right_status']), (400, 200))
        verifier = captured['fields']['code_verifier']
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        self.assertEqual(captured['params']['code_challenge'], [challenge])
        self.assertEqual(captured['params']['code_challenge_method'], ['S256'])
        self.assertNotIn('test-code', self.store.load(BINDING))

    def test_hard_deadline_terminates_only_owned_request_child(self):
        children = []
        actual_popen = subprocess.Popen
        def slow_child(*args, **kwargs):
            child = actual_popen([sys.executable, '-c', 'import time;time.sleep(10)'], **kwargs)
            children.append(child)
            return child
        started = time.time()
        with patch('ai_foundation.klm_9b_handler.subprocess.Popen', slow_child):
            with self.assertRaises(TimeoutError):
                bounded_request({}, deadline=time.time() + .05)
        self.assertLess(time.time() - started, 2)
        self.assertIsNotNone(children[0].poll())

    def source(self):
        raw = b'{"task":"keep original"}'
        sha = hashlib.sha256(raw).hexdigest()
        pointer = {'source_id': 'approved-inbox', 'record_id': 'record-1',
                   'source_revision': 'row:' + sha, 'privacy_scope': 'private'}
        return pointer, {'raw': raw, 'sha256': sha, 'revision': pointer['source_revision']}

    def answer(self, candidate_id=1):
        return json.dumps({'atoms': [{'candidate_id': candidate_id, 'meaning': {
            'kind': 'instruction', 'modality': 'assertion', 'polarity': 'positive',
            'subject': 'owner', 'predicate': 'requests', 'object': 'preservation'}}]})

    def test_exact_source_atom_handoff_records_only_hashes_not_raw_text(self):
        journal = ReadonlyReceiptJournal(self.root / 'work.db')
        calls = []
        def infer(payload, *, deadline):
            calls.append((payload, deadline))
            return self.answer()
        handler = Existing9BKlmHandler(journal, infer=infer, clock=lambda: 100)
        p, source = self.source()
        result = handler(p, source, deadline=220)
        self.assertFalse(result['execution_authority'])
        self.assertTrue(result['result_ref'].startswith('klm-atoms-sha256:'))
        self.assertEqual(calls[0][0]['model'], MODEL)
        self.assertEqual(calls[0][0]['keep_alive'], 0)
        self.assertFalse(calls[0][0]['think'])
        self.assertIn('candidate_id', calls[0][0]['messages'][0]['content'])
        self.assertNotIn('exact unique substring', calls[0][0]['messages'][0]['content'])
        self.assertEqual(calls[0][1], 220)
        self.assertNotIn(b'keep original', journal.path.read_bytes())

    def test_unknown_or_noninteger_candidate_cannot_be_promoted(self):
        journal = ReadonlyReceiptJournal(self.root / 'work.db')
        p, source = self.source()
        for candidate in [2, 0, True, '1']:
            handler = Existing9BKlmHandler(
                journal, infer=lambda *a, **kw: self.answer(candidate), clock=lambda: 100)
            with self.assertRaises(ValueError):
                handler(p, source, deadline=220)
        import sqlite3
        with sqlite3.connect(journal.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM klm_atoms').fetchone()[0], 0)

    def test_duplicate_candidates_and_model_generated_quotes_are_rejected(self):
        journal = ReadonlyReceiptJournal(self.root / 'work.db')
        p, source = self.source()
        duplicate = json.loads(self.answer())
        duplicate['atoms'].append(duplicate['atoms'][0])
        injected = json.loads(self.answer())
        injected['atoms'][0]['quote'] = 'made up'
        for reply in (duplicate, injected):
            handler = Existing9BKlmHandler(
                journal, infer=lambda *a, **kw: json.dumps(reply), clock=lambda: 100)
            with self.assertRaises(ValueError):
                handler(p, source, deadline=220)

    def test_equal_values_keep_separate_exact_source_spans(self):
        raw = b'{"a":"same","b":"same"}'
        choices, spans = _source_candidates(raw)
        self.assertEqual(len(choices), 2)
        self.assertNotEqual(spans[1], spans[2])
        self.assertEqual(raw[slice(*spans[1])], b'same')
        self.assertEqual(raw[slice(*spans[2])], b'same')
        with self.assertRaisesRegex(ValueError, 'INBOX_CANONICAL_SOURCE_REQUIRED'):
            _source_candidates(b'{"b":"same","a":"same"}')

    def test_unverified_or_late_source_does_not_produce_a_receipt(self):
        journal = ReadonlyReceiptJournal(self.root / 'work.db')
        p, source = self.source()
        handler = Existing9BKlmHandler(journal, infer=lambda *a, **kw: self.fail('unverified source'), clock=lambda: 100)
        with self.assertRaises(ValueError):
            handler(p, dict(source, sha256='0' * 64), deadline=220)
        now = [100]
        def late(*args, deadline):
            now[0] = deadline + 1
            return self.answer()
        handler = Existing9BKlmHandler(journal, infer=late, clock=lambda: now[0])
        with self.assertRaises(TimeoutError):
            handler(p, source, deadline=220)


    def test_local_9b_bounded_structured_classification_keeps_source_spans(self):
        journal = ReadonlyReceiptJournal(self.root / 'work.db')
        pointer, source = self.source()
        observed = []
        def infer(payload, *, deadline):
            observed.append((deadline, payload['think'], payload['keep_alive'],
                             payload['options']['num_predict']))
            return self.answer()
        handler = Existing9BKlmHandler(journal, infer=infer, clock=lambda: 100)
        result = handler(pointer, source, deadline=340)
        self.assertEqual(observed, [(340, False, 0, 512)])
        self.assertFalse(result['execution_authority'])
        self.assertTrue(result['result_ref'].startswith('klm-atoms-sha256:'))
        self.assertNotIn(b'keep original', journal.path.read_bytes())

    def test_generation_schema_only_allows_canonical_meaning_categories(self):
        from ai_foundation.knowledge_lifecycle import KINDS, MODALITIES, POLARITIES
        schema = _classification_schema(9)
        self.assertFalse(schema['additionalProperties'])
        items = schema['properties']['atoms']
        self.assertEqual((items['minItems'], items['maxItems']), (1, 8))
        self.assertFalse(items['items']['additionalProperties'])
        properties = items['items']['properties']
        self.assertEqual((properties['candidate_id']['minimum'],
                          properties['candidate_id']['maximum']), (1, 9))
        meaning = properties['meaning']
        self.assertFalse(meaning['additionalProperties'])
        self.assertEqual(set(meaning['properties']['kind']['enum']), KINDS)
        self.assertEqual(set(meaning['properties']['modality']['enum']), MODALITIES)
        self.assertEqual(set(meaning['properties']['polarity']['enum']), POLARITIES)
        self.assertEqual(set(meaning['required']),
                         {'kind','modality','polarity','subject','predicate','object'})
        self.assertEqual(meaning['properties']['subject']['maxLength'], 512)
        self.assertEqual(set(meaning['properties']), set(meaning['required']) |
                         {'condition', 'speaker_claim', 'valid_from', 'valid_until'})
        self.assertEqual(meaning['properties']['condition']['type'], ['string', 'null'])
        self.assertEqual(meaning['properties']['speaker_claim']['maxLength'], 512)
        self.assertEqual(meaning['properties']['valid_from']['maxLength'], 40)
        self.assertEqual(meaning['properties']['valid_until']['maxLength'], 40)
        for count in [0, -1, 33, True, '9']:
            with self.assertRaises(ValueError):
                _classification_schema(count)

    def test_klm_model_request_uses_actual_dynamic_schema(self):
        journal = ReadonlyReceiptJournal(self.root / 'work.db')
        pointer, source = self.source()
        captures = []
        def inspect(payload, *, deadline):
            captures.append(payload['format'])
            return self.answer()
        Existing9BKlmHandler(journal, infer=inspect, clock=lambda: 100)(
            pointer, source, deadline=220)
        self.assertEqual(len(captures), 1)
        self.assertEqual(captures[0], _classification_schema(1))

    def test_over_240_second_request_is_refused_before_spawning(self):
        with self.assertRaisesRegex(TimeoutError, 'KLM_REQUEST_DEADLINE_REQUIRED'):
            bounded_request({}, deadline=341, clock=lambda: 100)


if __name__ == '__main__':
    unittest.main()
