"""Read owner-private fidelity labels and independent review pins, aggregate only.

The authenticated native host fixes data_root. Under its existing owner data
root, human-model/fidelity/{reviews,contracts}.json are separate private JSON
documents, not model output or MCP arguments. The trusted owner review process
must independently provision contracts.json; this reader never generates pins,
labels, owner answers, consent or execution authority.

reviews.json: {"version": 1, "reviews": [evaluator review rows]}
contracts.json: {"version": 1, "review_contracts": {review_ref: row_sha256}}
The pin encoding is the canonical JSON contract of human_model_fidelity.py.
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import stat

from .human_model_fidelity import evaluate_owner_answer_fidelity

MAX_BYTES = 1024 * 1024


def _unique(pairs):
    row = {}
    for key, value in pairs:
        if key in row:
            raise ValueError("OWNER_REVIEW_JSON_AMBIGUOUS")
        row[key] = value
    return row


def _directory(path, *, parent=None, private=False):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    try:
        info = os.fstat(fd)
        if (info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode)
                or info.st_mode & (0o077 if private else 0o022)):
            raise PermissionError("OWNER_REVIEW_DIRECTORY_NOT_PRIVATE")
    except Exception:
        os.close(fd)
        raise
    return fd


def _document(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid()
                or before.st_mode & 0o077 or before.st_size > MAX_BYTES):
            raise PermissionError("OWNER_REVIEW_FILE_NOT_PRIVATE")
        chunks, total = [], 0
        while total <= MAX_BYTES:
            chunk = os.read(fd, min(65536, MAX_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        after = os.fstat(fd)
        if (total > MAX_BYTES or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
            raise ValueError("OWNER_REVIEW_FILE_CHANGED")
        raw = b"".join(chunks)
        row = json.loads(raw, object_pairs_hook=_unique)
        return row, raw
    finally:
        os.close(fd)


def _summary(status, reason=None):
    result = evaluate_owner_answer_fidelity(
        [], trusted_review_refs=[], trusted_review_contracts={})
    result.update(status=status, fidelity_evaluation_status=status,
                  source="OWNER_PRIVATE_REVIEW_CONTRACTS", model_calls=0,
                  native_effects=0)
    if reason is not None:
        result["reason"] = reason
    return result


def evaluate_owner_private_fidelity(data_root):
    """Native owner-only read adapter; paths, rows and pins never enter output.

    Absent owner reviews are NOT_EVALUATED. Insecure, malformed, changed or
    mismatched reviews are BLOCKED, not silently counted as a valid empty set.
    This is not an HTTP/MCP registration and must not accept a remote root.
    """
    try:
        root = Path(data_root)
        if not root.is_absolute() or ".." in root.parts:
            raise PermissionError("OWNER_DATA_ROOT_INVALID")
        with ExitStack() as stack:
            parent = _directory(root)
            stack.callback(os.close, parent)
            try:
                for child in ("human-model", "fidelity"):
                    parent = _directory(child, parent=parent, private=True)
                    stack.callback(os.close, parent)
                reviews, review_bytes = _document(parent, "reviews.json")
                pins, pin_bytes = _document(parent, "contracts.json")
            except FileNotFoundError:
                return _summary("NOT_EVALUATED", "OWNER_REVIEW_FILES_NOT_PROVIDED")
            if (type(reviews) is not dict or set(reviews) != {"version", "reviews"}
                    or type(reviews["version"]) is not int or reviews["version"] != 1
                    or type(pins) is not dict or set(pins) != {"version", "review_contracts"}
                    or type(pins["version"]) is not int or pins["version"] != 1
                    or type(pins["review_contracts"]) is not dict):
                raise ValueError("OWNER_REVIEW_DOCUMENT_INVALID")
            result = evaluate_owner_answer_fidelity(
                reviews["reviews"], trusted_review_refs=list(pins["review_contracts"]),
                trusted_review_contracts=pins["review_contracts"])
            # Revocation/replacement of either document during evaluation must
            # not yield a trusted sample from a stale pair of owner files.
            if (_document(parent, "reviews.json")[1] != review_bytes
                    or _document(parent, "contracts.json")[1] != pin_bytes):
                raise ValueError("OWNER_REVIEW_FILE_CHANGED")
            result.update(status=result["fidelity_evaluation_status"],
                          source="OWNER_PRIVATE_REVIEW_CONTRACTS", model_calls=0,
                          native_effects=0)
            return result
    except (OSError, ValueError, TypeError, RecursionError):
        # Exception details may include private paths or JSON fragments.
        return _summary("BLOCKED", "OWNER_REVIEW_FILES_OR_CONTRACTS_INVALID")
