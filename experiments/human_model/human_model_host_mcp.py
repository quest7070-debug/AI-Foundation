"""Bounded owner-side HumanModel port for the EXISTING authenticated MCP host.

Never a listener, credential reader, or replacement model manager. The host
constructs this only after authenticating the owner and binding the existing
external USB HumanModel Ledger, trusted source reader and Guard. MCP arguments
select an exact source key only; they never carry actor claims, private source
text, source hashes or authorization.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import re
import sqlite3
from pathlib import Path
from dataclasses import dataclass

from ai_foundation.human_model_collection_guard import GuardCollectionConsent
from ai_foundation.human_model_context import HumanModelBinding
from ai_foundation.mcp_host import McpHostPrincipal
from ai_foundation.primary_review_events import _validate as validate_review_reference
from human_model_source_admission import HostCollectionGrant, TrustedSourceSnapshot
from human_model_owner_publication import (
    publish_exact_owner_observation,
    reconcile_cancelled_collection_consent,
    owner_lifecycle_tick,
)
from human_model_management_audit import audit_ledger


@dataclass(frozen=True)
class TrustedOwnerSourcePort:
    """Supplied by trusted host; never built from model/MCP request payload.

    read_current(system, record_id) must independently verify the original
    actor and record revision from the canonical Chat/Drive source. Its
    private snapshot must contain no inferred speaker authentication.
    grant_for(...) must resolve an existing source-bound collection intent
    with the exact approved purpose, current source hash and revision.
    """
    grant_for: object
    read_current: object

    def __post_init__(self):
        if not callable(self.grant_for) or not callable(self.read_current):
            raise ValueError("TRUSTED_SOURCE_ADAPTER_REQUIRED")


class HumanModelOwnerMcpPort:
    """Optional, fail-closed capability injected into existing MCP host.

    The owner identity is the authenticated MCP principal ID. If deployed
    transport uses another user namespace it must normalize the trusted host
    identity *before* creating the session; never guess from source content.
    """
    def __init__(self, *, binding: HumanModelBinding,
                 consent: GuardCollectionConsent, open_owner_ledger,
                 open_readonly_connection,
                 source: TrustedOwnerSourcePort | None = None,
                 answer_agent_factory=None, authorize_correction=None,
                 open_review_readonly_connection=None):
        if (not isinstance(binding, HumanModelBinding)
                or not isinstance(consent, GuardCollectionConsent)
                or consent.binding != binding
                or consent.owner != binding.owner_id
                or not callable(open_owner_ledger)
                or not callable(open_readonly_connection)
                or (source is not None
                    and not isinstance(source, TrustedOwnerSourcePort))
                or (answer_agent_factory is not None
                    and not callable(answer_agent_factory))
                or (authorize_correction is not None and not callable(authorize_correction))
                or (open_review_readonly_connection is not None
                    and not callable(open_review_readonly_connection))):
            raise ValueError("HOST_OWNER_MCP_BINDING_REQUIRED")
        self.binding = binding
        self.consent = consent
        self.open_owner_ledger = open_owner_ledger
        self.open_readonly_connection = open_readonly_connection
        self.source = source
        self.answer_agent_factory = answer_agent_factory
        self.authorize_correction = authorize_correction
        self.open_review_readonly_connection = open_review_readonly_connection

    @property
    def can_correct(self):
        return (self.source is not None and callable(self.authorize_correction)
                and callable(self.open_review_readonly_connection))

    @classmethod
    def from_existing_external(
        cls, *, binding: HumanModelBinding,
        consent: GuardCollectionConsent,
        source: TrustedOwnerSourcePort | None = None,
        answer_agent_factory=None, authorize_correction=None,
        open_review_readonly_connection=None,
    ):
        """Production factory: same existing external ledger, never fallback.

        This factory does NOT install a listener, migrate schema or import
        owner content. The caller must still provide a trusted authenticated
        source adapter and current Guard-approved collection request.
        """
        from human_model_ledger import Ledger
        from storage_location import validated_ledger_path
        def current_path():
            path = validated_ledger_path(binding.root)
            if not path.is_file() or path.is_symlink():
                raise FileNotFoundError("EXISTING_EXTERNAL_OWNER_LEDGER_REQUIRED")
            return path
        def writer():
            # The optional admission table is a separately reviewed owner
            # migration. Do not let the ordinary Ledger initializer silently
            # repair/create a source schema before that acceptance.
            path = current_path()
            with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as check:
                names = {x[0] for x in check.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if not {'evidence', 'model_views', 'model_sources',
                        'change_log', 'human_source_admissions'} <= names:
                    raise RuntimeError("OWNER_ADMISSION_SCHEMA_NOT_PREPARED")
                columns = {row[1] for row in check.execute(
                    "PRAGMA table_info(human_source_admissions)")}
                from human_model_owner_publication import _COLUMNS
                if columns != _COLUMNS:
                    raise RuntimeError("OWNER_ADMISSION_SCHEMA_NOT_PREPARED")
            return Ledger(path)
        def reader():
            path = current_path()
            db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
            db.execute("PRAGMA query_only=ON")
            return db
        return cls(
            binding=binding, consent=consent,
            open_owner_ledger=writer,
            open_readonly_connection=reader, source=source,
            answer_agent_factory=answer_agent_factory,
            authorize_correction=authorize_correction,
            open_review_readonly_connection=open_review_readonly_connection)

    def _owner(self, principal: McpHostPrincipal):
        if (not isinstance(principal, McpHostPrincipal)
                or principal.principal_id != self.binding.owner_id):
            raise PermissionError("AUTHENTICATED_HUMANMODEL_OWNER_REQUIRED")
        return principal.principal_id

    def answer(self, principal, *, question, scope):
        """Respond as a provisional owner simulation to an authorized agent.

        No client-supplied model, ledger path or owner identity. The factory is
        injected by the authenticated host and must bind the existing selected
        local model, exact owner/view and Guard-approved read context.
        """
        owner = self._owner(principal)
        if type(question) is not str or not question.strip() or len(question) > 2048:
            raise ValueError("BOUNDED_OWNER_QUESTION_REQUIRED")
        if type(scope) is not str or scope not in self.binding.scopes:
            raise PermissionError("OWNER_QUESTION_SCOPE_NOT_APPROVED")
        if self.answer_agent_factory is None:
            raise PermissionError("HOST_OWNER_ANSWER_AGENT_NOT_CONNECTED")
        from ai_foundation.auto_agent import AutoCapabilityAgent
        agent = self.answer_agent_factory(owner)
        if (not isinstance(agent, AutoCapabilityAgent)
                or agent.request.owner_id != owner
                or agent._human_model_context is None
                or agent._human_model_context.binding != self.binding):
            raise PermissionError("OWNER_ANSWER_AGENT_BINDING_MISMATCH")
        return agent.answer_owner_question(question, scope=scope)

    def status(self, principal):
        self._owner(principal)
        # A status read must not construct Ledger(), whose initializer may
        # create tables. The host supplies an existing SQLite RO connection.
        try:
            with closing(self.open_readonly_connection()) as db:
                if not isinstance(db, sqlite3.Connection):
                    raise TypeError('READONLY_CONNECTION_REQUIRED')
                db.execute('PRAGMA query_only=ON')
                report = audit_ledger(db)
        except (OSError, sqlite3.Error, TypeError):
            return {'status': 'OWNER_LEDGER_UNAVAILABLE',
                    'execution_authority': False}
        # Audit only returns counters and fixed reason codes; never return
        # source IDs, original text, directory paths, stable source digests.
        return report

    def collect(self, principal, *, source_system, record_id, scope, run_id):
        owner = self._owner(principal)
        grant = self._source_grant(owner, source_system, record_id, scope, run_id)
        with closing(self.open_owner_ledger()) as ledger:
            result = publish_exact_owner_observation(
                ledger, grant, current_authenticated_owner=owner,
                grant_verifier=self.consent,
                read_current=self.source.read_current)
        return result.safe_receipt()

    def _source_grant(self, owner, source_system, record_id, scope, run_id):
        if self.source is None:
            raise PermissionError("TRUSTED_OWNER_SOURCE_NOT_CONNECTED")
        if (type(source_system) is not str
                or source_system not in {"chat","drive","explicit-owner-input","owner-event"}
                or type(record_id) is not str or not 1 <= len(record_id) <= 256
                or type(scope) is not str or scope not in self.binding.scopes
                or type(run_id) is not str or not 1 <= len(run_id) <= 128):
            raise ValueError("BOUNDED_OWNER_SOURCE_KEY_REQUIRED")
        # The snapshot and grant come from an authenticated ORIGINAL source
        # adapter, not the user text or untrusted tool parameters.
        try:
            grant = self.source.grant_for(owner, source_system, record_id,
                                          scope, run_id)
        except Exception:
            raise PermissionError("OWNER_SOURCE_GRANT_UNAVAILABLE") from None
        if (type(grant) is not HostCollectionGrant
                or grant.owner_id != owner
                or grant.source_system != source_system
                or grant.source_record_id != record_id
                or grant.scope != scope or grant.consent_id != run_id):
            raise PermissionError("OWNER_SOURCE_GRANT_MISMATCH")
        if self.consent(grant) is not True:
            raise PermissionError("CURRENT_COLLECTION_GUARD_REQUIRED")
        return grant

    def _exact_current_review(self, task_id, generation_sha256,
                              answer_evidence_sha256):
        """Read actual current Work review, not caller-supplied answer metadata.

        The trusted host injects a read-only connection to the *existing*
        owner-scoped Work DB; do not discover DB paths from tool arguments.
        """
        try:
            with closing(self.open_review_readonly_connection()) as db:
                if not isinstance(db, sqlite3.Connection):
                    raise PermissionError("OWNER_REVIEW_WORK_NOT_BOUND")
                db.execute('PRAGMA query_only=ON')
                current = db.execute(
                    "SELECT generation_sha256 FROM primary_review_transitions "
                    "WHERE job_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                    (task_id,)).fetchone()
                exact = db.execute(
                    "SELECT outcome,evidence_sha256,answer_text "
                    "FROM primary_review_transitions WHERE job_id=? "
                    "AND generation_sha256=? AND event='PRIMARY_REVIEW_RESOLVED'",
                    (task_id, generation_sha256)).fetchone()
            return (current is not None and current[0] == generation_sha256
                    and exact is not None
                    and exact[0] == "MATCHED_EXISTING_DELEGATION"
                    and exact[1] == answer_evidence_sha256
                    and isinstance(exact[2], str) and bool(exact[2]))
        except (sqlite3.Error, OSError, TypeError, PermissionError):
            return False

    def correct(self, principal, *, source_system, record_id, scope, run_id,
                corrects_evidence_sha256, task_id, generation_sha256,
                answer_evidence_sha256):
        """Correct exact current task answer + original owner source, not a model claim.

        The existing Guard source grant and owner-specific correction authority
        remain required. Executed effects and historical answers are untouched.
        """
        owner = self._owner(principal)
        if not self.can_correct:
            raise PermissionError("HOST_OWNER_CORRECTION_NOT_CONNECTED")
        if (type(corrects_evidence_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", corrects_evidence_sha256) is None):
            raise ValueError("EXACT_CORRECTION_SOURCE_DIGEST_REQUIRED")
        validate_review_reference(task_id, generation_sha256)
        if (type(answer_evidence_sha256) is not str
                or re.fullmatch(r"[0-9a-f]{64}", answer_evidence_sha256) is None):
            raise ValueError("EXACT_CORRECTION_ANSWER_EVIDENCE_REQUIRED")
        if not self._exact_current_review(task_id, generation_sha256,
                                          answer_evidence_sha256):
            raise PermissionError("EXACT_CURRENT_OWNER_ANSWER_NOT_VERIFIED")
        grant = self._source_grant(owner, source_system, record_id, scope, run_id)
        # Select an exact, unique authenticated source in this owner's scope.
        # Never select a favourable row from duplicates or correct a model's
        # generated answer as if that answer were owner source evidence.
        with closing(self.open_readonly_connection()) as db:
            db.execute("PRAGMA query_only=ON")
            rows = db.execute(
                "SELECT e.id FROM evidence e JOIN human_source_admissions a "
                "ON a.evidence_id=e.id WHERE e.content_sha256=? AND e.scope=? "
                "AND e.kind='observation' AND e.privacy='private' "
                "AND a.owner_binding_sha256=? AND a.state='ACTIVE' LIMIT 2",
                (corrects_evidence_sha256, scope,
                 hashlib.sha256(owner.encode()).hexdigest())).fetchall()
        if len(rows) != 1:
            raise PermissionError("CORRECTION_SOURCE_NOT_UNIQUE_AND_AUTHENTICATED")
        def revalidate_exact_owner_decision(owner_id, old_id, exact_grant):
            # Re-read the Work answer at the owner's correction decision
            # boundary; a stale generation is not valid correction authority.
            if not self._exact_current_review(task_id, generation_sha256,
                                              answer_evidence_sha256):
                return False
            try:
                return self.authorize_correction(
                    owner_id, old_id, exact_grant, task_id,
                    generation_sha256, answer_evidence_sha256) is True
            except Exception:
                return False

        with closing(self.open_owner_ledger()) as ledger:
            result = publish_exact_owner_observation(
                ledger, grant, current_authenticated_owner=owner,
                grant_verifier=self.consent,
                read_current=self.source.read_current,
                corrects_evidence_id=rows[0][0],
                authorize_correction=revalidate_exact_owner_decision)
        return {**result.safe_receipt(), "source_correction_recorded": True,
                "original_answer_verified": True,
                "views_rebuilt": False, "task_effects_changed": False}

    def revoked(self, principal, *, run_id):
        owner = self._owner(principal)
        if type(run_id) is not str or not 1 <= len(run_id) <= 128:
            raise ValueError("EXACT_GUARD_RUN_REQUIRED")
        store = self.consent.guard.store
        if store is None or not callable(getattr(store, "is_cancelled", None)):
            raise PermissionError("CURRENT_GUARD_STORE_REQUIRED")
        # A Guard cancellation is a prerequisite, not an MCP-supplied fact.
        with closing(self.open_owner_ledger()) as ledger:
            result = reconcile_cancelled_collection_consent(
                ledger, run_id, current_authenticated_owner=owner,
                is_guard_cancelled=store.is_cancelled)
        return result.safe_receipt()

    def on_guard_cancelled(self, run_id):
        """Invoked AFTER existing Operator/Guard committed cancellation.

        Does not require a second user prompt or MCP session: the original
        Guard cancellation is the sole revocation authority. It is bound to
        this exact configured owner; unrelated Guard runs have zero matches.
        """
        store = self.consent.guard.store
        if (type(run_id) is not str or not run_id
                or store is None or not callable(getattr(store,"is_cancelled",None))):
            raise PermissionError("GUARD_CANCEL_NOT_VERIFIED")
        if not store.is_cancelled(run_id):
            raise PermissionError("GUARD_CANCEL_NOT_VERIFIED")
        # Most Operator cancellations are unrelated to HumanModel. Do not
        # touch the private owner volume for ordinary tasks or denied pending
        # requests that were never granted collection authority.
        try:
            with store._connect() as db:
                matched = db.execute(
                    "SELECT 1 FROM approvals WHERE run_id=? "
                    "AND action='human_model_collect'", (run_id,)
                ).fetchone() is not None
        except Exception:
            raise PermissionError("CURRENT_GUARD_STORE_REQUIRED") from None
        if not matched:
            return {"status": "NO_HUMANMODEL_GRANT",
                    "execution_authority": False}
        with closing(self.open_owner_ledger()) as ledger:
            return reconcile_cancelled_collection_consent(
                ledger, run_id,
                current_authenticated_owner=self.binding.owner_id,
                is_guard_cancelled=store.is_cancelled).safe_receipt()

    def refresh(self, principal):
        owner = self._owner(principal)
        if self.source is None:
            raise PermissionError("TRUSTED_OWNER_SOURCE_NOT_CONNECTED")
        with closing(self.open_owner_ledger()) as ledger:
            # This is intentionally bounded and avoids the 9B lease.
            return owner_lifecycle_tick(
                ledger, current_authenticated_owner=owner,
                consent_current=self.consent.active_digest,
                read_current=self.source.read_current)
