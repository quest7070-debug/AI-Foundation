#!/usr/bin/env python3
"""Single owner-local production recovery entrypoint for Operator + mobile Gateway.

This is not a second deployment authority. Both independently scoped releases
reuse the existing Guard approvals, Canon revisions, immutable source, owner
TTY consent, existing staged backups, launchd and rollback state machines.
The new Operator recovery adapter allows replacement of an *unresponsive*
incumbent only when its exact installed source/launchd definition/PID are
independently bound. A healthy busy Operator remains protected.
No GitHub runner, MCP caller or model can mint a Guard approval with this file.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import plistlib
import re
from types import SimpleNamespace
import sys
from itertools import islice

from ai_foundation.operator_release_transaction import OperatorOnlyCutover
from ai_foundation.guard import GuardCore
from ai_foundation.operator_actions import OperatorActions
from scripts import m1_mobile_gateway_successor as mobile
from scripts import m1_operator_release_cli as cli
from scripts.m1_operator_release_host import (
    FixedOperatorHost, OperatorHostDenied, _loaded_definition_match,
)

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_REF = re.compile(r"[0-9a-f]{64}\Z")
_OPERATOR = "m1-operator"
_MAX = 512


class RecoveryDenied(RuntimeError):
    """Only fixed error codes; never include private runtime paths."""


@dataclass(frozen=True)
class ApprovedOperator:
    scope: object
    gate: object
    host: object
    run_id: str
    request_ref: str


class UnresponsiveOperatorHost(FixedOperatorHost):
    """Original Operator adapter, with tightly attested hung-incumbent switch.

    OperatorOnlyCutover is still the sole state machine and enforces both the
    original Guard approval and trusted owner release confirmation at every
    effect boundary. This adapter does not grant authority or skip staging.
    """

    def _prior_physical_binding(self, scope):
        try:
            _, original = self._rollback_material(scope)
            if self.plist.read_bytes() != original:
                return False
            installed = plistlib.loads(original)
            loaded = self._launch("print", self.target)
            return (
                loaded.returncode == 0
                and _loaded_definition_match(loaded.stdout, installed)
                and self._pid_owned() is True
            )
        except (OSError, ValueError, TypeError, KeyError,
                plistlib.InvalidFileException, OperatorHostDenied):
            return False

    def switch_operator(self, scope):
        if self.verify_candidate(scope) is not True:
            raise OperatorHostDenied("PINNED_CANDIDATE_REQUIRED")
        if self.current_scope_ref() != scope.scope_ref:
            raise OperatorHostDenied("LAST_MOMENT_SOURCE_CHANGE")
        # Independently verify the actual current process, definition and
        # restorable original bytes, even if its HTTP event loop is stuck.
        if not self._prior_physical_binding(scope):
            raise OperatorHostDenied("UNRESPONSIVE_PREDECESSOR_UNATTESTED")
        live = self._human()
        if live is not None and (
                type(live.get("activity")) is not list or live["activity"]):
            raise OperatorHostDenied("OPERATOR_BUSY_OR_ACTIVITY_UNVERIFIED")
        if self._launch("bootout", self.target).returncode:
            raise OperatorHostDenied("OPERATOR_BOOTOUT_REJECTED")
        if not self._await_unregistered():
            raise OperatorHostDenied("OPERATOR_BOOTOUT_SETTLE_TIMEOUT")
        self._atomic_plist(self.candidate_definition)
        self._bootstrap_settled()

    def verify_rollback(self, scope):
        if super().verify_rollback(scope):
            return True
        # The original Operator was unresponsive before recovery. A rollback
        # to the exact original source + launchd/PID can be physically verified
        # even when that original API remains unavailable. This does NOT claim
        # restoration of API health or successful service-level recovery.
        return self._prior_physical_binding(scope)


def _operator_rows(home):
    """One bounded reader for all *existing* owner Operator release journals.

    No status is rewritten and no Guard store is created by this discovery.
    The only authority remains the existing Guard DB and the selected original
    CutoverRegistry file. Both request and apply use the same inventory.
    """
    guard_db, primary = cli._guard_path(home)
    siblings = list(islice(
        primary.parent.glob("operator-owner-main-release-*.json"),
        _MAX + 1))
    if len(siblings) > _MAX:
        raise RecoveryDenied("OPERATOR_LEDGER_INVENTORY_UNBOUNDED")
    if any(re.fullmatch(r"operator-owner-main-release-[0-9a-f]{20}\.json",
                        p.name) is None for p in siblings):
        raise RecoveryDenied("OPERATOR_LEDGER_NAME_UNTRUSTED")
    paths = ([primary] if primary.exists() or primary.is_symlink() else [])
    paths += sorted(siblings)
    rows = []
    for path in paths:
        try:
            doc = json.loads(cli._owner_file(path, limit=500000))
            if (type(doc) is not dict or type(doc.get("schema")) is not int
                    or doc["schema"] not in (1, 2)
                    or type(doc.get("paths")) is not dict):
                raise ValueError("invalid journal")
            row = doc["paths"].get(_OPERATOR)
            if row is None:
                continue
            if (type(row) is not dict or row.get("path") != _OPERATOR
                    or row.get("status") not in
                    ("PREPARED", "CUTOVER", "VERIFIED", "ROLLED_BACK")
                    or type(row.get("release_scope")) is not dict
                    or type(row.get("release_scope_ref")) is not str
                    or type(row.get("release_run_id")) is not str
                    or not _RUN.fullmatch(row["release_run_id"])
                    or type(row.get("release_request_ref")) is not str
                    or not _REF.fullmatch(row["release_request_ref"])
                    or type(row.get("release_canon_revision")) is not str
                    or not row["release_canon_revision"].startswith("canon-source/v1:")):
                raise ValueError("invalid operator release row")
            rows.append((path, row, doc["schema"]))
        except (OSError, ValueError, TypeError, KeyError):
            raise RecoveryDenied("OPERATOR_LEDGER_UNTRUSTED") from None
    return guard_db, rows


def _existing_operator_gate(home, scope, run_id, request_ref, *, readonly):
    """Find one exact PREPARED request; four unrelated ones stay historical."""
    guard_db, rows = _operator_rows(home)
    matches = []
    for path, row, schema in rows:
        if (row["release_run_id"] != run_id
                or row["release_request_ref"] != request_ref
                or row["release_scope_ref"] != scope.scope_ref):
            continue
        if (row["status"] != "PREPARED"
                or row["release_scope"] != scope.as_dict()
                or row.get("candidate_authority") != scope.candidate_authority):
            raise RecoveryDenied("OPERATOR_LEDGER_UNTRUSTED")
        if schema == 2:
            history = row.get("history")
            if (type(history) is not list or not history
                    or type(history[-1]) is not dict
                    or any(history[-1].get(k) != row.get(k)
                           for k in ("status", "release_scope_ref",
                                     "release_run_id", "release_request_ref",
                                     "release_scope", "generation"))):
                raise RecoveryDenied("OPERATOR_LEDGER_UNTRUSTED")
        matches.append(path)
    if len(matches) != 1:
        raise RecoveryDenied("EXACT_OPERATOR_JOURNAL_NOT_UNIQUE")
    store = (cli.ReadOnlyGuardStore(guard_db) if readonly
             else cli.SQLiteGuardStore(guard_db))
    return cli.GuardReleaseGate(store, matches[0])


def _operator_predecessor(home, scope, source):
    """Select a single physically loaded, previously VERIFIED Operator.

    Its HTTP endpoint may be stuck, but its original staged code, exact
    launchd definition, PID and TCP listener MUST match the VERIFIED journal.
    Never reclassify unrelated historical PREPARED entries as approved.
    """
    guard_db, rows = _operator_rows(home)
    host = UnresponsiveOperatorHost(source, home=home)
    matches = []
    for path, row, schema in rows:
        if row["status"] != "VERIFIED":
            continue
        if (row.get("candidate_authority") ==
                scope.candidate_authority
                or row.get("candidate_endpoint") != scope.previous_endpoint):
            continue
        record = SimpleNamespace(**row)
        identity = host.diagnose_current_release(record)
        if identity in ("VERIFIED", "RUNNING_OPERATOR_API_UNAVAILABLE"):
            # A pinned loaded source may legitimately have an unresponsive
            # HTTP event loop. Other, ambiguous identity states are rejected.
            matches.append((path, row))
    if len(matches) != 1:
        raise RecoveryDenied("VERIFIED_OPERATOR_PREDECESSOR_NOT_UNIQUE")
    path, row = matches[0]
    return guard_db, path, row["release_scope_ref"]


def _operator_request(head):
    source = _source(head)
    home = Path.home()
    scope = _operator_scope(source, head, home)
    canon = cli._release_canon(source)
    if canon.get("status") != "CANON_SOURCE_VERIFIED":
        raise RecoveryDenied("OPERATOR_CANON_SOURCE_UNVERIFIED")
    db, ledger, previous_ref = _operator_predecessor(home, scope, source)
    if not cli._tty_confirm(
            "New Operator recovery Guard request (NOT approval).\\n"
            "Immutable source " + head + "\\nScope " + scope.scope_ref,
            "REQUEST " + scope.scope_ref[:16]):
        raise RecoveryDenied("OWNER_TERMINAL_CONFIRMATION_REQUIRED")
    # Only after owner-local confirmation open the original Guard store for
    # a NEW request, and retain the unchanged VERIFIED predecessor evidence.
    gate = cli.GuardReleaseGate(cli.SQLiteGuardStore(db), ledger)
    receipt = gate.prepare(scope, canon_revision=canon["canon_revision"],
                           verified_predecessor_ref=previous_ref)
    if (receipt.get("status") != "WAITING_HUMAN"
            or receipt.get("ok") is not True
            or receipt.get("scope_ref") != scope.scope_ref):
        raise RecoveryDenied("OPERATOR_GUARD_REQUEST_NOT_ACCEPTED")
    return {"operator": "WAITING_HUMAN",
            "operator_scope_ref": scope.scope_ref,
            "operator_run_id": receipt["run_id"],
            "operator_request_ref": receipt["request_ref"],
            "operator_approved": False, "service_mutations": 0}


def _gateway_request(head):
    receipt = mobile.run(
        argparse.Namespace(operation="request", expected_head=head,
                           run_id=None, request_ref=None))
    if receipt.get("status") != "WAITING_HUMAN":
        raise RecoveryDenied("GATEWAY_GUARD_REQUEST_NOT_ACCEPTED")
    return {"gateway": "WAITING_HUMAN",
            "gateway_scope_ref": receipt["scope_ref"],
            "gateway_run_id": receipt["run_id"],
            "gateway_request_ref": receipt["request_ref"],
            "gateway_approved": False, "service_mutations": 0}


def _source(head):
    cli._owner_session()
    if type(head) is not str or not _SHA.fullmatch(head):
        raise RecoveryDenied("EXACT_SOURCE_SHA_REQUIRED")
    home = Path.home()
    staged = home / ".ai-foundation-tunnel-sources" / head
    return cli._owner_staged_source(head, home, staged)


def _operator_scope(source, head, home):
    """Validate both distinct immutable identities, never mix their digests.

    Operator's source_sha is the SHA-256 of the package+installed-state
    manifest (64 hex chars), NOT the 40-character Git commit. The canonical
    factory independently verifies the live config and committed package;
    candidate_authority must bind the supplied exact Git commit.
    """
    scope = cli._release_scope(source, head, home)
    if (scope.path != _OPERATOR
            or scope.candidate_authority != "github-commit:" + head
            or type(scope.source_sha) is not str
            or not _REF.fullmatch(scope.source_sha)):
        raise RecoveryDenied("OPERATOR_SCOPE_NOT_SOURCE_BOUND")
    return scope


def _approved_operator(head, run_id, request_ref):
    if (type(run_id) is not str or not _RUN.fullmatch(run_id)
            or type(request_ref) is not str or not _REF.fullmatch(request_ref)):
        raise RecoveryDenied("EXACT_OPERATOR_RUN_REF_REQUIRED")
    source = _source(head)
    home = Path.home()
    scope = _operator_scope(source, head, home)
    gate = _existing_operator_gate(
        home, scope, run_id, request_ref, readonly=True)
    record = gate.registry.get(_OPERATOR)
    canon = cli._release_canon(source)
    if (record is None or record.status != "PREPARED"
            or record.release_scope_ref != scope.scope_ref
            or record.release_run_id != run_id
            or record.release_request_ref != request_ref
            or canon.get("status") != "CANON_SOURCE_VERIFIED"
            or canon.get("canon_revision") != record.release_canon_revision):
        raise RecoveryDenied("OPERATOR_CANON_OR_JOURNAL_CHANGED")
    verified = gate.verify(scope, run_id, request_ref)
    if (verified.get("status") != "APPROVED" or
            verified.get("ok") is not True or
            verified.get("approved") is not True or
            verified.get("scope_ref") != scope.scope_ref):
        raise RecoveryDenied("EXACT_OPERATOR_GUARD_APPROVAL_REQUIRED")
    return ApprovedOperator(
        scope, gate, UnresponsiveOperatorHost(source, home=home),
        run_id, request_ref)


def _operator_cutover(head, run_id, request_ref):
    auth = _approved_operator(head, run_id, request_ref)
    # The writable journal uses the same preverified exact existing file and
    # Guard DB, but no metadata has been written until the transaction starts.
    gate = _existing_operator_gate(
        Path.home(), auth.scope, run_id, request_ref, readonly=False)
    owner_gate = cli.InteractiveOwnerGate(
        auth.scope, run_id, request_ref, confirmer=cli._tty_confirm)
    result = OperatorOnlyCutover(gate, auth.host, owner_gate).execute(
        auth.scope, run_id, request_ref)
    if (result.status != "VERIFIED" or
            result.scope_ref != auth.scope.scope_ref or
            result.guard_approved is not True):
        raise RecoveryDenied("OPERATOR_CUTOVER_READBACK_UNVERIFIED")
    return {"operator": "VERIFIED", "operator_scope_ref": auth.scope.scope_ref}


def _exact_pending_for_owner(head, service, run_id, request_ref, source, home):
    """Original Guard request, authenticated M1 owner and exact current scope.

    A terminal confirmation does not invent authority. The actual Guard
    action remains OperatorActions.approve_pending's atomic CAS on the
    original Guard store, identical to the authenticated Operator UI's
    decision action. Neither GitHub nor this program can auto-approve.
    """
    if (type(run_id) is not str or not _RUN.fullmatch(run_id)
            or type(request_ref) is not str or not _REF.fullmatch(request_ref)):
        raise RecoveryDenied("EXACT_OWNER_GUARD_RUN_REF_REQUIRED")
    if service == "operator":
        scope = _operator_scope(source, head, home)
        gate = _existing_operator_gate(
            home, scope, run_id, request_ref, readonly=True)
        path = _OPERATOR
    elif service == "gateway":
        scope = mobile._context(head).scope
        gate = mobile._gateway_gate(home, readonly=True)
        path = mobile._PATH
    else:
        raise RecoveryDenied("UNKNOWN_GUARD_DECISION_SERVICE")
    record = gate.registry.get(path)
    if (record is None or record.status != "PREPARED"
            or record.release_run_id != run_id
            or record.release_request_ref != request_ref
            or record.release_scope_ref != scope.scope_ref
            or record.release_scope != scope.as_dict()
            or record.candidate_authority != "github-commit:" + head):
        raise RecoveryDenied("EXACT_PENDING_OWNER_RELEASE_REQUIRED")
    canon = cli._release_canon(source)
    if (canon.get("status") != "CANON_SOURCE_VERIFIED"
            or canon.get("canon_revision") != record.release_canon_revision):
        raise RecoveryDenied("PENDING_OWNER_CANON_CHANGED")
    pending = gate.verify(scope, run_id, request_ref, require_approved=False)
    if (pending.get("ok") is not True
            or pending.get("status") != "PENDING"
            or pending.get("approved") is not False
            or pending.get("scope_ref") != scope.scope_ref):
        raise RecoveryDenied("EXACT_PENDING_GUARD_DECISION_REQUIRED")
    return (service, scope, run_id, request_ref, gate)


def _owner_guard_decisions(head, selected, args):
    """Owner TTY makes BOTH explicit decisions before ANY Guard write.

    This is an emergency local presentation of the existing Guard decision
    action while both previously installed HTTP UIs are unavailable. It
    adds no approval DB, delegation, privilege, or unsolicited automation.
    """
    source = _source(head)
    home = Path.home()
    guard_db, _ = cli._guard_path(home)
    entries = []
    if selected in ("operator", "both"):
        entries.append(_exact_pending_for_owner(
            head, "operator", args.operator_run_id,
            args.operator_request_ref, source, home))
    if selected in ("gateway", "both"):
        entries.append(_exact_pending_for_owner(
            head, "gateway", args.gateway_run_id,
            args.gateway_request_ref, source, home))
    # Review the two independent immutable scopes, with distinct explicit
    # typed consent, BEFORE the first durable decision is written.
    for service, scope, run_id, request_ref, gate in entries:
        prompt = ("Authorize current EXISTING Guard production_deploy request.\n"
                  "Service: " + service + "\nGit candidate: " + head +
                  "\nScope: " + scope.scope_ref + "\nRun: " + run_id +
                  "\nRequest: " + request_ref +
                  "\nThis approves the exact Guard request but does NOT "
                  "restart or install services.")
        if not cli._tty_confirm(
                prompt, "AUTHORIZE " + scope.scope_ref[:16]):
            raise RecoveryDenied("OWNER_TERMINAL_CONFIRMATION_REQUIRED")
    store = cli.SQLiteGuardStore(guard_db)
    actions = OperatorActions(GuardCore(store.runtime_state(), store=store))
    decisions = {"status": "GUARD_PARTIAL_APPROVAL", "source_sha": head,
                 "operator": "NOT_REQUESTED", "gateway": "NOT_REQUESTED",
                 "service_mutations": 0}
    for service, scope, run_id, request_ref, gate in entries:
        try:
            result = actions.approve_pending(run_id, request_ref)
            if result.ok is not True or result.status != "APPROVED":
                decisions[service] = "UNVERIFIED"
                return decisions
            verified = gate.verify(scope, run_id, request_ref)
            if (verified.get("ok") is not True
                    or verified.get("status") != "APPROVED"
                    or verified.get("approved") is not True
                    or verified.get("scope_ref") != scope.scope_ref):
                decisions[service] = "UNVERIFIED"
                return decisions
            decisions[service] = "APPROVED"
        except (OSError, ValueError, RuntimeError, KeyError, TypeError):
            decisions[service] = "UNVERIFIED"
            return decisions
    decisions["status"] = "GUARD_APPROVED"
    return decisions


def _gateway_authorized(head, run_id, request_ref):
    if (type(run_id) is not str or not _RUN.fullmatch(run_id)
            or type(request_ref) is not str or not _REF.fullmatch(request_ref)):
        raise RecoveryDenied("EXACT_GATEWAY_RUN_REF_REQUIRED")
    ctx = mobile._context(head)
    mobile._approved_gate(ctx, run_id, request_ref)
    return ctx


def _gateway_cutover(head, run_id, request_ref):
    _gateway_authorized(head, run_id, request_ref)
    receipt = mobile.run(
        argparse.Namespace(operation="apply", expected_head=head,
                           run_id=run_id, request_ref=request_ref))
    if receipt.get("status") != "VERIFIED":
        raise RecoveryDenied("GATEWAY_CUTOVER_READBACK_UNVERIFIED")
    return {"gateway": "VERIFIED",
            "gateway_scope_ref": receipt["scope_ref"],
            "gateway_upstream": receipt["operator_upstream"],
            "mobile_owner_post": "NOT_VERIFIED"}


def run(args):
    """Run the original exact Guard transactions, never use implied approval.

    Gateway-only and Operator-only modes keep the other installed service.
    Every Operator cutover requires a *fresh* Gateway->Operator verification
    after the Operator effect; the prior Gateway-first result is not enough.
    """
    head = args.expected_head
    _source(head)
    if args.operation == "inspect":
        return {"status": "STAGED_SOURCE_OBSERVED_NO_EFFECT",
                "candidate_sha": head, "operator": "NOT_AUTHORIZED",
                "gateway": "NOT_AUTHORIZED", "release_permitted": False,
                "guard_writes": 0, "service_mutations": 0}
    selected = args.service
    if selected not in ("operator", "gateway", "both"):
        raise RecoveryDenied("RECOVERY_SERVICE_INVALID")
    if args.operation == "request":
        if any((args.operator_run_id, args.operator_request_ref,
                args.gateway_run_id, args.gateway_request_ref)):
            raise RecoveryDenied("REQUEST_CANNOT_REUSE_GUARD_APPROVAL")
        requests = {"status": "OWNER_GUARD_REQUESTS_INCOMPLETE",
                    "source_sha": head, "operator": "NOT_REQUESTED",
                    "gateway": "NOT_REQUESTED", "service_mutations": 0}
        if selected in ("operator", "both"):
            requests.update(_operator_request(head))
        if selected in ("gateway", "both"):
            try:
                requests.update(_gateway_request(head))
            except Exception:
                if requests["operator"] == "WAITING_HUMAN":
                    requests["gateway"] = "UNVERIFIED"
                    requests["status"] = "OPERATOR_REQUESTED_GATEWAY_UNVERIFIED"
                    return requests
                raise
        requests["status"] = "WAITING_HUMAN"
        return requests
    if args.operation == "approve":
        return _owner_guard_decisions(head, selected, args)

    # Complete all exact original Guard verification BEFORE any effect.
    if selected in ("operator", "both"):
        _approved_operator(head, args.operator_run_id,
                           args.operator_request_ref)
    if selected in ("gateway", "both"):
        _gateway_authorized(head, args.gateway_run_id,
                            args.gateway_request_ref)
    result = {"status": "RECOVERY_INCOMPLETE", "source_sha": head,
              "operator": "NOT_REQUESTED", "gateway": "NOT_REQUESTED"}
    if selected in ("gateway", "both"):
        result.update(_gateway_cutover(
            head, args.gateway_run_id, args.gateway_request_ref))
    if selected in ("operator", "both"):
        try:
            result.update(_operator_cutover(
                head, args.operator_run_id, args.operator_request_ref))
        except Exception:
            # A failed Operator cutover cannot be replayed or greened from
            # another service's prior receipt. Leave the existing journal
            # authoritative and preserve an already VERIFIED Gateway.
            if result["gateway"] == "VERIFIED":
                result["operator"] = "UNVERIFIED"
                result["status"] = "GATEWAY_VERIFIED_OPERATOR_UNVERIFIED"
                result["mobile_owner_post"] = "NOT_VERIFIED"
                return result
            raise

        # The NEW Operator must serve the currently installed Gateway. In a
        # one-unit Operator replacement, Gateway is not restarted or reapproved.
        # An HTTP 200 seen before cutover is never substituted here.
        if selected == "both":
            result["gateway_upstream_at_cutover"] = result.get(
                "gateway_upstream", "UNVERIFIED")
        try:
            upstream = mobile._gateway_transport_state()
        except (OSError, ValueError, RuntimeError):
            upstream = None
        result["gateway_upstream"] = (
            upstream if upstream in ("OPERATOR_READY",
                                    "OPERATOR_UNAVAILABLE")
            else "UNVERIFIED")
        if upstream != "OPERATOR_READY":
            result["status"] = (
                "GATEWAY_AND_OPERATOR_VERIFIED_UPSTREAM_UNVERIFIED"
                if selected == "both"
                else "OPERATOR_VERIFIED_GATEWAY_UPSTREAM_UNVERIFIED")
            result["mobile_owner_post"] = "NOT_VERIFIED"
            return result

    result["status"] = (
        "GATEWAY_AND_OPERATOR_VERIFIED" if selected == "both"
        else "GATEWAY_VERIFIED" if selected == "gateway"
        else "OPERATOR_VERIFIED")
    result["mobile_owner_post"] = "NOT_VERIFIED"
    return result


def recover_once(args):
    """Single authenticated owner TTY, independently Guarded one-shot release.

    Operator-only replacement is for a source-verified incumbent that is
    independently proved quiescent or unresponsive by the original host. It
    never restarts the mobile Gateway; no owner input can forge a Guard grant.
    """
    selected = args.service
    if selected not in ("operator", "gateway", "both"):
        raise RecoveryDenied("RECOVERY_SERVICE_INVALID")
    if any((args.operator_run_id, args.operator_request_ref,
            args.gateway_run_id, args.gateway_request_ref)):
        raise RecoveryDenied("RECOVERY_CANNOT_REUSE_OLD_REQUESTS")
    def stage(operation, **fields):
        return run(argparse.Namespace(**{**vars(args), **fields,
                                         "operation": operation}))
    request = stage("request")
    services = ("operator", "gateway") if selected == "both" else (selected,)
    unselected = set(("operator", "gateway")) - set(services)
    if (request.get("status") != "WAITING_HUMAN"
            or request.get("source_sha") != args.expected_head
            or request.get("service_mutations") != 0
            or any(request.get(service) != "WAITING_HUMAN"
                   or request.get(service + "_approved") is not False
                   for service in services)
            or any(request.get(service) != "NOT_REQUESTED"
                   for service in unselected)):
        return {**request, "status": "RECOVERY_REQUEST_INCOMPLETE"}
    ids = {}
    scopes = []
    for service in services:
        run_id = request.get(service + "_run_id")
        request_ref = request.get(service + "_request_ref")
        scope_ref = request.get(service + "_scope_ref")
        if (type(run_id) is not str or not _RUN.fullmatch(run_id)
                or type(request_ref) is not str or not _REF.fullmatch(request_ref)
                or type(scope_ref) is not str or not _REF.fullmatch(scope_ref)):
            return {"status": "RECOVERY_REQUEST_REF_UNVERIFIED",
                    "source_sha": args.expected_head, "service_mutations": 0}
        scopes.append(scope_ref)
        ids[service + "_run_id"] = run_id
        ids[service + "_request_ref"] = request_ref
    if len(set(scopes)) != len(scopes):
        return {"status": "RECOVERY_SCOPE_COLLISION",
                "source_sha": args.expected_head, "service_mutations": 0}
    approved = stage("approve", **ids)
    if (approved.get("status") != "GUARD_APPROVED"
            or approved.get("source_sha") != args.expected_head
            or approved.get("service_mutations") != 0
            or any(approved.get(service) != "APPROVED"
                   for service in services)
            or any(approved.get(service) != "NOT_REQUESTED"
                   for service in unselected)):
        return {**approved, "status": "RECOVERY_APPROVAL_INCOMPLETE"}

    result = stage("apply", **ids)
    expected_status = {
        "operator": "OPERATOR_VERIFIED",
        "gateway": "GATEWAY_VERIFIED",
        "both": "GATEWAY_AND_OPERATOR_VERIFIED",
    }[selected]
    if (result.get("status") != expected_status
            or result.get("source_sha") != args.expected_head
            or result.get("gateway_upstream") != "OPERATOR_READY"
            or result.get("mobile_owner_post") != "NOT_VERIFIED"
            or any(result.get(service) != "VERIFIED" for service in services)
            or any(result.get(service) != "NOT_REQUESTED"
                   for service in unselected)):
        return {**result, "status": "RECOVERY_NOT_FULLY_VERIFIED"}
    return result


def main(argv=None):
    """Fail closed for incomplete Operator/Gateway independent readback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=(
        "inspect", "request", "approve", "apply", "recover"))
    parser.add_argument("--service", choices=("operator", "gateway", "both"),
                        default="both")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--operator-run-id")
    parser.add_argument("--operator-request-ref")
    parser.add_argument("--gateway-run-id")
    parser.add_argument("--gateway-request-ref")
    args = parser.parse_args(argv)
    if args.operation == "inspect" and any((
            args.operator_run_id, args.operator_request_ref,
            args.gateway_run_id, args.gateway_request_ref)):
        parser.error("inspect cannot consume Guard authorization")
    try:
        result = recover_once(args) if args.operation == "recover" else run(args)
        print(json.dumps(result, sort_keys=True), flush=True)
        expected_by_service = {
            "operator": "OPERATOR_VERIFIED",
            "gateway": "GATEWAY_VERIFIED",
            "both": "GATEWAY_AND_OPERATOR_VERIFIED",
        }
        allowed = {
            "inspect": frozenset({"STAGED_SOURCE_OBSERVED_NO_EFFECT"}),
            "request": frozenset({"WAITING_HUMAN"}),
            "approve": frozenset({"GUARD_APPROVED"}),
            "apply": frozenset(expected_by_service.values()),
            "recover": frozenset({expected_by_service[args.service]}),
        }
        if result.get("status") not in allowed[args.operation]:
            return 3
        if args.operation in ("apply", "recover"):
            if args.service in ("operator", "both") and (
                    result.get("operator") != "VERIFIED"
                    or result.get("gateway_upstream") != "OPERATOR_READY"):
                return 3
            if args.service in ("gateway", "both") and (
                    result.get("gateway") != "VERIFIED"
                    or result.get("gateway_upstream") != "OPERATOR_READY"):
                return 3
            if args.operation == "recover":
                other = {"operator": "gateway", "gateway": "operator"}.get(
                    args.service)
                if (other is not None
                        and result.get(other) != "NOT_REQUESTED"):
                    return 3
                if result.get("mobile_owner_post") != "NOT_VERIFIED":
                    return 3
        return 0
    except (RecoveryDenied, cli.OwnerReleaseDenied,
            OperatorHostDenied, mobile.GatewaySuccessorDenied,
            OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        reason = (str(exc) if type(exc) is RecoveryDenied
                  else "OWNER_PRODUCTION_RECOVERY_NOT_VERIFIED")
        print(json.dumps({"status": "BLOCKED", "reason": reason}, sort_keys=True),
              flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
