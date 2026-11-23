"""Drive API only plans: fixed multipart endpoint, exact scope and readback."""
import hashlib
import json
import unittest
from urllib import error

from ai_foundation.development_drive_plan import (
    APP_KEY, DRIVE_FILE_SCOPE, PlanStoreUnverified, GooglePlanHTTPFailure,
)
from ai_foundation.development_drive_text import (
    CreateOnlyDriveTextPlanStore, DriveOnlyPlanHTTP,
)


class FakeDrive:
    def __init__(self):
        self.items = {}
        self.contents = {}
        self.requests = []
        self.corrupt = False

    def call(self, service, method, path, *, query=None, body=None):
        self.requests.append((service, method, path))
        if (service, method, path) != ("drive", "GET", "/files"):
            raise AssertionError("not read-only metadata")
        digest = query["q"].split("value='")[1].split("'")[0]
        rows = [x for x in self.items.values()
                if x["appProperties"][APP_KEY] == digest]
        return {"files": rows}

    def create_text(self, digest, text):
        self.requests.append(("drive", "POST", "/upload"))
        ident = "appOwnedTextFile_123456"
        self.items[ident] = {
            "id": ident, "mimeType": "text/plain",
            "appProperties": {APP_KEY: digest},
        }
        self.contents[ident] = text
        return ident

    def read_text(self, file_id):
        self.requests.append(("drive", "GET", "/files/alt=media"))
        return self.contents[file_id] + ("altered" if self.corrupt else "")


class TextStoreTest(unittest.TestCase):
    def setUp(self):
        self.api = FakeDrive()
        self.store = CreateOnlyDriveTextPlanStore(self.api)
        self.content = '{"schema":"foundation-drive-api-text-smoke/v1","execution":"NONE"}'
        self.digest = hashlib.sha256(self.content.encode()).hexdigest()

    def test_exact_create_read_and_idempotent_no_second_upload(self):
        first = self.store.create_once(self.digest, self.content)
        self.assertEqual(first, "appOwnedTextFile_123456")
        self.assertEqual(self.store.read(first), self.content)
        self.assertEqual(self.store.create_once(self.digest, self.content), first)
        self.assertEqual(self.api.requests.count(("drive", "POST", "/upload")), 1)
        self.assertTrue(all(x[0] == "drive" for x in self.api.requests))

    def test_native_legacy_doc_with_same_digest_is_hold_not_duplicate(self):
        self.api.items["legacyDoc12345"] = {
            "id": "legacyDoc12345",
            "mimeType": "application/vnd.google-apps.document",
            "appProperties": {APP_KEY: self.digest},
        }
        with self.assertRaisesRegex(PlanStoreUnverified, "FORMAT_UNVERIFIED"):
            self.store.create_once(self.digest, self.content)
        self.assertEqual(self.api.requests.count(("drive", "POST", "/upload")), 0)

    def test_corrupted_exact_content_no_overwrite_and_no_retry(self):
        ident = self.store.create_once(self.digest, self.content)
        self.api.corrupt = True
        with self.assertRaisesRegex(PlanStoreUnverified, "CONTENT_MISMATCH"):
            self.store.create_once(self.digest, self.content)
        self.assertEqual(self.api.requests.count(("drive", "POST", "/upload")), 1)
        self.assertEqual(ident, "appOwnedTextFile_123456")

    def test_corrupt_on_initial_readback_fails_closed(self):
        self.api.corrupt = True
        with self.assertRaisesRegex(PlanStoreUnverified, "WRITE_READBACK"):
            self.store.create_once(self.digest, self.content)
        self.assertEqual(self.api.requests.count(("drive", "POST", "/upload")), 1)

    def test_ambiguous_duplicate_denied(self):
        self.api.items["firstFile1234567"] = {
            "id": "firstFile1234567", "mimeType": "text/plain",
            "appProperties": {APP_KEY: self.digest},
        }
        self.api.items["secondFile1234567"] = {
            "id": "secondFile1234567", "mimeType": "text/plain",
            "appProperties": {APP_KEY: self.digest},
        }
        with self.assertRaisesRegex(PlanStoreUnverified, "COVERAGE_UNVERIFIED"):
            self.store.create_once(self.digest, self.content)

    def test_wrong_sha_and_long_plan_never_calls_drive(self):
        for digest, content in [("a" * 64, self.content),
                                (self.digest, "x" * 9000)]:
            with self.assertRaisesRegex(ValueError, "INVALID_DRIVE_TEXT_PLAN"):
                self.store.create_once(digest, content)
        self.assertEqual(self.api.requests, [])


class Response:
    def __init__(self, blob):
        self.blob = blob
    def __enter__(self):
        return self
    def __exit__(self, *_):
        return False
    def read(self, count):
        return self.blob[:count]


class TransportTest(unittest.TestCase):
    def setUp(self):
        self.content = '{"plan":"test"}'
        self.digest = hashlib.sha256(self.content.encode()).hexdigest()
        self.id = "exactTextFile_123456"

    def test_multipart_body_fixed_drive_upload_endpoint_and_media_get(self):
        reqs = []
        metadata = {"id": self.id, "mimeType": "text/plain",
                    "appProperties": {APP_KEY: self.digest},
                    "size": str(len(self.content.encode()))}
        def opener(req, timeout):
            reqs.append((req, timeout))
            if req.get_method() == "POST":
                return Response(json.dumps(metadata).encode())
            return Response(self.content.encode())
        http = DriveOnlyPlanHTTP(lambda: ("owner-token", (DRIVE_FILE_SCOPE,)),
                                 opener=opener)
        self.assertEqual(http.create_text(self.digest, self.content), self.id)
        self.assertEqual(http.read_text(self.id), self.content)
        upload, t1 = reqs[0]
        get, t2 = reqs[1]
        self.assertEqual((t1, t2), (8, 8))
        self.assertEqual(upload.full_url,
                         "https://www.googleapis.com/upload/drive/v3/files"
                         "?uploadType=multipart&fields=id,mimeType,appProperties,size")
        self.assertEqual(get.full_url,
                         "https://www.googleapis.com/drive/v3/files/"
                         + self.id + "?alt=media")
        self.assertTrue(upload.get_header("Content-type").startswith("multipart/related; boundary="))
        body = upload.data
        self.assertIn(b"Content-Type: application/json; charset=UTF-8", body)
        self.assertIn(b"Content-Type: text/plain; charset=UTF-8", body)
        self.assertIn(self.content.encode(), body)
        self.assertIn(self.digest.encode(), body)
        self.assertEqual(upload.get_header("Authorization"), "Bearer owner-token")
        self.assertEqual(get.get_header("Authorization"), "Bearer owner-token")
        self.assertNotIn(b"docs.googleapis.com", body)

    def test_wrong_oauth_scope_rejected_before_network(self):
        for scope in [
            ("https://www.googleapis.com/auth/drive.readonly",),
            (DRIVE_FILE_SCOPE, "https://www.googleapis.com/auth/drive"),
        ]:
            http = DriveOnlyPlanHTTP(
                lambda: ("x", scope),
                opener=lambda *_a, **_kw: self.fail("network must not open"))
            with self.assertRaisesRegex(PermissionError, "DRIVE_FILE_OWNER_SCOPE_REQUIRED"):
                http.create_text(self.digest, self.content)

    def test_invalid_file_id_and_utf8_are_not_accepted(self):
        http = DriveOnlyPlanHTTP(lambda: ("token", (DRIVE_FILE_SCOPE,)),
                                 opener=lambda *_a, **_kw: Response(b"\xff"))
        for bad in ["../private", "", "x" * 200]:
            with self.assertRaises(ValueError):
                http.read_text(bad)
        with self.assertRaisesRegex(PlanStoreUnverified, "INVALID_UTF8"):
            http.read_text(self.id)

    def test_http_error_reports_only_status_and_reason(self):
        from io import BytesIO
        def fail(req, timeout):
            raise error.HTTPError(req.full_url, 403,
                                  "private billing data", {},
                                  BytesIO(b'{"error":{"errors":[{"reason":"SERVICE_DISABLED"}]}}'))
        http = DriveOnlyPlanHTTP(lambda: ("token", (DRIVE_FILE_SCOPE,)),
                                 opener=fail)
        with self.assertRaises(GooglePlanHTTPFailure) as context:
            http.read_text(self.id)
        e = context.exception
        self.assertEqual((e.service, e.method, e.status, e.reason),
                         ("drive", "GET", 403, "SERVICE_DISABLED"))
        self.assertNotIn("private", str(e))


if __name__ == "__main__":
    unittest.main()
