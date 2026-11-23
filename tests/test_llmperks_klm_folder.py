"""Network-free owner app-folder placement tests: identity, no duplicates, fail-closed."""
from contextlib import nullcontext
from hashlib import sha256
from types import SimpleNamespace

import pytest

from ai_foundation.development_drive_plan import APP_KEY
from ai_foundation.llmperks_klm_folder import (
    RESEARCH_FOLDER_DIGEST, RESEARCH_FOLDER_NAME,
    FOLDER_MIME, FolderPlacementUnverified, place_owner_note,
)


class FakeHTTP:
    def __init__(self):
        self.folder = None
        self.create_count = 0

    def call(self, service, method, path, *, query=None, body=None):
        assert service == "drive" and path == "/files"
        if method == "GET":
            assert RESEARCH_FOLDER_DIGEST in query["q"]
            return {"files": [] if not self.folder else [{
                "id": self.folder, "mimeType": FOLDER_MIME,
                "appProperties": {APP_KEY: RESEARCH_FOLDER_DIGEST},
                "name": RESEARCH_FOLDER_NAME, "parents": ["owner-root-id"],
            }]}
        assert method == "POST" and query is None
        assert body["mimeType"] == FOLDER_MIME
        assert body["appProperties"][APP_KEY] == RESEARCH_FOLDER_DIGEST
        self.create_count += 1
        assert self.folder is None
        self.folder = "owner-created-research-folder-id"
        return {"id": self.folder, "mimeType": FOLDER_MIME}


class FakeStore:
    def __init__(self, text):
        self.text = text
        self.digest = sha256(text.encode()).hexdigest()
        self.file_id = "owner-created-source-note-id"
        self.http = FakeHTTP()
        self.find_count = 0

    def _find(self, digest):
        self.find_count += 1
        return self.file_id if digest == self.digest else None

    def read(self, file_id):
        assert file_id == self.file_id
        return self.text


def make_ports(text):
    store = FakeStore(text)
    base = SimpleNamespace(runtime="/owner-private", probe=lambda: True)
    return (base, store, lambda _: nullcontext()), store


def test_create_folder_and_move_exact_existing_note_only_once(monkeypatch):
    from ai_foundation import llmperks_klm_folder as target
    ports, store = make_ports("Research only, no execution")
    state = {"parent": "owner-private-root-id", "patches": 0}

    def metadata(_base, method, file_id, *, query=None):
        assert file_id == store.file_id
        if method == "PATCH":
            assert query["removeParents"] == state["parent"]
            assert query["addParents"] == store.http.folder
            state["parent"] = store.http.folder
            state["patches"] += 1
        return {"id": file_id, "mimeType": "text/plain",
                "parents": [state["parent"]],
                "appProperties": {APP_KEY: store.digest},
                "trashed": False}
    monkeypatch.setattr(target, "_file_request", metadata)
    first = place_owner_note(store.digest, owner_ports=ports)
    second = place_owner_note(store.digest, owner_ports=ports)
    assert first["status"] == "RESEARCH_NOTE_MOVED_TO_FOLDER"
    assert second["status"] == "RESEARCH_NOTE_ALREADY_IN_FOLDER"
    assert state["patches"] == store.http.create_count == 1
    assert first["folder_id"] == second["folder_id"] == store.http.folder
    assert first["execution_authorized"] is False
    assert store.find_count >= 4


def test_missing_or_tampered_content_never_creates_folder(monkeypatch):
    ports, store = make_ports("Research only")
    with pytest.raises(FolderPlacementUnverified, match="RESEARCH_NOTE_NOT_STORED"):
        place_owner_note("0" * 64, owner_ports=ports)
    store.text = "Different content"
    with pytest.raises(FolderPlacementUnverified, match="RESEARCH_NOTE_DIGEST_UNVERIFIED"):
        place_owner_note(store.digest, owner_ports=ports)
    assert store.http.create_count == 0


def test_other_file_identity_is_denied_before_patch(monkeypatch):
    from ai_foundation import llmperks_klm_folder as target
    ports, store = make_ports("Research")
    def changed_metadata(_base, method, file_id, *, query=None):
        assert method == "GET"
        return {"id": file_id, "mimeType": "text/plain",
                "parents": ["owner-private-root-id"],
                "appProperties": {APP_KEY: "0" * 64}}
    monkeypatch.setattr(target, "_file_request", changed_metadata)
    with pytest.raises(FolderPlacementUnverified, match="RESEARCH_NOTE_PARENT_UNVERIFIED"):
        place_owner_note(store.digest, owner_ports=ports)
    assert store.http.create_count == 1


def test_invalid_digest_denied_before_any_authorized_port():
    with pytest.raises(ValueError, match="RESEARCH_NOTE_SHA256_REQUIRED"):
        place_owner_note("../other-file")
