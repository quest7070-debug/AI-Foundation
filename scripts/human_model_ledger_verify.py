"""Read-only verification of an existing HumanModel SQLite ledger on the M1 USB volume."""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from human_model_ssd_provision import select_mount

def verify():
    from sys import path as sys_path
    sys_path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "human_model"))
    from storage_location import validated_ledger_path
    from human_model_management_audit import audit_ledger
    db_path = validated_ledger_path(select_mount() / "HumanModel")
    if not db_path.is_file():
        raise RuntimeError("ledger does not exist")
    # Read-only URI prevents accidental DB creation or writes.
    con = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
    try:
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        names = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"evidence", "model_views", "model_sources", "change_log"}
        if integrity != "ok" or not required.issubset(names):
            raise RuntimeError("ledger schema or integrity invalid")
        count = con.execute("SELECT COUNT(*) FROM evidence").fetchone()[0]
        audit = audit_ledger(con)
        return {"external_usb": True, "read_only": True, "integrity": integrity,
                "schema_verified": True, "evidence_count": count,
                "human_model_management": audit}
    finally:
        con.close()

if __name__ == "__main__":
    result = verify()
    print(json.dumps(result, sort_keys=True))
    # Audit is structural and read-only, never actor/consent authority.
    if result["human_model_management"]["status"] in {
            "INTEGRITY_FAILED", "SCHEMA_UNAVAILABLE", "COVERAGE_INCOMPLETE",
            "STRUCTURE_INVALID", "AUDIT_UNAVAILABLE"}:
        raise SystemExit(2)
