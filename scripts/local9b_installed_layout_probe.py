#!/usr/bin/env python3
"""Read-only structural check of the installed 9B worker and its state root.

P4 releases deliberately separate immutable executable/source code from
the original queue inbox/results. Both paths are taken from the existing
owner-bound LaunchAgent, never from Issue/model text. No installed module
is imported, no script executed, no directory created, no host path exported.
"""
from __future__ import annotations

import ast
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from m1_runtime_status_probe import _worker_path, _worker_root, require_m1

STATE = ("inbox", "results")
MODULES = ("development_host.py", "development_loop.py", "host_compute_lease.py")
MAX_WORKER = 65536


def _root_contract(source: bytes) -> str:
    try:
        tree = ast.parse(source.decode("utf-8"))
    except (UnicodeDecodeError, SyntaxError):
        return "UNREADABLE_WORKER_SOURCE"
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "ROOT"
                   for target in node.targets):
            continue
        expr = ast.unparse(node.value)
        if expr == "Path(__file__).resolve().parent":
            return "LEGACY_SINGLE_ROOT"
        if ("configure_worker_paths(__file__" in expr
                and "AI_FOUNDATION_LOCAL9B_STATE_ROOT" in expr):
            return "P4_SEPARATE_STATE_ROOT"
    return "WORKER_ROOT_UNKNOWN"


def _status(path, kind):
    try:
        if path.is_symlink():
            return "UNTRUSTED_SYMLINK"
        meta = path.lstat()
        okay = ((stat.S_ISDIR(meta.st_mode) if kind == "dir"
                 else stat.S_ISREG(meta.st_mode))
                and meta.st_uid == os.getuid() and not meta.st_mode & 0o022)
        return "PRESENT" if okay else "UNTRUSTED_OR_WRONG_TYPE"
    except FileNotFoundError:
        return "MISSING"
    except (PermissionError, OSError):
        return "UNAVAILABLE"


def inspect_worker_layout(worker: Path, *, state_root: Path | None = None) -> dict:
    worker = Path(worker)
    meta = worker.lstat()
    if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
            or meta.st_mode & 0o022 or meta.st_size > MAX_WORKER):
        raise ValueError("UNTRUSTED_INSTALLED_WORKER")
    source = worker.read_bytes()
    if len(source) > MAX_WORKER:
        raise ValueError("OVERSIZE_INSTALLED_WORKER")
    mode = _root_contract(source)
    code = worker.parent
    state = code if state_root is None else Path(state_root)
    if mode == "P4_SEPARATE_STATE_ROOT" and state_root is None:
        raise ValueError("P4_STATE_ROOT_UNBOUND")
    if mode == "P4_SEPARATE_STATE_ROOT":
        package = code.parent / "src" / "ai_foundation"
    else:
        package = state / "modules" / "ai_foundation"
    observed = {"worker": _status(worker, "file"),
                "state_root": _status(state, "dir"),
                "code_root": _status(code, "dir"),
                "source_package": _status(package, "dir")}
    observed.update({name: _status(state / name, "dir") for name in STATE})
    observed.update({name: _status(package / name, "file") for name in MODULES})
    if mode == "P4_SEPARATE_STATE_ROOT":
        observed["worker_paths_helper"] = _status(code / "local9b_worker_paths.py", "file")
    blocked = (mode == "WORKER_ROOT_UNKNOWN" or
               mode == "UNREADABLE_WORKER_SOURCE" or
               any(value != "PRESENT" for value in observed.values()))
    return {
        "schema": "foundation-local9b-installed-layout/v2",
        "status": "LAYOUT_BLOCKED" if blocked else "STRUCTURE_OBSERVED",
        "worker_sha256": sha256(source).hexdigest(),
        "root_contract": mode,
        "code_state_separated": bool(state != code),
        "entries": observed,
        "model_invoked": False,
        "worker_executed": False,
        "filesystem_modified": False,
    }


def main():
    try:
        require_m1()
        home = Path.home()
        worker = _worker_path(home)
        state_root = _worker_root(home)
        result = inspect_worker_layout(worker, state_root=state_root)
        print("LOCAL9B_INSTALLED_LAYOUT=" +
              json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0 if result["status"] == "STRUCTURE_OBSERVED" else 2
    except (OSError, ValueError, TypeError) as exc:
        print("LOCAL9B_INSTALLED_LAYOUT=" + json.dumps({
            "status": "LAYOUT_UNAVAILABLE",
            "reason": type(exc).__name__.upper(),
            "model_invoked": False, "worker_executed": False,
            "filesystem_modified": False,
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
