"""Owner Drive app-file runtime wiring: isolated fake APIs and admission E2E."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from ai_foundation.development_admission import (
    BenefitReceipt, CostReceipt, HardwareReceipt, HostContract, plan_and_submit,
)
from ai_foundation.development_drive_consent_setup import RESULT, write_result
from ai_foundation.development_drive_runtime import (
    ACCEPTANCE, ACCEPTANCE_LOCK, TEST_DIGEST, TEST_TEXT, OwnerDriveNotVerified,
    _exclusive_acceptance, load_owner_drive_plan_port,
)


class Vault:
    def __init__(self, own=True):
        self.keys = {"development-drive-appfile-v1"} if own else {"klm-drive-readonly-v1"}
        self.read = []
    def available(self, name):
        self.read.append(name)
        return name in self.keys


class FakeGoogle:
    def __init__(self):
        self.calls = []
        self.items = {}
        self.docs = {}
        self.corrupt = False
    def call(self, service, method, path, *, query=None, body=None):
        self.calls.append((service, method, path))
        if service == "drive" and method == "GET":
            if query["q"] == "trashed = false":
                return {"files": []}
            digest = query["q"].split("value='")[1].split("'")[0]
            return {"files": [row for row in self.items.values()
                               if row["appProperties"]["foundationAdmissionDigest"] == digest]}
        if service == "drive" and method == "POST":
            doc_id = "ownerappfiledocid123"
            row = {"id": doc_id, "mimeType": body["mimeType"],
                   "appProperties": body["appProperties"]}
            self.items[doc_id] = row
            self.docs[doc_id] = ""
            return row
        if service == "docs" and method == "POST":
            doc_id = path.split("/")[2].split(":")[0]
            self.docs[doc_id] = body["requests"][0]["insertText"]["text"]
            return {"documentId": doc_id}
        if service == "docs" and method == "GET":
            text = self.docs[path.split("/")[-1]]
            return {"body": {"content": [{"paragraph": {"elements": [
                {"textRun": {"content": text + ("changed" if self.corrupt else "") + "\n"}}
            ]}}]}}
        raise AssertionError((service, method, path))


class PortTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.runtime = self.home / "Library/Application Support/AI-Foundation/klm-drive"
        self.runtime.mkdir(mode=0o700, parents=True)
        write_result(self.runtime, {
            "status": "DRIVE_FILE_CONSENT_AND_READ_PROBE_VERIFIED",
            "scope_count": 1, "writer_enabled": False,
        })
        self.vault = Vault()
        self.google = FakeGoogle()

    def port(self, **kwargs):
        return load_owner_drive_plan_port(
            home=self.home, vault=kwargs.pop("vault", self.vault),
            clock=kwargs.pop("clock", time.time),
            http_factory=lambda _token: self.google, **kwargs)

    def test_port_is_lazy_and_uses_only_separate_owner_binding(self):
        port = self.port()
        self.assertEqual(self.google.calls, [])
        self.assertEqual(self.vault.read, ["development-drive-appfile-v1"])
        self.assertTrue(port.token.available())
        self.assertNotIn("klm-drive-readonly-v1", self.vault.read)

    def test_scope_probe_is_metadata_get_only(self):
        self.port().probe()
        self.assertEqual(self.google.calls, [("drive", "GET", "/files")])
        self.assertFalse((self.runtime / ACCEPTANCE).exists())

    def test_inert_test_doc_creates_only_once_with_independent_readback(self):
        port = self.port()
        self.assertEqual(port.acceptance_create_once(), "APPFILE_TEST_DOC_READBACK_VERIFIED")
        self.assertEqual(port.acceptance_create_once(), "APPFILE_TEST_DOC_READBACK_VERIFIED")
        proof = json.loads((self.runtime / ACCEPTANCE).read_text())
        self.assertEqual(proof["plan_sha256"], TEST_DIGEST)
        self.assertEqual(proof["status"], "APPFILE_TEST_DOC_READBACK_VERIFIED")
        self.assertEqual(proof["execution"], "NONE")
        self.assertEqual(list(self.google.docs.values()), [TEST_TEXT])
        self.assertEqual(sum(x[:2] == ("drive", "POST") for x in self.google.calls), 1)
        self.assertEqual((self.runtime / ACCEPTANCE).stat().st_mode & 0o777, 0o600)

    def test_read_only_reconciliation_detects_existing_blank_and_exact_doc(self):
        port = self.port()
        self.assertEqual(port.inspect_existing_test_plan(), "NOT_FOUND")
        doc_id = "ownerappfiledocid123"
        self.google.items[doc_id] = {
            "id": doc_id, "mimeType": "application/vnd.google-apps.document",
            "appProperties": {"foundationAdmissionDigest": TEST_DIGEST},
        }
        self.google.docs[doc_id] = ""
        self.assertEqual(port.inspect_existing_test_plan(), "EMPTY_AFTER_CREATE")
        self.google.docs[doc_id] = TEST_TEXT
        self.assertEqual(port.inspect_existing_test_plan(), "EXACT")
        self.assertFalse(any(method == "POST" for _, method, _ in self.google.calls))
        self.assertFalse((self.runtime / ACCEPTANCE).exists())


    def test_acceptance_lock_serializes_before_any_google_call(self):
        port = self.port()
        with _exclusive_acceptance(self.runtime):
            with self.assertRaisesRegex(
                    OwnerDriveNotVerified, "APPFILE_ACCEPTANCE_CONCURRENT"):
                port.acceptance_create_once()
            self.assertEqual(self.google.calls, [])
            self.assertFalse((self.runtime / ACCEPTANCE).exists())
        self.assertEqual(port.acceptance_create_once(),
                         "APPFILE_TEST_DOC_READBACK_VERIFIED")
        self.assertEqual(sum(x[:2] == ("drive", "POST")
                             for x in self.google.calls), 1)

    def test_untrusted_lock_permissions_block_without_request(self):
        lock = self.runtime / ACCEPTANCE_LOCK
        lock.write_text("")
        lock.chmod(0o644)
        with self.assertRaisesRegex(
                OwnerDriveNotVerified, "APPFILE_ACCEPTANCE_LOCK_UNTRUSTED"):
            self.port().acceptance_create_once()
        self.assertEqual(self.google.calls, [])
        self.assertFalse((self.runtime / ACCEPTANCE).exists())

    def test_lock_is_stable_private_sidecar_not_unlinked(self):
        lock = self.runtime / ACCEPTANCE_LOCK
        self.port().acceptance_create_once()
        self.assertTrue(lock.is_file())
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        inode = lock.stat().st_ino
        self.port().acceptance_create_once()
        self.assertEqual(lock.stat().st_ino, inode)
        self.assertEqual(sum(x[:2] == ("drive", "POST")
                             for x in self.google.calls), 1)

    def test_resume_existing_blank_writes_only_that_doc_and_never_recreates(self):
        doc_id = "ownerappfiledocid123"
        self.google.items[doc_id] = {
            "id": doc_id, "mimeType": "application/vnd.google-apps.document",
            "appProperties": {"foundationAdmissionDigest": TEST_DIGEST},
        }
        self.google.docs[doc_id] = ""
        port = self.port()
        self.assertEqual(port.resume_existing_empty_test_plan(),
                         "APPFILE_TEST_DOC_READBACK_VERIFIED")
        self.assertEqual(self.google.docs[doc_id], TEST_TEXT)
        self.assertEqual(port.resume_existing_empty_test_plan(),
                         "APPFILE_TEST_DOC_READBACK_VERIFIED")
        self.assertEqual(sum(x[:2] == ("drive", "POST") for x in self.google.calls), 0)
        self.assertEqual(sum(x[:2] == ("docs", "POST") for x in self.google.calls), 1)
        receipt = json.loads((self.runtime / ACCEPTANCE).read_text())
        self.assertEqual(receipt["plan_id"], doc_id)

    def test_resume_does_not_create_or_mutate_unrecognized_document(self):
        port = self.port()
        with self.assertRaisesRegex(OwnerDriveNotVerified, "EXISTING_TEST_DOC_REQUIRED"):
            port.resume_existing_empty_test_plan()
        doc_id = "ownerappfiledocid123"
        self.google.items[doc_id] = {
            "id": doc_id, "mimeType": "application/vnd.google-apps.document",
            "appProperties": {"foundationAdmissionDigest": TEST_DIGEST},
        }
        self.google.docs[doc_id] = "someone else's edits"
        with self.assertRaisesRegex(OwnerDriveNotVerified, "EXISTING_TEST_DOC_CHANGED"):
            port.resume_existing_empty_test_plan()
        self.assertFalse(any(method == "POST" for _, method, _ in self.google.calls))
        self.assertFalse((self.runtime / ACCEPTANCE).exists())

    def test_uncertain_write_does_not_generate_acceptance_receipt(self):
        self.google.corrupt = True
        with self.assertRaisesRegex(Exception, "READBACK"):
            self.port().acceptance_create_once()
        self.assertFalse((self.runtime / ACCEPTANCE).exists())
        with self.assertRaisesRegex(Exception, "CONTENT_MISMATCH"):
            self.port().acceptance_create_once()
        self.assertEqual(sum(x[:2] == ("drive", "POST") for x in self.google.calls), 1)

    def test_missing_receipt_is_a_hold_without_keychain_access(self):
        (self.runtime / RESULT).unlink()
        with self.assertRaises(OwnerDriveNotVerified):
            self.port()
        self.assertEqual(self.vault.read, [])

    def test_unsafe_receipt_modes_or_symlink_rejected(self):
        receipt = self.runtime / RESULT
        receipt.chmod(0o644)
        with self.assertRaises(OwnerDriveNotVerified):
            self.port()
        receipt.chmod(0o600)
        target = self.runtime / "other"
        receipt.rename(target)
        receipt.symlink_to(target)
        with self.assertRaises(OwnerDriveNotVerified):
            self.port()

    def test_forged_authority_fields_and_future_time_rejected(self):
        receipt = self.runtime / RESULT
        saved = json.loads(receipt.read_text())
        saved["writer_enabled"] = True
        receipt.write_text(json.dumps(saved))
        with self.assertRaises(OwnerDriveNotVerified):
            self.port()
        saved["writer_enabled"] = False
        saved["observed_at"] = time.time() + 3600
        receipt.write_text(json.dumps(saved))
        with self.assertRaises(OwnerDriveNotVerified):
            self.port()
        saved["observed_at"] = time.time()
        saved["guard_allow"] = True
        receipt.write_text(json.dumps(saved))
        with self.assertRaises(OwnerDriveNotVerified):
            self.port()

    def test_readonly_grant_never_substitutes_owner_appfile_grant(self):
        with self.assertRaisesRegex(OwnerDriveNotVerified, "APPFILE_KEYCHAIN"):
            self.port(vault=Vault(own=False))

    def test_existing_verified_consent_accepted_without_new_oauth(self):
        row = json.loads((self.runtime / RESULT).read_text())
        row["status"] = "DRIVE_FILE_CONSENT_ALREADY_VALID"
        (self.runtime / RESULT).write_text(json.dumps(row))
        self.assertIsNotNone(self.port().drive)

    def test_port_drives_existing_admission_plan_and_guard_not_a_new_gate(self):
        now = time.time()
        contract = HostContract(
            effect="draft_code", target="src/ai_foundation/task_result.py",
            test_sha256="a" * 64, required_ram_bytes=1024,
            required_disk_bytes=1024, minimum_relative_gain=0.1,
            guard_scope="development:fixed-test")
        receipts = (
            CostReceipt(now, "m1:cost-receipt", True, 0, 0, "NOT_APPLICABLE_LOCAL"),
            BenefitReceipt(now, "m1:benefit-receipt", "pass_rate", 10, 12, "higher", True),
            HardwareReceipt(now, "m1:hardware-receipt", "macOS", "arm64", "Apple M1",
                            10 * 1024**3, 10 * 1024**3, False),
        )
        class Verifiers:
            def cost(self, *_): return receipts[0]
            def benefit(self, *_): return receipts[1]
            def hardware(self, *_): return receipts[2]
        class Guard:
            status = "DENY"
            def authorize(self, *_): return self.status
        class Executor:
            submitted = False
            def submit(self, *_):
                self.submitted = True
                return "queued:test"
        guard, executor = Guard(), Executor()
        port = self.port()
        denied = plan_and_submit(
            "owner-trial", contract=contract, verifiers=Verifiers(),
            drive=port.drive, guard=guard, executor=executor, now=now)
        self.assertEqual(denied["reason"], "GUARD_DENIED")
        self.assertFalse(executor.submitted)
        guard.status = "ALLOW"
        allowed = plan_and_submit(
            "owner-trial", contract=contract, verifiers=Verifiers(),
            drive=port.drive, guard=guard, executor=executor, now=now)
        self.assertEqual(allowed["status"], "SUBMITTED_UNVERIFIED")
        self.assertTrue(executor.submitted)
        self.assertEqual(sum(x[:2] == ("drive", "POST") for x in self.google.calls), 1)


if __name__ == "__main__":
    unittest.main()
