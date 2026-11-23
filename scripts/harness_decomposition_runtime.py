#!/usr/bin/env python3
"""Host-bound Harness decomposition -> GitHub child Issue readback, single turn.

This is a thin entrypoint to the existing GitHub API and Harness role ports.
Default is an observational preview. --publish-one creates at most one
*unapproved* GitHub Issue. Nothing grants ready/Guard, runs 9B, merges or
deploys. The host retains ownership of current base, exact fixed test pins,
profile/Seatbelt identity and GitHub write permission.

Run only on the reviewed host with an owner-staged, SHA256-pinned config.
Do not feed config from Issue text, CI logs or LLM responses.
"""
from __future__ import annotations

import argparse
import base64
import binascii
from contextlib import nullcontext
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_foundation.development_harness_roles import (
    HarnessRoleRuntime, HostBoundHarnessAgent, propose_decomposition,
    verify_decomposition_proposal)
from ai_foundation.host_compute_lease import HostComputeLease
from dev_autonomy_intake import GitHubAPI
from harness_decomposition_issue_bridge import (
    GitHubChildIssuePort, child_issue_candidates,
    publish_next_child_from_github,
    admit_next_independent_child_from_github)

REPO = "quest7070-dev/AI-Foundation"
SCHEMA = "foundation-harness-decomposition-host/v1"
SHA256_PATTERN = re.compile(r"[a-f0-9]{64}")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _pinned_file(path: str, expected: str, *, max_bytes: int = 65536) -> bytes:
    if (type(path) is not str or not Path(path).is_absolute()
            or type(expected) is not str or not SHA256_PATTERN.fullmatch(expected)):
        raise ValueError("HOST_FILE_PIN_INVALID")
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        raise ValueError("HOST_FILE_NOT_REGULAR")
    info = source.stat()
    if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022
            or info.st_size > max_bytes):
        raise ValueError("HOST_FILE_MODE_OR_SIZE_INVALID")
    body = source.read_bytes()
    if len(body) > max_bytes or _digest(body) != expected:
        raise ValueError("HOST_FILE_BYTES_DRIFT")
    return body


def load_host_config(path: str, sha256: str) -> dict:
    raw = _pinned_file(path, sha256)
    try:
        config = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("HOST_CONFIG_JSON_INVALID") from exc
    required = {"schema", "repository", "parent_issue", "base_sha",
                "reviewed_contracts", "harness"}
    if (type(config) is not dict
            or not required <= set(config)
            or set(config) - required not in (set(), {"base"})
            or config["schema"] != SCHEMA or config["repository"] != REPO
            or type(config["parent_issue"]) is not int or config["parent_issue"] < 1
            or type(config["base_sha"]) is not str
            or not re.fullmatch(r"[a-f0-9]{40}", config["base_sha"])):
        raise ValueError("HOST_CONFIG_SCHEMA_INVALID")
    base = config.get("base", "main")
    if (type(base) is not str or not re.fullmatch(
            r"(?:main|local9b/[A-Za-z0-9_./-]{1,140})", base)
            or ".." in base):
        raise ValueError("HOST_BASE_BRANCH_INVALID")
    if type(config["harness"]) is not dict or set(config["harness"]) != {
            "argv", "cwd", "timeout_s", "seatbelt_sha256", "patch_sha256"}:
        raise ValueError("HOST_HARNESS_BINDING_INVALID")
    h = config["harness"]
    a = h["argv"]
    if (type(a) is not list or len(a) != 8
            or a[0:2] != ["/usr/bin/sandbox-exec", "-f"]
            or a[4:7] != ["--profile", "headless", "--patch"]
            or any(type(value) is not str or not value for value in a)
            or any(not Path(a[index]).is_absolute() for index in (2, 3, 7))
            or Path(a[3]).name != "dsh"
            or type(h["cwd"]) is not str or not Path(h["cwd"]).is_absolute()
            or type(h["timeout_s"]) is not int
            or not 1 <= h["timeout_s"] <= 3600):
        raise ValueError("HOST_HARNESS_BINDING_INVALID")
    _pinned_file(a[2], h["seatbelt_sha256"], max_bytes=65536)
    _pinned_file(a[7], h["patch_sha256"], max_bytes=262144)
    cwd = Path(h["cwd"])
    if (not cwd.is_dir() or cwd.is_symlink()
            or cwd.stat().st_mode & 0o022):
        raise ValueError("HOST_HARNESS_PRIVATE_HOME_INVALID")
    # Models, API keys and billing settings are NOT accepted as config fields.
    # The approved sandbox/profile owns provider routing and zero-cost policy.
    return config


def _verify_scope(config: dict) -> dict:
    # The host-pinned payload contains exactly one contract per target path.
    # Use the existing finite python-fixed-test validator without reimplementing it.
    from local9b_task_recipe import validate_contract
    records = config["reviewed_contracts"]
    if type(records) is not dict or not 1 <= len(records) <= 8:
        raise ValueError("HOST_SCOPE_INCOMPLETE")
    scope = {}
    for target, pins in records.items():
        if type(target) is not str or type(pins) is not dict or set(pins) != {
                "test", "test_sha256", "instruction"}:
            raise ValueError("HOST_SCOPE_INVALID")
        contract = {
            "recipe": "python-fixed-test", "base": config.get("base", "main"),
            "base_sha": config["base_sha"], "target": target,
            "test": pins["test"], "test_sha256": pins["test_sha256"],
            "instruction": pins["instruction"],
        }
        validate_contract(contract)
        scope[target] = contract
    return scope


def _read_contents(api, path, sha):
    payload = api.request(api.repo_path(
        "/contents/" + quote(path, safe="/") + "?ref=" + sha))
    if (type(payload) is not dict
            or payload.get("path") != path or payload.get("type") != "file"
            or payload.get("target") is not None
            or payload.get("submodule_git_url") is not None):
        raise ValueError("HOST_GITHUB_PINNED_FILE_INVALID")
    return payload


def verify_host_baseline(api, config: dict) -> dict:
    """Check current main identity AND GitHub-hosted fixed test bytes."""
    sha = config["base_sha"]
    base = config.get("base", "main")
    commit = api.request(api.repo_path(
        "/commits/" + quote(base, safe="")))
    if type(commit) is not dict or commit.get("sha") != sha:
        raise ValueError("HOST_BASE_SHA_MOVED")
    scope = _verify_scope(config)
    for target, contract in scope.items():
        _read_contents(api, target, sha)   # Source file must exist on this base.
        response = _read_contents(api, contract["test"], sha)
        if response.get("encoding") != "base64" or type(response.get("content")) is not str:
            raise ValueError("HOST_FIXED_TEST_NOT_READABLE")
        try:
            test_source = base64.b64decode(
                response["content"].replace("\n", ""), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("HOST_FIXED_TEST_CONTENT_INVALID") from exc
        if _digest(test_source) != contract["test_sha256"]:
            raise ValueError("HOST_FIXED_TEST_SHA_DRIFT")
    return scope


def verify_parent_scope(api, config: dict, scope: dict) -> dict:
    """No-model parent admission: exact Issue identity, label and file scope."""
    from github_task_orchestrator import metadata
    parent_no = config["parent_issue"]
    parent = GitHubChildIssuePort(api).read_parent(parent_no)
    if (type(parent) is not dict or parent.get("number") != parent_no
            or parent.get("state") not in ("open", "OPEN")):
        raise ValueError("HOST_PARENT_NOT_OPEN")
    labels = parent.get("labels", [])
    if type(labels) is not list or any(type(row) is not dict for row in labels):
        raise ValueError("HOST_PARENT_LABELS_INVALID")
    names = {row.get("name") for row in labels}
    if ("foundation-autodev:ready" not in names
            or "foundation-autodev:hold" in names):
        raise ValueError("HOST_PARENT_NOT_APPROVED")
    paths, deps = metadata(parent.get("body", ""), parent_no)
    if paths != sorted(scope) or deps:
        raise ValueError("HOST_PARENT_SCOPE_INVALID")
    return {"status": "PRE_MODEL_VERIFIED", "execution_authorized": False,
            "parent_issue": parent_no,
            "base": config.get("base", "main"),
            "base_sha": config["base_sha"],
            "reviewed_targets": len(scope)}


def _safe_inference_env(private_home: str) -> dict:
    # Never expose GitHub write secrets, inherited HOME or cloud API tokens.
    keep = {"PATH", "OLLAMA_HOST", "OLLAMA_API_KEY",
            "LANG", "LC_ALL", "TMPDIR", "TERM"}
    local = os.environ.get("OLLAMA_HOST", "")
    if (local and not re.fullmatch(
            r"(?:http://)?(?:127\.0\.0\.1|localhost):[0-9]{2,5}", local)):
        raise ValueError("HARNESS_NONLOCAL_OLLAMA_HOST")
    env = {key: value for key, value in os.environ.items() if key in keep}
    env["HOME"] = private_home
    env["DSH_HOME"] = private_home
    return env


def _save_plan_receipt(path: str, proposal: dict, *, host_file: str) -> str:
    """One immutable owner-local receipt, not a separate task state database."""
    target = Path(path)
    host = Path(host_file)
    if (not target.is_absolute() or target.parent.resolve(strict=True) !=
            host.parent.resolve(strict=True) or target.is_symlink()
            or target.exists()):
        raise ValueError("HOST_PLAN_RECEIPT_PATH_INVALID")
    body = (json.dumps(proposal, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")
    if len(body) > 65536:
        raise ValueError("HOST_PLAN_RECEIPT_TOO_LARGE")
    fd = os.open(target, os.O_EXCL | os.O_CREAT | os.O_WRONLY |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(body)
            out.flush()
            os.fsync(out.fileno())
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return _digest(body)


def _load_plan_receipt(path: str, expected_sha256: str) -> dict:
    body = _pinned_file(path, expected_sha256)
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("HOST_PLAN_DUPLICATE_JSON_KEY")
            obj[key] = value
        return obj
    try:
        proposal = json.loads(body, object_pairs_hook=unique)
    except json.JSONDecodeError as exc:
        raise ValueError("HOST_PLAN_JSON_INVALID") from exc
    if type(proposal) is not dict:
        raise ValueError("HOST_PLAN_SCHEMA_INVALID")
    return proposal


def run_one(config: dict, api, roles, *, publish=False, admit=False,
            proposal_receipt=None, stage_plan_file=None,
            owner_config_path=None, lease=None) -> dict:
    """One host-owned, bounded inference turn; no internal job/task queue."""
    contracts = verify_host_baseline(api, config)
    scope = {key: value["test"] for key, value in contracts.items()}
    verify_parent_scope(api, config, scope)
    if publish and admit:
        raise ValueError("HOST_CHILD_EFFECTS_MUTUALLY_EXCLUSIVE")
    if proposal_receipt is None:
        if publish or admit:
            raise ValueError("PUBLISH_REQUIRES_FROZEN_PROPOSAL")
        # Reuse the canonical M1 compute lease; busy means defer, never
        # launch an alternate model, evict Ollama, or consume an Issue.
        with (lease.hold() if lease is not None else nullcontext()):
            proposal = propose_decomposition(
                roles, issue_number=config["parent_issue"],
                base_sha=config["base_sha"], reviewed_scope=scope,
                reviewed_instructions={
                    key: contract["instruction"] for key, contract in contracts.items()
                })
    else:
        proposal = verify_decomposition_proposal(
            proposal_receipt, issue_number=config["parent_issue"],
            base_sha=config["base_sha"], reviewed_scope=scope)
    # Revalidate the immutable GitHub snapshot after model output.
    verify_host_baseline(api, config)
    port = GitHubChildIssuePort(api)
    parent = port.read_parent(config["parent_issue"])
    children = port.find_children(config["parent_issue"],
                                  proposal["proposal_sha256"])
    candidate = child_issue_candidates(
        proposal=proposal, current_parent=parent,
        reviewed_contracts=config["reviewed_contracts"],
        existing_children=children, base=config.get("base", "main"))
    if admit:
        # This is only a projection of a parent's existing exact scope to one
        # independent child. No dependent Draft may be assumed integrated.
        verify_host_baseline(api, config)
        return admit_next_independent_child_from_github(
            api=api, proposal=proposal,
            reviewed_contracts=config["reviewed_contracts"],
            base=config.get("base", "main"))
    if not publish:
        receipt_sha256 = None
        if stage_plan_file is not None:
            if type(owner_config_path) is not str or proposal_receipt is not None:
                raise ValueError("HOST_PLAN_STAGING_INVALID")
            receipt_sha256 = _save_plan_receipt(
                stage_plan_file, proposal, host_file=owner_config_path)
        return {
            "status": "PLAN_STAGED" if receipt_sha256 else "PREVIEW_ONLY",
            "plan_file_sha256": receipt_sha256,
            "execution_authorized": False,
            "proposal_sha256": proposal["proposal_sha256"],
            "parent_issue": proposal["issue_number"],
            "children": [{
                "step_id": item["step_id"],
                "status": item["status"],
                "target": item.get("source_target"),
                "depends_on_issues": item.get("depends_on_issues", []),
            } for item in candidate["children"]],
        }
    verify_host_baseline(api, config)
    return publish_next_child_from_github(
        api=api, proposal=proposal,
        reviewed_contracts=config["reviewed_contracts"],
        base=config.get("base", "main"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host-config", required=True)
    parser.add_argument("--host-config-sha256", required=True)
    parser.add_argument("--publish-one", action="store_true")
    parser.add_argument("--admit-one", action="store_true",
                        help="Use existing parent's ready scope for one independent child")
    parser.add_argument("--preflight", action="store_true",
                        help="Check GitHub/host pins without any model call")
    parser.add_argument("--stage-plan", help="Create one private immutable plan receipt")
    parser.add_argument("--proposal-file", help="Previously staged plan receipt")
    parser.add_argument("--proposal-sha256", help="SHA256 of frozen plan receipt")
    args = parser.parse_args(argv)
    if ((args.proposal_file is None) != (args.proposal_sha256 is None)
            or (args.stage_plan is not None and
                (args.proposal_file is not None or args.publish_one
                 or args.admit_one or args.preflight))
            or (args.preflight and (args.publish_one or args.admit_one
                                    or args.proposal_file))
            or (args.publish_one and args.admit_one)
            or ((args.publish_one or args.admit_one)
                and args.proposal_file is None)):
        parser.error("stage a plan first, then publish one using its pinned receipt")
    try:
        config = load_host_config(args.host_config, args.host_config_sha256)
        token = os.environ.get("GITHUB_TOKEN", "")
        api = GitHubAPI(token, REPO)
        if args.preflight:
            contracts = verify_host_baseline(api, config)
            result = verify_parent_scope(api, config, contracts)
            print("HARNESS_DECOMPOSITION=" + json.dumps(
                result, sort_keys=True, ensure_ascii=False))
            return 0
        binding = config["harness"]
        agent = HostBoundHarnessAgent(
            tuple(binding["argv"]), binding["cwd"],
            _safe_inference_env(binding["cwd"]), binding["timeout_s"])
        roles = HarnessRoleRuntime({"decomposition": agent})
        compute_lease = HostComputeLease() if not args.proposal_file else None
        frozen = (_load_plan_receipt(args.proposal_file, args.proposal_sha256)
                  if args.proposal_file is not None else None)
        if args.publish_one or args.admit_one:
            # Same-host mutex across publication and existing-scope admission.
            # GitHub readback
            # still provides the authority; a cross-host race is not silently
            # interpreted as success.
            lockfile = Path(args.host_config + ".publish.lock")
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(lockfile, flags, 0o600)
            with os.fdopen(fd, "r+", encoding="utf-8") as lock:
                os.fchmod(lock.fileno(), 0o600)
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                result = run_one(config, api, roles, publish=args.publish_one,
                                 admit=args.admit_one,
                                 proposal_receipt=frozen, lease=compute_lease)
        else:
            result = run_one(config, api, roles, proposal_receipt=frozen,
                             stage_plan_file=args.stage_plan,
                             owner_config_path=args.host_config,
                             lease=compute_lease)
        print("HARNESS_DECOMPOSITION=" + json.dumps(
            result, sort_keys=True, ensure_ascii=False))
        return 0
    except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
        # Log only a bounded error class/code, never private Issue/model text.
        code = str(exc)
        if not re.fullmatch(r"[A-Z0-9_]{4,80}", code):
            code = type(exc).__name__.upper()
        print("HARNESS_DECOMPOSITION=BLOCKED:" + code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
