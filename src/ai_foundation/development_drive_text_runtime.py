"""Owner-only Drive API text writer acceptance, never Docs API nor 9B.

Uses the same approved drive.file Keychain/token, private consent receipt and
stable owner-only acceptance lock as the native Doc port. This is an explicit
inert smoke, not a general write-enable switch.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import tempfile
import time

from .development_drive_plan import GooglePlanHTTPFailure, FILE_ID
from .development_drive_runtime import (
    _exclusive_acceptance, load_owner_drive_plan_port,
)
from .development_drive_text import DriveOnlyPlanHTTP, CreateOnlyDriveTextPlanStore

TEXT_ACCEPTANCE = "development-drive-text-acceptance.json"
TEXT_TEST_TEXT = json.dumps({
    "schema": "foundation-drive-api-text-smoke/v1",
    "execution": "NONE",
    "status": "INTEGRATION_READBACK_ONLY_NOT_AN_ADMISSION",
    "purpose": "Verify Drive-only UTF-8 plan upload and exact media readback",
}, sort_keys=True, separators=(",", ":"))
TEXT_TEST_DIGEST = sha256(TEXT_TEST_TEXT.encode("utf-8")).hexdigest()


def _write_text_receipt(runtime, file_id, checked_at):
    if (type(file_id) is not str or FILE_ID.fullmatch(file_id) is None
            or type(checked_at) not in (float, int) or
            not math.isfinite(checked_at) or checked_at <= 0):
        raise ValueError("DRIVE_TEXT_RECEIPT_UNVERIFIED")
    payload = {
        "status": "DRIVE_TEXT_PLAN_READBACK_VERIFIED",
        "file_id": file_id,
        "plan_sha256": TEXT_TEST_DIGEST,
        "observed_at": checked_at,
        "mime_type": "text/plain",
        "execution": "NONE",
    }
    fd, temp = tempfile.mkstemp(prefix=".drive-text-test-", dir=runtime)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(payload, out, sort_keys=True)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, Path(runtime) / TEXT_ACCEPTANCE)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def text_port(*, base=None, transport_class=DriveOnlyPlanHTTP):
    base = load_owner_drive_plan_port() if base is None else base
    http = transport_class(base.token)
    return base, CreateOnlyDriveTextPlanStore(http)


def check_or_write(*, write=False, base=None, transport_class=DriveOnlyPlanHTTP,
                   clock=time.time):
    base, store = text_port(base=base, transport_class=transport_class)
    # The owner app's exact Drive OAuth scope must work before a read/write.
    base.probe()
    if not write:
        existing = store._find(TEXT_TEST_DIGEST)
        if existing is None:
            return "DRIVE_TEXT_TEST_FILE_ABSENT"
        if store.read(existing) != TEXT_TEST_TEXT:
            raise ValueError("DRIVE_TEXT_EXISTING_CONTENT_UNVERIFIED")
        return "DRIVE_TEXT_TEST_FILE_EXACT"
    # Lock before the second metadata lookup, actual multipart creation and
    # receipt so concurrent owner workflows can never duplicate the plan.
    with _exclusive_acceptance(base.runtime):
        file_id = store.create_once(TEXT_TEST_DIGEST, TEXT_TEST_TEXT)
        if store.read(file_id) != TEXT_TEST_TEXT:
            raise ValueError("DRIVE_TEXT_READBACK_UNVERIFIED")
        if store._find(TEXT_TEST_DIGEST) != file_id:
            raise ValueError("DRIVE_TEXT_IDENTITY_UNVERIFIED")
        _write_text_receipt(base.runtime, file_id, clock())
    return "DRIVE_TEXT_PLAN_READBACK_VERIFIED"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Owner-only Drive text writer acceptance")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--inspect", action="store_true",
                       help="Drive metadata + optional text media GET; no changes")
    modes.add_argument("--create-inert-text", action="store_true",
                       help="one fixed non-executable Drive text plan, no Docs API")
    args = parser.parse_args(argv)
    try:
        print(check_or_write(write=args.create_inert_text))
        return 0
    except GooglePlanHTTPFailure as exc:
        print("GOOGLE_HTTP_STAGE=DRIVE_TEXT")
        print("GOOGLE_HTTP_STATUS=" + str(exc.status))
        print("GOOGLE_HTTP_REASON=" + exc.reason)
        return 2
    except Exception as exc:
        # Stable class name only; never print exception messages or URLs.
        print("DRIVE_TEXT_PLAN=UNVERIFIED:" + type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
