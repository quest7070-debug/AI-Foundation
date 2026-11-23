"""Create-only Google Drive plan store for a SEPARATELY owner-consented drive.file grant.

KLM's existing OAuth is read-only and MUST NOT be reused or widened.
This adapter sees only its app-created documents, never old Drive originals.
No token discovery, service installation, shared-folder mutation or generic API.
"""
from __future__ import annotations

import json
import re
from urllib import error, parse, request

DRIVE_FILE_SCOPE = "https://www.googleapis.com/auth/drive.file"
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")
APP_KEY = "foundationAdmissionDigest"


class PlanStoreUnverified(RuntimeError):
    pass


class GooglePlanHTTPFailure(PlanStoreUnverified):
    """Sanitized HTTP failure; API response body, URL and tokens stay private."""
    def __init__(self, service, method, status, reason="UNKNOWN"):
        self.service = service
        self.method = method
        self.status = status
        self.reason = reason
        super().__init__("GOOGLE_HTTP_UNVERIFIED")


def _safe_google_reason(exc):
    """Only a bounded machine code may cross the credential boundary."""
    try:
        raw = exc.read(8192)
        row = json.loads(raw)
        obj = row.get("error", {})
        if type(obj) is not dict:
            return "UNKNOWN"
        reasons = [obj.get("status")]
        errors = obj.get("errors", [])
        if type(errors) is list:
            reasons.extend(e.get("reason") for e in errors[:3] if type(e) is dict)
        details = obj.get("details", [])
        if type(details) is list:
            reasons.extend(e.get("reason") for e in details[:3] if type(e) is dict)
        for item in reversed(reasons):
            if type(item) is str and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", item):
                return item
    except (OSError, ValueError, TypeError):
        pass
    return "UNKNOWN"



def _doc_text(document):
    """Read exactly one generated single-tab Docs body, with no opaque controls."""
    if type(document) is not dict:
        raise PlanStoreUnverified("DOC_SCHEMA_INVALID")
    body = document.get("body")
    if type(body) is not dict:
        tabs = document.get("tabs")
        if (type(tabs) is not list or len(tabs) != 1 or
                type(tabs[0]) is not dict or type(tabs[0].get("documentTab")) is not dict):
            raise PlanStoreUnverified("DOC_TABS_UNVERIFIED")
        body = tabs[0]["documentTab"].get("body")
    if type(body) is not dict or type(body.get("content")) is not list:
        raise PlanStoreUnverified("DOC_BODY_UNVERIFIED")
    chunks = []
    for item in body["content"]:
        if type(item) is not dict or item.get("table") is not None:
            raise PlanStoreUnverified("DOC_STRUCTURE_UNVERIFIED")
        para = item.get("paragraph")
        if para is None:
            continue
        if type(para) is not dict or type(para.get("elements")) is not list:
            raise PlanStoreUnverified("DOC_ELEMENTS_UNVERIFIED")
        for element in para["elements"]:
            if (type(element) is not dict or
                    type(element.get("textRun")) is not dict or
                    type(element["textRun"].get("content")) is not str):
                raise PlanStoreUnverified("DOC_NON_TEXT_ELEMENT")
            chunks.append(element["textRun"]["content"])
    text = "".join(chunks)
    return text[:-1] if text.endswith("\n") else text


class ScopedGooglePlanHTTP:
    """Tiny fixed-host HTTP transport. Token supplier returns (token, scopes).

    The owner binding must independently verify the exact granted scopes from
    Google's token exchange/refresh; this class never upgrades OAuth itself.
    """
    ORIGINS = {"drive": "https://www.googleapis.com/drive/v3",
               "docs": "https://docs.googleapis.com/v1"}

    def __init__(self, token_supplier, *, opener=None):
        self.token_supplier = token_supplier
        self.opener = request.urlopen if opener is None else opener

    def call(self, service, method, path, *, query=None, body=None):
        if service not in self.ORIGINS or method not in ("GET", "POST"):
            raise PermissionError("UNSUPPORTED_PLAN_API")
        # Only the exact resource paths required by our store; no arbitrary API.
        if service == "drive":
            if path != "/files" or (method == "POST" and query):
                raise PermissionError("DRIVE_API_SCOPE_DENIED")
        elif not re.fullmatch(r"/documents/[A-Za-z0-9_-]{10,160}(?::batchUpdate)?", path):
            raise PermissionError("DOCS_API_SCOPE_DENIED")
        elif (method == "POST") != path.endswith(":batchUpdate"):
            raise PermissionError("DOCS_METHOD_DENIED")
        if method == "GET" and body is not None:
            raise PermissionError("GET_BODY_DENIED")
        token_and_scopes = self.token_supplier()
        if (type(token_and_scopes) is not tuple or len(token_and_scopes) != 2 or
                type(token_and_scopes[0]) is not str or not token_and_scopes[0] or
                type(token_and_scopes[1]) not in (tuple, frozenset) or
                set(token_and_scopes[1]) != {DRIVE_FILE_SCOPE}):
            raise PermissionError("DRIVE_FILE_OWNER_SCOPE_REQUIRED")
        url = self.ORIGINS[service] + path
        if query:
            if method != "GET" or service != "drive" or path != "/files":
                raise PermissionError("QUERY_SCOPE_DENIED")
            url += "?" + parse.urlencode(query)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Authorization": "Bearer " + token_and_scopes[0],
                   "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = request.Request(url, headers=headers, data=data, method=method)
        try:
            with self.opener(req, timeout=8) as response:
                raw = response.read(131073)
                if len(raw) > 131072:
                    raise PlanStoreUnverified("GOOGLE_RESPONSE_TOO_LARGE")
                parsed = json.loads(raw)
                if type(parsed) is not dict:
                    raise PlanStoreUnverified("GOOGLE_SCHEMA_UNVERIFIED")
                return parsed
        except error.HTTPError as exc:
            # No URL, headers, response body or client credential in reports.
            raise GooglePlanHTTPFailure(
                service, method, int(exc.code), _safe_google_reason(exc)) from None


class CreateOnlyDrivePlanStore:
    """Drive/Docs adapter: owner app's own files, no deletion or updates to old files.

    Concurrent writers MUST be serialized by the existing Guard/Work effect
    claim. No backend CAS exists for Google files.create. An uncertain create
    requires re-query by digest before a caller may ever retry.
    """
    def __init__(self, transport):
        self.http = transport

    def _find(self, digest):
        query = ("trashed = false and appProperties has { key='" + APP_KEY +
                 "' and value='" + digest + "' }")
        result = self.http.call("drive", "GET", "/files",
                                query={"q": query, "pageSize": 3,
                                       "fields": "nextPageToken,files(id,mimeType,appProperties)"})
        files = result.get("files")
        if (type(files) is not list or len(files) > 1 or
                result.get("nextPageToken") is not None):
            raise PlanStoreUnverified("PLAN_LOOKUP_COVERAGE_UNVERIFIED")
        if files:
            item = files[0]
            if (type(item) is not dict or type(item.get("id")) is not str or
                    not FILE_ID.fullmatch(item["id"]) or
                    item.get("mimeType") != "application/vnd.google-apps.document" or
                    type(item.get("appProperties")) is not dict or
                    item["appProperties"].get(APP_KEY) != digest):
                raise PlanStoreUnverified("PLAN_IDENTITY_UNVERIFIED")
            return item["id"]
        return None

    def create_once(self, digest, text):
        if (type(digest) is not str or not HEX64.fullmatch(digest) or
                type(text) is not str or not text or
                len(text.encode("utf-8")) > 8192):
            raise ValueError("INVALID_PLAN")
        if __import__("hashlib").sha256(text.encode("utf-8")).hexdigest() != digest:
            raise ValueError("PLAN_DIGEST_MISMATCH")
        existing = self._find(digest)
        if existing is not None:
            if self.read(existing) != text:
                raise PlanStoreUnverified("EXISTING_PLAN_CONTENT_MISMATCH")
            return existing
        created = self.http.call("drive", "POST", "/files", body={
            "name": "Foundation autonomous trial - " + digest[:12],
            "mimeType": "application/vnd.google-apps.document",
            "appProperties": {APP_KEY: digest},
        })
        doc_id = created.get("id")
        if (type(doc_id) is not str or not FILE_ID.fullmatch(doc_id) or
                created.get("mimeType") != "application/vnd.google-apps.document"):
            raise PlanStoreUnverified("CREATE_RESPONSE_UNVERIFIED")
        # A create followed by failed content writing is UNCERTAIN; future
        # calls observe this digest and refuse to overwrite/create again.
        written = self.http.call("docs", "POST", "/documents/" + doc_id + ":batchUpdate",
                                 body={"requests": [{"insertText": {
                                     "endOfSegmentLocation": {}, "text": text}}]})
        if written.get("documentId") != doc_id or self.read(doc_id) != text:
            raise PlanStoreUnverified("DOC_WRITE_READBACK_MISMATCH")
        if self._find(digest) != doc_id:
            raise PlanStoreUnverified("PLAN_RACE_OR_IDENTITY_UNVERIFIED")
        return doc_id

    def read(self, doc_id):
        if type(doc_id) is not str or not FILE_ID.fullmatch(doc_id):
            raise ValueError("INVALID_PLAN_ID")
        return _doc_text(self.http.call("docs", "GET", "/documents/" + doc_id))
