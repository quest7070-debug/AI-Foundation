"""Read-only resolution of an already Guard-verified immutable KLM stage."""
from hashlib import sha256
import json
from pathlib import Path
import plistlib
import re

LABEL = "dev.quest7070.ai-foundation.klm-drive"
ENTRY = "scripts/klm_drive_host_tick.py"
MODULE = "src/ai_foundation/knowledge_lifecycle.py"


def staged_previous_root(plist_bytes, home, *, read_bytes, verify_stage, guard_accepts):
    """Resolve rollback source only; this never approves a new deployment."""
    def require(ok):
        if not ok:
            raise ValueError("PREVIOUS_KLM_STAGE_UNVERIFIED")
    row = plistlib.loads(plist_bytes)
    args = row.get("ProgramArguments")
    require(row.get("Label") == LABEL and row.get("StartInterval") == 900
            and type(args) is list and all(type(arg) is str for arg in args))
    entries = [Path(arg) for arg in args if arg.endswith("/" + ENTRY)]
    require(len(entries) == 1 and entries[0].is_absolute())
    root = entries[0].parents[1]
    stage = root.parent
    home = Path(home)
    parent = home / "Library/Application Support/AI-Foundation/operator-release-staging"
    require(root.name == "candidate" and stage.parent == parent
            and re.fullmatch(r"[0-9a-f]{64}", stage.name) is not None)
    for component in (root, *root.parents):
        require(not component.is_symlink())
        if component == home:
            break
    env = row.get("EnvironmentVariables")
    require(type(env) is dict and type(env.get("PYTHONPATH")) is str
            and env["PYTHONPATH"].split(":")[0] == str(root / "src")
            and env["PYTHONPATH"].count(str(root)) == 1)
    manifest = json.loads(read_bytes(stage / "manifest.json", max_bytes=2097152))
    commit = manifest.get("candidate_commit")
    require(manifest.get("scope_ref") == stage.name and type(commit) is str
            and re.fullmatch(r"[0-9a-f]{40}", commit) is not None)
    require(verify_stage(stage, stage.name) is True)
    source = read_bytes(root / MODULE, max_bytes=2097152)
    require(guard_accepts(commit, sha256(source).hexdigest()) is True)
    return root
