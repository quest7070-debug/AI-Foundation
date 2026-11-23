"""Read-only preflight against the *installed* Operator Guard state.

The positive-feature publisher may not manufacture a fresh empty GuardState
and call it the current production Guard. Read the exact owner-installed
Operator config and existing Guard SQLite using mode=ro/query_only, checking
only the current exact plan's cancellation and current zero-cost spending.
Never create or migrate Guard tables, grant approval, print private config
values, or edit the Operator database.
"""
from __future__ import annotations

import os
from pathlib import Path
import plistlib
import sqlite3
import stat
from urllib.parse import quote

from ai_foundation.core import GuardState, CanonContract
from ai_foundation.development_guard_admission import GuardAdmissionPort
from ai_foundation.guard import GuardCore
from ai_foundation.productization import load_config

_LABEL = "dev.quest7070.ai-foundation.operator"


class InstalledGuardUnavailable(ValueError):
    pass


def _existing_owner(path, *, directory=False):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink():
        raise InstalledGuardUnavailable("OWNER_GUARD_PATH_INVALID")
    try:
        info = path.lstat()
    except OSError:
        raise InstalledGuardUnavailable("OWNER_GUARD_PATH_MISSING") from None
    if (info.st_uid != os.getuid() or info.st_mode & 0o022 or
            (not stat.S_ISDIR(info.st_mode) if directory
             else not stat.S_ISREG(info.st_mode))):
        raise InstalledGuardUnavailable("OWNER_GUARD_FILE_UNTRUSTED")
    return path


def _installed_guard_database(home):
    home = Path(home)
    agent = _existing_owner(
        home / "Library" / "LaunchAgents" / (_LABEL + ".plist"))
    if agent.stat().st_size > 32768:
        raise InstalledGuardUnavailable("OPERATOR_PLIST_TOO_LARGE")
    try:
        row = plistlib.loads(agent.read_bytes())
        if row.get("Label") != _LABEL:
            raise ValueError("wrong label")
        argv = row.get("ProgramArguments")
        if (type(argv) is not list or len(argv) > 24
                or argv.count("--config") != 1):
            raise ValueError("wrong argv")
        config = _existing_owner(argv[argv.index("--config") + 1])
        if config.stat().st_size > 65536:
            raise ValueError("oversize config")
        cfg = load_config(str(config))
        root = _existing_owner(cfg.data_dir, directory=True)
        name = Path(cfg.guard_db)
        if (name.is_absolute() or ".." in name.parts
                or str(name) in ("", ".") or len(name.parts) != 1):
            raise ValueError("guard filename not fixed")
        db = _existing_owner(root / name)
        if db.stat().st_size > 1024 * 1024 * 1024:
            raise ValueError("unbounded guard DB")
        return db
    except InstalledGuardUnavailable:
        raise
    except (OSError, ValueError, KeyError, TypeError, plistlib.InvalidFileException):
        raise InstalledGuardUnavailable("OPERATOR_GUARD_CONFIG_UNVERIFIED") from None


class _LiveReadOnlyGuardStore:
    """Minimum store queries used by GuardCore.preflight, no migrations."""
    def __init__(self, db):
        self.db = _existing_owner(db)
        # Require exact existing schema, never initialize a new authority.
        with self._connect() as c:
            required = {"guard_meta", "cancellations"}
            present = {row[0] for row in c.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND "
                "name IN ('guard_meta','cancellations')")}
            if present != required:
                raise InstalledGuardUnavailable("GUARD_SCHEMA_UNVERIFIED")

    def _connect(self):
        # Use a read-only URI with SQL query-only. There is intentionally no
        # SQLiteGuardStore() construction (that would CREATE/ALTER tables).
        db_uri = self.db.resolve(strict=True).as_uri() + "?mode=ro"
        connection = sqlite3.connect(db_uri, uri=True, timeout=3.0)
        connection.execute("PRAGMA query_only=ON")
        return connection

    def spent(self):
        with self._connect() as db:
            row = db.execute(
                "SELECT value FROM guard_meta WHERE key='spent'").fetchone()
        if row is None or type(row[0]) is not int or row[0] < 0:
            raise InstalledGuardUnavailable("GUARD_SPENDING_UNVERIFIED")
        return row[0]

    def is_cancelled(self, run_id):
        if type(run_id) is not str or not run_id.startswith(
                "foundation-admission-") or len(run_id) != 53:
            raise InstalledGuardUnavailable("GUARD_RUN_ID_UNTRUSTED")
        with self._connect() as db:
            row = db.execute(
                "SELECT 1 FROM cancellations WHERE run_id=? LIMIT 1",
                (run_id,)).fetchone()
        return row is not None


def load_live_owner_admission(contract, *, home=None):
    """Exact host-provided scope only; return current Guard preflight port.

    This yields no new permission. The producer must still hold the shared M1
    lease and an eligible zero-yen, approved reviewed-branch contract, and
    read back Guard again at the final ready-Issue and queue boundary.
    """
    from ai_foundation.development_admission import HostContract
    if type(contract) is not HostContract:
        raise InstalledGuardUnavailable("HOST_CONTRACT_UNVERIFIED")
    owner = Path.home() if home is None else Path(home)
    db = _installed_guard_database(owner)
    store = _LiveReadOnlyGuardStore(db)
    core = GuardCore(GuardState(), store=store)
    return GuardAdmissionPort(
        core, CanonContract("code", "code-v1"),
        delegated_contracts=frozenset({contract}))
