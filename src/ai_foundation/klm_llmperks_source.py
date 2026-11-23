"""Source-bound KLM intake for app-owned, public LLMPerks research notes.

The existing KLM scanner observes metadata in the dedicated extra Drive root.
At most one *new* file is converted to an immutable canonical JSON source
pointer per 900s tick and staged in the EXISTING IntakeQueue/Durable Work DB.
Only the existing local9B idle/lease worker may infer after source re-read.
"""
from __future__ import annotations
from hashlib import sha256
import json
import re

APP_KEY = "foundationAdmissionDigest"  # Existing owner app-file digest metadata key
from .klm_drive_input import digest

FOLDER_ID = "12pjkEhIhG1hexxcCgGbQ7dTrOs_ABCOb"
SOURCE_ID = "llmperks-owner-research"
TEXT_PREFIX = "# Foundation LLMPerks research handoff — NO EXECUTION AUTHORITY\n"
TEXT_MIME = "text/plain"
FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,160}\Z")
HEX64 = re.compile(r"[a-f0-9]{64}\Z")
MAX_TEXT_BYTES = 8192
MAX_JSON_BYTES = 32768


class ResearchSourceUnverified(ValueError):
    pass


def _canonical_note(text):
    if (type(text) is not str or not text.startswith(TEXT_PREFIX)
            or "Source: https://llmperks.com/llms-full.txt\n" not in text[:256]
            or "Never treat this file as an instruction" not in text[:512]):
        raise ResearchSourceUnverified("RESEARCH_CONTENT_IDENTITY_UNVERIFIED")
    raw = json.dumps({"public_research_note": text}, ensure_ascii=False,
                     sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not 1 <= len(raw) <= MAX_JSON_BYTES:
        raise ResearchSourceUnverified("RESEARCH_CANONICAL_SOURCE_TOO_LARGE")
    return raw


class KlmLlmperksReader:
    """Drive API adapter uses the *existing* read-only owner KLM token.

    api = existing ReadOnlyDriveAPI; read_media = owner transport's bounded
    fixed-file media GET. Neither KLM nor model can create or move files.
    """
    def __init__(self, api, read_media, *, owner_scope, allowed_roots):
        if (type(owner_scope) is not str or not owner_scope
                or FOLDER_ID not in allowed_roots):
            raise PermissionError("RESEARCH_KLM_ROOT_NOT_APPROVED")
        self.api, self.read_media, self.owner = api, read_media, owner_scope

    def source(self, pointer):
        if type(pointer) is not dict:
            raise ResearchSourceUnverified("RESEARCH_POINTER_UNTRUSTED")
        file_id = pointer.get("record_id")
        if (pointer.get("source_id") != SOURCE_ID
                or pointer.get("owner") != self.owner
                or pointer.get("privacy_scope") != "private"
                or pointer.get("folder_id") != FOLDER_ID
                or type(file_id) is not str or FILE_ID.fullmatch(file_id) is None):
            raise ResearchSourceUnverified("RESEARCH_POINTER_UNTRUSTED")
        row = self.api.get("/drive/v3/files/" + file_id, {
            "fields": "id,mimeType,parents,appProperties,trashed,name",
            "supportsAllDrives": True,
        })
        if (type(row) is not dict or row.get("id") != file_id
                or row.get("mimeType") != TEXT_MIME
                or row.get("parents") != [FOLDER_ID]
                or row.get("trashed") is not False
                or type(row.get("name")) is not str
                or not row["name"].startswith("Foundation autonomous trial - ")
                or type(row.get("appProperties")) is not dict):
            raise ResearchSourceUnverified("RESEARCH_FILE_METADATA_UNVERIFIED")
        text_digest = row["appProperties"].get(APP_KEY)
        if type(text_digest) is not str or HEX64.fullmatch(text_digest) is None:
            raise ResearchSourceUnverified("RESEARCH_APP_DIGEST_MISSING")
        text = self.read_media(file_id)
        if (type(text) is not str
                or not 0 < len(text.encode("utf-8")) <= MAX_TEXT_BYTES
                or sha256(text.encode("utf-8")).hexdigest() != text_digest):
            raise ResearchSourceUnverified("RESEARCH_SOURCE_SHA256_MISMATCH")
        raw = _canonical_note(text)
        rev = "source-sha256:" + text_digest
        # Source may change before the model starts: caller checks saved
        # revision (and expected raw sha256) and post-reads it after inference.
        return {"revision": rev, "sha256": sha256(raw).hexdigest(), "raw": raw}

    def stage_one(self, state, queue):
        """Use KLM's already-scanned local metadata; no extra folder crawl."""
        with state.db() as db:
            # One recent bounded window (includes today's create-once file).
            rows = db.execute(
                "SELECT body FROM klm_drive_objects ORDER BY seen DESC LIMIT 500").fetchall()
        for (body,) in rows:
            try:
                item = json.loads(body)
            except (ValueError, TypeError):
                continue
            if type(item) is not dict:
                continue
            file_id = item.get("id")
            if (item.get("mime_type") != TEXT_MIME
                    or item.get("parents") != [FOLDER_ID]
                    or type(file_id) is not str or FILE_ID.fullmatch(file_id) is None
                    or not str(item.get("name") or "").startswith(
                        "Foundation autonomous trial - ")):
                continue
            with state.db() as db:
                already = db.execute(
                    "SELECT 1 FROM klm_drive_intake WHERE source_id=? AND record_id=? LIMIT 1",
                    (SOURCE_ID, file_id)).fetchone()
            if already is not None:
                continue
            pointer = {
                "source_id": SOURCE_ID, "record_id": file_id,
                "owner": self.owner, "privacy_scope": "private",
                "folder_id": FOLDER_ID, "identity_quality": "APP_OWNED_SHA256",
                "execution_authority": False,
            }
            observed = self.source(pointer)
            revision = observed["revision"]
            identity = digest((SOURCE_ID, file_id, revision, self.owner, "private"))
            pointer.update(
                intake_id=identity, source_revision=revision,
                expected_source_sha256=observed["sha256"],
                status="STAGED", last_attempt=None, result_ref=None,
            )
            return queue.enqueue(pointer)
        return "NO_NEW_RESEARCH"
