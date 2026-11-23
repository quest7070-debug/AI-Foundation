"""Owner-Mac adapter for the separately consented Google Drive app-file plan store.

The only source of a write-scoped credential is the existing owner Keychain
binding. The KLM read-only binding is never consulted. Construction does not
refresh credentials, call Google or create files; the host explicitly selects
a metadata probe, a non-executable acceptance plan, or Guard-bound admission.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import time

from .development_drive_consent_setup import RESULT, private_runtime, probe_app_file_scope
from .development_drive_oauth import BINDING, DriveFileToken
from .development_drive_plan import (
    CreateOnlyDrivePlanStore, ScopedGooglePlanHTTP, GooglePlanHTTPFailure, FILE_ID,
)

ACCEPTANCE = "development-drive-plan-acceptance.json"
ACCEPTANCE_LOCK = "development-drive-plan-acceptance.lock"
# A fixed, inert plan. It cannot enter the candidate/Guard/9B intake paths.
TEST_TEXT = json.dumps({
    "schema": "foundation-drive-appfile-smoke/v1",
    "execution": "NONE",
    "status": "INTEGRATION_READBACK_ONLY_NOT_AN_ADMISSION",
    "purpose": "Verify one app-created Google Doc without changing existing Drive files",
}, sort_keys=True, separators=(",", ":"))
TEST_DIGEST = sha256(TEST_TEXT.encode("utf-8")).hexdigest()


class OwnerDriveNotVerified(RuntimeError):
    pass


@dataclass(frozen=True)
class OwnerDrivePlanPort:
    runtime: Path
    token: DriveFileToken
    drive: CreateOnlyDrivePlanStore

    def probe(self):
        # Exercise the *same* scoped transport that will create the plan.
        return probe_app_file_scope(self.token, http_factory=lambda _token: self.drive.http)

    def inspect_existing_test_plan(self):
        """Reconcile an uncertain create with READ-ONLY Drive + Docs calls.

        Never create a second document, overwrite the first or claim success
        solely because Google returned an ID. This is a troubleshooting port.
        """
        self.probe()
        doc_id = self.drive._find(TEST_DIGEST)
        if doc_id is None:
            return "NOT_FOUND"
        content = self.drive.read(doc_id)
        if content == TEST_TEXT:
            return "EXACT"
        if content == "":
            return "EMPTY_AFTER_CREATE"
        return "CONTENT_MISMATCH"

    def resume_existing_empty_test_plan(self, *, clock=time.time):
        """Resume ONLY the one fixed inert acceptance Doc after uncertain create.

        The initial files.create may already have happened. It is unsafe to
        create again. Exact digest lookup + independent Docs GET determines
        whether the existing document is empty, completed or contaminated.
        """
        with _exclusive_acceptance(self.runtime):
            self.probe()
            doc_id = self.drive._find(TEST_DIGEST)
            if doc_id is None:
                raise OwnerDriveNotVerified("APPFILE_EXISTING_TEST_DOC_REQUIRED")
            current = self.drive.read(doc_id)
            if current != TEST_TEXT:
                if current != "":
                    raise OwnerDriveNotVerified("APPFILE_EXISTING_TEST_DOC_CHANGED")
                result = self.drive.http.call(
                    "docs", "POST", "/documents/" + doc_id + ":batchUpdate",
                    body={"requests": [{"insertText": {
                        "endOfSegmentLocation": {}, "text": TEST_TEXT}}]})
                if result.get("documentId") != doc_id:
                    raise OwnerDriveNotVerified("APPFILE_RESUME_RESPONSE_UNVERIFIED")
            if self.drive.read(doc_id) != TEST_TEXT:
                raise OwnerDriveNotVerified("APPFILE_RESUME_READBACK_MISMATCH")
            if self.drive._find(TEST_DIGEST) != doc_id:
                raise OwnerDriveNotVerified("APPFILE_RESUME_IDENTITY_CHANGED")
            _write_acceptance(self.runtime, doc_id, clock())
            return "APPFILE_TEST_DOC_READBACK_VERIFIED"

    def acceptance_create_once(self, *, clock=time.time):
        """Explicit owner-initiated write, serialized by one stable local lock.

        Google files.create has no compare-and-swap. Two simultaneous callers
        can both see no matching digest and create duplicate Docs. Serialize
        *before* metadata lookup and hold through the final private receipt.
        """
        with _exclusive_acceptance(self.runtime):
            self.probe()
            doc_id = self.drive.create_once(TEST_DIGEST, TEST_TEXT)
            if self.drive.read(doc_id) != TEST_TEXT:
                raise OwnerDriveNotVerified("APPFILE_TEST_READBACK_MISMATCH")
            _write_acceptance(self.runtime, doc_id, clock())
            return "APPFILE_TEST_DOC_READBACK_VERIFIED"


@contextmanager
def _exclusive_acceptance(runtime):
    """Stable owner-only lock; never remove while another process can use it."""
    path = Path(runtime) / ACCEPTANCE_LOCK
    fd = os.open(path, os.O_CREAT | os.O_RDWR |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o077):
            raise OwnerDriveNotVerified("APPFILE_ACCEPTANCE_LOCK_UNTRUSTED")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise OwnerDriveNotVerified("APPFILE_ACCEPTANCE_CONCURRENT") from exc
        yield
    finally:
        os.close(fd)


def _verified_owner_receipt(runtime, now):
    path = runtime / RESULT
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1
                or info.st_size < 12 or info.st_size > 2048
                or path.is_symlink()):
            raise OwnerDriveNotVerified("OWNER_CONSENT_RECEIPT_UNTRUSTED")
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise OwnerDriveNotVerified("OWNER_CONSENT_RECEIPT_UNAVAILABLE") from exc
    if (type(receipt) is not dict or
            set(receipt) != {"status", "scope_count", "writer_enabled", "observed_at"} or
            receipt.get("status") not in {
                "DRIVE_FILE_CONSENT_AND_READ_PROBE_VERIFIED",
                "DRIVE_FILE_CONSENT_ALREADY_VALID",
            } or type(receipt.get("scope_count")) is not int
            or receipt["scope_count"] != 1
            or receipt.get("writer_enabled") is not False
            or type(receipt.get("observed_at")) not in (int, float)
            or not math.isfinite(receipt["observed_at"])
            or not 0 < receipt["observed_at"] <= now + 60):
        raise OwnerDriveNotVerified("OWNER_CONSENT_RECEIPT_UNVERIFIED")


def load_owner_drive_plan_port(*, home=None, vault=None,
                               http_factory=ScopedGooglePlanHTTP,
                               clock=time.time):
    """One host-owned injection port for development_admission.plan_and_submit.

    The existing Guard/Work effect ledger remains the *only* execution gate.
    This adapter provides the Drive port, not verifiers, authority or executor.
    """
    runtime = private_runtime(home)
    _verified_owner_receipt(runtime, clock())
    if vault is None:
        from .macos_keychain import MacOSKeychain
        vault = MacOSKeychain()
    if vault.available(BINDING) is not True:
        raise OwnerDriveNotVerified("OWNER_APPFILE_KEYCHAIN_BINDING_REQUIRED")
    token = DriveFileToken(vault)
    drive = CreateOnlyDrivePlanStore(http_factory(token))
    return OwnerDrivePlanPort(runtime=runtime, token=token, drive=drive)


def _write_acceptance(runtime, doc_id, observed_at):
    if type(doc_id) is not str or FILE_ID.fullmatch(doc_id) is None:
        raise OwnerDriveNotVerified("APPFILE_TEST_DOC_ID_UNVERIFIED")
    if type(observed_at) not in (int, float) or not math.isfinite(observed_at):
        raise OwnerDriveNotVerified("APPFILE_TEST_TIME_UNVERIFIED")
    result = {"status": "APPFILE_TEST_DOC_READBACK_VERIFIED",
              "plan_sha256": TEST_DIGEST, "plan_id": doc_id,
              "observed_at": observed_at, "execution": "NONE"}
    fd, path = tempfile.mkstemp(prefix=".appfile-test-", dir=runtime)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(result, out, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(path, 0o600)
        os.replace(path, runtime / ACCEPTANCE)
    finally:
        if os.path.exists(path):
            os.unlink(path)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Owner Drive app-file plan verification")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--probe", action="store_true",
                       help="only metadata GET; no Drive file creation")
    modes.add_argument("--create-test-plan", action="store_true",
                       help="explicitly create/read back one inert app-owned document")
    modes.add_argument("--inspect-test-plan", action="store_true",
                       help="read-only reconciliation of a partially created test document")
    modes.add_argument("--resume-existing-test-plan", action="store_true",
                       help="repair ONLY the already-created, unchanged blank test document")
    args = parser.parse_args(argv)
    try:
        port = load_owner_drive_plan_port()
        if args.probe:
            port.probe()
            print("APPFILE_SCOPE_GET=VERIFIED")
        elif args.inspect_test_plan:
            status = port.inspect_existing_test_plan()
            print("APPFILE_TEST_DOC=" + status)
            # Not an acceptance receipt; no write or second create.
            return 0 if status == "EXACT" else 3
        elif args.resume_existing_test_plan:
            print(port.resume_existing_empty_test_plan())
        else:
            print(port.acceptance_create_once())
        return 0
    except GooglePlanHTTPFailure as exc:
        print("GOOGLE_HTTP_STAGE=" + exc.service.upper() + "_" + exc.method)
        print("GOOGLE_HTTP_STATUS=" + str(exc.status))
        print("GOOGLE_HTTP_REASON=" + exc.reason)
        return 2
    except Exception as exc:
        # Do not echo API URLs, private paths or credential-bearing exceptions.
        print("OWNER_DRIVE_PLAN=UNVERIFIED:" + type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
