#!/usr/bin/env python3
"""Owner-local successor release for the already-installed remote Gateway.

A single, bounded Gateway replacement transaction. Existing Canon, Guard,
release registry, private owner TTY, launchd and rollback primitives remain
authoritative. Neither GitHub CI nor this program can approve on behalf of
the owner. The one-time bootstrap is NEVER replayed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import http.client
from itertools import islice
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time

from ai_foundation.release_gate import ImmutableReleaseScope
from scripts import m1_mobile_gateway_bootstrap as gateway
from scripts import m1_operator_release_cli as owner

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_REF = re.compile(r"[0-9a-f]{64}\Z")
_RUN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_PATH = "m1-remote-gateway"
_ENDPOINT = "https://127.0.0.1:8793/mobile-owner"
_MAX_LEDGERS = 512
_STATUSES = frozenset(("PREPARED", "CUTOVER", "VERIFIED", "ROLLED_BACK"))


class GatewaySuccessorDenied(RuntimeError):
    """Safe fixed-code denial. Never include owner file paths or secrets."""


@dataclass(frozen=True)
class ReleaseContext:
    scope: ImmutableReleaseScope
    predecessor_ref: str | None
    plist: Path
    previous_bytes: bytes
    candidate_bytes: bytes
    previous_mode: int
    source: Path


def _gateway_transport_state():
    """Accept only the installed Gateway's *exact* bounded TLS health contract.

    A known 503 means the separate Operator upstream is unavailable; it does
    not mean the Gateway listener itself is unusable. Some installed versions
    append literal backslash-n, rather than a real newline, to their JSON.
    Neither variant grants approval or proves a physical Android POST.
    """
    connection = http.client.HTTPSConnection(
        "127.0.0.1", gateway.PORT, timeout=4,
        context=ssl._create_unverified_context())
    try:
        connection.request("GET", "/health", headers={"Host": "127.0.0.1"})
        response = connection.getresponse()
        body = response.read(129)
        if len(body) > 128:
            return None
        body = body.rstrip(b"\r\n")
        if body.endswith(b"\n".replace(b"\n", b"\\n")):
            body = body[:-2]
        if response.status == 200 and body == b'{"ok":true,"upstream":true}':
            return "OPERATOR_READY"
        if response.status == 503 and body == b'{"ok":false,"upstream":false}':
            return "OPERATOR_UNAVAILABLE"
        return None
    except (OSError, ValueError, http.client.HTTPException, ssl.SSLError):
        return None
    finally:
        connection.close()


def _gateway_transport_readback(plist, expected, *, strict_local):
    """Read back exact on-disk definition, current launchd PID, socket and TLS."""
    if plist.read_bytes() != expected:
        return None
    for attempt in range(40):
        pid = gateway._running()
        if pid is not None and gateway._port_owned(pid, strict_local=strict_local):
            live = _gateway_transport_state()
            if live is not None:
                return live
        if attempt != 39:
            time.sleep(.5)
    return None


def _validate_gateway_row(doc):
    """Validate the one historical Gateway record without reconciling Operator."""
    if (type(doc) is not dict or type(doc.get("schema")) is not int
            or doc["schema"] not in (1, 2)
            or type(doc.get("paths")) is not dict):
        raise GatewaySuccessorDenied("GATEWAY_LEDGER_UNTRUSTED")
    row = doc["paths"].get(_PATH)
    if row is None:
        return False
    if (type(row) is not dict or row.get("path") != _PATH
            or row.get("status") not in _STATUSES
            or type(row.get("release_scope")) is not dict
            or type(row.get("release_scope_ref")) is not str
            or type(row.get("release_run_id")) is not str
            or not _RUN.fullmatch(row["release_run_id"])
            or type(row.get("release_request_ref")) is not str
            or not _REF.fullmatch(row["release_request_ref"])
            or type(row.get("release_canon_revision")) is not str
            or not row["release_canon_revision"].startswith("canon-source/v1:")):
        raise GatewaySuccessorDenied("GATEWAY_LEDGER_UNTRUSTED")
    try:
        scope = ImmutableReleaseScope(**row["release_scope"])
    except (ValueError, TypeError, KeyError):
        raise GatewaySuccessorDenied("GATEWAY_LEDGER_UNTRUSTED") from None
    if (scope.path != _PATH or scope.scope_ref != row["release_scope_ref"]
            or scope.candidate_authority != row.get("candidate_authority")
            or scope.candidate_endpoint != row.get("candidate_endpoint")):
        raise GatewaySuccessorDenied("GATEWAY_LEDGER_UNTRUSTED")
    if doc["schema"] == 2:
        history = row.get("history")
        keys = ("status", "release_scope_ref", "release_run_id",
                "release_request_ref", "candidate_authority", "generation")
        if (type(history) is not list or not history
                or type(history[-1]) is not dict
                or any(history[-1].get(k) != row.get(k) for k in keys)):
            raise GatewaySuccessorDenied("GATEWAY_LEDGER_UNTRUSTED")
    return True


def _gateway_gate(home, *, readonly=False):
    """Reuse the single existing Gateway journal and original Guard database.

    The four historical Operator PREPARED journals are not Gateway requests.
    Reject missing, duplicate, untrusted or oversized inventories, without
    creating a replacement authority store or silently changing history.
    """
    guard_db, primary = owner._guard_path(home)
    siblings = list(islice(
        primary.parent.glob("operator-owner-main-release-*.json"),
        _MAX_LEDGERS + 1))
    if len(siblings) > _MAX_LEDGERS:
        raise GatewaySuccessorDenied("GATEWAY_LEDGER_INVENTORY_UNBOUNDED")
    if any(re.fullmatch(r"operator-owner-main-release-[0-9a-f]{20}\.json",
                        path.name) is None for path in siblings):
        raise GatewaySuccessorDenied("GATEWAY_LEDGER_NAME_UNTRUSTED")
    paths = ([primary] if primary.exists() or primary.is_symlink() else [])
    paths += sorted(siblings)
    matches = []
    for path in paths:
        try:
            doc = json.loads(owner._owner_file(path, limit=500000))
            if _validate_gateway_row(doc):
                matches.append(path)
        except (OSError, ValueError, TypeError, KeyError):
            raise GatewaySuccessorDenied("GATEWAY_LEDGER_UNTRUSTED") from None
    if len(matches) != 1:
        raise GatewaySuccessorDenied(
            "GATEWAY_LEDGER_NOT_UNIQUELY_BOUND" if matches
            else "EXISTING_GATEWAY_LEDGER_NOT_FOUND")
    store = (owner.ReadOnlyGuardStore(guard_db) if readonly
             else owner.SQLiteGuardStore(guard_db))
    return owner.GuardReleaseGate(store, matches[0])


def _context(head, *, observe_only=False):
    """Pin source, actual installed Gateway definition and exact old authority."""
    owner._owner_session()
    if type(head) is not str or not _SHA.fullmatch(head):
        raise GatewaySuccessorDenied("PINNED_SOURCE_REQUIRED")
    root = Path.home() / ".ai-foundation-tunnel-sources"
    source = root / head
    if gateway._commit(source) != head:
        raise GatewaySuccessorDenied("STAGED_SOURCE_UNVERIFIED")
    plist, previous, installed, mode = gateway._owned_plist()
    pid = gateway._running()
    if pid is None or not gateway._port_owned(pid, strict_local=True):
        raise GatewaySuccessorDenied("CURRENT_GATEWAY_PID_NOT_BOUND")
    if not observe_only and _gateway_transport_state() is None:
        raise GatewaySuccessorDenied("CURRENT_GATEWAY_TRANSPORT_UNVERIFIED")
    installed_dir = installed.get("WorkingDirectory")
    if type(installed_dir) is not str:
        raise GatewaySuccessorDenied("INSTALLED_SOURCE_UNBOUND")
    predecessor = Path(installed_dir)
    if (root.is_symlink() or predecessor.parent != root
            or not _SHA.fullmatch(predecessor.name)
            or predecessor.is_symlink() or not predecessor.is_dir()):
        raise GatewaySuccessorDenied("INSTALLED_SOURCE_UNTRUSTED")
    if predecessor.name == head:
        raise GatewaySuccessorDenied("CANDIDATE_ALREADY_INSTALLED")
    candidate = gateway._candidate_plist(installed, source)
    if candidate == previous:
        raise GatewaySuccessorDenied("NO_GATEWAY_CHANGE")
    predecessor_ref = None
    old_endpoint = "https://127.0.0.1:8793"
    pending_ref = None
    record = None
    if not observe_only:
        record = _gateway_gate(Path.home(), readonly=True).registry.get(_PATH)
        if record is not None:
            if record.status == "VERIFIED":
                if (record.candidate_authority !=
                        "github-commit:" + predecessor.name
                        or record.candidate_endpoint != _ENDPOINT):
                    raise GatewaySuccessorDenied("PREDECESSOR_NOT_MATCHED")
                predecessor_ref = record.release_scope_ref
                old_endpoint = record.candidate_endpoint
            elif record.status == "PREPARED":
                # The *same* release was already requested. Applying it must
                # not be mistaken for a second unreconciled release. Derive
                # the previous endpoint only from its exact existing scope;
                # never accept a new candidate/old source under a pending ref.
                if (type(record.release_scope) is not dict or
                        type(record.release_scope_ref) is not str):
                    raise GatewaySuccessorDenied("PENDING_GATEWAY_SCOPE_UNTRUSTED")
                try:
                    pending_scope = ImmutableReleaseScope(**record.release_scope)
                except (ValueError, TypeError, KeyError):
                    raise GatewaySuccessorDenied(
                        "PENDING_GATEWAY_SCOPE_UNTRUSTED") from None
                if (pending_scope.path != _PATH or
                        pending_scope.source_sha != head or
                        pending_scope.candidate_authority != "github-commit:" + head or
                        pending_scope.candidate_endpoint != _ENDPOINT or
                        pending_scope.scope_ref != record.release_scope_ref):
                    raise GatewaySuccessorDenied("PENDING_GATEWAY_SCOPE_CHANGED")
                old_endpoint = pending_scope.previous_endpoint
                pending_ref = pending_scope.scope_ref
            elif record.status != "ROLLED_BACK":
                raise GatewaySuccessorDenied("PREVIOUS_GATEWAY_RELEASE_UNRECONCILED")
    scope = ImmutableReleaseScope(
        path=_PATH, source_sha=head,
        previous_authority=("launchd:" + gateway.LABEL + ":sha256:" +
                            hashlib.sha256(previous).hexdigest()),
        previous_endpoint=old_endpoint,
        candidate_authority="github-commit:" + head,
        candidate_endpoint=_ENDPOINT,
        rollback_procedure="RESTORE_EXACT_PREVIOUS_GATEWAY_LAUNCHAGENT_AND_PID_READBACK",
        switch_target=gateway.LABEL,
        readback_target="PID_BOUND_127.0.0.1_8793",
        rollback_readback_target="PRIOR_PLIST_AND_8793_HEALTH",
    )
    if pending_ref is not None and scope.scope_ref != pending_ref:
        raise GatewaySuccessorDenied("PENDING_GATEWAY_SCOPE_CHANGED")
    return ReleaseContext(scope, predecessor_ref, plist, previous,
                          candidate, mode, source)


def _request(ctx, head):
    canon = owner._release_canon(ctx.source)
    if canon.get("status") != "CANON_SOURCE_VERIFIED":
        raise GatewaySuccessorDenied("CANON_SOURCE_UNVERIFIED")
    if not owner._tty_confirm(
            "New Gateway-only Guard request (NOT approval).\n"
            "Commit " + head + "\nScope " + ctx.scope.scope_ref,
            "REQUEST " + ctx.scope.scope_ref[:16]):
        raise GatewaySuccessorDenied("OWNER_TERMINAL_CONFIRMATION_REQUIRED")
    result = _gateway_gate(Path.home()).prepare(
        ctx.scope, canon_revision=canon["canon_revision"],
        verified_predecessor_ref=ctx.predecessor_ref)
    if (result.get("status") != "WAITING_HUMAN" or
            result.get("ok") is not True or
            result.get("scope_ref") != ctx.scope.scope_ref):
        raise GatewaySuccessorDenied("GUARD_REQUEST_NOT_ACCEPTED")
    return {"status": "WAITING_HUMAN", "scope_ref": ctx.scope.scope_ref,
            "run_id": result["run_id"], "request_ref": result["request_ref"],
            "approved": False, "service_mutations": 0}


def _approved_gate(ctx, run_id, request_ref):
    if (type(run_id) is not str or not _RUN.fullmatch(run_id)
            or type(request_ref) is not str or not _REF.fullmatch(request_ref)):
        raise GatewaySuccessorDenied("EXACT_GUARD_RUN_REF_REQUIRED")
    gate = _gateway_gate(Path.home(), readonly=True)
    record = gate.registry.get(_PATH)
    if (record is None or record.status != "PREPARED"
            or record.release_scope_ref != ctx.scope.scope_ref
            or record.release_run_id != run_id
            or record.release_request_ref != request_ref):
        raise GatewaySuccessorDenied("EXACT_PREPARED_RELEASE_REQUIRED")
    canon = owner._release_canon(ctx.source)
    if (canon.get("status") != "CANON_SOURCE_VERIFIED"
            or canon["canon_revision"] != record.release_canon_revision):
        raise GatewaySuccessorDenied("CANON_CHANGED")
    proof = gate.verify(ctx.scope, run_id, request_ref)
    if (proof.get("status") != "APPROVED" or
            proof.get("approved") is not True or
            proof.get("scope_ref") != ctx.scope.scope_ref):
        raise GatewaySuccessorDenied("EXACT_OWNER_GUARD_APPROVAL_REQUIRED")
    return gate


def _apply(ctx, head, run_id, request_ref):
    _approved_gate(ctx, run_id, request_ref)
    if not owner._tty_confirm(
            "Apply EXACT owner-approved Gateway-only replacement.\n"
            "Scope " + ctx.scope.scope_ref,
            "APPLY " + ctx.scope.scope_ref[:16]):
        raise GatewaySuccessorDenied("OWNER_TERMINAL_CONFIRMATION_REQUIRED")
    if (gateway._owned_plist()[1] != ctx.previous_bytes
            or gateway._commit(ctx.source) != head
            or _gateway_transport_state() is None):
        raise GatewaySuccessorDenied("GATEWAY_CHANGED_BEFORE_CUTOVER")
    _approved_gate(ctx, run_id, request_ref)
    gateway._backup(Path.home(), ctx.previous_bytes, ctx.scope.scope_ref[:16])
    # In-flight Guard approval can be revoked: recheck at the effect edge.
    if (gateway._owned_plist()[1] != ctx.previous_bytes
            or gateway._commit(ctx.source) != head
            or _gateway_transport_state() is None):
        raise GatewaySuccessorDenied("GATEWAY_CHANGED_BEFORE_CUTOVER")
    _approved_gate(ctx, run_id, request_ref)
    writer = _gateway_gate(Path.home())
    writer.registry.transition(_PATH, "PREPARED", "CUTOVER")
    try:
        gateway._stop_and_start(ctx.plist, ctx.candidate_bytes, ctx.previous_mode)
        upstream = _gateway_transport_readback(
            ctx.plist, ctx.candidate_bytes, strict_local=True)
        if upstream is None:
            raise GatewaySuccessorDenied("NEW_GATEWAY_TRANSPORT_READBACK_FAILED")
        writer.registry.transition(_PATH, "CUTOVER", "VERIFIED")
    except BaseException:
        try:
            gateway._stop_and_start(ctx.plist, ctx.previous_bytes,
                                    ctx.previous_mode)
            if _gateway_transport_readback(
                    ctx.plist, ctx.previous_bytes, strict_local=True) is None:
                raise GatewaySuccessorDenied("ROLLBACK_TRANSPORT_READBACK_FAILED")
            writer.registry.transition(_PATH, "CUTOVER", "ROLLED_BACK")
        except BaseException as exc:
            raise GatewaySuccessorDenied("MANUAL_RECOVERY_REQUIRED") from exc
        raise
    return {"status": "VERIFIED", "scope_ref": ctx.scope.scope_ref,
            "gateway_only": True, "operator_unchanged": True,
            "operator_upstream": upstream, "mobile_owner_post": "NOT_VERIFIED"}


def run(args):
    inspect = args.operation == "inspect"
    ctx = _context(args.expected_head, observe_only=inspect)
    if inspect:
        # Without an authenticated Guard read this is only source inspection.
        return {"status": "GATEWAY_SOURCE_OBSERVED_NO_EFFECT",
                "candidate_sha": args.expected_head,
                "gateway_launchd_and_pid_bound": True,
                "gateway_http": "NOT_CHECKED", "guard_registry": "NOT_CHECKED",
                "release_permitted": False, "guard_writes": 0,
                "service_mutations": 0}
    if args.operation == "request":
        return _request(ctx, args.expected_head)
    if args.operation == "apply":
        return _apply(ctx, args.expected_head, args.run_id, args.request_ref)
    raise GatewaySuccessorDenied("UNKNOWN_GATEWAY_OPERATION")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "request", "apply"))
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--request-ref")
    args = parser.parse_args(argv)
    if args.operation != "apply" and (args.run_id or args.request_ref):
        parser.error("run/ref only valid for apply")
    try:
        result = run(args)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except (GatewaySuccessorDenied, gateway.BootstrapDenied,
            owner.OwnerReleaseDenied, OSError, ValueError,
            TypeError, KeyError, RuntimeError) as exc:
        reason = (str(exc) if type(exc) is GatewaySuccessorDenied else
                  str(exc) if type(exc) is gateway.BootstrapDenied else
                  "OWNER_GATEWAY_PREREQUISITE_UNVERIFIED")
        print(json.dumps({"status": "BLOCKED", "reason": reason}, sort_keys=True),
              flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
