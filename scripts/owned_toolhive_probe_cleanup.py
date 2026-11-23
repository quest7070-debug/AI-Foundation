#!/usr/bin/env python3
"""Fail-closed Docker cleanup for one uniquely named ToolHive CI probe.

Only exact run-scoped ToolHive workload names and their verified DNS/egress
helpers are eligible. This helper never operates on canonical production names
and never uses a shell or guesses ownership from a name alone.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess


_PROBE = re.compile(r"foundation-files-pr183-[1-9][0-9]*-[1-9][0-9]*\Z")
_HELPERS = ("-dns", "-egress")


class ProbeIdentityError(RuntimeError):
    """Owned probe identity could not be established; no deletion is safe."""


def _docker(args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["docker", *args], capture_output=True, text=True, timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProbeIdentityError("DOCKER_COMMAND_UNAVAILABLE") from exc
    if result.returncode:
        # Do not echo potentially private Docker output into CI.
        raise ProbeIdentityError("DOCKER_COMMAND_FAILED")
    return result.stdout


def owned_family(server: str, command=_docker) -> list[str]:
    """Validate every similarly named container before permitting any deletion."""
    if not _PROBE.fullmatch(server):
        raise ProbeIdentityError("INVALID_RUN_SCOPED_PROBE_NAME")
    names = command(["container", "ls", "-a", "--format", "{{.Names}}"]).splitlines()
    if len(names) > 2000 or len(names) != len(set(names)):
        raise ProbeIdentityError("DOCKER_INVENTORY_AMBIGUOUS")
    family = sorted(n for n in names if n == server or n.startswith(server + "-"))
    allowed = {server, *(server + suffix for suffix in _HELPERS)}
    if any(n not in allowed for n in family):
        raise ProbeIdentityError("UNEXPECTED_PROBE_FAMILY_MEMBER")
    # Validate the whole family first: an unowned helper must not lead to partial deletion.
    for name in family:
        raw = command(["container", "inspect", "--format", "{{json .Config.Labels}}", name])
        try:
            labels = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise ProbeIdentityError("PROBE_LABELS_INVALID") from exc
        if not isinstance(labels, dict) or labels.get("toolhive") != "true" or labels.get("toolhive-name") != server:
            raise ProbeIdentityError("PROBE_OWNERSHIP_UNVERIFIED")
        auxiliary = labels.get("toolhive-auxiliary-workload") == "true"
        if auxiliary != (name != server):
            raise ProbeIdentityError("PROBE_AUXILIARY_LABEL_MISMATCH")
    return family


def preflight(server: str, command=_docker) -> None:
    if owned_family(server, command):
        raise ProbeIdentityError("PROBE_IDENTITY_ALREADY_EXISTS")


def cleanup(server: str, command=_docker) -> int:
    family = owned_family(server, command)
    for name in family:
        # "rm" is limited to a fully validated unique probe identity, never production.
        command(["container", "rm", "--force", name])
    if owned_family(server, command):
        raise ProbeIdentityError("PROBE_FAMILY_CLEANUP_INCOMPLETE")
    return len(family)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("preflight", "cleanup"))
    parser.add_argument("server")
    args = parser.parse_args()
    try:
        if args.operation == "preflight":
            preflight(args.server)
            print("FILES_PROBE_IDENTITY_FREE")
        else:
            removed = cleanup(args.server)
            print(f"FILES_PROBE_OWNED_FAMILY_ABSENT removed={removed}")
    except ProbeIdentityError as exc:
        print(f"::error::{exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
