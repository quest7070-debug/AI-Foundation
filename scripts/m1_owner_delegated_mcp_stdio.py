"""Explicit owner-delegated MCP session for one-shot existing Guard decisions.

This is a separate owner-local stdio process, NOT a listener or a model tool.
It cannot create approvals/delegations. Owner first clicks the exact option
in the existing Operator UI. No pending grant => no private approval tools.
The source and deployment are Draft-only until a separate accepted release.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
from ai_foundation.authority_manifest import verify as verify_authority_manifest
from ai_foundation.core import GuardState
from ai_foundation.guard import GuardCore
from ai_foundation.mcp_host import AuthenticatedMcpHost, McpHostAuthorizer
from ai_foundation.mcp_owner_grants import McpOwnerGrants
from ai_foundation.operator_actions import OperatorActions
from ai_foundation.productization import load_config
from ai_foundation.storage_admission import StorageAdmission
from ai_foundation.store import SQLiteGuardStore, approval_request_ref
from foundation_mcp_stdio import MCPStdio, OperatorAggregateProxy, serve_stdio

PRINCIPAL = "macos-owner-local"


class _GuardCurrent:
    """Minimal current Guard projection; no Operator constructor side effects."""

    def __init__(self, path):
        self.path = Path(path)

    def as_dict(self):
        with sqlite3.connect("file:"+str(self.path.resolve())+"?mode=ro",
                             uri=True, timeout=3) as db:
            rows = db.execute(
                "SELECT run_id,action,target,request_nonce,canon_revision,effect_id "
                "FROM approval_requests ORDER BY updated_at DESC,run_id LIMIT 100"
            ).fetchall()
        return {"attention": [{
            "kind": "approval", "run_id": run, "action": action,
            "status": "WAITING_HUMAN",
            "approval_ref": approval_request_ref(run,action,target,nonce,canon,effect)
              if nonce and canon and effect else ""
        } for run,action,target,nonce,canon,effect in rows]}


class LiveOwnerMcpOperator:
    """No Work initialization; only the current canonical Guard is mutable."""

    def __init__(self, guard_store, *, aggregate=None):
        self.actions = OperatorActions(GuardCore(guard_store.runtime_state(),
                                                  store=guard_store))
        self._guard = _GuardCurrent(guard_store.path)
        self._status = aggregate if aggregate is not None else OperatorAggregateProxy()

    def snapshot(self):
        return self._guard

    def human_payload(self):
        return self._status.human_payload()

    def act(self, action, run_id, request_ref):
        # Direct Guard exact revision CAS; never use legacy no-ref fallback.
        if action == "approve":
            return self.actions.approve_pending(run_id, request_ref)
        if action == "cancel":
            return self.actions.deny_pending(run_id, request_ref)
        raise ValueError("unsupported current Guard decision")


def build_owner_mcp(guard_store, *, aggregate=None, development_port_factory=None,
                    ticket_filter=None):
    """Trusted launcher binds optional local development tickets to the same Guard.

    The factory is installed host code, not an MCP argument or client-selected
    path. Without it the existing owner stdio catalog remains unchanged.
    """
    grants = McpOwnerGrants(guard_store, initialize=False)
    operator = LiveOwnerMcpOperator(guard_store, aggregate=aggregate)
    if development_port_factory is not None and not callable(development_port_factory):
        raise ValueError("TRUSTED_DEVELOPMENT_FACTORY_REQUIRED")
    development_port = (development_port_factory(operator.actions.guard)
                        if development_port_factory is not None else None)

    def authorize(principal, tool, run_id):
        if (ticket_filter is not None and run_id and tool in {
                "development_continue", "development_admit", "development_run",
                "development_status", "development_deliver"}
                and ticket_filter(run_id) is not True):
            return False
        if tool == "development_cycle":
            return (development_port is not None
                    and callable(getattr(development_port, "cycle_one", None))
                    and development_port.authorize_list(principal) is True)
        if tool == "development_continue":
            return (development_port is not None
                    and callable(getattr(development_port, "continue_reviewed", None))
                    and callable(getattr(development_port, "authorize_admit", None))
                    and development_port.authorize_admit(principal, run_id) is True
                    and development_port.authorize(principal, run_id) is True)
        if tool == "development_admit":
            return (development_port is not None
                    and callable(getattr(development_port, "authorize_admit", None))
                    and development_port.authorize_admit(principal, run_id) is True)
        if tool == "development_request":
            return (development_port is not None
                    and callable(getattr(development_port, "authorize_request", None))
                    and development_port.authorize_request(principal) is True)
        if tool == "development_list":
            return (development_port is not None
                    and development_port.authorize_list(principal) is True)
        if tool in {"development_run", "development_status"}:
            return (development_port is not None
                    and development_port.authorize(principal, run_id) is True)
        if tool == "development_deliver":
            return (development_port is not None
                    and development_port.authorize_delivery(principal, run_id) is True)
        return grants.authorize(principal, tool, run_id)

    auth = McpHostAuthorizer(owner_authorize=authorize)
    scopes = {"foundation_status", "approval_requests", "review_candidate",
              "submit_decision:AUTHORIZE", "submit_decision:DENY"}
    exposed = ["foundation_status", "approval_requests",
               "review_candidate", "submit_decision"]
    if development_port is not None:
        scopes.update({"development_list", "development_run", "development_status",
                       "development_deliver"})
        exposed += ["development_list", "development_run", "development_status", "development_deliver"]
    if development_port is not None and callable(getattr(development_port, "request", None)):
        scopes.add("development_request")
        exposed.append("development_request")
    if development_port is not None and getattr(development_port, "can_admit", False):
        scopes.add("development_admit")
        exposed.append("development_admit")
        if callable(getattr(development_port, "continue_reviewed", None)):
            scopes.add("development_continue")
            exposed.append("development_continue")
        if callable(getattr(development_port, "cycle_one", None)):
            scopes.add("development_cycle")
            exposed.append("development_cycle")
    principal, token = AuthenticatedMcpHost.issue_principal(
        PRINCIPAL, scopes, ttl_seconds=300)
    auth.register(principal, token)
    host = AuthenticatedMcpHost(
        operator, auth, claim_owner_decision=grants.claim,
        development_port=development_port)
    return MCPStdio(host, principal.session_id, token,
                    exposed_tools=tuple(exposed))

class TrustedOwnerSessionRenewal:
    """Renew only the original host-authenticated, fixed-scope owner session.

    A persistent tunnel can outlive the session TTL. Recheck installed Guard,
    grants and original ticket manifest on renewal; never copy the old grant,
    accept a model-supplied principal, or re-arm consumed Work.
    """

    def __init__(self, factory):
        if not callable(factory):
            raise ValueError("TRUSTED_OWNER_SESSION_FACTORY_REQUIRED")
        self._factory = factory
        self._service = factory()

    def dispatch(self, message):
        service = self._service
        if service.host.authorizer.authenticate(
                service.session_id, service.token) is None:
            replacement = self._factory()
            if replacement.exposed_tools != service.exposed_tools:
                # Fresh host permission inventory must not expand mid-session.
                raise PermissionError("OWNER_MCP_SCOPE_CHANGED")
            service.host = replacement.host
            service.session_id = replacement.session_id
            service.token = replacement.token
        return service.dispatch(message)


def scheduled_ticket_allowed(root, ticket_id, *, work_db, scope_ref, scope_current):
    """Select already individually authorized work before unattended discovery.

    This is a selector only: build_development_port/admit still enforce every
    exact owner manifest, Work, source, model, egress, and delivery boundary.
    Revoked or absent broad scope cannot suppress an independent exact review.
    """
    from m1_development_scope_delegation import delegated_record
    from m1_development_ticket_factory import (
        _ID, _owner_manifest, _strict_json, _validate_ticket, _owner_local_repo)
    try:
        if type(ticket_id) is not str or not _ID.fullmatch(ticket_id):
            return False
        path = root / "development" / "tickets.json"
        if path.exists() or path.is_symlink():
            doc = _strict_json(_owner_manifest(path))
            if (type(doc) is not dict or doc.get("version") != 1
                    or type(doc.get("tickets")) is not list):
                return False
            rows = [x for x in doc["tickets"] if type(x) is dict
                    and x.get("ticket_id") == ticket_id]
            if rows:
                if len(rows) != 1:
                    return False
                record = rows[0]
                _validate_ticket(record)
                if record.get("source_origin") == "owner-local-review-v1":
                    return True
                return (scope_ref is not None and scope_current() is True
                        and record.get("source_origin") == "owner-scope-delegation-v1"
                        and record.get("scope_ref") == scope_ref)
        explicit = root / "development" / "reviews" / (ticket_id + ".json")
        if explicit.exists() or explicit.is_symlink():
            # Only a genuine exact owner review may pass. Do not use a file
            # name, candidate presence or the broad grant as a substitute.
            from m1_development_review_candidate import select_review_repo
            from m1_strata_owner_ticket_admission import reviewed_contract
            repo = select_review_repo(root, _owner_local_repo(), ticket_id,
                                      work_db=work_db)
            row = reviewed_contract(root, repo, ticket_id)
            return row.get("source_origin") == "owner-local-review-v1"
        if scope_ref is None or scope_current() is not True:
            return False
        row = delegated_record(root, _owner_local_repo(), ticket_id, work_db=work_db)
        return row is not None and row.get("scope_ref") == scope_ref
    except (OSError, ValueError, PermissionError, RuntimeError, UnicodeError):
        return False


def main():
    from m1_development_bridge import require_m1
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise SystemExit("M1_OWNER_SESSION_REQUIRED")
    p = argparse.ArgumentParser()
    # The trusted host installation fixes this configuration path, never a
    # property of the untrusted MCP JSON request or an AI-proposed tool arg.
    p.add_argument("--config", required=True)
    p.add_argument("--enable-local-development", action="store_true",
                   help="Opt in to owner-approved local CODE tickets; no listener")
    p.add_argument("--scheduled-cycle", action="store_true",
                   help="One owner-local, scope-bound cycle on existing worker tick")
    args = p.parse_args()
    config = load_config(args.config)
    root = Path(config.data_dir).resolve(strict=True)
    verify_authority_manifest(root, config)
    guard_path = root / config.guard_db
    if not guard_path.is_file() or guard_path.is_symlink():
        raise RuntimeError("OWNER_GUARD_UNAVAILABLE")
    storage = StorageAdmission(root)
    store = SQLiteGuardStore(guard_path, storage_admission=storage)
    development_factory = None
    scheduled_ref = None
    scheduled_canon = None
    scheduled_guard = None
    ticket_filter = None
    if args.scheduled_cycle:
        from m1_direct_development import installed_config
        from m1_operator_release_canon import observe_installed_canon
        from m1_development_review_candidate import _installed_live_source_repo
        from m1_development_scope_delegation import autonomous_scope, prepare_guard_scope
        from m1_development_owner_review import OwnerDevelopmentReview
        from m1_development_ticket_factory import _owner_local_repo
        stage=_installed_live_source_repo(_owner_local_repo())
        if (not args.enable_local_development or ROOT != stage
                or Path(args.config).resolve(strict=True)!=installed_config()[0]):
            raise PermissionError("INSTALLED_SCHEDULED_HOST_REQUIRED")
        scheduled_canon=observe_installed_canon(ROOT)
        scheduled_guard=GuardCore(store.runtime_state(),store=store)
        scheduled_ref=autonomous_scope(root,guard=scheduled_guard,canon=scheduled_canon)
        def scope_current():
            return (scheduled_ref is not None
                    and autonomous_scope(root,guard=scheduled_guard,
                         canon=observe_installed_canon(ROOT))==scheduled_ref)

        def ticket_filter(ticket_id):
            return scheduled_ticket_allowed(root, ticket_id,
                work_db=config.work_db, scope_ref=scheduled_ref,
                scope_current=scope_current)
    if args.enable_local_development:
        from m1_development_ticket_factory import build_development_port
        # The trusted launcher chooses the manifest under its verified data
        # root. MCP JSON cannot choose paths or manufacture reviewed contracts.
        from ai_foundation.development_requests import DevelopmentRequestPort
        from ai_foundation.durable_work import SQLiteWorkStore
        def development_factory(guard):
            port = build_development_port(root=root, config=config, repo=ROOT, guard=guard)
            def admit_reviewed(ticket_id, instruction_sha256):
                from m1_strata_owner_ticket_admission import admit
                admit(ticket_id, expected_instruction_sha256=instruction_sha256,
                      expected_root=root)
                return build_development_port(root=root, config=config, repo=ROOT, guard=guard)
            def refresh_admitted(ticket_id, instruction_sha256):
                # Rebind only a previously installed, exact owner-private
                # manifest contract. Never call fresh admission for a VERIFIED
                # intake: review snapshot intentionally accepts WAITING_HUMAN
                # only. The factory rechecks Work, source, test and live scope.
                from hashlib import sha256
                from m1_development_ticket_factory import (
                    _ID, _owner_manifest, _strict_json, _validate_ticket)
                if type(ticket_id) is not str or not _ID.fullmatch(ticket_id):
                    return None
                manifest = _strict_json(_owner_manifest(root / "development" / "tickets.json"))
                if (type(manifest) is not dict or manifest.get("version") != 1
                        or type(manifest.get("tickets")) is not list):
                    return None
                records = [row for row in manifest["tickets"]
                           if type(row) is dict and row.get("ticket_id") == ticket_id]
                if len(records) != 1:
                    return None
                record = records[0]
                _validate_ticket(record)
                if (record.get("source_origin") not in {
                        "owner-local-review-v1", "owner-scope-delegation-v1"}
                        or sha256(record["instruction"].encode()).hexdigest()
                        != instruction_sha256):
                    return None
                return build_development_port(root=root, config=config, repo=ROOT, guard=guard)
            def review_available(ticket_id):
                # A file's presence is only an admission hint, never a
                # signature or public-source decision. The unchanged owner
                # admission validates all bytes and explicit confirmation.
                from m1_development_ticket_factory import _ID
                if type(ticket_id) is not str or not _ID.fullmatch(ticket_id):
                    return False
                path = root / "development" / "reviews" / (ticket_id + ".json")
                try:
                    info = path.lstat()
                except FileNotFoundError:
                    # A one-time owner UI grant can replace repeated reviews
                    # only for safe, exact tracked source/test pairs. This
                    # probes without writing, claiming Work or contacting LLM.
                    try:
                        from m1_development_scope_delegation import delegated_record
                        from m1_development_ticket_factory import _owner_local_repo
                        return delegated_record(
                            root, _owner_local_repo(), ticket_id,
                            work_db=config.work_db) is not None
                    except (OSError, ValueError, PermissionError,
                            RuntimeError, UnicodeError):
                        return False
                except OSError:
                    return False
                import stat
                return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                        and info.st_mode & 0o077 == 0)
            def prepare_scope(ticket_ids):
                from m1_development_scope_delegation import prepare_guard_scope
                from m1_development_ticket_factory import _owner_local_repo
                from m1_operator_release_canon import observe_installed_canon
                try:
                    return prepare_guard_scope(
                        root, _owner_local_repo(), ticket_ids,
                        guard=guard, storage=storage, work_db=config.work_db,
                        canon_observer=lambda: observe_installed_canon(ROOT))
                except (OSError, ValueError, PermissionError, RuntimeError, UnicodeError):
                    return {"state": "SCOPE_PREPARATION_BLOCKED",
                            "execution_started": False}
            work=SQLiteWorkStore(root/config.work_db)
            def discover(submit):
                from local9b_failure_candidates import discover_work_regression
                from m1_development_scope_delegation import autonomous_scope
                from m1_development_ticket_factory import _owner_local_repo
                return discover_work_regression(_owner_local_repo(),work,
                    source_main=scheduled_canon["source_main"],storage=storage,submit=submit,
                    scope_current=lambda:autonomous_scope(root,guard=guard,
                        canon=observe_installed_canon(ROOT))==scheduled_ref)
            return DevelopmentRequestPort(port, work=work,
                                          principal_id=PRINCIPAL, storage_admission=storage,
                                          admit_reviewed=admit_reviewed,
                                          review_available=review_available,
                                          refresh_admitted=refresh_admitted,
                                          prepare_scope=prepare_scope,
                                          discover=discover if args.scheduled_cycle and scheduled_ref is not None else None)
    if args.scheduled_cycle:
        from m1_p4_mcp_stdio_e2e import _request
        service=build_owner_mcp(store,development_port_factory=development_factory,
                                ticket_filter=ticket_filter)
        response=service.dispatch(_request(1,"tools/call",name="development_cycle",arguments={}))
        result=response.get("result",{})
        if result.get("isError") is not False:
            print('{"state":"SCHEDULED_CYCLE_BLOCKED"}')
            return
        record=json.loads(result["content"][0]["text"])
        state=record.get("state") or record.get("status")
        if state == "NO_ELIGIBLE_TICKET" and scheduled_ref is None:
            repo=_owner_local_repo()
            pending=OwnerDevelopmentReview(root,repo_factory=lambda:repo,
                                           work_db=config.work_db).pending_request_ids()
            scope_result=prepare_guard_scope(root,repo,pending,guard=scheduled_guard,
                storage=storage,work_db=config.work_db,
                canon_observer=lambda:observe_installed_canon(ROOT))
            state=(scope_result or {}).get("state") or "SCHEDULED_SCOPE_NOT_ACTIVE"
        import re
        if type(state) is not str or not re.fullmatch(r"[A-Z0-9_]{2,96}",state):
            state="SCHEDULED_CYCLE_RECEIPT_UNVERIFIED"
        print(json.dumps({"state":state}))
        return
    serve_stdio(TrustedOwnerSessionRenewal(lambda: build_owner_mcp(
        store, development_port_factory=development_factory)))


if __name__ == "__main__":
    main()


