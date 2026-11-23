"""App-owned LLMPerks research folder, without widening existing drive.file.

The KLM read-only Drive crawler may scan this dedicated folder after its root
is separately registered. This module DOES NOT change the KLM host root list,
Sheets Inbox, local 9B, admission routes, or user-wide Drive permissions.
"""
from __future__ import annotations
from hashlib import sha256
import json
from urllib import request, parse, error

from .development_drive_plan import (
    APP_KEY, DRIVE_FILE_SCOPE, FILE_ID, HEX64,
    PlanStoreUnverified, GooglePlanHTTPFailure, _safe_google_reason,
)
from .llmperks_owner_drive import existing_owner_ports

RESEARCH_FOLDER_NAME = "AI-Foundation LLMPerks research"
RESEARCH_FOLDER_DIGEST = sha256(b"AI-Foundation LLMPerks owner research folder v1").hexdigest()
FOLDER_MIME = "application/vnd.google-apps.folder"
FILE_MIME = "text/plain"
API = "https://www.googleapis.com/drive/v3"


class FolderPlacementUnverified(ValueError):
    pass


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _opener():
    return request.build_opener(request.ProxyHandler({}), _NoRedirect())


def _folder_matches(store, folder_id):
    transport = store.http
    # The existing writer is already scoped to the owner-created app files.
    query = ("trashed = false and appProperties has { key='" + APP_KEY
             + "' and value='" + RESEARCH_FOLDER_DIGEST + "' }")
    rows = transport.call("drive", "GET", "/files",
                          query={"q": query, "pageSize": 3,
                                 "fields": "nextPageToken,files(id,mimeType,appProperties,parents,name)"})
    files = rows.get("files")
    if (type(files) is not list or len(files) > 1
            or rows.get("nextPageToken") is not None):
        raise FolderPlacementUnverified("RESEARCH_FOLDER_LOOKUP_UNVERIFIED")
    if not files:
        return None
    item = files[0]
    if (type(item) is not dict or type(item.get("id")) is not str
            or FILE_ID.fullmatch(item["id"]) is None
            or item.get("mimeType") != FOLDER_MIME
            or item.get("name") != RESEARCH_FOLDER_NAME
            or type(item.get("appProperties")) is not dict
            or item["appProperties"].get(APP_KEY) != RESEARCH_FOLDER_DIGEST):
        raise FolderPlacementUnverified("RESEARCH_FOLDER_IDENTITY_UNVERIFIED")
    if folder_id is not None and folder_id != item["id"]:
        raise FolderPlacementUnverified("RESEARCH_FOLDER_CHANGED")
    return item["id"]


def ensure_folder(store):
    """Called only inside the existing owner lock; one create/reconciliation."""
    found = _folder_matches(store, None)
    if found is not None:
        return found, "EXISTING"
    transport = store.http
    reply = transport.call("drive", "POST", "/files", body={
        "name": RESEARCH_FOLDER_NAME,
        "mimeType": FOLDER_MIME,
        "appProperties": {APP_KEY: RESEARCH_FOLDER_DIGEST},
    })
    created = reply.get("id")
    if type(created) is not str or FILE_ID.fullmatch(created) is None:
        raise FolderPlacementUnverified("RESEARCH_FOLDER_CREATE_UNVERIFIED")
    # Resolve even if a concurrent Google Drive request was uncertain:
    # never blindly create a second folder after a failed lookup.
    if _folder_matches(store, created) != created:
        raise FolderPlacementUnverified("RESEARCH_FOLDER_READBACK_UNVERIFIED")
    return created, "CREATED"


def _file_request(base, method, file_id, *, query=None):
    if (type(file_id) is not str or FILE_ID.fullmatch(file_id) is None
            or method not in {"GET", "PATCH"}):
        raise FolderPlacementUnverified("RESEARCH_FILE_REQUEST_DENIED")
    pair = base.token()
    if (type(pair) is not tuple or len(pair) != 2
            or type(pair[0]) is not str or not pair[0]
            or set(pair[1]) != {DRIVE_FILE_SCOPE}):
        raise FolderPlacementUnverified("DRIVE_FILE_OWNER_SCOPE_REQUIRED")
    url = API + "/files/" + file_id
    if query:
        url += "?" + parse.urlencode(query)
    req = request.Request(
        url, method=method, headers={
            "Authorization": "Bearer " + pair[0],
            "Accept": "application/json",
        })
    try:
        with _opener().open(req, timeout=8) as response:
            raw = response.read(4097)
    except error.HTTPError as exc:
        raise GooglePlanHTTPFailure(
            "drive", method, int(exc.code), _safe_google_reason(exc)) from None
    if len(raw) > 4096:
        raise FolderPlacementUnverified("RESEARCH_FILE_META_OVERSIZE")
    try:
        value = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise FolderPlacementUnverified("RESEARCH_FILE_META_INVALID") from exc
    if type(value) is not dict:
        raise FolderPlacementUnverified("RESEARCH_FILE_META_INVALID")
    return value


def _metadata(base, file_id):
    obj = _file_request(base, "GET", file_id,
                        query={"fields": "id,mimeType,parents,appProperties,trashed"})
    if obj.get("id") != file_id or obj.get("trashed") is True:
        raise FolderPlacementUnverified("RESEARCH_FILE_IDENTITY_UNVERIFIED")
    return obj


def place_owner_note(digest, *, owner_ports=None):
    """Reconcile one existing digest-verified app-owned note into its app folder.

    The exact file ID can ONLY come from the approved owner's digest lookup.
    No arbitrary file path, third-party file or Drive folder ID is accepted.
    This does not make a KLM semantic task; that requires an independent
    source-bound KLM adapter, and MUST NOT be falsely reported as completed.
    """
    if type(digest) is not str or HEX64.fullmatch(digest) is None:
        raise ValueError("RESEARCH_NOTE_SHA256_REQUIRED")
    base, store, lock_factory = existing_owner_ports() if owner_ports is None else owner_ports
    base.probe()
    with lock_factory(base.runtime):
        file_id = store._find(digest)
        if file_id is None:
            raise FolderPlacementUnverified("RESEARCH_NOTE_NOT_STORED")
        text = store.read(file_id)
        if type(text) is not str or sha256(text.encode("utf-8")).hexdigest() != digest:
            raise FolderPlacementUnverified("RESEARCH_NOTE_DIGEST_UNVERIFIED")
        folder_id, _ = ensure_folder(store)
        info = _metadata(base, file_id)
        if (info.get("mimeType") != FILE_MIME
                or type(info.get("appProperties")) is not dict
                or info["appProperties"].get(APP_KEY) != digest
                or type(info.get("parents")) is not list
                or len(info["parents"]) != 1
                or type(info["parents"][0]) is not str
                or FILE_ID.fullmatch(info["parents"][0]) is None):
            raise FolderPlacementUnverified("RESEARCH_NOTE_PARENT_UNVERIFIED")
        source_parent = info["parents"][0]
        if source_parent == folder_id:
            status = "RESEARCH_NOTE_ALREADY_IN_FOLDER"
        else:
            _file_request(base, "PATCH", file_id, query={
                "addParents": folder_id,
                "removeParents": source_parent,
                "fields": "id,mimeType,parents,appProperties",
            })
            status = "RESEARCH_NOTE_MOVED_TO_FOLDER"
        proof = _metadata(base, file_id)
        if (proof.get("parents") != [folder_id]
                or proof.get("mimeType") != FILE_MIME
                or proof.get("appProperties", {}).get(APP_KEY) != digest
                or store.read(file_id) != text
                or store._find(digest) != file_id):
            raise FolderPlacementUnverified("RESEARCH_NOTE_PLACEMENT_READBACK_UNVERIFIED")
    return {"status": status, "folder_id": folder_id,
            "file_id": file_id, "sha256": digest, "execution_authorized": False}
