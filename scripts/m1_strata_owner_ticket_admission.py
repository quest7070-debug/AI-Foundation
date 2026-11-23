"""Owner-private on-M1 admission of a new reviewed public CODE ticket.

The local caller chooses only a ticket ID. The reviewed 0600 document lives
outside the source checkout; this file never sends source to a model, starts
model calls, runs tests, creates GitHub issues or changes main.
"""
from __future__ import annotations

import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from ai_foundation.sensitive_input_scan import contains_sensitive_value
from m1_development_ticket_factory import (
    _ID, _owner_file, _owner_manifest, _private_dir, _strict_json, _validate_ticket, _owner_local_repo,
    MAX_OWNER_DEVELOPMENT_TICKETS,
)
from m1_direct_development import git, installed_config, write_private

REVIEWED = "owner-reviewed-public-nonsecret-v1"
REPO = "quest7070-dev/AI-Foundation"


def reviewed_contract(root, repo, ticket_id, *, expected_instruction_sha256=None):
    """Verify private consent and exact tracked source/test bytes before Work."""
    if type(ticket_id) is not str or not _ID.fullmatch(ticket_id):
        raise ValueError("OWNER_TICKET_ID_INVALID")
    root, repo = Path(root), Path(repo)
    path = root / "development" / "reviews" / (ticket_id + ".json")
    try:
        raw = _strict_json(_owner_file(path))
    except FileNotFoundError:
        # No individual owner review exists. Only an already owner-enabled,
        # path-bounded local delegation may supply equivalent admission input.
        # Existing malformed/symlinked reviews cannot fall back to delegation.
        from m1_development_scope_delegation import delegated_record
        delegated = delegated_record(
            root, repo, ticket_id,
            expected_instruction_sha256=expected_instruction_sha256)
        if delegated is None:
            raise PermissionError("EXACT_OWNER_REVIEW_OR_DELEGATION_REQUIRED") from None
        return delegated
    required = {"version", "review", "ticket_id", "model", "base_sha",
                "target", "test", "source_sha256", "test_sha256",
                "public_source_sha256", "public_instruction_sha256",
                "instruction"}
    if type(raw) is not dict or set(raw) != required:
        raise ValueError("OWNER_PUBLIC_REVIEW_INVALID")
    if (raw["version"] != 1 or raw["review"] != REVIEWED
            or raw["ticket_id"] != ticket_id
            or raw["model"] not in ("m1", "auto", "strata")):
        raise ValueError("OWNER_PUBLIC_REVIEW_INVALID")
    record = {key: raw[key] for key in required if key not in {"version", "review"}}
    if record["model"] == "m1":
        for key in ("public_source_sha256", "public_instruction_sha256"):
            record.pop(key)
    record["source_origin"] = "owner-local-review-v1"
    _validate_ticket(record)
    if expected_instruction_sha256 is not None:
        if (type(expected_instruction_sha256) is not str
                or len(expected_instruction_sha256) != 64
                or sha256(record["instruction"].encode()).hexdigest() != expected_instruction_sha256):
            raise ValueError("OWNER_REQUEST_INSTRUCTION_CHANGED")
    if (raw["public_source_sha256"] != raw["source_sha256"]
            or raw["public_instruction_sha256"] != sha256(raw["instruction"].encode()).hexdigest()):
        raise ValueError("OWNER_PUBLIC_REVIEW_INVALID")
    # The owner reviews a local committed baseline independently of the CLI
    # release. No GitHub upload or installed-runtime replacement is required.
    if (git(repo, "rev-parse", "HEAD") != record["base_sha"]
            or git(repo, "status", "--porcelain", "--untracked-files=no")):
        raise ValueError("OWNER_SOURCE_REVISION_NOT_PINNED")
    source = repo / record["target"]
    test = repo / record["test"]
    for path, expected in ((source, record["source_sha256"]),
                           (test, record["test_sha256"])):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 262144:
            raise ValueError("OWNER_REVIEWED_FILE_UNAVAILABLE")
        relative = str(path.relative_to(repo))
        if git(repo, "ls-files", "--error-unmatch", "--", relative) != relative:
            raise ValueError("OWNER_REVIEWED_SOURCE_NOT_TRACKED")
        if sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError("OWNER_REVIEWED_SOURCE_CHANGED")
    # A reviewed PUBLIC_NONSECRET claim is necessary but never substitutes
    # for the limited sensitive-input scan of what would cross to MainPC.
    try:
        reviewed_source = source.read_text("utf-8")
    except UnicodeError:
        raise ValueError("OWNER_REVIEWED_SOURCE_ENCODING_INVALID") from None
    if (contains_sensitive_value(reviewed_source)
            or contains_sensitive_value(record["instruction"])):
        raise ValueError("OWNER_PUBLIC_EGRESS_DENIED")
    return record


def admit(ticket_id, *, expected_instruction_sha256=None, expected_root=None):
    from m1_development_bridge import require_m1
    require_m1()
    if os.getuid() != 501 or os.geteuid() != 501:
        raise PermissionError("M1_OWNER_SESSION_REQUIRED")
    _, config, data_root = installed_config()
    if expected_root is not None and Path(expected_root).resolve() != Path(data_root).resolve():
        raise PermissionError("SAME_OWNER_DEVELOPMENT_ROOT_REQUIRED")
    repo = _owner_local_repo()
    # Standing-scope delegation cannot select a new release worktree.
    # Only a previously saved, explicit owner review may be revalidated
    # against the physically installed immutable Operator source.
    review = data_root / "development" / "reviews" / (ticket_id + ".json")
    if review.exists() or review.is_symlink():
        from m1_development_review_candidate import select_review_repo
        repo = select_review_repo(data_root, repo, ticket_id,
                                  work_db=config.work_db)
    record = reviewed_contract(data_root, repo, ticket_id,
                               expected_instruction_sha256=expected_instruction_sha256)
    development = _private_dir(data_root / "development")
    lock = development / "reviewed-strata-install.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manifest = development / "tickets.json"
        document = _strict_json(_owner_manifest(manifest))
        if (type(document) is not dict or set(document) != {"version", "tickets"}
                or document.get("version") != 1 or type(document["tickets"]) is not list):
            raise ValueError("OWNER_TICKET_MANIFEST_INVALID")
        for item in document["tickets"]:
            _validate_ticket(item)
        existing = [item for item in document["tickets"]
                    if item["ticket_id"] == ticket_id]
        if existing:
            if existing == [record]:
                return {"status": "ALREADY_ADMITTED", "ticket_id": ticket_id,
                        "github_in_run_loop": False, "model_calls": 0}
            raise ValueError("OWNER_TICKET_CONTRACT_CHANGED")
        if len(document["tickets"]) >= MAX_OWNER_DEVELOPMENT_TICKETS:
            raise ValueError("OWNER_TICKET_CAPACITY_REACHED")
        document["tickets"].append(record)
        # Exactly one existing owner-private manifest: no new DB, port,
        # scheduler, model-provider or inference permit.
        write_private(manifest, json.dumps(document, indent=2, sort_keys=True) + "\n")
    finally:
        os.close(fd)
    return {"status": "TICKET_ADMITTED", "ticket_id": ticket_id,
            "github_in_run_loop": False, "model_calls": 0}

