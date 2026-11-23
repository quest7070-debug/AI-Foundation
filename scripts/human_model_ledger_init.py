"""Explicit one-time SQLite schema initialization on the verified external USB volume."""
from __future__ import annotations
import json
import sqlite3
import sys
from pathlib import Path
from human_model_ssd_provision import select_mount

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "human_model"))
from storage_location import validated_ledger_path
from human_model_ledger import Ledger

def initialize():
    mount = select_mount()
    path = validated_ledger_path(mount / "HumanModel")
    if path.exists() or path.is_symlink():
        raise RuntimeError("ledger already exists: refusing reinitialization")
    ledger = Ledger.open_external(mount / "HumanModel")
    try:
        row = ledger.db.execute("PRAGMA integrity_check").fetchone()
        tables = ledger.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        if row != ("ok",) or tables < 4:
            raise RuntimeError("new ledger failed integrity/schema verification")
    finally:
        ledger.close()
    return {"initialized": True, "external_usb": True, "integrity": "ok", "table_count": tables}

if __name__ == "__main__":
    print(json.dumps(initialize(), sort_keys=True))
