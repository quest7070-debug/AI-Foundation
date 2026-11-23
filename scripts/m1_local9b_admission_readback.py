"""Read-only independent M1 check of exact worker-only admission release.

No service/Guard mutation, no model call, no queue or source content output.
"""
from __future__ import annotations
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import pwd
import re
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import m1_local9b_admission_release as target


def readback():
    result = {
        "status": "BLOCKED",
        "operator_service_mutations": 0,
        "worker_service_mutations": 0,
        "model_calls": 0,
        "native_dispatches": 0,
        "release_permitted": False,
        "candidate_blob": target.CANDIDATE,
    }
    try:
        import platform
        target.require(platform.system() == "Darwin"
                       and platform.machine() == "arm64"
                       and os.getuid() == 501, "M1_REQUIRED")
        home = Path(pwd.getpwuid(os.getuid()).pw_dir)
        worker_plist = home / "Library/LaunchAgents" / (target.WORKER_LABEL + ".plist")
        raw = target.read_owned(worker_plist, 32768)
        row = plistlib.loads(raw)
        target.require(row.get("Label") == target.WORKER_LABEL,
                       "WORKER_LABEL_CHANGED")
        args = row["ProgramArguments"]
        matches = [x for x in args if type(x) is str
                   and x.endswith("/local9b_autodev_worker.py")]
        target.require(len(matches) == 1, "WORKER_ENTRY_UNVERIFIED")
        entry = Path(matches[0])
        info = target.launch("print", "gui/501/" + target.WORKER_LABEL)
        target.require(info.returncode == 0 and str(entry) in info.stdout,
                       "WORKER_LAUNCH_CONFIGURATION_UNKNOWN")
        queue = row.get("EnvironmentVariables", {}).get("AI_FOUNDATION_LOCAL9B_STATE_ROOT")
        target.require(type(queue) is str and Path(queue).is_absolute()
                       and all((Path(queue) / name).is_dir()
                               for name in ("inbox", "results")), "WORKER_QUEUE_ROOT_CHANGED")
        old = (target.sha(raw) == target.OLD_WORKER_PLIST
               and target.sha(target.read_owned(entry, 2097152)) == target.OLD_WORKER)
        if old:
            target.require(entry.parents[2].name == target.P4_SHA,
                           "WORKER_PRIOR_SOURCE_NOT_P4")
            reviewed = target.read_owned(
                ROOT / "scripts/m1_local9b_admission_candidate.py", 2097152)
            target.require_exact_worker_delta(
                target.read_owned(entry, 2097152), reviewed)
            git = subprocess.run(["/usr/bin/git", "-C", str(ROOT), "hash-object",
                                  "scripts/m1_local9b_admission_candidate.py"],
                                 capture_output=True, text=True, timeout=8, check=False)
            target.require(git.returncode == 0 and
                           git.stdout.strip() == target.CANDIDATE,
                           "WORKER_CANDIDATE_BLOB_CHANGED")
            report = {"status": "PRIOR_WORKER_OBSERVED",
                      "one_hunk_candidate_delta_verified": True,
                      "ready_for_owner_gated_review": True,
                      "worker_queue_root_preserved": True,
                      "prior_worker_source_verified": True}
        else:
            root = home / "Library/Application Support/AI-Foundation/local9b-admission-releases" / target.CANDIDATE
            target.require(entry == root / "repo/scripts/local9b_autodev_worker.py",
                           "INSTALLED_WORKER_SOURCE_UNRECOGNIZED")
            manifest_raw = target.read_owned(root / "manifest.json", 262144)
            manifest = json.loads(manifest_raw)
            target.require(manifest.get("candidate_blob") == target.CANDIDATE
                           and manifest.get("preserved_queue_root") == queue
                           and type(manifest.get("files")) is dict
                           and 30 <= len(manifest["files"]) <= 512,
                           "RELEASE_MANIFEST_INVALID")
            for name, expected in manifest["files"].items():
                path = Path(name)
                target.require(not path.is_absolute() and ".." not in path.parts
                               and path.parts[:1] == ("repo",) and path.suffix == ".py"
                               and target.sha(target.read_owned(root / path, 2097152)) == expected,
                               "RELEASE_SOURCE_CHANGED")
            target.require(target.read_owned(root / "prior.plist", 32768)
                           and target.sha(target.read_owned(root / "prior.plist", 32768))
                           == target.OLD_WORKER_PLIST, "PRIOR_BACKUP_CHANGED")
            proposal = target.read_owned(root / "proposed.plist", 32768)
            target.require(raw == proposal, "INSTALLED_PLIST_DRIFT")
            # Independently derive the same installed Operator's DB path.
            # Never instantiate SQLiteGuardStore: its constructor writes schema
            # state, which would violate this strictly read-only preflight.
            op_row = plistlib.loads(target.read_owned(
                home / "Library/LaunchAgents" / (target.OP_LABEL + ".plist"), 32768))
            op_args = op_row["ProgramArguments"]
            target.require(op_args.count("--config") == 1, "GUARD_CONFIG_UNBOUND")
            working = Path(op_row.get("WorkingDirectory", "/"))
            cfg_path = Path(op_args[op_args.index("--config") + 1])
            cfg_path = cfg_path if cfg_path.is_absolute() else working / cfg_path
            config = json.loads(target.read_owned(cfg_path, 65536))
            data = Path(config["data_dir"]).expanduser()
            if not data.is_absolute(): data = working / data
            db_name = Path(config.get("guard_db", "guard.db"))
            target.require(not db_name.is_absolute() and ".." not in db_name.parts,
                           "GUARD_DB_PATH_UNTRUSTED")
            db_path = data / db_name
            scope = target.scope()
            with sqlite3.connect(db_path.as_uri() + "?mode=ro",
                                 uri=True, timeout=2) as db:
                effect = db.execute("SELECT status,target FROM effects WHERE effect_id=?",
                                    ("release:" + scope.scope_ref,)).fetchone()
            target.require(effect == ("VERIFIED", "release-scope:" + scope.scope_ref),
                           "CANON_GUARD_EFFECT_NOT_VERIFIED")
            report = {"status": "APPLIED_VERIFIED",
                      "worker_queue_root_preserved": True,
                      "files_verified": len(manifest["files"]),
                      "prior_plist_backup_verified": True,
                      "guard_effect_verified": True,
                      "worker_launch_configuration_verified": True}
        result.update(report)
    except (OSError, ValueError, KeyError, TypeError, AttributeError,
            IndexError, sqlite3.Error, plistlib.InvalidFileException,
            subprocess.TimeoutExpired) as exc:
        result["reason"] = (str(exc) if isinstance(exc, target.Denied)
                            else "READBACK_UNAVAILABLE_" + type(exc).__name__)
    return result


if __name__ == "__main__":
    print(json.dumps(readback(), sort_keys=True))
