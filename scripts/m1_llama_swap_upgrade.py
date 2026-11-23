"""Read-only, narrow M1 llama-swap v272 upgrade preflight.

Never emit model names, file paths, private config, model bytes or shell output.
The exact plist is existing Foundation owner runtime; this probe never changes
homebrew, model processes, manifests, Guard or launchd.
"""
from __future__ import annotations
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess

OWNER_LABEL = "dev.quest7070.ai-foundation.llama-swap"
EXECUTABLE = Path("/opt/homebrew/bin/llama-swap")
HOMEBREW = Path("/opt/homebrew/bin/brew")
RELATIVE_MANIFEST = Path("Library/Application Support/AI-Foundation/local-compute/llama-swap.yaml")
LATEST_RELEASE = "v272"
LATEST_ARM64_SHA256 = "ee16e99873d76e0560000742d2524d7b97932c77c9b57a402283015839ef9d25"


def owner_regular(path, *, limit):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or not 0 < info.st_size <= limit):
        raise ValueError("OWNER_SOURCE_UNTRUSTED")
    return path.read_bytes()



def gguf_header_plausible(path):
    """Bounded, read-only sanity check; never proof of original model identity.

    An empty placeholder or tiny lookalike must not satisfy a model cutover
    preflight. Full model provenance and host Guard admission stay separate.
    """
    try:
        # Do not follow a symlink swapped in after a separate lstat check.
        # fstat the actual opened descriptor; read only the fixed header.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size < 1024 * 1024:
                return False
            header = os.read(fd, 24)
        finally:
            os.close(fd)
    except OSError:
        return False
    return (len(header) == 24 and header[:4] == b"GGUF"
            and int.from_bytes(header[4:8], "little") == 3
            and 0 < int.from_bytes(header[8:16], "little") <= 12000
            and int.from_bytes(header[16:24], "little") <= 10000)

def fixed_command(args, *, max_bytes=500):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=10,
                                env={"PATH": "/opt/homebrew/bin:/usr/bin:/bin",
                                     "HOME": str(Path.home())})
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or len(result.stdout) > max_bytes:
        return None
    return result.stdout.strip()


def _running_version():
    """llama-swap's own read-only version endpoint, not the Homebrew symlink."""
    import http.client
    import json
    connection = http.client.HTTPConnection("127.0.0.1", 9292, timeout=3)
    try:
        connection.request("GET", "/api/version",
                           headers={"Host": "127.0.0.1", "Accept": "application/json"})
        response = connection.getresponse()
        if response.status != 200:
            return "UNVERIFIED"
        data = response.read(2049)
        if len(data) > 2048:
            return "UNVERIFIED"
        row = json.loads(data)
        version = row.get("version") if type(row) is dict else None
        if type(version) is str and re.fullmatch(r"v?[0-9]{1,4}", version):
            return "v" + version.lstrip("v")
        return "UNVERIFIED"
    except (OSError, ValueError, TypeError):
        return "UNVERIFIED"
    finally:
        connection.close()


def _artifact_roots(artifacts, home):
    """Classify missing original paths without exporting any owner filesystem path.

    A different mount or owner home never authorizes an inferred substitute.
    """
    home = Path(home).resolve()
    counts = {"CURRENT_HOME": 0, "OTHER_USER_HOME": 0,
              "REMOVABLE_VOLUME": 0, "OTHER_ABSOLUTE": 0}
    source_volumes_present = 0
    exact_home_rebase_candidates = 0
    for p in artifacts.values():
        path = Path(p)
        parts = path.parts
        if path.is_relative_to(home):
            counts["CURRENT_HOME"] += 1
        elif len(parts) >= 4 and parts[:2] == ("/", "Users"):
            counts["OTHER_USER_HOME"] += 1
            candidate = home.joinpath(*parts[3:])
            try:
                stat_info = candidate.lstat()
                if (stat.S_ISREG(stat_info.st_mode)
                        and stat_info.st_uid == os.getuid()
                        and stat_info.st_size > 1048576):
                    exact_home_rebase_candidates += 1
            except OSError:
                pass
        elif len(parts) >= 3 and parts[:2] == ("/", "Volumes"):
            counts["REMOVABLE_VOLUME"] += 1
            source_volumes_present += int(
                Path("/Volumes", parts[2]).is_dir()
                and os.path.ismount(Path("/Volumes", parts[2])))
        else:
            counts["OTHER_ABSOLUTE"] += 1
    known_roots = {
        "OLLAMA_BLOBS": home / ".ollama/models/blobs",
        "HUGGINGFACE_CACHE": home / ".cache/huggingface/hub",
        "OWNER_MODELS": home / "Models",
        "FOUNDATION_MODELS": home / "Library/Application Support/AI-Foundation/models",
    }
    return {
        "configured_path_classes": counts,
        "mounted_configured_volumes": source_volumes_present,
        "same_suffix_existing_owner_files": exact_home_rebase_candidates,
        "existing_known_model_roots": {
            key: path.is_dir() and not path.is_symlink()
            for key, path in known_roots.items()
        },
        "resolution_granted": False,
    }



def runtime_cutover_preconditions(observed):
    """Source-only gate: never grants a model stop, service restart or Guard approval."""
    block = lambda reason: {"status": "BLOCKED", "reason": reason,
                            "runtime_restart_authorized": False}
    if observed.get("ready_for_fixed_upgrade") is not True:
        return block("INSTALLED_OWNER_CONFIGURATION_UNVERIFIED")
    if (observed.get("installed_version") != LATEST_RELEASE
            or observed.get("brew_formula_version") != "272"):
        return block("V272_BINARY_NOT_INSTALLED")
    count = observed.get("declared_model_paths")
    if type(count) is not int or not 1 <= count <= 32:
        return block("MODEL_MANIFEST_UNVERIFIED")
    if (type(observed.get("artifact_missing")) is not int
            or observed["artifact_missing"] != 0
            or observed.get("artifact_found") != count
            or observed.get("artifact_parents_existing") != count):
        return block("MODEL_ARTIFACTS_MISSING")
    if (observed.get("all_declared_absolute") is not True
            or observed.get("artifact_symlinks") != 0):
        return block("MODEL_PATH_IDENTITY_UNVERIFIED")
    if observed.get("gguf_headers_plausible") != count:
        return block("MODEL_GGUF_HEADER_UNVERIFIED")
    live = observed.get("live_runtime_version")
    if live == LATEST_RELEASE:
        return {"status": "ALREADY_CURRENT_BINARY", "reason": "LIVE_V272",
                "runtime_restart_authorized": False}
    if live != "v256":
        return block("LIVE_PROCESS_VERSION_UNVERIFIED")
    # Header plausibility (even with a 1 MiB size floor) cannot establish
    # original model identity: a padded synthetic header passes that check.
    # This read-only probe has no independent owner-pinned model hashes.
    # Never turn format evidence into a restored-originals acceptance.
    return block("MODEL_ORIGINAL_IDENTITY_UNVERIFIED")


def audit(*, home=None, inspect_version=fixed_command):
    if __package__:
        from .m1_development_bridge import require_m1
    else:
        from m1_development_bridge import require_m1
    require_m1()
    home = Path.home() if home is None else Path(home)
    manifest = home / RELATIVE_MANIFEST
    path = home / "Library/LaunchAgents" / (OWNER_LABEL + ".plist")
    result = {"status": "UPGRADE_AUDIT", "target": LATEST_RELEASE,
              "model_calls": 0, "service_mutations": 0, "guard_effects": 0,
              "expected_asset_sha256": LATEST_ARM64_SHA256}
    try:
        plist = plistlib.loads(owner_regular(path, limit=32768))
        args = plist.get("ProgramArguments")
        if (plist.get("Label") != OWNER_LABEL or type(args) is not list
                or not all(type(a) is str and 0 < len(a) <= 4096 for a in args)):
            raise ValueError("PLIST_IDENTITY_MISMATCH")
        result["launchd_binary_exact"] = args[0] == str(EXECUTABLE)
        result["launchd_manifest_exact"] = str(manifest) in args
    except (OSError, ValueError, plistlib.InvalidFileException, IndexError):
        result["status"] = "PLIST_UNVERIFIED"
        result["runtime_cutover"] = runtime_cutover_preconditions(result)
        return result
    try:
        data = owner_regular(manifest, limit=131072)
        from ai_foundation.local_model_availability import manifest_artifacts
        artifacts = manifest_artifacts(manifest)
        result["manifest_readable"] = bool(data)
        result["declared_model_paths"] = len(artifacts)
        result["artifact_found"] = sum(p.is_file() for p in artifacts.values())
        result["artifact_missing"] = sum(not p.is_file() for p in artifacts.values())
        result["artifact_parents_existing"] = sum(p.parent.is_dir() for p in artifacts.values())
        result["artifact_symlinks"] = sum(p.is_symlink() for p in artifacts.values())
        result["gguf_headers_plausible"] = sum(
            gguf_header_plausible(p) for p in artifacts.values())
        result["all_declared_absolute"] = all(p.is_absolute() for p in artifacts.values())
        result["model_origin"] = _artifact_roots(artifacts, home)
    except (OSError, ValueError, PermissionError, ImportError):
        result["manifest_readable"] = False
    result["live_runtime_version"] = _running_version()
    result["binary_present"] = EXECUTABLE.is_file()
    version = inspect_version([str(EXECUTABLE), "--version"]) if result["binary_present"] else None
    match = re.search(r"\bv?(\d{1,4})\b", version or "")
    result["installed_version"] = ("v" + match.group(1) if match else "UNVERIFIED")
    result["brew_managed"] = False
    if HOMEBREW.is_file():
        versions = inspect_version([str(HOMEBREW), "list", "--versions", "llama-swap"])
        # Homebrew may retain older rollback kegs: "llama-swap 256 272".
        # Select the currently executable version, not the last listed keg.
        fields = versions.split() if type(versions) is str else []
        kegs = fields[1:]
        result["brew_managed"] = (
            len(fields) >= 2 and fields[0] == "llama-swap"
            and len(kegs) <= 8
            and all(re.fullmatch(r"[0-9]+(?:\\.[0-9]+)*", x) for x in kegs))
        binary_version = result["installed_version"].removeprefix("v")
        result["brew_formula_version"] = (
            binary_version if result["brew_managed"]
            and binary_version in kegs else "UNVERIFIED")
    result["runtime_version_matches_disk"] = (
        result["live_runtime_version"] != "UNVERIFIED"
        and result["live_runtime_version"] == result["installed_version"])
    result["ready_for_fixed_upgrade"] = (
        result["launchd_binary_exact"] is True
        and result["launchd_manifest_exact"] is True
        and result["binary_present"] is True
        and result["brew_managed"] is True
        and result.get("manifest_readable") is True)
    result["runtime_cutover"] = runtime_cutover_preconditions(result)
    return result

def _brew(args, *, timeout):
    """No shell, no environment secrets, and never touch a running model."""
    env = {"PATH": "/opt/homebrew/bin:/usr/bin:/bin",
           "HOME": str(Path.home()),
           "USER": os.environ.get("USER", ""),
           "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
           "HOMEBREW_NO_ANALYTICS": "1",
           "HOMEBREW_NO_INSTALL_CLEANUP": "1"}
    try:
        cp = subprocess.run([str(HOMEBREW), *args], env=env,
                            capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return cp.returncode == 0


def stage_v272_binary():
    """Install upstream reviewed Homebrew v272; do NOT touch launchd or models.

    We only accept the exact observed v256 Homebrew/owner runtime. A successful
    package update is not the live-process version until later separate
    idle/Guard-authorized launchd cutover and independent readback.
    """
    before = audit()
    base = {"target": LATEST_RELEASE, "model_calls": 0,
            "service_mutations": 0, "model_process_stops": 0,
            "launchd_restarts": 0, "runtime_version_verified": False}
    if before.get("ready_for_fixed_upgrade") is not True:
        return {**base, "status": "UPGRADE_PREFLIGHT_DENIED"}
    if before.get("installed_version") == LATEST_RELEASE and (
            before.get("brew_formula_version") == "272"):
        return {**base, "status": "V272_BINARY_ALREADY_PRESENT"}
    if (before.get("installed_version") != "v256"
            or before.get("brew_formula_version") != "256"):
        return {**base, "status": "UPGRADE_BASE_VERSION_CHANGED"}
    if not _brew(["update", "--quiet"], timeout=210):
        return {**base, "status": "HOMEBREW_FORMULA_REFRESH_UNAVAILABLE"}
    # The official Homebrew tap includes the same release SHA256 as upstream's
    # darwin_arm64 GitHub Release asset. Refuse a changed formula/other release.
    formula = fixed_command([str(HOMEBREW), "cat",
                             "mostlygeek/llama-swap/llama-swap"], max_bytes=16384)
    if (type(formula) is not str or 'version "272"' not in formula
            or LATEST_ARM64_SHA256 not in formula):
        return {**base, "status": "REVIEWED_V272_FORMULA_NOT_FOUND"}
    if not _brew(["upgrade", "mostlygeek/llama-swap/llama-swap"], timeout=360):
        # The package operation could have committed despite a missing response.
        # Never retry automatically: perform only the independent local readback.
        after = audit()
        return {**base, "status": ("V272_BINARY_INSTALLED_LIVE_UNVERIFIED"
                                  if after.get("installed_version") == LATEST_RELEASE
                                  and after.get("brew_formula_version") == "272"
                                  else "HOMEBREW_UPGRADE_UNCERTAIN")}
    after = audit()
    if (after.get("ready_for_fixed_upgrade") is not True
            or after.get("installed_version") != LATEST_RELEASE
            or after.get("brew_formula_version") != "272"
            or after.get("declared_model_paths") != before.get("declared_model_paths")):
        return {**base, "status": "BINARY_READBACK_MISMATCH"}
    return {**base, "status": "V272_BINARY_INSTALLED_LIVE_UNVERIFIED",
            "missing_model_paths": after.get("artifact_missing"),
            "package_version": "v272"}

