"""Explicit, fail-closed provisioning of the isolated HumanModel ledger on a mounted USB volume.

Never runs automatically on a push. Refuses ambiguous disks and pre-existing target paths.
"""
from __future__ import annotations
import argparse
import os
from pathlib import Path
from human_model_volume_inventory import diskutil

def select_mount():
    candidates = []
    volumes = Path("/Volumes")
    for mount in volumes.iterdir():
        if mount.is_symlink() or not mount.is_dir() or not os.path.ismount(mount):
            continue
        try:
            info = diskutil("info", str(mount))
        except Exception:
            continue
        if (info.get("Internal") is False and info.get("BusProtocol") == "USB"
                and info.get("Writable") is True and info.get("MountPoint") == str(mount)):
            candidates.append(mount)
    if len(candidates) != 1:
        raise RuntimeError("expected exactly one mounted writable external USB volume")
    return candidates[0]

def provision():
    mount = select_mount()
    root = mount / "HumanModel"
    if root.exists() or root.is_symlink():
        raise RuntimeError("HumanModel already exists: refusing to overwrite or reuse")
    if os.statvfs(mount).f_bavail * os.statvfs(mount).f_frsize < 1024**3:
        raise RuntimeError("less than 1 GiB free: refusing provisioning")
    # Re-check mount immediately before creating any directory.
    if not os.path.ismount(mount):
        raise RuntimeError("external volume was unmounted")
    root.mkdir(mode=0o700)
    (root / "ledger").mkdir(mode=0o700)
    (root / "sources").mkdir(mode=0o700)
    (root / "models").mkdir(mode=0o700)
    (root / "indexes").mkdir(mode=0o700)
    (root / "evaluation").mkdir(mode=0o700)
    (root / "backups").mkdir(mode=0o700)
    # No private mount path or volume identifier in CI logs.
    return {"provisioned": True, "external_usb": True, "ledger_initialized": False}

if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="explicitly create directories")
    args = parser.parse_args()
    if args.apply:
        print(json.dumps(provision()))
    else:
        mount = select_mount()
        print(json.dumps({"ready": True, "human_model_exists": (mount / "HumanModel").exists()}))
