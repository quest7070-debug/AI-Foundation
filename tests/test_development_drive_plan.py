"""All Google calls are fake; verifies create-only scope and unknown-effect denial."""
import hashlib
import io
import json
import unittest
from urllib import error

from ai_foundation.development_drive_plan import (
    CreateOnlyDrivePlanStore, PlanStoreUnverified, ScopedGooglePlanHTTP,
    DRIVE_FILE_SCOPE, GooglePlanHTTPFailure, _doc_text,
)


class FakeGoogle:
    def __init__(self):
        self.items = {}
        self.text = {}
        self.calls = []
        self.duplicate = False
        self.write_mismatch = False
        self.fail_docs_write = False

    def call(self, service, method, path, *, query=None, body=None):
        self.calls.append((service, method, path))
        if service == "drive" and method == "GET":
            digest = query["q"].split("value='")[1].split("'")[0]
            docs = [x for x in self.items.values()
                    if x["appProperties"]["foundationAdmissionDigest"] == digest]
            if self.duplicate and docs:
                docs *= 2
            return {"files": docs}
        if service == "drive" and method == "POST":
            doc_id = "planfileid123456"
            row = {"id": doc_id, "mimeType": body["mimeType"],
                   "appProperties": body["appProperties"]}
            self.items[doc_id] = row
            self.text[doc_id] = ""
            return dict(row)
        if service == "docs" and method == "POST":
            if self.fail_docs_write:
                raise RuntimeError("timeout after Drive create")
            doc_id = path.split("/")[2].split(":")[0]
            self.text[doc_id] = body["requests"][0]["insertText"]["text"]
            return {"documentId": doc_id}
        if service == "docs" and method == "GET":
            doc_id = path.split("/")[-1]
            body = self.text[doc_id]
            return {"body": {"content": [{"paragraph": {"elements": [
                {"textRun": {"content": body + ("changed" if self.write_mismatch else "") + "\n"}}]}}]}}
        raise AssertionError("unexpected API request")


class DrivePlanTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeGoogle()
        self.store = CreateOnlyDrivePlanStore(self.server)
        self.text = '{"candidate":"oss"}'
        self.digest = hashlib.sha256(self.text.encode()).hexdigest()

    def test_create_read_and_idempotent_read(self):
        first = self.store.create_once(self.digest, self.text)
        self.assertEqual(first, "planfileid123456")
        self.assertEqual(self.store.read(first), self.text)
        self.assertEqual(self.store.create_once(self.digest, self.text), first)
        self.assertEqual([x[:2] for x in self.server.calls].count(("drive", "POST")), 1)

    def test_digest_mismatch_fails_before_request(self):
        with self.assertRaisesRegex(ValueError, "PLAN_DIGEST_MISMATCH"):
            self.store.create_once("a"*64, self.text)
        self.assertEqual(self.server.calls, [])

    def test_unknown_duplicate_fails_closed(self):
        self.store.create_once(self.digest, self.text)
        self.server.duplicate = True
        with self.assertRaisesRegex(PlanStoreUnverified, "COVERAGE"):
            self.store.create_once(self.digest, self.text)

    def test_existing_content_modified_does_not_overwrite(self):
        self.store.create_once(self.digest, self.text)
        self.server.text["planfileid123456"] = "{}"
        with self.assertRaisesRegex(PlanStoreUnverified, "CONTENT_MISMATCH"):
            self.store.create_once(self.digest, self.text)
        self.assertEqual([x[:2] for x in self.server.calls].count(("drive", "POST")), 1)

    def test_created_but_docs_timeout_cannot_retry_write(self):
        self.server.fail_docs_write = True
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            self.store.create_once(self.digest, self.text)
        self.server.fail_docs_write = False
        with self.assertRaisesRegex(PlanStoreUnverified, "CONTENT_MISMATCH"):
            self.store.create_once(self.digest, self.text)
        self.assertEqual([x[:2] for x in self.server.calls].count(("drive", "POST")), 1)

    def test_docs_readback_mismatch_rejected(self):
        self.server.write_mismatch = True
        with self.assertRaisesRegex(PlanStoreUnverified, "DOC_WRITE_READBACK"):
            self.store.create_once(self.digest, self.text)

    def test_large_plan_denied_before_request(self):
        with self.assertRaisesRegex(ValueError, "INVALID_PLAN"):
            self.store.create_once(self.digest, "x"*9000)

    def test_nontext_docs_controls_fail_closed(self):
        with self.assertRaisesRegex(PlanStoreUnverified, "NON_TEXT"):
            _doc_text({"body": {"content": [{"paragraph": {"elements": [
                {"inlineObjectElement": {"inlineObjectId": "private"}}]}}]}})

    def test_multitab_docs_fail_closed(self):
        with self.assertRaisesRegex(PlanStoreUnverified, "TABS"):
            _doc_text({"tabs": [{}, {}]})

    def test_no_broad_scope_accepted(self):
        http = ScopedGooglePlanHTTP(
            lambda: ("secret", ("https://www.googleapis.com/auth/drive.readonly",)),
            opener=lambda *_a, **_k: self.fail("request must not run"))
        with self.assertRaisesRegex(PermissionError, "DRIVE_FILE_OWNER_SCOPE_REQUIRED"):
            http.call("drive", "GET", "/files")

    def test_invalid_external_origin_never_opened(self):
        http = ScopedGooglePlanHTTP(
            lambda: ("secret", (DRIVE_FILE_SCOPE,)),
            opener=lambda *_a, **_k: self.fail("request must not run"))
        with self.assertRaisesRegex(PermissionError, "DOCS_API_SCOPE_DENIED"):
            http.call("docs", "GET", "/documents/../../secret")

    def test_http_error_reports_only_safe_stage_status_and_reason(self):
        body = b'{"error":{"status":"PERMISSION_DENIED","errors":[{"reason":"accessNotConfigured","message":"private-account-token"}]}}'
        def opener(req, timeout):
            raise error.HTTPError(req.full_url, 403, "Forbidden private-account-token",
                                  {}, io.BytesIO(body))
        http = ScopedGooglePlanHTTP(lambda: ("secret", (DRIVE_FILE_SCOPE,)),
                                    opener=opener)
        with self.assertRaises(GooglePlanHTTPFailure) as caught:
            http.call("docs", "GET", "/documents/ownerappfiledocid123")
        failure = caught.exception
        self.assertEqual((failure.service, failure.method, failure.status, failure.reason),
                         ("docs", "GET", 403, "accessNotConfigured"))
        self.assertNotIn("private-account-token", str(failure))
        self.assertNotIn("secret", str(failure))
        self.assertNotIn("docs.googleapis.com", str(failure))

    def test_http_error_malformed_response_is_not_logged(self):
        def opener(req, timeout):
            raise error.HTTPError(req.full_url, 500, "Oops", {},
                                  io.BytesIO(b'private-account-token'))
        http = ScopedGooglePlanHTTP(lambda: ("secret", (DRIVE_FILE_SCOPE,)),
                                    opener=opener)
        with self.assertRaises(GooglePlanHTTPFailure) as caught:
            http.call("drive", "GET", "/files")
        self.assertEqual(caught.exception.reason, "UNKNOWN")
        self.assertEqual(caught.exception.status, 500)

    def test_owner_scoped_http_has_fixed_google_origin(self):
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def read(self, _): return b'{"files":[]}'
        def opener(req, timeout):
            calls.append((req.full_url, req.get_method(), timeout,
                          req.get_header("Authorization")))
            return Response()
        http = ScopedGooglePlanHTTP(lambda: ("short-lived", (DRIVE_FILE_SCOPE,)),
                                    opener=opener)
        self.assertEqual(http.call("drive", "GET", "/files"), {"files": []})
        self.assertEqual(calls[0][0], "https://www.googleapis.com/drive/v3/files")
        self.assertEqual(calls[0][1:3], ("GET", 8))
        self.assertEqual(calls[0][3], "Bearer short-lived")


if __name__ == "__main__":
    unittest.main()
