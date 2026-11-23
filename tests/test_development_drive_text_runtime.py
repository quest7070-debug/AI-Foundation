"""Drive-only M1 receipt path: no Docs API, no Guard or model."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from ai_foundation.development_admission import (
    CostReceipt, BenefitReceipt, HardwareReceipt, HostContract, plan_and_submit,
)
from ai_foundation.development_drive_text_runtime import (
    text_port,
)
from ai_foundation.development_drive_text_runtime import (
    TEXT_ACCEPTANCE, TEXT_TEST_DIGEST, TEXT_TEST_TEXT,
    check_or_write,
)


class FakeTextHTTP:
    def __init__(self, token):
        self.token = token
        self.objects = {}
        self.counts = {"read": 0, "write": 0, "list": 0}

    def call(self, service, method, path, *, query=None, body=None):
        assert (service, method, path) == ("drive", "GET", "/files")
        self.counts["list"] += 1
        digest = query["q"].split("value='")[1].split("'")[0]
        return {"files": [obj["metadata"] for obj in self.objects.values()
                          if obj["metadata"]["appProperties"]["foundationAdmissionDigest"] == digest]}

    def create_text(self, digest, text):
        self.counts["write"] += 1
        file_id = "textSmokeFile_123456"
        self.objects[file_id] = {
            "metadata": {"id": file_id, "mimeType": "text/plain",
                         "appProperties": {"foundationAdmissionDigest": digest}},
            "body": text,
        }
        return file_id

    def read_text(self, file_id):
        self.counts["read"] += 1
        return self.objects[file_id]["body"]


class FakeBase:
    def __init__(self, runtime):
        self.runtime = runtime
        self.token = object()
        self.probes = 0
    def probe(self):
        self.probes += 1
        return "APPFILE_SCOPE_GET_VERIFIED"


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime = Path(self.tmp.name)
        self.runtime.chmod(0o700)
        self.base = FakeBase(self.runtime)
        self.http = FakeTextHTTP(self.base.token)
        self.factory = lambda token: self.http

    def test_inspect_absent_does_not_create(self):
        self.assertEqual(check_or_write(base=self.base, transport_class=self.factory),
                         "DRIVE_TEXT_TEST_FILE_ABSENT")
        self.assertEqual(self.http.counts["write"], 0)
        self.assertFalse((self.runtime / TEXT_ACCEPTANCE).exists())

    def test_one_inert_text_file_and_private_receipt(self):
        self.assertEqual(check_or_write(
            write=True, base=self.base, transport_class=self.factory,
            clock=lambda: 1200.0), "DRIVE_TEXT_PLAN_READBACK_VERIFIED")
        self.assertEqual(self.http.counts["write"], 1)
        receipt = self.runtime / TEXT_ACCEPTANCE
        row = json.loads(receipt.read_text())
        self.assertEqual(row["plan_sha256"], TEXT_TEST_DIGEST)
        self.assertEqual(row["execution"], "NONE")
        self.assertEqual(row["mime_type"], "text/plain")
        self.assertEqual(row["status"], "DRIVE_TEXT_PLAN_READBACK_VERIFIED")
        self.assertEqual(receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.http.objects[row["file_id"]]["body"], TEXT_TEST_TEXT)
        # A repeat is a verified read only, not a second create.
        self.assertEqual(check_or_write(
            write=True, base=self.base, transport_class=self.factory),
            "DRIVE_TEXT_PLAN_READBACK_VERIFIED")
        self.assertEqual(self.http.counts["write"], 1)

    def test_corrupted_existing_text_never_overwrites(self):
        check_or_write(write=True, base=self.base, transport_class=self.factory)
        obj = next(iter(self.http.objects.values()))
        obj["body"] = "changed by someone else"
        with self.assertRaisesRegex(Exception, "MISMATCH"):
            check_or_write(write=True, base=self.base, transport_class=self.factory)
        self.assertEqual(self.http.counts["write"], 1)

    def test_native_doc_same_digest_blocks_drive_only_migration(self):
        self.http.objects["legacyDoc_123456"] = {
            "metadata": {
                "id": "legacyDoc_123456",
                "mimeType": "application/vnd.google-apps.document",
                "appProperties": {"foundationAdmissionDigest": TEXT_TEST_DIGEST},
            },
            "body": "",
        }
        with self.assertRaisesRegex(Exception, "FORMAT_UNVERIFIED"):
            check_or_write(write=True, base=self.base, transport_class=self.factory)
        self.assertEqual(self.http.counts["write"], 0)
        self.assertFalse((self.runtime / TEXT_ACCEPTANCE).exists())

    def test_drive_text_is_real_port_shape_for_existing_guarded_admission(self):
        # Same immutable candidate digest, with Drive-only file storage.
        # The Guard/Work boundaries are NOT modified by text serialization.
        now = time.time()
        contract = HostContract(
            effect="draft_code", target="src/ai_foundation/task_result.py",
            test_sha256="a" * 64, required_ram_bytes=1024,
            required_disk_bytes=1024, minimum_relative_gain=0.1,
            guard_scope="development:fixed-test")
        receipts = (
            CostReceipt(now, "m1:cost-fixed", True, 0, 0, "NOT_APPLICABLE_LOCAL"),
            BenefitReceipt(now, "m1:benefit-fixed", "pass_rate",
                           10, 12, "higher", True),
            HardwareReceipt(now, "m1:hardware-fixed", "macOS", "arm64",
                            "Apple M1", 10 * 1024**3, 10 * 1024**3, False),
        )
        class Verifiers:
            def cost(self, *_): return receipts[0]
            def benefit(self, *_): return receipts[1]
            def hardware(self, *_): return receipts[2]
        class Guard:
            allow = False
            def authorize(self, *_): return "ALLOW" if self.allow else "DENY"
        class Queue:
            submissions = 0
            def submit(self, *_):
                self.submissions += 1
                return "queued:fixed-case"
        guard, queue = Guard(), Queue()
        _base, textstore = text_port(base=self.base, transport_class=self.factory)
        denied = plan_and_submit("fixed-case", contract=contract,
                                 verifiers=Verifiers(), drive=textstore,
                                 guard=guard, executor=queue, now=now)
        self.assertEqual(denied["reason"], "GUARD_DENIED")
        self.assertEqual(queue.submissions, 0)
        self.assertEqual(self.http.counts["write"], 1)
        guard.allow = True
        approved = plan_and_submit("fixed-case", contract=contract,
                                   verifiers=Verifiers(), drive=textstore,
                                   guard=guard, executor=queue, now=now)
        self.assertEqual(approved["status"], "SUBMITTED_UNVERIFIED")
        self.assertEqual(queue.submissions, 1)
        self.assertEqual(self.http.counts["write"], 1)
        self.assertEqual(len(self.http.objects), 1)

    def test_exact_text_digest_differs_from_old_native_acceptance(self):
        from ai_foundation.development_drive_runtime import TEST_DIGEST
        self.assertNotEqual(TEXT_TEST_DIGEST, TEST_DIGEST)
        self.assertEqual(hashlib.sha256(TEXT_TEST_TEXT.encode()).hexdigest(),
                         TEXT_TEST_DIGEST)


if __name__ == "__main__":
    unittest.main()
