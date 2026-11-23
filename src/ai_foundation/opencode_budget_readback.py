"""Read-only OpenCode budget observation from a signed-in local OpenCode server.

Official OpenCode 2 endpoint GET /api/experimental/usage/limits returns a
workspace plus its effective Console budgets for the active location. This
module only summarizes a host-supplied observation; it never reads credentials,
starts a CLI, changes policies, uses model inference or authorizes a release.

A qualified workspace-wide shared all-spend zero-dollar limit is one part of
the no-charge contract. The separate Console Billing / Go / auth / Guard
requirements are NOT inferred from this observation.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import PurePosixPath
from urllib.parse import urlencode
import urllib.request

_MAX_BYTES = 65536
_WORKSPACE_ID = re.compile(r"[A-Za-z0-9_-]{2,160}\Z")


def summarize_workspace_budget(raw, *, expected_workspace_id,
                               expected_location_directory):
    """Interpret OpenCode's local API body without trusting a synthetic attestation.

    A caller must independently attest the read came from its authenticated,
    owner-selected local OpenCode instance; this parser never issues such an
    attestation and cannot grant external inference or Operator release.
    """
    status = {"status": "HOLD_UNVERIFIED",
              "workspace_zero_budget_observed": False,
              "account_independently_attested": False,
              "auto_recharge_verified": False,
              "go_extra_usage_verified": False,
              "execution_authorized": False}
    if (type(raw) is not bytes or not 0 < len(raw) <= _MAX_BYTES
            or type(expected_workspace_id) is not str
            or _WORKSPACE_ID.fullmatch(expected_workspace_id) is None
            or not _pinned_location(expected_location_directory)):
        return {**status, "reason": "UNTRUSTED_LOCAL_RESPONSE"}
    try:
        def unique(pairs):
            d = {}
            for k, v in pairs:
                if k in d:
                    raise ValueError("duplicate JSON key")
                d[k] = v
            return d
        obj = json.loads(raw.decode("utf-8", "strict"),
                         object_pairs_hook=unique)
    except (UnicodeError, ValueError):
        return {**status, "reason": "INVALID_LOCAL_RESPONSE"}
    # Upstream Location.response(UsageLimits.Info) is always an envelope:
    # {"location":{"directory":"..."}, "data": <Info | null>}.
    # A bare data body or a response from a different location must not
    # attest the intended account, even when its workspace ID matches.
    if (type(obj) is not dict or set(obj) != {"location", "data"}
            or type(obj["location"]) is not dict
            or set(obj["location"]) != {"directory"}
            or obj["location"]["directory"] != expected_location_directory):
        return {**status, "reason": "LOCATION_OR_RESPONSE_ENVELOPE_MISMATCH"}
    obj = obj["data"]
    if type(obj) is not dict:
        return {**status, "reason": "LOCAL_ACCOUNT_NOT_SIGNED_IN"}
    ws = obj.get("workspace")
    budgets = obj.get("budgets")
    if (type(ws) is not dict or ws.get("id") != expected_workspace_id
            or type(budgets) is not list or len(budgets) > 200):
        return {**status, "reason": "ACCOUNT_SCOPE_OR_BUDGETS_MISSING"}
    # Do not select a favorable row from an ambiguous policy list. A second
    # workspace-wide all-spend row (including malformed limits) needs owner
    # review rather than silently treating the first $0 row as authoritative.
    qualifying = 0
    for b in budgets:
        if type(b) is not dict:
            continue
        is_all_spend = (
            b.get("scope") == "combined"
            and b.get("per") == "set"
            and b.get("coverage") == "all"
            and b.get("shared") is True
            and b.get("picked") is False
            and b.get("models") == []
            and b.get("vendors") == []
            and b.get("inputPriceAtLeast") is None
        )
        if not is_all_spend:
            continue
        limit = b.get("limit")
        if type(limit) not in (int, float) or not math.isfinite(limit) or limit != 0:
            return {**status, "reason": "CONFLICTING_WORKSPACE_ALL_SPEND_BUDGET"}
        qualifying += 1
        if qualifying > 1:
            return {**status, "reason": "AMBIGUOUS_WORKSPACE_ALL_SPEND_BUDGET"}
    if qualifying == 1:
        return {**status, "status": "ZERO_WORKSPACE_BUDGET_OBSERVED_UNATTESTED",
                "reason": "BILLING_AND_NATIVE_ACCOUNT_ATTESTATION_REQUIRED",
                "workspace_zero_budget_observed": True}
    return {**status, "reason": "NO_QUALIFYING_WORKSPACE_ZERO_BUDGET"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def _pinned_location(value):
    """Require one canonical owner-selected location; never use server CWD."""
    return (type(value) is str and 2 <= len(value) <= 1024
            and value.startswith("/") and value != "/"
            and "\\" not in value
            and all(ord(char) >= 32 and ord(char) != 127 for char in value)
            and all(part not in ("", ".", "..") for part in value[1:].split("/"))
            and str(PurePosixPath(value)) == value)


def probe_local_signed_in_budget(*, port, expected_workspace_id,
                                 location_directory):
    """Read the selected location's signed-in Console budgets over loopback.

    The official API resolves the Console workspace from location[directory].
    An omitted location would instead use the server's current workspace and
    could attest the wrong account. No port discovery, file reads or login.
    This syntax-only observation never itself authorizes billing or execution.
    """
    if type(port) is not int or not 1 <= port <= 65535:
        return {"status": "HOLD_UNVERIFIED", "reason": "PINNED_LOCAL_PORT_REQUIRED",
                "workspace_zero_budget_observed": False,
                "execution_authorized": False}
    if not _pinned_location(location_directory):
        return {"status": "HOLD_UNVERIFIED", "reason": "PINNED_LOCATION_REQUIRED",
                "workspace_zero_budget_observed": False,
                "execution_authorized": False}
    url = ("http://127.0.0.1:" + str(port) +
           "/api/experimental/usage/limits?" +
           urlencode({"location[directory]": location_directory}))
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), _NoRedirect())
    req = urllib.request.Request(url, method="GET",
                                  headers={"Accept": "application/json"})
    try:
        with opener.open(req, timeout=3) as response:
            if response.status != 200:
                raise ValueError("non-successful local response")
            raw = response.read(_MAX_BYTES + 1)
    except (ValueError, OSError):
        return {"status": "HOLD_UNVERIFIED", "reason": "LOCAL_BUDGET_API_UNAVAILABLE",
                "workspace_zero_budget_observed": False,
                "execution_authorized": False}
    return summarize_workspace_budget(
        raw, expected_workspace_id=expected_workspace_id,
        expected_location_directory=location_directory)


def bind_observed_budget_to_review(review, *, port, expected_workspace_id,
                                   location_directory, attest_owner_workspace,
                                   probe=probe_local_signed_in_budget):
    """Bind the owner's *existing* $0 policy observation to the Free review.

    Reuses the current OpenCodeReviewEvidence and the current GET-only probe;
    no new receipt DB, periodic monitor, approval level or provider route.
    The trusted owner host must independently attest that this exact local
    server/selected workspace AND location belong to the intended account.
    Neither a user's prior setting report nor a synthetic successful GET can
    perform that attestation. No credential or workspace ID is returned/logged.
    This is a one-time/change-triggered admission, not a per-request poll.
    """
    from dataclasses import replace
    from .next_service_preflight import OpenCodeReviewEvidence

    if not isinstance(review, OpenCodeReviewEvidence):
        raise TypeError("OPENCODE_REVIEW_REQUIRED")
    # Always clear any caller-supplied budget flag before evaluating the new
    # observation. An unreachable/mismatched account cannot preserve a stale
    # positive grant.
    denied = replace(review, workspace_zero_budget_verified=False)
    if (type(port) is not int or not 1 <= port <= 65535
            or type(expected_workspace_id) is not str
            or _WORKSPACE_ID.fullmatch(expected_workspace_id) is None
            or not _pinned_location(location_directory)
            or not callable(attest_owner_workspace)):
        return denied, "OWNER_ACCOUNT_BINDING_REQUIRED"
    try:
        observation = probe(port=port, expected_workspace_id=expected_workspace_id,
                            location_directory=location_directory)
    except (OSError, ValueError, TypeError):
        return denied, "BUDGET_READBACK_UNAVAILABLE"
    if (type(observation) is not dict
            or observation.get("status") != "ZERO_WORKSPACE_BUDGET_OBSERVED_UNATTESTED"
            or observation.get("workspace_zero_budget_observed") is not True
            or observation.get("execution_authorized") is not False):
        return denied, "ZERO_WORKSPACE_BUDGET_NOT_OBSERVED"
    try:
        owner_bound = attest_owner_workspace(
            port=port, expected_workspace_id=expected_workspace_id,
            location_directory=location_directory)
    except (OSError, ValueError, TypeError):
        owner_bound = False
    if owner_bound is not True:
        return denied, "OWNER_ACCOUNT_BINDING_REQUIRED"
    # This flag proves only the source-bound effective $0 budget. Independent
    # Free-model price, recharge/Go switches, existing Guard release and the
    # model-level egress fence remain mandatory in opencode_readiness/host.
    return replace(denied, workspace_zero_budget_verified=True), "OWNER_ZERO_BUDGET_BOUND"

def main():
    """One-shot host-owned readback from stdin; never prints account identifiers.

    Intended for an authorized local owner process (not GitHub/cloud CI).
    Input is exactly {port, location_directory, expected_workspace_id};
    output is a credential-free observation, never an owner/Guard attestation.
    No port scanning, background watcher, network inference, or state mutation.
    """
    import sys
    try:
        raw = sys.stdin.buffer.read(4097)
        if not 0 < len(raw) <= 4096:
            raise ValueError("readback input size")
        def unique(pairs):
            record = {}
            for key, value in pairs:
                if key in record:
                    raise ValueError("duplicate field")
                record[key] = value
            return record
        request = json.loads(raw.decode("utf-8", "strict"),
                             object_pairs_hook=unique)
        if (type(request) is not dict
                or set(request) != {
                    "port", "location_directory", "expected_workspace_id"}):
            raise ValueError("unreviewed request")
        result = probe_local_signed_in_budget(**request)
    except (UnicodeError, ValueError, TypeError, OSError):
        result = {"status": "HOLD_UNVERIFIED",
                  "reason": "TRUSTED_LOCAL_READBACK_INPUT_REQUIRED",
                  "workspace_zero_budget_observed": False}
    # Deliberately never return workspace ID, directory, spend, URL or secret.
    output = {
        "status": result.get("status", "HOLD_UNVERIFIED"),
        "reason": result.get("reason", "LOCAL_BUDGET_API_UNAVAILABLE"),
        "workspace_zero_budget_observed":
            result.get("workspace_zero_budget_observed") is True,
        "account_independently_attested": False,
        "execution_authorized": False,
    }
    sys.stdout.write(json.dumps(output, sort_keys=True) + "\n")
    return 0 if output["workspace_zero_budget_observed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

