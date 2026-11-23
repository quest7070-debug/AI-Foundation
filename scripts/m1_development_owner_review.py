"""Owner-local CODE review handoff; only existing Operator POST may confirm.

No model, test, Work transition or execution is performed. The existing private
review format and admission remain authoritative.
"""
from __future__ import annotations

import fcntl
from hashlib import sha256
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat

if __package__:
    from . import m1_development_review_candidate as prepare
    from . import m1_strata_owner_ticket_admission as admission
else:
    import m1_development_review_candidate as prepare
    import m1_strata_owner_ticket_admission as admission
from ai_foundation.sensitive_input_scan import contains_sensitive_value
from ai_foundation.durable_work import SQLiteWorkStore
from ai_foundation.orchestration import WorkStatus


class OwnerDevelopmentReview:
    def __init__(self, root, *, repo_factory, work_db="work.db", storage_admission=None):
        if not callable(repo_factory):
            raise ValueError("TRUSTED_OWNER_REPO_REQUIRED")
        self.root = Path(root).resolve(strict=True)
        self.repo_factory = repo_factory
        self.work_db = work_db
        self.storage_admission = storage_admission
        self._key = secrets.token_bytes(32)

    def _current(self, ticket_id):
        """Exactly the same trusted source selection as the pending list."""
        owner_repo = self.repo_factory()
        repo, document = prepare.resolve_review_snapshot(
            self.root, owner_repo, ticket_id, work_db=self.work_db)
        text = {}
        for field, digest in (("target", "source_sha256"),
                              ("test", "test_sha256")):
            raw = (repo / document[field]).read_bytes()
            if (not 0 < len(raw) <= 262144
                    or sha256(raw).hexdigest() != document[digest]):
                raise ValueError("REVIEW_BYTES_CHANGED")
            text[field + "_text"] = raw.decode("utf-8")
        next_repo, next_document = prepare.resolve_review_snapshot(
            self.root, owner_repo, ticket_id, work_db=self.work_db)
        if next_repo != repo or next_document != document:
            raise ValueError("REVIEW_SNAPSHOT_CHANGED")
        return repo, document, text

    def _token(self, document):
        payload = json.dumps(document, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()
        return hmac.new(self._key, payload, sha256).hexdigest()

    def pending_request_ids(self):
        """Read only bounded owner-scoped pending IDs for the mobile review page.

        This is a selection aid, not an owner review, Guard approval or Work
        admission.  Only IDs cross the rendering boundary; private request
        text, source, DB paths and secrets stay inside the owner's M1.
        """
        path = self.root / self.work_db
        if not path.resolve().is_relative_to(self.root):
            raise PermissionError("WORK_DATABASE_OUTSIDE_OWNER_ROOT")
        info = path.lstat()
        if (path.is_symlink() or not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid() or info.st_mode & 0o022):
            raise PermissionError("OWNER_WORK_DATABASE_UNVERIFIED")
        prefix = ("mcp-development-request:" +
                  sha256(prepare._OWNER.encode()).hexdigest() + ":")
        with sqlite3.connect(path.resolve().as_uri() + "?mode=ro",
                             uri=True, timeout=2) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT job_id FROM work_steps WHERE position=0 "
                "AND name='development-request' AND status=? "
                "AND substr(job_id,1,?)=? ORDER BY job_id LIMIT 64",
                (WorkStatus.WAITING_HUMAN.value, len(prefix), prefix)
            ).fetchall()
        ids = []
        for (job_id,) in rows:
            if (type(job_id) is not str or not job_id.startswith(prefix)
                    or prepare._ID.fullmatch(job_id[len(prefix):]) is None):
                raise ValueError("OWNER_PENDING_TICKET_ID_UNVERIFIED")
            ids.append(job_id[len(prefix):])
        return tuple(ids)

    def pending_review_statuses(self):
        """Current owner UI readiness from the SAME live-source gate as preview.

        No arbitrary CI checkout, stale verified ledger, local missing path
        or draft source can be called PREVIEW_READY. The browser cannot
        influence source selection. Output contains only existing owner
        ticket IDs and fixed safe reasons, never private paths or text.
        """
        tickets = self.pending_request_ids()
        try:
            owner_repo = self.repo_factory()
        except (OSError, ValueError, PermissionError, RuntimeError):
            return tuple({
                "ticket_id": ticket,
                "state": "OWNER_LOCAL_REPOSITORY_UNVERIFIED"}
                for ticket in tickets)
        public_reasons = frozenset({
            "REVIEW_SCOPE_SELECTION_REQUIRED",
            "OWNER_CHECKOUT_NOT_CLEAN",
            "OWNER_CHECKOUT_CHANGED_DURING_REVIEW",
            "REQUEST_NOT_WAITING_FOR_REVIEW",
            "REQUEST_CONTENT_INVALID",
            "REQUEST_CHANGED_DURING_REVIEW",
            "OWNER_BASE_UNVERIFIED",
            "OWNER_WORK_DATABASE_UNVERIFIED",
        })
        statuses = []
        for ticket in tickets:
            state = "PREVIEW_READY"
            try:
                prepare.resolve_review_snapshot(
                    self.root, owner_repo, ticket, work_db=self.work_db)
            except (OSError, ValueError, PermissionError, RuntimeError,
                    sqlite3.Error) as error:
                code = error.args[0] if len(error.args) == 1 else None
                if code in public_reasons and type(code) is str:
                    state = code
                elif code == "OWNER_INSTALLED_REVIEW_SOURCE_UNVERIFIED":
                    state = "LIVE_OPERATOR_SOURCE_UNVERIFIED"
                elif code == "CANDIDATE_SOURCE_OR_TEST_UNVERIFIED":
                    state = "PINNED_SOURCE_OR_TEST_UNVERIFIED"
                else:
                    state = "PREVIEW_UNVERIFIED"
            statuses.append({"ticket_id": ticket, "state": state})
        return tuple(statuses)

    def preview(self, ticket_id):
        _, document, text = self._current(ticket_id)
        return {**document, **text, "preview_token": self._token(document)}

    def _review(self, ticket_id, preview_token, model):
        repo, document, text = self._current(ticket_id)
        if not hmac.compare_digest(preview_token, self._token(document)):
            raise PermissionError("REVIEW_PREVIEW_CHANGED")
        if (contains_sensitive_value(text["target_text"])
                or contains_sensitive_value(document["instruction"])):
            raise PermissionError("OWNER_PUBLIC_EGRESS_DENIED")
        record = {key: document[key] for key in (
            "ticket_id", "base_sha", "target", "test", "source_sha256",
            "test_sha256", "instruction")}
        record.update(version=1, review=admission.REVIEWED, model=model,
                      public_source_sha256=document["source_sha256"],
                      public_instruction_sha256=document["instruction_sha256"])
        payload = (json.dumps(record, sort_keys=True, ensure_ascii=False,
                              indent=2) + "\n").encode()
        return repo, document, payload

    def _validate_saved(self, repo, document, ticket_id):
        admission.reviewed_contract(
            self.root, repo, ticket_id,
            expected_instruction_sha256=document["instruction_sha256"])
        if prepare.snapshot(self.root, repo, ticket_id, work_db=self.work_db) != document:
            raise PermissionError("REVIEW_CHANGED_OR_CANCELLED")

    def confirm(self, ticket_id, *, preview_token, model, source_reviewed=False,
                test_reviewed=False, public_nonsecret=False):
        if (source_reviewed is not True or test_reviewed is not True
                or public_nonsecret is not True
                or type(model) is not str or model not in {"m1", "auto", "strata"}
                or type(preview_token) is not str):
            raise PermissionError("EXPLICIT_OWNER_REVIEW_REQUIRED")
        repo, document, payload = self._review(ticket_id, preview_token, model)
        path = self.root / "development" / "reviews" / (ticket_id + ".json")
        result = {"status": "OWNER_REVIEW_SAVED", "ticket_id": ticket_id,
                  "execution_started": False, "model_calls": 0}
        # Exact immutable readback creates no lock or directory and remains
        # available when new writes are refused by storage admission.
        if path.exists() or path.is_symlink():
            if prepare._owner_file(path) != payload:
                raise PermissionError("IMMUTABLE_OWNER_REVIEW_CONFLICT")
            self._validate_saved(repo, document, ticket_id)
            return result
        if self.storage_admission is not None:
            self.storage_admission.require("owner CODE review")
        development = prepare._private_dir(self.root / "development")
        lock = development / "reviewed-strata-install.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            repo, document, payload = self._review(ticket_id, preview_token, model)
            folder = prepare._private_dir(development / "reviews")
            created = False
            try:
                out_fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            except FileExistsError:
                if prepare._owner_file(path) != payload:
                    raise PermissionError("IMMUTABLE_OWNER_REVIEW_CONFLICT") from None
            else:
                created = True
                try:
                    with os.fdopen(out_fd, "wb") as out:
                        out.write(payload)
                        out.flush()
                        os.fsync(out.fileno())
                except BaseException:
                    path.unlink(missing_ok=True)
                    raise
            try:
                self._validate_saved(repo, document, ticket_id)
            except BaseException:
                if created:
                    path.unlink(missing_ok=True)
                raise
        finally:
            os.close(fd)
        return result


    def delegation_status(self):
        from m1_development_scope_delegation import load_scope
        try:
            scope = load_scope(self.root)
        except (OSError, ValueError, PermissionError):
            return {"status": "UNVERIFIED"}
        if scope is None:
            return {"status": "DISABLED"}
        return {"status": "ENABLED" if scope["enabled"] else "DISABLED",
                "model": scope["model"] if scope["enabled"] else "NONE",
                "draft_delivery": scope["allow_draft_delivery"]
                if scope["enabled"] else False}

    def enable_delegation(self, *, model, allow_draft_delivery,
                          scope_confirmed=False):
        from m1_development_scope_delegation import enable_scope
        return enable_scope(
            self.root, model=model,
            allow_draft_delivery=allow_draft_delivery,
            confirmed=scope_confirmed)

    def revoke_delegation(self, *, revoke_confirmed=False):
        from m1_development_scope_delegation import revoke_scope
        return revoke_scope(self.root, confirmed=revoke_confirmed)


    def cancel(self, ticket_id, *, preview_token, withdrawal_confirmed=False):
        """Withdraw one exact unadmitted request; never cancel executable work."""
        if withdrawal_confirmed is not True or type(preview_token) is not str:
            raise PermissionError("EXPLICIT_OWNER_WITHDRAWAL_REQUIRED")
        _, document, _ = self._current(ticket_id)
        if not hmac.compare_digest(preview_token, self._token(document)):
            raise PermissionError("REVIEW_PREVIEW_CHANGED")
        development = prepare._private_dir(self.root / "development")
        lock = development / "reviewed-strata-install.lock"
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _, current, _ = self._current(ticket_id)
            if current != document or not hmac.compare_digest(preview_token, self._token(current)):
                raise PermissionError("REVIEW_PREVIEW_CHANGED")
            manifest = development / "tickets.json"
            if manifest.exists() or manifest.is_symlink():
                inventory = prepare._strict_json(prepare._owner_file(manifest))
                if (type(inventory) is not dict or set(inventory) != {"version", "tickets"}
                        or type(inventory["version"]) is not int or inventory["version"] != 1
                        or type(inventory["tickets"]) is not list):
                    raise PermissionError("OWNER_TICKET_MANIFEST_INVALID")
                for row in inventory["tickets"]:
                    admission._validate_ticket(row)
                    if row["ticket_id"] == ticket_id:
                        raise PermissionError("ADMITTED_TICKET_CANNOT_BE_WITHDRAWN")
            prefix = "mcp-development-request:" + sha256(prepare._OWNER.encode()).hexdigest() + ":"
            work = SQLiteWorkStore(self.root / self.work_db)
            steps = work.load(prefix + ticket_id)
            if (not steps or steps[0].name != "development-request"
                    or steps[0].status is not WorkStatus.WAITING_HUMAN):
                raise PermissionError("UNADMITTED_PENDING_REQUEST_REQUIRED")
            saved = steps[0]
            request = prepare._strict_json(saved.result)
            if request != {"ticket_id": ticket_id, "instruction": document["instruction"]}:
                raise PermissionError("REQUEST_CHANGED_DURING_REVIEW")
            changed = work.cancel_development_review(prefix + ticket_id, saved.result)
            current = work.load(prefix + ticket_id)
            if (changed is not True or not current
                    or current[0].status is not WorkStatus.CANCELLED
                    or current[0].result != saved.result):
                raise PermissionError("REQUEST_CHANGED_OR_ADMITTED")
        finally:
            os.close(fd)
        return {"status": "REQUEST_WITHDRAWN", "ticket_id": ticket_id,
                "state": "CANCELLED", "execution_started": False, "model_calls": 0}
