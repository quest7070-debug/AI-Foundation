"""Read the source-reviewed service research ledger at Operator bootstrap.

This is a bounded read-only projection from a fixed repository path, *not*
a dynamic provider-discovery agent and never an execution/admission authority.
Missing/corrupt/replaced data is omitted, leaving runtime routes unchanged.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

MAX_RESEARCH_BYTES = 128 * 1024
MAX_RESEARCH_ITEMS = 100
_SERVICE_ID = re.compile(r"[a-z][a-z0-9-]{0,79}\Z")


def load_harness_research_ledger(repository_root):
    """Return validated research-only ledger, or None (never infer approval)."""
    path = Path(repository_root) / "docs/data/free_ai_route_candidates_20261109.json"
    try:
        if not path.is_file() or path.is_symlink():
            return None
        if path.stat().st_size > MAX_RESEARCH_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError):
        return None
    if (type(data) is not dict or data.get("deployment_state") != "RESEARCH_ONLY"
            or data.get("default_route_enabled") is not False):
        return None
    records = data.get("services")
    if type(records) is not list or not 0 < len(records) <= MAX_RESEARCH_ITEMS:
        return None
    names = set()
    for record in records:
        if type(record) is not dict:
            return None
        sid = record.get("id")
        if (type(sid) is not str or not _SERVICE_ID.fullmatch(sid)
                or sid in names or record.get("enabled") is not False
                or type(record.get("name")) is not str
                or not 0 < len(record["name"]) <= 160
                or type(record.get("route_kind")) is not str
                or not 0 < len(record["route_kind"]) <= 64):
            return None
        names.add(sid)
    return data
