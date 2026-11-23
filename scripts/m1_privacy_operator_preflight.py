"""Read-only installed Operator inventory for the no-model privacy fast path.

No Guard write, service restart, 9B dispatch, source copy or private text output.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import platform
import re
import stat
import subprocess
from urllib.request import ProxyHandler, build_opener

OPERATOR_LABEL = "dev.quest7070.ai-foundation.operator"
WORKER_LABEL = "dev.quest7070.ai-foundation.local9b-autodev"
FILES = ("guard.py", "inference_service.py", "human_model_context.py",
         "routed_agent_model.py", "sensitive_input_scan.py")
TARGET = "61612fb4edcadf6fc508cfbdd36ad6d559e99d11"


def checked(path, limit=1048576):
    item = Path(path)
    info = item.lstat()
    if not (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
            and not (info.st_mode & 0o022) and 0 < info.st_size <= limit):
        raise ValueError("UNTRUSTED_RELEASE_FILE")
    return item.read_bytes()


def service(home, label):
    raw = checked(home / "Library/LaunchAgents" / (label + ".plist"), 32768)
    row = plistlib.loads(raw)
    args = row.get("ProgramArguments")
    if row.get("Label") != label or type(args) is not list or len(args) > 24:
        raise ValueError("SERVICE_BINDING_CHANGED")
    paths = [Path(arg) for arg in args
             if type(arg) is str and arg.startswith("/") and arg.endswith(".py")]
    if len(paths) != 1:
        raise ValueError("SERVICE_ENTRY_UNVERIFIED")
    entry = paths[0]
    source = checked(entry)
    result = subprocess.run(["/bin/launchctl", "print", "gui/" + str(os.getuid()) + "/" + label],
                            capture_output=True, text=True, timeout=8, check=False)
    if result.returncode:
        raise ValueError("SERVICE_LAUNCHD_UNAVAILABLE")
    pid = re.search(r"^\s*pid = ([0-9]+)\s*$", result.stdout, re.M)
    return {"definition_sha256": sha256(raw).hexdigest(),
            "entry_sha256": sha256(source).hexdigest(),
            "entry_name": entry.name,
            "loaded_entry_present": str(entry) in result.stdout,
            "running": pid is not None,
            "pid": int(pid.group(1)) if pid else None,
            "_path": entry, "_row": row}


def audit(home, repo_root):
    out = {"status": "BLOCKED", "target_sha": TARGET,
           "release_permitted": False, "service_mutations": 0,
           "model_calls": 0, "native_dispatches": 0}
    try:
        if platform.system() != "Darwin" or platform.machine() != "arm64" or os.getuid() != 501:
            raise ValueError("M1_OWNER_REQUIRED")
        op = service(home, OPERATOR_LABEL)
        worker = service(home, WORKER_LABEL)
        if op["entry_name"] == "launcher.py":
            # Independent, immutable post-release verification for the exact
            # one-service overlay. No Guard data or personal source is read.
            release = op["_path"].parent
            if release.name != TARGET[:12]:
                raise ValueError("UNRECOGNIZED_RELEASE_LOCATION")
            raw = checked(release / "manifest.json", 262144)
            manifest = json.loads(raw)
            if manifest.get("schema") != 1 or manifest.get("candidate_sha") != TARGET:
                raise ValueError("CANDIDATE_RELEASE_MISMATCH")
            old = checked(release / "prior.plist", 32768)
            if sha256(old).hexdigest() != "9bb6decbf24ef6710a318e2cb2a4f681d6fceff81ad8b8e228899aa49b58dc03":
                raise ValueError("PRIOR_BACKUP_UNVERIFIED")
            files = manifest.get("files")
            if type(files) is not dict or not 1 <= len(files) <= 512:
                raise ValueError("SOURCE_MANIFEST_INVALID")
            for name, digest in files.items():
                p = Path(name)
                if p.is_absolute() or ".." in p.parts or p.parts[:2] != ("src", "ai_foundation"):
                    raise ValueError("SOURCE_MANIFEST_PATH_INVALID")
                if sha256(checked(release / p)).hexdigest() != digest:
                    raise ValueError("RELEASE_SOURCE_DRIFT")
            launcher_sha = sha256(checked(op["_path"])).hexdigest()
            if launcher_sha != manifest.get("launcher_sha256"):
                raise ValueError("RELEASE_LAUNCHER_CHANGED")
            # This is an *Operator* post-release readback. The worker may be
            # updated later under its own Guard-pinned release (#561).
            # Still require registered/loaded worker identity, but do not
            # falsely invalidate the Operator because an unrelated service
            # has an independently approved new plist/source version.
            worker_bound = bool(worker["loaded_entry_present"])
            with build_opener(ProxyHandler({})).open(
                "http://127.0.0.1:8766/internal/privacy-fastpath-release", timeout=3) as response:
                proof = json.loads(response.read(8192))
            proof_ok = (op["running"] and op["loaded_entry_present"]
                        and worker_bound
                        and proof.get("pid") == op["pid"]
                        and proof.get("candidate_sha") == TARGET
                        and proof.get("manifest_sha256") == sha256(raw).hexdigest()
                        and proof.get("startup_sources_verified") is True)
            out.update(status="OBSERVED" if proof_ok else "BLOCKED",
                       loaded_operator_verified=bool(proof_ok),
                       operator_package_files_verified=len(files),
                       exact_prior_plist_backup_verified=True,
                       worker_service_identity_observed=worker_bound,
                       worker_version_attested_by_this_probe=False,
                       operator_source_sha=TARGET)
            return out
        if op["entry_name"] != "m1_p4_operator_launcher.py":
            allowed = {"human_model_operator_launcher.py": "HUMANMODEL_WRAPPER",
                       "operator_server.py": "DIRECT_OPERATOR"}
            kind = allowed.get(op["entry_name"], "UNKNOWN")
            out.update(reason="DEPLOYED_OPERATOR_LAYOUT_CHANGED",
                       operator_entry_kind=kind,
                       current_operator_plist_sha256=op["definition_sha256"],
                       current_operator_entry_sha256=op["entry_sha256"],
                       operator_loaded_entry_present=op["loaded_entry_present"],
                       worker_plist_sha256=worker["definition_sha256"],
                       worker_loaded_entry_present=worker["loaded_entry_present"])
            if kind == "DIRECT_OPERATOR":
                # Prove where the currently registered direct launcher would
                # import modules from; hash only fixed names, never source text.
                package = op["_path"].parent.parent / "src/ai_foundation"
                values = op["_row"].get("EnvironmentVariables", {})
                pythonpath = values.get("PYTHONPATH", "")
                pkg_bound = type(pythonpath) is str and str(package.parent) in pythonpath.split(os.pathsep)
                hashes = {}
                for name in FILES:
                    target = package / name
                    current = sha256(checked(target)).hexdigest() if target.exists() else "ABSENT"
                    candidate = sha256(checked(repo_root / "src/ai_foundation" / name)).hexdigest()
                    hashes[name] = {"installed": current, "candidate": candidate,
                                    "equal": current == candidate}
                out.update(operator_pythonpath_bound=pkg_bound,
                           installed_package_file_hashes=hashes)
            return out
        root = op["_path"].parents[2]
        manifest_raw = checked(root / "manifest.json", 65536)
        manifest = json.loads(manifest_raw)
        if (not isinstance(manifest.get("candidate_sha"), str)
                or not re.fullmatch("[a-f0-9]{40}", manifest["candidate_sha"])
                or not isinstance(manifest.get("files"), dict)):
            raise ValueError("INSTALLED_MANIFEST_INVALID")
        hashes = {}
        files = manifest["files"]
        for name in FILES:
            key = "repo/src/ai_foundation/" + name
            candidate = checked(repo_root / "src/ai_foundation" / name)
            candidate_sha = sha256(candidate).hexdigest()
            stored = files.get(key)
            if stored is not None:
                installed = checked(root / key)
                if sha256(installed).hexdigest() != stored:
                    raise ValueError("INSTALLED_SOURCE_DRIFT")
            hashes[name] = {"installed": stored or "ABSENT", "candidate": candidate_sha,
                            "equal": stored == candidate_sha}
        proof_ok = False
        if op["running"]:
            opener = build_opener(ProxyHandler({}))
            with opener.open("http://127.0.0.1:8766/internal/p4-release", timeout=3) as response:
                proof = json.loads(response.read(4097))
            proof_ok = (proof.get("candidate_sha") == manifest["candidate_sha"]
                        and proof.get("pid") == op["pid"]
                        and proof.get("manifest_sha256") == sha256(manifest_raw).hexdigest()
                        and proof.get("startup_sources_verified") is True)
        state_root = worker["_row"].get("EnvironmentVariables", {}).get("AI_FOUNDATION_LOCAL9B_STATE_ROOT")
        worker_state_ok = (type(state_root) is str and Path(state_root).is_absolute()
                           and Path(state_root).is_dir()
                           and all((Path(state_root) / name).is_dir() for name in ("inbox", "results")))
        out.update(status="OBSERVED" if proof_ok and worker_state_ok
                   and op["loaded_entry_present"] and worker["loaded_entry_present"] else "BLOCKED",
                   installed_operator_release=manifest["candidate_sha"],
                   installed_source_manifest_verified=True, loaded_operator_verified=proof_ok,
                   current_operator_plist_sha256=op["definition_sha256"],
                   current_operator_entry_sha256=op["entry_sha256"],
                   worker_unchanged_candidate=True,
                   worker_queue_root_preserved=bool(worker_state_ok),
                   worker_plist_sha256=worker["definition_sha256"],
                   files=hashes)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.TimeoutExpired,
            plistlib.InvalidFileException) as exc:
        out["reason"] = str(exc) if isinstance(exc, ValueError) and str(exc).isupper() else "HOST_INVENTORY_UNAVAILABLE"
    return out


if __name__ == "__main__":
    print(json.dumps(audit(Path.home(), Path(__file__).resolve().parents[1]), sort_keys=True))
