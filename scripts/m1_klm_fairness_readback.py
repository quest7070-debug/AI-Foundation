#!/usr/bin/env python3
"""Independent, no-effect verification of the pinned KLM fairness LaunchAgent."""
from __future__ import annotations

from hashlib import sha1
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import stat
import subprocess

OLD = "398592a317afc18dad7b1e55c3458324bb15889c"
NEW = "799a1ad8a0584da6e2a852a363e5edfd61454bf8"
LABEL = "dev.quest7070.ai-foundation.klm-drive"
ENTRY = "scripts/klm_drive_host_tick.py"
BLOBS = {
    ENTRY: "cb642dc679c8de3f719e5797aca7167a4dcbe131",
    "src/ai_foundation/klm_drive_work.py": "0536eea6be8a6f4b5cb2c38870500890065bf4d6",
    "src/ai_foundation/klm_9b_handler.py": "6f92ea5ebd9d5b67fdcc85484e43d3ae85b63676",
    "src/ai_foundation/klm_llmperks_source.py": "c6fbcfcef2241ae0718e6c5b1655c2b8ecf5c73a",
}


class ReadbackDenied(ValueError):
    pass


def insist(condition, code):
    if not condition:
        raise ReadbackDenied(code)


def bounded_owner_file(path, *, maximum, private=False):
    fd = os.open(str(path), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        meta = os.fstat(fd)
        insist(stat.S_ISREG(meta.st_mode) and meta.st_uid == os.getuid()
               and not (meta.st_mode & (0o077 if private else 0o022))
               and 0 < meta.st_size <= maximum, "READBACK_FILE_UNTRUSTED")
        raw = os.read(fd, maximum + 1)
        insist(len(raw) <= maximum, "READBACK_FILE_TOO_LARGE")
        return raw
    finally:
        os.close(fd)


def blob(raw):
    return sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()


def readback(*, home=None):
    insist(platform.system() == "Darwin" and platform.machine() == "arm64"
           and os.getuid() == 501, "EXACT_M1_OWNER_REQUIRED")
    home = Path.home() if home is None else Path(home)
    releases = home / "Library/Application Support/AI-Foundation/klm-drive/releases"
    new = releases / NEW
    plist = home / "Library/LaunchAgents" / (LABEL + ".plist")
    installed = plistlib.loads(bounded_owner_file(plist, maximum=32768))
    insist(installed.get("Label") == LABEL and installed.get("StartInterval") == 900,
           "KLM_SERVICE_IDENTITY_DRIFT")
    args = installed.get("ProgramArguments")
    env = installed.get("EnvironmentVariables")
    insist(type(args) is list and type(env) is dict
           and sum(x == str(new / ENTRY) for x in args if type(x) is str) == 1,
           "KLM_ACTIVE_RELEASE_NOT_EXPECTED")
    py_path = env.get("PYTHONPATH")
    insist(type(py_path) is str and py_path.count(NEW) == 1
           and OLD not in py_path, "KLM_PYTHONPATH_DRIFT")
    previous = plistlib.loads(bounded_owner_file(
        new / "previous-klm-launchagent.plist", maximum=32768, private=True))
    expected = dict(previous)
    prior_args = previous.get("ProgramArguments")
    prior_env = previous.get("EnvironmentVariables")
    insist(previous.get("Label") == LABEL and previous.get("StartInterval") == 900
           and type(prior_args) is list and type(prior_env) is dict
           and sum(x == str(releases / OLD / ENTRY)
                   for x in prior_args if type(x) is str) == 1,
           "KLM_PREVIOUS_BACKUP_INVALID")
    old_py = prior_env.get("PYTHONPATH")
    insist(type(old_py) is str and old_py.count(OLD) == 1,
           "KLM_PREVIOUS_PYTHONPATH_INVALID")
    expected["ProgramArguments"] = [
        arg.replace(OLD, NEW) if type(arg) is str else arg for arg in prior_args]
    expected["EnvironmentVariables"] = {
        **prior_env, "PYTHONPATH": old_py.replace(OLD, NEW)}
    insist(installed == expected, "KLM_UNRELATED_SERVICE_CONFIG_CHANGED")
    insist(new.is_dir() and not new.is_symlink(), "NEW_RELEASE_DIRECTORY_UNTRUSTED")
    for name, expected_blob in BLOBS.items():
        raw = bounded_owner_file(new / name, maximum=1048576)
        insist(blob(raw) == expected_blob, "NEW_RELEASE_PINNED_SOURCE_DRIFT")
    git = subprocess.run(
        ["/usr/bin/git", "-C", str(new), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=8, check=False)
    insist(git.returncode == 0 and git.stdout.strip() == NEW,
           "NEW_RELEASE_GIT_HEAD_DRIFT")
    launch = subprocess.run(["/bin/launchctl", "print", "gui/501/" + LABEL],
                            capture_output=True, text=True, timeout=16, check=False)
    insist(launch.returncode == 0 and str(new / ENTRY) in launch.stdout,
           "KLM_SERVICE_NOT_REGISTERED_TO_PIN")
    return {
        "status": "APPLIED_VERIFIED", "release_sha": NEW,
        "previous_release_sha": OLD, "service": LABEL,
        "interval_seconds": 900, "rollback_backup_preserved": True,
        "service_definition_unrelated_changes": False,
        "pinned_files_read_back": len(BLOBS),
        "model_calls": 0, "new_database": False,
        "owner_data_writes": 0,
    }


def main():
    try:
        result = readback()
        print("KLM_FAIRNESS_READBACK=" + json.dumps(result, sort_keys=True))
    except Exception as exc:
        code = str(exc) if type(exc) is ReadbackDenied else "UNEXPECTED_" + type(exc).__name__
        print("KLM_FAIRNESS_READBACK=" + json.dumps(
            {"status": "BLOCKED", "reason": code, "model_calls": 0,
             "owner_data_writes": 0}, sort_keys=True))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
