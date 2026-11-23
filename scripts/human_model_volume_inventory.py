"""Read-only macOS external-volume inventory; no data contents or private paths logged."""
from __future__ import annotations
import json
import os
import plistlib
import subprocess
from pathlib import Path


def diskutil(*args):
    result = subprocess.run(
        ["/usr/sbin/diskutil", args[0], "-plist", *args[1:]],
        check=True, capture_output=True, timeout=15)
    return plistlib.loads(result.stdout)


def free_bytes(mount):
    """Filesystem free bytes without creating files."""
    try:
        stat = os.statvfs(mount)
        return stat.f_bavail * stat.f_frsize
    except OSError:
        return None


def inventory():
    disks = diskutil("list")
    # diskutil list can omit APFS volume mount points; inspect mounted volumes too.
    mount_roots = [p for p in Path("/Volumes").iterdir() if p.is_dir()] if Path("/Volumes").is_dir() else []
    records = []
    diagnostics = {"mounted_under_volumes": 0, "internal_flag_unknown": 0, "internal_volumes": 0, "diskutil_info_errors": 0}
    inspected = set()
    seen_mounts = set()
    for disk in disks.get("AllDisksAndPartitions", []):
        candidates = [disk, *disk.get("Partitions", [])]
        for item in candidates:
            device = item.get("DeviceIdentifier")
            if not device or device in inspected:
                continue
            inspected.add(device)
            try:
                info = diskutil("info", device)
            except (subprocess.SubprocessError, ValueError, plistlib.InvalidFileException):
                diagnostics["diskutil_info_errors"] += 1
                continue
            mount = info.get("MountPoint")
            if not mount or not str(mount).startswith("/Volumes/"):
                continue
            if mount in seen_mounts:
                continue
            seen_mounts.add(mount)
            diagnostics["mounted_under_volumes"] += 1
            # Keep uncertainty explicit; do not assume unknown Internal means external.
            if info.get("Internal") is None:
                diagnostics["internal_flag_unknown"] += 1
                continue
            if info.get("Internal") is not False:
                diagnostics["internal_volumes"] += 1
                continue
            # A mount under /Volumes is not proof of an external physical SSD.
            # Do not emit volume names, mount paths, UUIDs or serial numbers.
            records.append({
                "external": info.get("Internal") is False,
                "removable": info.get("RemovableMedia"),
                "protocol": info.get("BusProtocol"),
                "solid_state": info.get("SolidState"),
                "writable": info.get("Writable"),
                "free_bytes": free_bytes(mount),
                "has_human_model_dir": (Path(mount) / "HumanModel").is_dir(),
                "has_ledger": (Path(mount) / "HumanModel" / "ledger" / "human_model.sqlite3").exists(),
            })
    # Fallback to mount-point inspection, independent of diskutil partition nesting.
    for root in mount_roots:
        try:
            info = diskutil("info", str(root))
        except (subprocess.SubprocessError, ValueError, plistlib.InvalidFileException):
            diagnostics["diskutil_info_errors"] += 1
            continue
        mount = info.get("MountPoint")
        if not mount or not str(mount).startswith("/Volumes/"):
            continue
        # Prevent duplicate records when diskutil list already found the same mount.
        if any(existing == mount for existing in seen_mounts):
            continue
        seen_mounts.add(mount)
        diagnostics["mounted_under_volumes"] += 1
        if info.get("Internal") is None:
            diagnostics["internal_flag_unknown"] += 1
            continue
        if info.get("Internal") is not False:
            diagnostics["internal_volumes"] += 1
            continue
        records.append({"external": True, "removable": info.get("RemovableMedia"),
                        "protocol": info.get("BusProtocol"), "solid_state": info.get("SolidState"),
                        "writable": info.get("Writable"), "free_bytes": free_bytes(mount),
                        "has_human_model_dir": (Path(mount) / "HumanModel").is_dir(),
                        "has_ledger": (Path(mount) / "HumanModel" / "ledger" / "human_model.sqlite3").exists()})
    # Disk images are not suitable destinations for the external SSD ledger.
    records = [record for record in records if record["protocol"] != "Disk Image"]
    diagnostics["mount_directories_seen"] = len(mount_roots)
    return {"candidate_count": len(records), "candidates": records, "diagnostics": diagnostics}


if __name__ == "__main__":
    print(json.dumps(inventory(), ensure_ascii=False, sort_keys=True))
