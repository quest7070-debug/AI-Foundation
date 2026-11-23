"""Harness decomposition -> existing GitHub Issue schema; no new scheduler.

The host supplies a current approved parent Issue and source/test pins.
Model purpose is commentary only; the runnable instruction, test and base
come from host-owned contracts. Emitted Issue candidates have NO ready label.
Existing one-shot worker/Guard must independently accept any published Issue.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Mapping

from github_task_orchestrator import metadata
from local9b_task_recipe import validate_contract

CHILD_PREFIX = "<!-- foundation-harness-child:v1 "
CHILD_PATTERN = re.compile(
    r"<!-- foundation-harness-child:v1 (\{[^\n]*\}) -->")
REQUIRED_PINS = frozenset({"test", "test_sha256", "instruction"})

def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("CHILD_PROVENANCE_DUPLICATE_KEY")
        value[key] = item
    return value


def _provenance_json(text):
    return json.loads(text, object_pairs_hook=_unique_object)



def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _child_identity(proposal, step):
    return {
        "parent_issue": proposal["issue_number"],
        "base_sha": proposal["base_sha"],
        "proposal_sha256": proposal["proposal_sha256"],
        "step_id": step["id"],
    }


def _parse_existing_child(issue, proposal, step):
    """Use independent GitHub readback, not untrusted step-ID -> number claims."""
    if type(issue) is not dict or type(issue.get("number")) is not int or issue["number"] < 1:
        raise ValueError("CHILD_ISSUE_ID_INVALID")
    if issue.get("state") not in ("open", "closed", "OPEN", "CLOSED"):
        raise ValueError("CHILD_ISSUE_STATE_INVALID")
    body = issue.get("body")
    if type(body) is not str or len(body) > 32768:
        raise ValueError("CHILD_ISSUE_BODY_INVALID")
    matches = list(CHILD_PATTERN.finditer(body))
    if len(matches) != 1:
        raise ValueError("CHILD_PROVENANCE_MISSING")
    try:
        marker = _provenance_json(matches[0].group(1))
    except json.JSONDecodeError as exc:
        raise ValueError("CHILD_PROVENANCE_INVALID") from exc
    expected = _child_identity(proposal, step)
    if (type(marker) is not dict or set(marker) != set(expected) | {"body_sha256"}
            or {k: marker.get(k) for k in expected} != expected):
        raise ValueError("CHILD_PROVENANCE_MISMATCH")
    raw = body[:matches[0].start()] + body[matches[0].end():]
    if hashlib.sha256(raw.encode()).hexdigest() != marker["body_sha256"]:
        raise ValueError("CHILD_ISSUE_EDITED_AFTER_CREATION")
    return issue["number"]


def _host_pins(proposal, reviewed_contracts, *, base="main"):
    if (not isinstance(reviewed_contracts, Mapping)
            or len(reviewed_contracts) != len(proposal["steps"])):
        raise ValueError("CHILD_SCOPE_CONTRACT_INCOMPLETE")
    if (type(base) is not str
            or not re.fullmatch(r"(?:main|local9b/[A-Za-z0-9_./-]{1,140})", base)
            or ".." in base):
        raise ValueError("CHILD_BASE_BRANCH_INVALID")
    scope = {}
    for path, pins in reviewed_contracts.items():
        if type(path) is not str or type(pins) is not dict or set(pins) != REQUIRED_PINS:
            raise ValueError("CHILD_SCOPE_CONTRACT_INVALID")
        contract = {
            "recipe": "python-fixed-test", "base": base,
            "base_sha": proposal["base_sha"], "target": path,
            "test": pins["test"], "test_sha256": pins["test_sha256"],
            "instruction": pins["instruction"],
        }
        validate_contract(contract)
        scope[path] = contract
    return scope


def child_issue_candidates(*, proposal, current_parent, reviewed_contracts,
                           existing_children=None, base="main"):
    """Build issue-sized step contracts from a scoped Harness decomposition.

    Current parent/children MUST be fresh GitHub API readbacks supplied by the
    caller, never model output. This function does not POST. Missing dependency
    issue numbers leave a step pending until a prior child has been published
    and independently read back by the existing GitHub owner.
    """
    if type(proposal) is not dict or type(proposal.get("steps")) is not list:
        raise ValueError("DECOMPOSITION_PROPOSAL_INVALID")
    from ai_foundation.development_harness_roles import verify_decomposition_proposal
    host_pins = _host_pins(proposal, reviewed_contracts, base=base)
    reviewed_scope = {target: pin["test"] for target, pin in host_pins.items()}
    verify_decomposition_proposal(
        proposal, issue_number=proposal["issue_number"],
        base_sha=proposal["base_sha"], reviewed_scope=reviewed_scope)

    parent_no = proposal["issue_number"]
    if (type(current_parent) is not dict or current_parent.get("number") != parent_no
            or current_parent.get("state") not in ("open", "OPEN")):
        raise ValueError("PARENT_ISSUE_NOT_CURRENT")
    labels = current_parent.get("labels", [])
    if type(labels) is not list or any(type(t) is not dict for t in labels):
        raise ValueError("PARENT_ISSUE_LABELS_INVALID")
    names = {v.get("name") for v in labels}
    if ("foundation-autodev:ready" not in names
            or "foundation-autodev:hold" in names):
        raise ValueError("PARENT_ISSUE_NOT_APPROVED")
    paths, deps = metadata(current_parent.get("body", ""), parent_no)
    if paths != sorted(reviewed_scope) or deps:
        raise ValueError("PARENT_ISSUE_SCOPE_MISMATCH")

    steps = {step["id"]: step for step in proposal["steps"]}
    existing_children = {} if existing_children is None else existing_children
    if (type(existing_children) is not dict or
            any(key not in steps for key in existing_children)):
        raise ValueError("CHILD_READBACK_UNEXPECTED")
    numbers = {}
    for step_id, issue in existing_children.items():
        numbers[step_id] = _parse_existing_child(issue, proposal, steps[step_id])
    if len(set(numbers.values())) != len(numbers) or parent_no in numbers.values():
        raise ValueError("CHILD_ISSUE_ID_COLLISION")

    results = []
    for step in proposal["steps"]:
        step_id = step["id"]
        if step_id in numbers:
            results.append({"step_id": step_id, "status": "EXISTING_CHILD",
                            "issue_number": numbers[step_id]})
            continue
        missing = sorted(set(step["depends_on"]) - set(numbers))
        if missing:
            results.append({"step_id": step_id, "status": "WAITING_CHILD_ISSUE_IDS",
                            "waiting_for": missing})
            continue
        refs = sorted({numbers[dep] for dep in step["depends_on"]})
        contract = host_pins[step["target"]]
        base = (
            "Harness decomposition child candidate (unapproved).\n"
            f"Parent: #{parent_no}\n"
            f"Step: {step_id}\n"
            # Model purpose is retained only in the content-hashed planning
            # receipt, never emitted as GitHub task instructions or markers.
            f"Base SHA: {proposal['base_sha']}\n"
            "Approval: NOT READY; requires existing Issue/Guard admission.\n\n"
            "<!-- foundation-autodev: "
            + _json({"paths": [step["target"]], "depends_on": refs})
            + " -->\n\n"
            + "\x60\x60\x60foundation-autodev-task\n"
            + _json(contract) + "\n\x60\x60\x60\n\n"
        )
        identity = {**_child_identity(proposal, step),
                    "body_sha256": hashlib.sha256(base.encode()).hexdigest()}
        body = base + CHILD_PREFIX + _json(identity) + " -->"
        if len(body) > 32768:
            raise ValueError("CHILD_ISSUE_BODY_TOO_LARGE")
        results.append({
            "step_id": step_id, "status": "CANDIDATE_NOT_AUTHORIZED",
            "title": f"[Harness child #{parent_no}/{step_id}] {step['target']}",
            "body": body,
            "labels": [],
            "execution_authorized": False,
            "source_target": step["target"],
            "acceptance_test": contract["test"],
            "depends_on_issues": refs,
        })
    return {
        "schema": "foundation-harness-child-issues/v1",
        "parent_issue": parent_no,
        "proposal_sha256": proposal["proposal_sha256"],
        "execution_authorized": False,
        "children": results,
    }



def propose_child_issue_candidates(*, roles, parent_issue_number, base_sha,
                                   reviewed_contracts, read_current_parent,
                                   read_existing_children, base="main"):
    """One bounded Harness -> existing Issue-contract handoff, read-only.

    The caller owns the admitted Harness role and both independent GitHub
    readback callbacks. Re-fetch parent/child Issues AFTER the inference turn,
    so a revoked parent label or edited child never becomes a new draft.
    Neither callback returns authority, credentials, or model metadata.
    """
    from ai_foundation.development_harness_roles import propose_decomposition
    if (not isinstance(reviewed_contracts, Mapping)
            or not callable(read_current_parent)
            or not callable(read_existing_children)):
        raise ValueError("DECOMPOSITION_HOST_BINDING_INVALID")
    scope = {}
    for path, pins in reviewed_contracts.items():
        if type(pins) is not dict or "test" not in pins:
            raise ValueError("DECOMPOSITION_HOST_BINDING_INVALID")
        scope[path] = pins["test"]
    proposal = propose_decomposition(
        roles, issue_number=parent_issue_number, base_sha=base_sha,
        reviewed_scope=scope,
        reviewed_instructions={
            target: pins["instruction"] for target, pins in reviewed_contracts.items()
        })
    current_parent = read_current_parent(parent_issue_number)
    existing = read_existing_children(parent_issue_number, proposal["proposal_sha256"])
    return child_issue_candidates(
        proposal=proposal, current_parent=current_parent,
        reviewed_contracts=reviewed_contracts, existing_children=existing,
        base=base)



def publish_one_unapproved_child(*, proposal, reviewed_contracts,
                                 read_current_parent, read_existing_children,
                                 create_issue, read_issue, base="main"):
    """Host-owned, one-child GitHub publication with independent readback.

    One call may create at most one unlabelled diagnostic Issue. The host MUST
    serialize its publication workers and supply a complete recent closed/open
    child discovery callback. Neither model output nor this adapter can grant
    ready status or launch a task. After uncertain HTTP write, never blindly
    retry: discover by the stable provenance marker first.
    """
    callbacks = (read_current_parent, read_existing_children,
                 create_issue, read_issue)
    if any(not callable(fn) for fn in callbacks):
        raise ValueError("CHILD_PUBLISH_HOST_CALLBACKS_REQUIRED")
    parent_no = proposal["issue_number"]
    identity = proposal["proposal_sha256"]
    parent = read_current_parent(parent_no)
    existing = read_existing_children(parent_no, identity)
    packet = child_issue_candidates(
        proposal=proposal, current_parent=parent,
        reviewed_contracts=reviewed_contracts, existing_children=existing,
        base=base)
    pending = [x for x in packet["children"]
               if x["status"] == "CANDIDATE_NOT_AUTHORIZED"]
    if not pending:
        return {"status": "NO_CHILD_CREATION", "parent_issue": parent_no}
    candidate = pending[0]

    # Publication is a distinct GitHub effect. Recheck changes after
    # the plan was constructed, in addition to the post-inference readback.
    if (read_current_parent(parent_no) != parent
            or read_existing_children(parent_no, identity) != existing):
        raise ValueError("CHILD_PUBLISH_READBACK_CHANGED")
    created = create_issue({"title": candidate["title"], "body": candidate["body"]})
    if type(created) is not dict or type(created.get("number")) is not int:
        raise ValueError("CHILD_PUBLISH_UNCERTAIN_CREATE")
    number = created["number"]
    current = read_issue(number)
    step = next(x for x in proposal["steps"] if x["id"] == candidate["step_id"])
    if (_parse_existing_child(current, proposal, step) != number
            or current["body"] != candidate["body"]):
        raise ValueError("CHILD_PUBLISH_REMOTE_READBACK_MISMATCH")
    labels = current.get("labels", [])
    if (type(labels) is not list
            or any(type(row) is not dict for row in labels)
            or any(row.get("name") in ("foundation-autodev:ready",
                                       "foundation-autodev:hold") for row in labels)):
        raise ValueError("CHILD_PUBLISH_UNEXPECTED_LABELS")
    return {"status": "CHILD_ISSUE_CREATED_UNAPPROVED",
            "parent_issue": parent_no, "step_id": candidate["step_id"],
            "issue_number": number, "execution_authorized": False}




def admit_one_independent_child(*, proposal, reviewed_contracts,
                                read_current_parent, read_existing_children,
                                add_ready_label, read_issue, base="main"):
    """Project existing parent ready scope to ONE independent, frozen child.

    The parent was already explicitly admitted for the exact reviewed paths,
    tests and instructions. A child with cross-step dependencies is *never*
    promoted: a closed Issue or an unmerged Draft is not proof that its
    predecessor's source is available at the pinned main base. This does not
    invoke a model or add a scheduler; the existing 9B worker still performs
    its independent one-shot, Guard and fixed-test admission.
    """
    if any(not callable(fn) for fn in (
            read_current_parent, read_existing_children,
            add_ready_label, read_issue)):
        raise ValueError("CHILD_ADMISSION_HOST_CALLBACKS_REQUIRED")
    parent_number = proposal["issue_number"]
    lineage = proposal["proposal_sha256"]
    parent = read_current_parent(parent_number)
    existing = read_existing_children(parent_number, lineage)
    child_issue_candidates(
        proposal=proposal, current_parent=parent,
        reviewed_contracts=reviewed_contracts, existing_children=existing,
        base=base)
    selected = None
    for step in proposal["steps"]:
        if step["depends_on"] or step["id"] not in existing:
            continue
        child = existing[step["id"]]
        if child.get("state") not in ("open", "OPEN"):
            continue
        labels = child.get("labels")
        if type(labels) is not list or any(
                type(item) is not dict or type(item.get("name")) is not str
                for item in labels):
            raise ValueError("CHILD_ADMISSION_LABELS_INVALID")
        names = {item["name"] for item in labels}
        if "foundation-autodev:hold" in names:
            continue
        if "foundation-autodev:ready" in names:
            continue
        selected = (step, child)
        break
    if selected is None:
        return {"status": "NO_INDEPENDENT_CHILD_TO_ADMIT",
                "execution_authorized": False, "parent_issue": parent_number}
    step, child = selected
    # Exact original body, source and pinned acceptance are checked in
    # child_issue_candidates. Verify live state once more before the label.
    if (read_current_parent(parent_number) != parent
            or read_existing_children(parent_number, lineage) != existing):
        raise ValueError("CHILD_ADMISSION_READBACK_CHANGED")
    number = child["number"]
    add_ready_label(number)
    observed = read_issue(number)
    if (_parse_existing_child(observed, proposal, step) != number
            or observed.get("state") not in ("open", "OPEN")):
        raise ValueError("CHILD_ADMISSION_REMOTE_READBACK_MISMATCH")
    names = {item.get("name") for item in observed.get("labels", [])
             if type(item) is dict}
    if ("foundation-autodev:ready" not in names
            or "foundation-autodev:hold" in names):
        raise ValueError("CHILD_ADMISSION_REMOTE_LABEL_MISMATCH")
    return {"status": "INDEPENDENT_CHILD_READY_FOR_EXISTING_WORKER",
            "parent_issue": parent_number, "issue_number": number,
            "step_id": step["id"],
            "authority_source": "EXACT_READY_PARENT_AND_PINNED_HOST_CONTRACT"}




class GitHubChildIssuePort:
    """Thin adapter for the already-authenticated GitHubAPI, not a new queue."""

    def __init__(self, api):
        if not hasattr(api, "request") or not hasattr(api, "repo_path"):
            raise ValueError("GITHUB_CHILD_PORT_UNBOUND")
        self.api = api

    def read_parent(self, issue_number):
        return self.api.request(self.api.repo_path(f"/issues/{issue_number}"))

    def read_issue(self, issue_number):
        return self.read_parent(issue_number)

    def find_children(self, parent_number, proposal_sha256):
        if (type(parent_number) is not int or parent_number < 1
                or type(proposal_sha256) is not str
                or not re.fullmatch(r"[a-f0-9]{64}", proposal_sha256)):
            raise ValueError("CHILD_SEARCH_IDENTITY_INVALID")
        found = {}
        # Scope is all Issues (including closed ones) so a prior publication
        # is never silently repeated after closure or a workflow restart.
        # Repository Issue/PR numbering already exceeds 500. Scan a bounded
        # 1,000-item window, then refuse incomplete deduplication.
        for page in range(1, 11):
            rows = self.api.request(self.api.repo_path(
                f"/issues?state=all&per_page=100&page={page}"))
            if type(rows) is not list or len(rows) > 100:
                raise ValueError("CHILD_SEARCH_GITHUB_SCHEMA_INVALID")
            for row in rows:
                if type(row) is not dict or "pull_request" in row:
                    continue
                body = row.get("body")
                title = row.get("title")
                # A previously published child with removed or malformed
                # provenance cannot be interpreted as missing and recreated.
                reserved = (type(title) is str
                            and title.startswith(f"[Harness child #{parent_number}/"))
                if type(body) is not str:
                    if reserved:
                        raise ValueError("CHILD_SEARCH_PROVENANCE_MISSING")
                    continue
                matches = list(CHILD_PATTERN.finditer(body))
                if len(matches) != 1:
                    if reserved:
                        raise ValueError("CHILD_SEARCH_PROVENANCE_MISSING")
                    continue
                try:
                    marker = _provenance_json(matches[0].group(1))
                except (json.JSONDecodeError, ValueError) as exc:
                    if reserved:
                        raise ValueError("CHILD_SEARCH_PROVENANCE_INVALID") from exc
                    continue
                if type(marker) is not dict or marker.get("parent_issue") != parent_number:
                    if reserved:
                        raise ValueError("CHILD_SEARCH_PROVENANCE_MISMATCH")
                    continue
                # A fresh LLM plan for the same parent cannot silently mint
                # another set of children. Preserve one immutable plan lineage
                # until the host explicitly resolves the existing work.
                if marker.get("proposal_sha256") != proposal_sha256:
                    raise ValueError("CHILD_PARENT_PLAN_DRIFT")
                step_id = marker.get("step_id")
                if type(step_id) is not str or step_id in found:
                    raise ValueError("CHILD_SEARCH_DUPLICATE_OR_INVALID")
                found[step_id] = row
            if len(rows) < 100:
                break
            if page == 10:
                raise ValueError("CHILD_SEARCH_INCOMPLETE")
        return found

    def add_ready_label(self, number):
        if type(number) is not int or number <= 0:
            raise ValueError("CHILD_ADMISSION_ISSUE_ID_INVALID")
        return self.api.request(self.api.repo_path(f"/issues/{number}/labels"),
                                method="POST",
                                payload={"labels": ["foundation-autodev:ready"]})

    def create_issue(self, payload):
        if (type(payload) is not dict or set(payload) != {"title", "body"}
                or any(type(value) is not str or not value for value in payload.values())):
            raise ValueError("CHILD_CREATE_PAYLOAD_INVALID")
        # No labels: a draft Issue cannot inherit ready state implicitly.
        return self.api.request(self.api.repo_path("/issues"),
                                method="POST", payload=payload)


def publish_next_child_from_github(*, api, proposal, reviewed_contracts, base="main"):
    """At most one GitHub Issue effect; trusted host must serialize callers."""
    port = GitHubChildIssuePort(api)
    return publish_one_unapproved_child(
        proposal=proposal, reviewed_contracts=reviewed_contracts,
        read_current_parent=port.read_parent,
        read_existing_children=port.find_children,
        create_issue=port.create_issue, read_issue=port.read_issue,
        base=base)


def admit_next_independent_child_from_github(*, api, proposal,
                                            reviewed_contracts, base="main"):
    """Owner-bound ready handoff; uses the existing Issue and 9B worker only."""
    port = GitHubChildIssuePort(api)
    return admit_one_independent_child(
        proposal=proposal, reviewed_contracts=reviewed_contracts,
        read_current_parent=port.read_parent,
        read_existing_children=port.find_children,
        add_ready_label=port.add_ready_label,
        read_issue=port.read_issue, base=base)
