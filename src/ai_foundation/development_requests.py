"""One owner-authorized CODE lifecycle over existing durable Work, Guard and Harness.

This is the single control plane for intent -> exact owner-scope admission ->
one guarded CODE attempt -> independent acceptance -> authorized Draft
delivery. The original M1 owner grant, source/test verification, Work claims,
paid-route restrictions and release approvals are *not* implemented here or
bypassed. Old failed/uncertain work is never reset or replayed. No separate
review UI, queue, scheduler, database, model, or agent is created.
"""
from hashlib import sha256
import json
import re


class DevelopmentRequestPort:
    """Orchestrate only already host-authorized Work and CODE capabilities."""

    def __init__(self, port, *, work, principal_id, storage_admission,
                 admit_reviewed=None, review_available=None, refresh_admitted=None,
                 prepare_scope=None, discover=None):
        if review_available is not None and not callable(review_available):
            raise ValueError("TRUSTED_OWNER_REVIEW_READER_REQUIRED")
        self.port = port
        self.work = work
        self.principal_id = principal_id
        self.storage_admission = storage_admission
        self.admit_reviewed = admit_reviewed
        self.can_admit = callable(admit_reviewed)
        self.review_available = review_available
        self.refresh_admitted = refresh_admitted
        if prepare_scope is not None and not callable(prepare_scope):
            raise ValueError("TRUSTED_SCOPE_PREPARER_REQUIRED")
        self.prepare_scope = prepare_scope
        if discover is not None and not callable(discover):
            raise ValueError("TRUSTED_DISCOVERY_REQUIRED")
        self.discover = discover
        self.prefix = "mcp-development-request:" + sha256(principal_id.encode()).hexdigest() + ":"

    def __getattr__(self, name):
        return getattr(self.port, name)

    @staticmethod
    def _validate_id(ticket_id):
        if type(ticket_id) is not str or not re.fullmatch(
                r"[a-z0-9][a-z0-9-]{0,47}", ticket_id):
            raise ValueError("INVALID_DEVELOPMENT_REQUEST_ID")

    def authorize_request(self, principal):
        return getattr(principal, "principal_id", None) == self.principal_id

    def _saved_request(self, ticket_id):
        self._validate_id(ticket_id)
        rows = self.work.load(self.prefix + ticket_id)
        return rows[0] if rows and rows[0].name == "development-request" else None

    def _pending(self, ticket_id):
        return self._saved_request(ticket_id) is not None

    def authorize(self, principal, ticket_id):
        return self.port.authorize(principal, ticket_id) or (
            self.authorize_request(principal) and self._pending(ticket_id))

    def authorize_admit(self, principal, ticket_id):
        return (self.can_admit and self.authorize_request(principal)
                and self._pending(ticket_id))

    def request(self, principal, ticket_id, instruction):
        """Store an immutable intent, never infer an executable permission."""
        if not self.authorize_request(principal):
            raise PermissionError("DEVELOPMENT_REQUEST_NOT_AUTHORIZED")
        self._validate_id(ticket_id)
        if type(instruction) is not str or not instruction.strip() or len(instruction) > 4000:
            raise ValueError("INVALID_DEVELOPMENT_INSTRUCTION")
        if self.port.authorize(principal, ticket_id):
            raise ValueError("DEVELOPMENT_TICKET_ALREADY_ADMITTED")
        contract = json.dumps({"ticket_id": ticket_id, "instruction": instruction},
                              ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        old = self._saved_request(ticket_id)
        if old is not None:
            if old.result != contract:
                raise ValueError("DEVELOPMENT_REQUEST_CONFLICT")
            return {"ticket_id": ticket_id, "state": self.status(principal, ticket_id)["state"],
                    "instruction_sha256": sha256(instruction.encode()).hexdigest(),
                    "replay_readonly": True, "execution_started": False}
        self.storage_admission.require("development request")
        replay = self.work.request_development_review(self.prefix + ticket_id, contract)
        return {"ticket_id": ticket_id, "state": self.status(principal, ticket_id)["state"],
                "instruction_sha256": sha256(instruction.encode()).hexdigest(),
                "replay_readonly": replay, "execution_started": False}

    def status(self, principal, ticket_id):
        saved = self._saved_request(ticket_id) if self.authorize_request(principal) else None
        if saved is not None and saved.status.value != "VERIFIED":
            state = ("REVIEW_REQUIRED" if saved.status.value == "WAITING_HUMAN"
                     else saved.status.value)
            return {"ticket_id": ticket_id, "state": state, "execution_started": False}
        if self.port.authorize(principal, ticket_id):
            return self.port.status(principal, ticket_id)
        if saved is not None:
            return {"ticket_id": ticket_id, "state": "ADMISSION_REFRESH_REQUIRED",
                    "execution_started": False}
        raise PermissionError("DEVELOPMENT_REQUEST_NOT_AUTHORIZED")

    def admit(self, principal, ticket_id):
        """Bind an exact existing owner review or standing source-scoped grant.

        Neither ticket content nor a caller-supplied model/scope can authorize
        this transition. The trusted owner M1 admission code must independently
        validate original source/test hashes and current scope generation.
        """
        if not self.authorize_admit(principal, ticket_id):
            raise PermissionError("DEVELOPMENT_ADMISSION_NOT_AUTHORIZED")
        saved = self._saved_request(ticket_id)
        if saved.status.value == "VERIFIED" and self.port.authorize(principal, ticket_id):
            return {**self.port.status(principal, ticket_id), "replay_readonly": True}
        if saved.status.value not in {"WAITING_HUMAN", "VERIFIED"}:
            return self.status(principal, ticket_id)
        request = json.loads(saved.result)
        if (type(request) is not dict or set(request) != {"ticket_id", "instruction"}
                or request["ticket_id"] != ticket_id
                or type(request["instruction"]) is not str):
            raise ValueError("DEVELOPMENT_REQUEST_RECEIPT_INVALID")
        digest = sha256(request["instruction"].encode()).hexdigest()
        # A VERIFIED intake has already crossed the owner admission boundary.
        # Restore only its existing manifest binding; never regenerate a
        # review or install a missing contract from a later source revision.
        restoring = saved.status.value == "VERIFIED"
        if restoring and not callable(self.refresh_admitted):
            return self.status(principal, ticket_id)
        self.storage_admission.require("reviewed development admission")
        refreshed = (self.refresh_admitted(ticket_id, digest) if restoring
                     else self.admit_reviewed(ticket_id, digest))
        if restoring and refreshed is None:
            return self.status(principal, ticket_id)
        if (refreshed.guard is not self.guard
                or refreshed.authorize(principal, ticket_id) is not True):
            raise PermissionError("SAME_GUARD_REVIEWED_TICKET_REQUIRED")
        from .orchestration import WorkStatus
        completed = False if restoring else self.work.transition(
            self.prefix + ticket_id, 0, WorkStatus.WAITING_HUMAN,
            WorkStatus.VERIFIED, saved.result)
        current = self._saved_request(ticket_id)
        if (current is None or current.status.value != "VERIFIED"
                or current.result != saved.result):
            return self.status(principal, ticket_id)
        self.port = refreshed
        return {**self.status(principal, ticket_id),
                "replay_readonly": not completed, "admission_completed": True}

    def run(self, principal, ticket_id):
        saved = self._saved_request(ticket_id) if self.authorize_request(principal) else None
        if saved is not None and saved.status.value != "VERIFIED":
            return self.status(principal, ticket_id)
        if not self.port.authorize(principal, ticket_id):
            return self.status(principal, ticket_id)
        return self.port.run(principal, ticket_id)

    def continue_reviewed(self, principal, ticket_id):
        """One admitted attempt; the host's separately scoped Draft follows."""
        if not self.authorize_admit(principal, ticket_id):
            raise PermissionError("REVIEWED_DEVELOPMENT_CONTINUATION_NOT_AUTHORIZED")
        saved = self._saved_request(ticket_id)
        if saved is not None and (saved.status.value == "WAITING_HUMAN"
                or (saved.status.value == "VERIFIED"
                    and not self.port.authorize(principal, ticket_id))):
            self.admit(principal, ticket_id)
        result = self.status(principal, ticket_id)
        return self.run(principal, ticket_id) if result.get("state") == "READY" else result

    def authorize_delivery(self, principal, ticket_id):
        saved = self._saved_request(ticket_id) if self.authorize_request(principal) else None
        if saved is not None and saved.status.value != "VERIFIED":
            return False
        return self.port.authorize_delivery(principal, ticket_id)

    def deliver(self, principal, ticket_id):
        if not self.authorize_delivery(principal, ticket_id):
            raise PermissionError("DEVELOPMENT_DELIVERY_NOT_AUTHORIZED")
        return self.port.deliver(principal, ticket_id)

    def list_tickets(self, principal, *, authorize_status):
        inventory = self.port.list_tickets(principal, authorize_status=authorize_status)
        rows = list(inventory["tickets"])
        seen = {row["ticket_id"] for row in rows}
        if self.authorize_request(principal):
            for job_id, _ in self.work.development_review_requests(self.prefix):
                ticket = job_id[len(self.prefix):]
                if ticket not in seen and authorize_status(ticket):
                    rows.append(self.status(principal, ticket))
                    seen.add(ticket)
        return {"tickets": rows, "ticket_count": len(rows)}

    def cycle_one(self, principal, *, authorize_status, authorize_pending,
                  authorize_delivery=None):
        """One minimal CODE action: ready edit, scoped admission, or Draft closeout.

        Exact current host grants are checked for every ticket. Authorized
        already-verified work may enter the host's separately authorized Draft
        delivery without repeating an LLM call or a test. Never re-arm failed,
        cancelled or uncertain Work. Avoid source-review disk probes when an
        already-admitted READY task can run immediately.
        """
        if (not self.authorize_list(principal) or not callable(authorize_status)
                or not callable(authorize_pending)
                or (authorize_delivery is not None and not callable(authorize_delivery))):
            raise PermissionError("DEVELOPMENT_CYCLE_NOT_AUTHORIZED")
        rows = self.list_tickets(principal, authorize_status=authorize_status)["tickets"]
        if type(rows) is not list or len(rows) > 96:
            raise ValueError("DEVELOPMENT_CYCLE_INVENTORY_UNVERIFIED")
        counts = {"review_required": 0, "failed_acceptance": 0,
                  "source_base_review": 0, "admission_refresh": 0,
                  "verified_local": 0, "other_terminal": 0}
        seen = set()
        waiting = []
        refreshing = []
        ready = []
        delivery = []
        examined = 0
        for row in rows:
            if (type(row) is not dict or type(row.get("ticket_id")) is not str
                    or type(row.get("state")) is not str):
                raise ValueError("DEVELOPMENT_CYCLE_INVENTORY_UNVERIFIED")
            ticket = row["ticket_id"]
            if ticket in seen:
                raise ValueError("DEVELOPMENT_CYCLE_DUPLICATE_TICKET")
            seen.add(ticket)
            if not authorize_status(ticket):
                continue
            examined += 1
            observed = self.status(principal, ticket)
            state = observed.get("state")
            if type(state) is not str:
                raise ValueError("DEVELOPMENT_CYCLE_STATE_UNVERIFIED")
            if state == "READY":
                ready.append(ticket)
            elif state == "REVIEW_REQUIRED":
                counts["review_required"] += 1
                if (self.can_admit and self.review_available is not None
                        and authorize_pending(ticket)):
                    waiting.append(ticket)
            elif state == "VERIFIED_LOCAL":
                counts["verified_local"] += 1
                if (authorize_delivery is not None
                        and not observed.get("github_published")
                        and "delivery_state" not in observed
                        and authorize_delivery(ticket)
                        and self.authorize_delivery(principal, ticket)):
                    delivery.append(ticket)
            elif state == "FAILED_REVIEW_REQUIRED":
                counts["failed_acceptance"] += 1
            elif state == "SOURCE_BASE_REVIEW_REQUIRED":
                counts["source_base_review"] += 1
            elif state == "ADMISSION_REFRESH_REQUIRED":
                counts["admission_refresh"] += 1
                if (self.can_admit and callable(self.refresh_admitted)
                        and authorize_pending(ticket)):
                    refreshing.append(ticket)
            else:
                counts["other_terminal"] += 1
        if ready:
            return self.run(principal, ready[0])
        for ticket in refreshing:
            outcome = self.continue_reviewed(principal, ticket)
            if outcome.get("state") != "ADMISSION_REFRESH_REQUIRED":
                return outcome
        # A standing grant is rechecked *inside* trusted M1 admission; a
        # positive availability hint alone has no authority to execute.
        for ticket in waiting:
            if self.review_available(ticket) is True:
                return self.continue_reviewed(principal, ticket)
        if delivery:
            # Host must again authorize development_deliver and invoke the
            # original idempotent publisher; this method has no Git effects.
            return self.status(principal, delivery[0])
        # If no existing authorized Work can run, propose the ordinary
        # bounded scope through the original Guard, once, using only the
        # host-authorized waiting tickets. This is not an approval.
        if waiting and self.prepare_scope is not None:
            scope = self.prepare_scope(tuple(waiting))
            if scope is not None:
                if scope.get("state") == "SCOPE_ACTIVATED":
                    for ticket in waiting:
                        if self.review_available(ticket) is True:
                            return self.continue_reviewed(principal, ticket)
                return scope
        # Unfinished committed work is not idle capacity for new discovery.
        # The scheduled host's narrower execution filter may hide protected or
        # blocked owner tickets. Inspect the actual locally authorized owner
        # inventory only inside this trusted discovery path, without exposing
        # hidden tickets or enlarging any execution grant. Historical failures
        # remain evidence, not implicitly completed or replayable work.
        if (self.discover is not None and self.authorize_request(principal)
                and all(counts[key] == 0 for key in
                        ("review_required", "failed_acceptance", "source_base_review",
                         "admission_refresh", "other_terminal"))):
            owner_rows = self.list_tickets(
                principal, authorize_status=lambda ticket: self.authorize(principal, ticket)
            )["tickets"]
            if (type(owner_rows) is list and len(owner_rows) <= 96
                    and all(type(row) is dict and row.get("state") == "VERIFIED_LOCAL"
                            for row in owner_rows)):
                found = self.discover(lambda ident, instruction:
                                      self.request(principal, ident, instruction))
                if found is not None:
                    return found
        if counts["failed_acceptance"]:
            gate = "OWNER_REVIEW_FAILED_LOCAL_ACCEPTANCE"
        elif counts["source_base_review"]:
            gate = "OWNER_RECONCILE_SOURCE_BASE"
        elif counts["review_required"]:
            gate = "EXACT_REVIEW_OR_EXISTING_SCOPE_REQUIRED"
        elif counts["admission_refresh"]:
            gate = "RECHECK_EXISTING_ADMISSION"
        else:
            gate = "NEW_ELIGIBLE_WORK_REQUIRED"
        return {
            "state": "NO_ELIGIBLE_TICKET",
            "execution_started": False,
            "authorized_examined": examined,
            "review_required": counts["review_required"],
            "blocked_state_counts": counts,
            "resume_only_after": gate,
            "retry_without_change": False,
            "work_failed_count_inferred": False,
        }
