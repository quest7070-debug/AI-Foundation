"""Read the installed Guard's exact current cancellation without creating grants."""
from pathlib import Path
import json
import os
import plistlib
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ai_foundation.development_admission import HostContract
from m1_owner_live_guard_preflight import (
    InstalledGuardUnavailable, load_live_owner_admission,
)


def fixture(tmp_path):
    home = tmp_path.resolve()
    path = home / "Library" / "LaunchAgents"
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    root = home / "owner-data"
    root.mkdir(mode=0o700)
    db = root / "guard.db"
    with sqlite3.connect(db) as conn:
        conn.executescript("""
        CREATE TABLE guard_meta(key TEXT PRIMARY KEY,value INTEGER NOT NULL);
        INSERT INTO guard_meta VALUES ('spent',0);
        CREATE TABLE cancellations(run_id TEXT PRIMARY KEY);
        """)
    db.chmod(0o600)
    cfg = home / "config.json"
    cfg.write_text(json.dumps({"schema_version":1,"data_dir":str(root)}))
    cfg.chmod(0o600)
    agent = path / "dev.quest7070.ai-foundation.operator.plist"
    agent.write_bytes(plistlib.dumps({
        "Label":"dev.quest7070.ai-foundation.operator",
        "ProgramArguments":["/usr/bin/python3","/opt/operator.py","--config",
                            str(cfg),"--port","8766"],
    }))
    agent.chmod(0o600)
    contract = HostContract("draft_code",
        "src/ai_foundation/literal_code_search.py", "a"*64,
        1024,1024,0.1,"development:fixed-test")
    return home, db, cfg, agent, contract


def test_current_owner_guard_exact_plan_can_preflight_but_not_grant(tmp_path):
    home, db, cfg, agent, contract = fixture(tmp_path)
    before = db.read_bytes()
    guard = load_live_owner_admission(contract, home=home)
    assert guard.authorize(contract,"reviewedownerplan123","f"*64) == "ALLOW"
    assert db.read_bytes() == before
    assert not list(home.glob("**/*.db-wal"))


def test_current_cancellation_denies_without_cached_approval(tmp_path):
    home, db, cfg, agent, contract = fixture(tmp_path)
    guard = load_live_owner_admission(contract, home=home)
    assert guard.authorize(contract,"reviewedownerplan123","e"*64) == "ALLOW"
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO cancellations VALUES (?)",
                     ("foundation-admission-" + "e"*32,))
    # Same port reads the *current* SQLite value at every exact preflight.
    assert guard.authorize(contract,"reviewedownerplan123","e"*64) == "DENY"
    assert guard.authorize(contract,"reviewedownerplan123","f"*64) == "ALLOW"


def test_untrusted_operator_binding_never_falls_back_to_empty_guard(tmp_path):
    home, db, cfg, agent, contract = fixture(tmp_path)
    agent.unlink()
    with pytest.raises(InstalledGuardUnavailable):
        load_live_owner_admission(contract, home=home)
    agent.symlink_to(cfg)
    with pytest.raises(InstalledGuardUnavailable):
        load_live_owner_admission(contract, home=home)


def test_missing_schema_does_not_initialize_guard_or_authority(tmp_path):
    home, db, cfg, agent, contract = fixture(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE cancellations")
    existing = db.read_bytes()
    with pytest.raises(InstalledGuardUnavailable):
        load_live_owner_admission(contract, home=home)
    assert db.read_bytes() == existing


def test_group_writable_config_blocks_current_guard_claim(tmp_path):
    home, db, cfg, agent, contract = fixture(tmp_path)
    cfg.chmod(0o666)
    with pytest.raises(InstalledGuardUnavailable):
        load_live_owner_admission(contract, home=home)
