"""Fresh native-source proofs for host-local KLM relation review.

Reuse the existing bounded Inbox/research readers and owner-private intake
pointers. Never reconstruct semantic meaning from hashes, replay a model, read
caller-selected URLs, persist source text or mint Google/Guard permissions.
"""
from dataclasses import dataclass, field
from hashlib import sha256
import json
import sqlite3

from .knowledge_lifecycle import (
    HEX64, MAX_SOURCE_BYTES, MAX_SPAN_BYTES, POLICY_VERSION, _digest,
)
from .klm_drive_input import INBOX_ID, digest
from .klm_drive_cycle import NativeInboxReader
from .klm_llmperks_source import KlmLlmperksReader, SOURCE_ID as RESEARCH_SOURCE_ID


class NativeReviewSourceError(PermissionError):
    """Fixed public categories only; original source/transport errors stay local."""


@dataclass(frozen=True)
class _NativeSourceAtomProof:
    atom_id: str
    index_sha256: str
    source_sha256: str
    span_sha256: str
    source_bytes: int
    _reader_binding: object = field(repr=False, compare=False)


class NativeKlmReviewReader:
    """Authenticated-host binding around the already approved native readers.

    The host constructs these readers from its existing token/config, just as
    klm_drive_host_tick does. Constructor arguments and native transports are
    never taken from MCP/model JSON. This proves current source bytes plus the
    identity of the *saved proposal*, not independent semantic accuracy.
    """

    def __init__(self, journal, *, authenticated_owner, scope, inbox=None, research=None):
        if (type(authenticated_owner) is not str or not authenticated_owner
                or len(authenticated_owner) > 256
                or scope not in {"drive-inbox", "drive-public-research"}
                or (inbox is not None and not isinstance(inbox, NativeInboxReader))
                or (research is not None and
                    (not isinstance(research, KlmLlmperksReader)
                     or research.owner != authenticated_owner))):
            raise NativeReviewSourceError("SOURCE_OWNER_SCOPE_UNBOUND")
        if ((scope == "drive-inbox" and inbox is None)
                or (scope == "drive-public-research" and research is None)):
            raise NativeReviewSourceError("SOURCE_READER_UNBOUND")
        self.journal, self.owner, self.scope = journal, authenticated_owner, scope
        self.inbox, self.research = inbox, research
        self._binding = object()

    def bound_to(self, owner, scope):
        return owner == self.owner and scope == self.scope

    def _indexed(self, atom_id):
        if type(atom_id) is not str or HEX64.fullmatch(atom_id) is None:
            raise NativeReviewSourceError("EXACT_SOURCE_ATOM_REQUIRED")
        try:
            uri = self.journal.path.resolve().as_uri() + "?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=1) as db:
                db.execute("PRAGMA query_only=ON")
                db.execute("BEGIN")
                row = db.execute("SELECT * FROM klm_atoms WHERE atom_id=?", (atom_id,)).fetchone()
                features = db.execute("SELECT * FROM klm_atom_features WHERE atom_id=?", (atom_id,)).fetchone()
                if row is None or features is None:
                    raise NativeReviewSourceError("SOURCE_PROVENANCE_UNAVAILABLE")
                if row[1] != "gdrive":
                    raise NativeReviewSourceError("SOURCE_KIND_UNSUPPORTED")
                expected_scope = ("drive-inbox" if row[2] == INBOX_ID else
                                  "drive-public-research" if row[2] == RESEARCH_SOURCE_ID else None)
                if expected_scope is None:
                    raise NativeReviewSourceError("SOURCE_KIND_UNSUPPORTED")
                if row[5] != self.scope or expected_scope != self.scope or row[12] != POLICY_VERSION:
                    raise NativeReviewSourceError("SOURCE_OWNER_SCOPE_UNBOUND")
                pointers = db.execute(
                    "SELECT intake_id,source_id,source_revision,owner,privacy_scope,record_id,job_id,pointer "
                    "FROM klm_drive_intake WHERE source_id=? AND source_revision=? "
                    "AND record_id=? AND owner=? AND privacy_scope=? LIMIT 2",
                    (row[2], row[4], row[3], self.owner, row[6])).fetchall()
        except sqlite3.Error:
            raise NativeReviewSourceError("SOURCE_PROVENANCE_UNAVAILABLE") from None
        if not pointers:
            # Historical hash-only atoms cannot authorize arbitrary refetch.
            raise NativeReviewSourceError("SOURCE_PROVENANCE_UNAVAILABLE")
        if len(pointers) != 1:
            raise NativeReviewSourceError("SOURCE_PROVENANCE_AMBIGUOUS")
        saved = pointers[0]
        if type(saved[7]) is not str or len(saved[7].encode()) > 65536:
            raise NativeReviewSourceError("SOURCE_POINTER_PIN_MISMATCH")
        try:
            pointer = json.loads(saved[7])
        except (ValueError, UnicodeError):
            raise NativeReviewSourceError("SOURCE_POINTER_PIN_MISMATCH") from None
        expected = dict(source_id=row[2], source_revision=row[4], owner=self.owner,
                        privacy_scope=row[6], record_id=row[3])
        identity = digest(tuple(expected[k] for k in
                                ("source_id", "record_id", "source_revision", "owner", "privacy_scope")))
        if (type(pointer) is not dict or any(pointer.get(k) != v for k, v in expected.items())
                or saved[:6] != (identity, row[2], row[4], self.owner, row[6], row[3])
                or saved[6] != "klm-drive:" + identity or pointer.get("intake_id") != identity):
            raise NativeReviewSourceError("SOURCE_POINTER_PIN_MISMATCH")
        return row, features, pointer, saved

    def _fresh(self, atom_id):
        row, features, pointer, saved = self._indexed(atom_id)
        reader = self.inbox if row[2] == INBOX_ID else self.research
        try:
            current = reader.source(pointer)
        except Exception:
            raise NativeReviewSourceError("SOURCE_READ_UNAVAILABLE") from None
        if type(current) is not dict or current.get("revision") != row[4]:
            raise NativeReviewSourceError("SOURCE_HISTORY_OR_REVISION_UNAVAILABLE")
        raw = current.get("raw")
        if (type(raw) is not bytes or not 0 < len(raw) <= MAX_SOURCE_BYTES
                or current.get("sha256") != row[7]
                or sha256(raw).hexdigest() != row[7]
                or ("expected_source_sha256" in pointer
                    and pointer["expected_source_sha256"] != row[7])):
            raise NativeReviewSourceError("SOURCE_BYTES_CHANGED")
        start, end = row[9:11]
        if (type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(raw) or end - start > MAX_SPAN_BYTES
                or sha256(raw[start:end]).hexdigest() != row[8]):
            raise NativeReviewSourceError("SOURCE_SPAN_CHANGED")
        if self._indexed(atom_id) != (row, features, pointer, saved):
            raise NativeReviewSourceError("SOURCE_PROOF_CHANGED")
        return row, features, raw

    def __call__(self, atom_id):
        row, features, raw = self._fresh(atom_id)
        return _NativeSourceAtomProof(atom_id, _digest((row, features)),
                                      row[7], row[8], len(raw), self._binding)

    def preview_atom(self, atom_id):
        """Fresh bounded span for the authenticated owner UI only, never a proof cache."""
        row, features, raw = self._fresh(atom_id)
        try:
            text = raw[row[9]:row[10]].decode("utf-8", errors="strict")
        except UnicodeError:
            raise NativeReviewSourceError("SOURCE_SPAN_ENCODING_UNAVAILABLE") from None
        return dict(atom_id=row[0], system=row[1], resource_id=row[2],
                    record_id=row[3], revision=row[4], source_sha256=row[7],
                    span_sha256=row[8], byte_start=row[9], byte_end=row[10],
                    meaning_sha256=row[11], span_text=text)

    def verify(self, proof, row, features):
        """Only a fresh proof from this reader can satisfy the saved review pins."""
        if (not isinstance(proof, _NativeSourceAtomProof)
                or proof._reader_binding is not self._binding
                or proof.atom_id != row[0]
                or proof.index_sha256 != _digest((row, features))
                or proof.source_sha256 != row[7] or proof.span_sha256 != row[8]
                or type(proof.source_bytes) is not int
                or not 0 <= row[9] < row[10] <= proof.source_bytes <= MAX_SOURCE_BYTES):
            raise NativeReviewSourceError("SOURCE_PROOF_CHANGED")
