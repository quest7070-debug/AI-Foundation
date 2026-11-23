import json
import os
from pathlib import Path
import tempfile
import unittest

from ai_foundation.klm_auth_setup import fresh_downloads, import_client, acquire_client, finish_setup
from ai_foundation.klm_drive_auth import BINDING, SCOPES


class Store:
    def __init__(self):
        self.values = {}
    def available(self, key):
        return key in self.values
    def load(self, key):
        return self.values[key]
    def save(self, key, value):
        self.values[key] = value


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.downloads = self.root / 'Downloads'
        self.downloads.mkdir()
        self.runtime = self.root / 'runtime'
        self.runtime.mkdir(mode=0o700)
        self.client = json.dumps({'installed': {
            'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'only-test',
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token'}})

    def download(self, name='client_secret_new.json', modified=200):
        path = self.downloads / name
        path.write_text(self.client)
        os.utime(path, (modified, modified))
        return path

    def test_only_new_stable_google_exports_are_selected(self):
        path = self.download()
        self.download('client_secret_old.json', modified=50)
        self.download('unrelated-auth-token.json')
        found, state = fresh_downloads(self.downloads, 100, {})
        self.assertEqual(found, [])
        self.assertEqual(set(state), {str(path)})
        found, _ = fresh_downloads(self.downloads, 100, state)
        self.assertEqual(found, [path])

    def test_symlink_or_growing_download_is_not_selected(self):
        path = self.download()
        (self.downloads / 'credentials_link.json').symlink_to(path)
        _, state = fresh_downloads(self.downloads, 100, {})
        path.write_text(self.client + ' ')
        found, _ = fresh_downloads(self.downloads, 100, state)
        self.assertEqual(found, [])
        self.assertNotIn(str(self.downloads / 'credentials_link.json'), state)

    def test_import_is_validated_private_and_never_overwrites(self):
        source = self.download()
        destination = self.runtime / 'oauth-client.json'
        import_client(source, destination)
        self.assertEqual(destination.read_text(), self.client)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(FileExistsError):
            import_client(source, destination)
        self.assertEqual(destination.read_text(), self.client)
        self.assertEqual(list(self.runtime.glob('.google-client-*')), [])

    def test_invalid_or_linked_config_is_not_published(self):
        source = self.download()
        source.write_text('{"refresh_token":"not-a-desktop-client"}')
        destination = self.runtime / 'oauth-client.json'
        with self.assertRaises(ValueError):
            import_client(source, destination)
        self.assertFalse(destination.exists())
        link = self.downloads / 'client_secret_link.json'
        link.symlink_to(source)
        with self.assertRaises(OSError):
            import_client(link, destination)

    def test_waiter_opens_guide_once_and_imports_download_without_path_input(self):
        self.download()
        now = [100]
        opened = []
        def sleep(seconds):
            now[0] += seconds
        result = acquire_client(self.runtime.resolve(), downloads=self.downloads,
                                started_at=100, timeout=3, clock=lambda: now[0],
                                sleep=sleep, open_browser=lambda url: opened.append(url))
        self.assertEqual(result, self.runtime.resolve() / 'oauth-client.json')
        self.assertEqual(len(opened), 1)
        self.assertTrue(opened[0].startswith('file:'))

    def test_existing_private_client_skips_download_and_guide(self):
        destination = self.runtime / 'oauth-client.json'
        destination.write_text(self.client)
        result = acquire_client(self.runtime, downloads=self.downloads, started_at=100,
                                open_browser=lambda url: self.fail('unnecessary guide'))
        self.assertEqual(result, destination)

    def test_read_probe_failure_never_resumes_scheduled_work(self):
        store = Store()
        store.save(BINDING, json.dumps({'scopes': sorted(SCOPES)}))
        def denied(token):
            raise PermissionError('read check failed')
        with self.assertRaises(PermissionError):
            finish_setup('unused', store, consent=lambda *a, **k: self.fail('unnecessary consent'),
                         probe=denied, resume=lambda: self.fail('must not resume'))

    def test_consent_then_readback_then_resume_have_fixed_order(self):
        store = Store()
        order = []
        def consent(client, native, **kwargs):
            order.append('consent')
            native.save(BINDING, json.dumps({'scopes': sorted(SCOPES)}))
        result = finish_setup('explicit-client', store, consent=consent,
                              probe=lambda token: order.append('probe'),
                              resume=lambda: order.append('resume'))
        self.assertEqual(order, ['consent', 'probe', 'resume'])
        self.assertFalse(result['klm_unattended_accepted'])

    def test_expired_own_grant_reopens_consent_once_without_manual_keychain_deletion(self):
        store = Store()
        store.save(BINDING, 'old-own-grant')
        order = []
        def probe(token):
            order.append('probe')
            if order == ['probe']:
                raise RuntimeError('OAUTH_HTTP_400')
        def consent(*args, **kwargs):
            order.append('consent')
            store.save(BINDING, 'new-own-grant')
        finish_setup('explicit', store, consent=consent, probe=probe, resume=lambda: order.append('resume'))
        self.assertEqual(order, ['probe', 'consent', 'probe', 'resume'])


    def test_oauth_non_object_reply_fails_closed_without_network(self):
        # A successful HTTP status is not evidence of a valid token response.
        from io import BytesIO
        from unittest.mock import patch
        from ai_foundation.klm_drive_auth import token_request

        class FakeOpener:
            def __init__(self, raw):
                self.raw = raw

            def open(self, req, timeout):
                self.assert_request = (req.get_method(), timeout)
                return BytesIO(self.raw)

        for raw in (b'null', b'[]', b'42', b'"PRIVATE_TOKEN"'):
            with self.subTest(raw=raw[:4]):
                opener = FakeOpener(raw)
                with patch('ai_foundation.klm_drive_auth.request.build_opener',
                           return_value=opener):
                    with self.assertRaisesRegex(
                            RuntimeError, 'OAUTH_TRANSPORT_OR_REPLY_INVALID'):
                        token_request({'grant_type': 'refresh_token'})
                self.assertEqual(opener.assert_request, ('POST', 10))

        opener = FakeOpener(b'{"access_token":"SYNTHETIC"}')
        with patch('ai_foundation.klm_drive_auth.request.build_opener',
                   return_value=opener):
            self.assertEqual(token_request({'grant_type': 'refresh_token'}),
                             {'access_token': 'SYNTHETIC'})


if __name__ == '__main__':
    unittest.main()
