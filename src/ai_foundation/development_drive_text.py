"""Create-once Google Drive text plans, using ONLY the already-enabled Drive API.

Alternative to native Google Docs when Docs API is disabled. Same exact
owner-consented drive.file token, appProperties plan digest, no overwrite,
delete, Docs API, other account files or privilege upgrade.

The sole allowed URLs are fixed Google Drive v3 upload/files endpoints.
"""
from __future__ import annotations

from hashlib import sha256
import json
import re
import secrets
from urllib import error, request

from .development_drive_plan import (
    APP_KEY, DRIVE_FILE_SCOPE, FILE_ID, HEX64, GooglePlanHTTPFailure,
    PlanStoreUnverified, ScopedGooglePlanHTTP, _safe_google_reason,
)


class DriveOnlyPlanHTTP(ScopedGooglePlanHTTP):
    """Fixed-origin multipart POST and raw-media GET, using same exact OAuth."""

    def _access_token(self):
        pair = self.token_supplier()
        if (type(pair) is not tuple or len(pair) != 2
                or type(pair[0]) is not str or not pair[0]
                or type(pair[1]) not in (tuple, frozenset)
                or set(pair[1]) != {DRIVE_FILE_SCOPE}):
            raise PermissionError("DRIVE_FILE_OWNER_SCOPE_REQUIRED")
        return pair[0]

    def _perform(self, req, *, media=False):
        try:
            with self.opener(req, timeout=8) as response:
                raw = response.read(131073 if not media else 8193)
        except error.HTTPError as exc:
            raise GooglePlanHTTPFailure(
                "drive", req.get_method(), int(exc.code),
                _safe_google_reason(exc)) from None
        if len(raw) > (8192 if media else 131072):
            raise PlanStoreUnverified("DRIVE_TEXT_RESPONSE_TOO_LARGE")
        if media:
            try:
                return raw.decode("utf-8", errors="strict")
            except UnicodeError as exc:
                raise PlanStoreUnverified("DRIVE_TEXT_INVALID_UTF8") from exc
        try:
            row = json.loads(raw)
        except (UnicodeError, ValueError) as exc:
            raise PlanStoreUnverified("DRIVE_TEXT_CREATE_RESPONSE_INVALID") from exc
        if type(row) is not dict:
            raise PlanStoreUnverified("DRIVE_TEXT_CREATE_RESPONSE_INVALID")
        return row

    def create_text(self, digest, content):
        if (type(digest) is not str or HEX64.fullmatch(digest) is None
                or type(content) is not str
                or not 0 < len(content.encode("utf-8")) <= 8192
                or sha256(content.encode("utf-8")).hexdigest() != digest):
            raise ValueError("INVALID_DRIVE_TEXT_PLAN")
        meta = {
            "name": "Foundation autonomous trial - " + digest[:12] + ".txt",
            "mimeType": "text/plain",
            "appProperties": {APP_KEY: digest},
        }
        boundary = "foundation" + secrets.token_hex(16)
        media = content.encode("utf-8")
        # A random boundary cannot be influenced by the candidate content.
        while boundary.encode() in media:
            boundary = "foundation" + secrets.token_hex(16)
        raw = (
            ("--" + boundary + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n").encode()
            + json.dumps(meta, sort_keys=True, separators=(",", ":")).encode()
            + ("\r\n--" + boundary + "\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n").encode()
            + media + ("\r\n--" + boundary + "--\r\n").encode()
        )
        url = ("https://www.googleapis.com/upload/drive/v3/files"
               "?uploadType=multipart&fields=id,mimeType,appProperties,size")
        req = request.Request(
            url, data=raw, method="POST",
            headers={
                "Authorization": "Bearer " + self._access_token(),
                "Accept": "application/json",
                "Content-Type": "multipart/related; boundary=" + boundary,
            },
        )
        reply = self._perform(req)
        if (type(reply.get("id")) is not str
                or FILE_ID.fullmatch(reply["id"]) is None
                or reply.get("mimeType") != "text/plain"
                or type(reply.get("appProperties")) is not dict
                or reply["appProperties"].get(APP_KEY) != digest
                or reply.get("size") != str(len(media))):
            raise PlanStoreUnverified("DRIVE_TEXT_CREATE_IDENTITY_UNVERIFIED")
        return reply["id"]

    def read_text(self, file_id):
        if type(file_id) is not str or FILE_ID.fullmatch(file_id) is None:
            raise ValueError("INVALID_DRIVE_TEXT_FILE_ID")
        req = request.Request(
            "https://www.googleapis.com/drive/v3/files/" + file_id + "?alt=media",
            headers={
                "Authorization": "Bearer " + self._access_token(),
                "Accept": "text/plain",
            },
            method="GET",
        )
        return self._perform(req, media=True)


class CreateOnlyDriveTextPlanStore:
    """Plan port compatible with admission.plan_and_submit: create_once/read.

    Digest is the same appProperties key as the native Docs port. A legacy
    Google Doc with the same digest is never reinterpreted as a text file:
    it is an unresolved existing effect and MUST NOT be duplicated.
    """
    def __init__(self, http):
        self.http = http

    def _find(self, digest):
        query = ("trashed = false and appProperties has { key='" + APP_KEY +
                 "' and value='" + digest + "' }")
        result = self.http.call("drive", "GET", "/files",
                                query={"q": query, "pageSize": 3,
                                       "fields": "nextPageToken,files(id,mimeType,appProperties)"})
        files = result.get("files")
        if (type(files) is not list or len(files) > 1 or
                result.get("nextPageToken") is not None):
            raise PlanStoreUnverified("DRIVE_TEXT_LOOKUP_COVERAGE_UNVERIFIED")
        if not files:
            return None
        item = files[0]
        if (type(item) is not dict or type(item.get("id")) is not str
                or FILE_ID.fullmatch(item["id"]) is None
                or item.get("mimeType") != "text/plain"
                or type(item.get("appProperties")) is not dict
                or item["appProperties"].get(APP_KEY) != digest):
            raise PlanStoreUnverified("DRIVE_TEXT_EXISTING_FORMAT_UNVERIFIED")
        return item["id"]

    def create_once(self, digest, content):
        if (type(digest) is not str or HEX64.fullmatch(digest) is None
                or type(content) is not str
                or not 0 < len(content.encode("utf-8")) <= 8192
                or sha256(content.encode("utf-8")).hexdigest() != digest):
            raise ValueError("INVALID_DRIVE_TEXT_PLAN")
        existing = self._find(digest)
        if existing is not None:
            if self.read(existing) != content:
                raise PlanStoreUnverified("DRIVE_TEXT_EXISTING_CONTENT_MISMATCH")
            return existing
        file_id = self.http.create_text(digest, content)
        if self.read(file_id) != content:
            raise PlanStoreUnverified("DRIVE_TEXT_WRITE_READBACK_MISMATCH")
        if self._find(digest) != file_id:
            raise PlanStoreUnverified("DRIVE_TEXT_RACE_OR_IDENTITY_UNVERIFIED")
        return file_id

    def read(self, file_id):
        return self.http.read_text(file_id)
