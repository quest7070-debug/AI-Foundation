import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts.m1_strata_local_first_setup import configure_strata
from scripts.m1_strata_finish_keychain import finish_keychain, BINDING, MODEL
from ai_foundation.macos_keychain import MacOSKeychain


class Response(io.BytesIO):
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class FinishKeychainTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        configure_strata(self.root, port=18080, apply=True)
        self.payload = {"api_key": "SYNTHETIC_PRIVATE_KEY", "keychain_password": "PRIVATE_PASSWORD"}
        self.store = mock.Mock()
        self.store.load.return_value = self.payload["api_key"]
        self.factory = mock.Mock(return_value=self.store)
        self.calls = []

    def open(self, req, timeout):
        self.calls.append(req)
        self.assertIsNone(req.data)
        self.assertEqual(timeout, 10)
        self.assertEqual(req.headers["Authorization"], "Bearer " + self.payload["api_key"])
        data = {"api_key": True} if req.full_url.endswith("/health") else {"data": [{"id": MODEL}]}
        return Response(json.dumps(data).encode())

    def run_finish(self, **kwargs):
        return finish_keychain(self.root, self.payload, opener=kwargs.get("opener", self.open), keychain_factory=self.factory)

    def test_unlock_save_readback_same_instance_without_inference(self):
        result = self.run_finish()
        self.assertEqual(result, {"status": "KEYCHAIN_REGISTERED_AUTHENTICATED_MODEL_VERIFIED", "model_calls": 0})
        self.assertEqual(self.store.method_calls, [mock.call.unlock("PRIVATE_PASSWORD"), mock.call.save(BINDING, "SYNTHETIC_PRIVATE_KEY"), mock.call.load(BINDING)])
        self.assertEqual(len(self.calls), 2)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_unlock_failure_cannot_save_and_does_not_export_error(self):
        self.store.unlock.side_effect = RuntimeError("PRIVATE_PASSWORD -25308")
        result = self.run_finish()
        self.assertEqual(result, {"status": "KEYCHAIN_UNLOCK_FAILED", "model_calls": 0})
        self.store.save.assert_not_called()
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_failed_readback_is_never_registration_success(self):
        self.store.load.return_value = "DIFFERENT_SECRET"
        self.assertEqual(self.run_finish()["status"], "KEYCHAIN_READBACK_FAILED")
        self.store.save.assert_called_once()

    def test_untrusted_model_and_missing_auth_cannot_touch_keychain(self):
        for data in ({"api_key": False}, {"data": [{"id": "UNREVIEWED"}]}):
            with self.subTest(data=data):
                self.factory.reset_mock()
                def open_bad(req, **kwargs):
                    row = {"api_key": True} if "data" in data and req.full_url.endswith("/health") else data
                    return Response(json.dumps(row).encode())
                self.assertEqual(self.run_finish(opener=open_bad)["status"], "AUTHENTICATED_MODEL_UNVERIFIED")
                self.factory.assert_not_called()

    def test_changed_endpoint_and_invalid_input_are_rejected_before_network(self):
        self.payload["extra"] = "PRIVATE"
        self.assertEqual(self.run_finish()["status"], "INPUT_REJECTED")
        del self.payload["extra"]
        path = self.root / "local-compute/endpoints.json"
        doc = json.loads(path.read_text())
        doc["endpoints"][0]["base_url"] = "http://untrusted.invalid"
        path.write_text(json.dumps(doc))
        self.assertEqual(self.run_finish()["status"], "AUTH_ENDPOINT_REVIEW_REQUIRED")
        self.assertEqual(self.calls, [])
        self.factory.assert_not_called()

    def test_native_unlock_uses_memory_and_returns_fixed_error_only(self):
        store = object.__new__(MacOSKeychain)
        store.lib = mock.Mock()
        store.lib.SecKeychainUnlock.return_value = 0
        store.unlock("PRIVATE_PASSWORD")
        store.lib.SecKeychainUnlock.assert_called_once_with(None, 16, b"PRIVATE_PASSWORD", True)
        store.lib.SecKeychainUnlock.return_value = -25293
        with self.assertRaisesRegex(RuntimeError, r"unlock failed \(-25293\)"):
            store.unlock("PRIVATE_PASSWORD")


if __name__ == "__main__":
    unittest.main()
