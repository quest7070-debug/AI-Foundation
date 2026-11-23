"""Owner-local KLM relation review backend for the existing Operator.

Only authenticated host wiring supplies root/Guard/Canon/native credentials.
No schema initialization, automatic decisions, new grant service or model calls.
"""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import secrets
from types import SimpleNamespace
import sqlite3
import stat

from ai_foundation.core import CanonContract
from ai_foundation.guard import GuardCore
from ai_foundation.knowledge_lifecycle import HEX64, PRIVACY, RELATIONS
from ai_foundation.klm_relation_review import (
    _allowed, _snapshot, relation_review_intent, request_relation_review,
    resolve_relation_review, unresolved_review_filter,
)
from ai_foundation.klm_review_source import NativeKlmReviewReader
from ai_foundation.store import approval_request_ref

SCOPES = {"drive-inbox", "drive-public-research"}
REASONS = {
    "DEPENDENCY_REVIEW", "REVISION_OR_REINTERPRETATION_REVIEW",
    "SAME_REVISION_INTERPRETATION_REVIEW", "CONDITION_TIME_OR_ATTRIBUTION_REVIEW",
    "POTENTIAL_CONTRADICTION", "UNKNOWN_POLARITY_REVIEW",
    "UNRESOLVED_VALUE_DIFFERENCE", "POTENTIAL_SUPPORT_KIND_REVIEW",
    "SAME_INFORMATION_CANDIDATE",
}


PUBLIC_REVIEW_ERRORS = frozenset({
    "M1_OWNER_SESSION_REQUIRED", "HOST_KLM_REVIEW_BINDING_REQUIRED",
    "SAME_INSTALLED_KLM_ROOT_REQUIRED", "INSTALLED_KLM_BINDING_CHANGED",
    "PRIVATE_EXISTING_KLM_DB_REQUIRED", "KLM_REVIEW_SCHEMA_UNAVAILABLE",
    "STORAGE_ADMISSION_UNBOUND",
    "DRIVE_AUTH_REQUIRED", "BOUNDED_REVIEW_LIST_REQUIRED",
    "EXACT_REVIEW_CURSOR_REQUIRED", "EXACT_REVIEW_KEY_REQUIRED",
    "CURRENT_REVIEW_REQUIRED", "SOURCE_KIND_UNSUPPORTED",
    "SAME_OWNER_NATIVE_SOURCE_REQUIRED", "REVIEW_CHANGED", "REVIEW_PREVIEW_CHANGED",
    "EXACT_REVIEW_DECISION_REQUIRED", "SOURCE_OWNER_SCOPE_UNBOUND",
    "SOURCE_READER_UNBOUND", "EXACT_SOURCE_ATOM_REQUIRED",
    "SOURCE_PROVENANCE_UNAVAILABLE", "SOURCE_PROVENANCE_AMBIGUOUS",
    "SOURCE_POINTER_PIN_MISMATCH", "SOURCE_READ_UNAVAILABLE",
    "SOURCE_HISTORY_OR_REVISION_UNAVAILABLE", "SOURCE_BYTES_CHANGED",
    "SOURCE_SPAN_CHANGED", "SOURCE_SPAN_ENCODING_UNAVAILABLE", "SOURCE_PROOF_CHANGED",
    "CURRENT_SCOPED_ATOM_FEATURES_REQUIRED", "SOURCE_SCOPE_PRIVACY_BOUNDARY",
    "EXACT_GUARD_REVIEW_REQUIRED", "REVIEW_CHANGED_OR_CANCELLED",
    "IMMUTABLE_REVIEW_DECISION_CONFLICT", "REVIEW_RUN_ALREADY_CONSUMED",
})


class KlmOwnerReviewError(PermissionError):
    pass


def _require_owner_host():
    if __package__:
        from .m1_development_bridge import require_m1
    else:
        from m1_development_bridge import require_m1
    require_m1()
    if os.getuid() != 501 or os.geteuid() != 501:
        raise KlmOwnerReviewError("M1_OWNER_SESSION_REQUIRED")


class OwnerKlmReview:
    def __init__(self, root, *, work_path, authenticated_owner, guard, canon,
                 reader_factory, storage_admission=None, binding_check=None):
        self.root = Path(root).resolve(strict=True)
        if (type(authenticated_owner) is not str or not authenticated_owner
                or len(authenticated_owner) > 256
                or not isinstance(guard, GuardCore) or guard.store is None
                or any(not callable(getattr(guard.store, name, None)) for name in
                       ("_connect", "is_approved_for", "request_approval"))
                or not isinstance(canon, CanonContract) or canon.clear is not True
                or not canon.revision or not callable(reader_factory)):
            raise KlmOwnerReviewError("HOST_KLM_REVIEW_BINDING_REQUIRED")
        self.journal = SimpleNamespace(path=Path(work_path).resolve(strict=True))
        self.owner, self.guard, self.canon = authenticated_owner, guard, canon
        self.reader_factory, self.storage = reader_factory, storage_admission
        self.binding_check = binding_check
        self._key = secrets.token_bytes(32)
        self._existing()
        with self._db() as db:
            tables = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"klm_atoms", "klm_atom_features", "klm_relation_reviews",
                "klm_relations", "klm_drive_intake"} <= tables:
            raise KlmOwnerReviewError("KLM_REVIEW_SCHEMA_UNAVAILABLE")

    @classmethod
    def from_installed(cls, root, *, guard, canon, storage_admission=None):
        """Bind the exact existing KLM service config; no source/Keychain read yet."""
        _require_owner_host()
        if __package__:
            from . import m1_klm_status_probe as probe
            from .klm_drive_host_tick import existing_work_db
        else:
            import m1_klm_status_probe as probe
            from klm_drive_host_tick import existing_work_db
        root = Path(root).resolve(strict=True)
        _, config_path = probe._fixed_service_paths(Path.home())
        config, _ = probe._json_owner(config_path, probe.MAX_CONFIG)
        if (set(config) != {"foundation_root", "roots", "owner_scope"}
                or Path(config["foundation_root"]).resolve(strict=True) != root
                or type(config["roots"]) is not list or not 1 <= len(config["roots"]) <= 32
                or any(type(value) is not str or not value for value in config["roots"])):
            raise KlmOwnerReviewError("SAME_INSTALLED_KLM_ROOT_REQUIRED")
        foundation, _ = probe._json_owner(root / "config.json", probe.MAX_CONFIG)
        work_path = existing_work_db(foundation, root)
        owner = config["owner_scope"]

        def check_binding():
            try:
                _, current_path = probe._fixed_service_paths(Path.home())
                current, _ = probe._json_owner(current_path, probe.MAX_CONFIG)
                current_foundation, _ = probe._json_owner(root / "config.json", probe.MAX_CONFIG)
                if (current_path != config_path or current != config
                        or existing_work_db(current_foundation, root) != work_path):
                    raise ValueError("binding changed")
            except Exception:
                raise KlmOwnerReviewError("INSTALLED_KLM_BINDING_CHANGED") from None

        def native_reader(scope):
            check_binding()
            # Same fixed native ports/credential boundary as klm_drive_host_tick.
            from ai_foundation.macos_keychain import MacOSKeychain
            from ai_foundation.klm_drive_auth import ReadonlyGoogleToken
            from ai_foundation.klm_drive_runtime import OwnerDriveHTTP, OwnerInboxHTTP
            from ai_foundation.klm_drive_input import ReadOnlyDriveAPI
            from ai_foundation.klm_drive_cycle import NativeInboxReader
            from ai_foundation.klm_llmperks_source import KlmLlmperksReader, FOLDER_ID
            token = ReadonlyGoogleToken(MacOSKeychain())
            if not token.available():
                raise KlmOwnerReviewError("DRIVE_AUTH_REQUIRED")
            transport = OwnerDriveHTTP(token)
            research = (KlmLlmperksReader(
                ReadOnlyDriveAPI(transport), transport.read_text_media,
                owner_scope=owner, allowed_roots=config["roots"])
                if FOLDER_ID in config["roots"] else None)
            return NativeKlmReviewReader(
                SimpleNamespace(path=work_path), authenticated_owner=owner, scope=scope,
                inbox=NativeInboxReader(OwnerInboxHTTP(token)), research=research)

        return cls(root, work_path=work_path, authenticated_owner=owner,
                   guard=guard, canon=canon, reader_factory=native_reader,
                   storage_admission=storage_admission, binding_check=check_binding)

    def _existing(self):
        if self.binding_check is not None:
            self.binding_check()
        info = self.journal.path.lstat()
        if (self.journal.path.is_symlink() or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o077
                or info.st_size > (1 << 30)):
            raise KlmOwnerReviewError("PRIVATE_EXISTING_KLM_DB_REQUIRED")

    @contextmanager
    def _db(self):
        self._existing()
        db = sqlite3.connect(self.journal.path.as_uri() + "?mode=ro", uri=True, timeout=1)
        try:
            db.execute("PRAGMA query_only=ON")
            db.execute("BEGIN")
            yield db
        finally:
            db.close()

    def list_reviews(self, *, limit=25, after=""):
        if type(limit) is not int or not 1 <= limit <= 50:
            raise KlmOwnerReviewError("BOUNDED_REVIEW_LIST_REQUIRED")
        if after and (type(after) is not str or HEX64.fullmatch(after) is None):
            raise KlmOwnerReviewError("EXACT_REVIEW_CURSOR_REQUIRED")
        with self._db() as db:
            rows = db.execute(
                "SELECT r.review_key,r.reason,a.scope,a.privacy "
                "FROM klm_relation_reviews r JOIN klm_atoms a ON a.atom_id=r.before_id "
                "WHERE " + unresolved_review_filter(db) +
                " AND r.review_key > ? ORDER BY r.review_key LIMIT ?",
                (after, limit + 1)).fetchall()
        reviews = [dict(review_key=key, reason=reason if reason in REASONS else "OTHER_REVIEW",
                        scope=scope if scope in SCOPES else "UNSUPPORTED",
                        privacy=privacy if privacy in PRIVACY else "UNVERIFIED",
                        source_binding="UNVERIFIED_UNTIL_NATIVE_READ")
                   for key, reason, scope, privacy in rows[:limit]]
        return {"status": "OBSERVED", "reviews": reviews, "limit": limit,
                "more": len(rows) > limit,
                "next_cursor": rows[limit - 1][0] if len(rows) > limit else "",
                "model_calls": 0}

    def _snapshot(self, key):
        if type(key) is not str or HEX64.fullmatch(key) is None:
            raise KlmOwnerReviewError("EXACT_REVIEW_KEY_REQUIRED")
        with self._db() as db:
            row = db.execute(
                "SELECT a.scope FROM klm_relation_reviews r JOIN klm_atoms a "
                "ON a.atom_id=r.before_id WHERE r.review_key=?", (key,)).fetchone()
            if row is None:
                raise KlmOwnerReviewError("CURRENT_REVIEW_REQUIRED")
            if row[0] not in SCOPES:
                raise KlmOwnerReviewError("SOURCE_KIND_UNSUPPORTED")
            snapshot = _snapshot(db, key, row[0])
        return row[0], snapshot

    def _reader(self, scope):
        reader = self.reader_factory(scope)
        if (not isinstance(reader, NativeKlmReviewReader)
                or not reader.bound_to(self.owner, scope)
                or reader.journal.path.resolve(strict=True) != self.journal.path):
            raise KlmOwnerReviewError("SAME_OWNER_NATIVE_SOURCE_REQUIRED")
        return reader

    def _token(self, document):
        raw = json.dumps(document, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":")).encode()
        return hmac.new(self._key, raw, sha256).hexdigest()

    def _preview_binding(self, review_key, scope, snapshot):
        fingerprint = sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode()).hexdigest()
        return dict(review_key=review_key, scope=scope, owner=self.owner,
                    canon_revision=self.canon.revision, snapshot_sha256=fingerprint)

    def preview(self, review_key):
        scope, snapshot = self._snapshot(review_key)
        reader = self._reader(scope)
        before = reader.preview_atom(snapshot[0][1])
        after = reader.preview_atom(snapshot[0][2])
        if self._snapshot(review_key) != (scope, snapshot):
            raise KlmOwnerReviewError("REVIEW_CHANGED")
        binding = self._preview_binding(review_key, scope, snapshot)
        return dict(status="PREVIEW", review_key=review_key, scope=scope,
                    privacy=snapshot[1][0][0][6],
                    reason=snapshot[0][3] if snapshot[0][3] in REASONS else "OTHER_REVIEW",
                    before=before, after=after, semantic_accuracy_verified=False,
                    canon_revision=self.canon.revision, model_calls=0,
                    preview_token=self._token(binding))

    def _confirmed(self, review_key, preview_token, decision, relation_kind):
        # Only immutable metadata is needed to verify what was previewed.
        # Native freshness is checked once by the core request/resolve below.
        scope, snapshot = self._snapshot(review_key)
        binding = self._preview_binding(review_key, scope, snapshot)
        if (type(preview_token) is not str or HEX64.fullmatch(preview_token) is None
                or not hmac.compare_digest(preview_token, self._token(binding))):
            raise KlmOwnerReviewError("REVIEW_PREVIEW_CHANGED")
        if not ((decision == "ACCEPT" and type(relation_kind) is str and relation_kind in RELATIONS)
                or (decision == "REJECT" and relation_kind == "")):
            raise KlmOwnerReviewError("EXACT_REVIEW_DECISION_REQUIRED")
        identity = json.dumps((self.owner, scope, review_key, decision,
                               relation_kind, self.canon.revision), separators=(",", ":"))
        run = "klm-review:" + sha256(identity.encode()).hexdigest()
        return dict(review_key=review_key, decision=decision, relation_kind=relation_kind,
                    authenticated_owner=self.owner, scope=scope,
                    canon=self.canon, run_id=run)

    def _approval_ref(self, intent):
        with self.guard.store._connect() as db:
            row = db.execute(
                "SELECT action,target,request_nonce,canon_revision,effect_id "
                "FROM approval_requests WHERE run_id=?", (intent.run_id,)).fetchone()
        if row is None or (row[0], row[1], row[3], row[4]) != (
                intent.action, intent.target, intent.canon_revision, intent.effect_id):
            return ""
        return approval_request_ref(intent.run_id, *row)

    def request(self, review_key, *, preview_token, decision, relation_kind=""):
        args = self._confirmed(review_key, preview_token, decision, relation_kind)
        intent = relation_review_intent(self.journal, **args)
        if (self.storage is not None and not _allowed(self.guard, self.canon, intent)
                and not self._approval_ref(intent)):
            self.storage.require("KLM relation review request")
        result = request_relation_review(self.journal, guard=self.guard,
                                        read_current=self._reader(args["scope"]), **args)
        return {**result, "review_key": review_key, "decision": decision,
                "relation_kind": relation_kind, "approval_ref": self._approval_ref(intent),
                "preview_token": preview_token}

    def resolve(self, review_key, *, preview_token, decision, relation_kind=""):
        args = self._confirmed(review_key, preview_token, decision, relation_kind)
        intent = relation_review_intent(self.journal, **args)
        if not _allowed(self.guard, self.canon, intent):
            raise KlmOwnerReviewError("EXACT_GUARD_REVIEW_REQUIRED")
        with self._db() as db:
            schema = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                                "AND name='klm_relation_dispositions'").fetchone()
            old = (db.execute("SELECT 1 FROM klm_relation_dispositions WHERE review_key=?",
                              (review_key,)).fetchone() if schema else None)
        if old is None:
            if self.storage is not None:
                self.storage.require("KLM relation review decision")
            elif schema is None:
                raise KlmOwnerReviewError("STORAGE_ADMISSION_UNBOUND")
        if schema is None:
            # Explicit approved mutation only: use the existing schema owner
            # against this same existing Work DB, never initialize on GET.
            if not _allowed(self.guard, self.canon, intent):
                raise KlmOwnerReviewError("REVIEW_CHANGED_OR_CANCELLED")
            from ai_foundation.knowledge_lifecycle import ReadonlyReceiptJournal
            ReadonlyReceiptJournal(self.journal.path)
        result = resolve_relation_review(self.journal, guard=self.guard,
                                        read_current=self._reader(args["scope"]), **args)
        return {**result, "review_key": review_key, "model_calls": 0}
