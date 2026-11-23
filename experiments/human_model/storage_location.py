"""Fail-closed external-volume storage placement for the isolated human-model experiment.

This module never migrates data, creates directories, or opens the ledger.
A caller must explicitly select a mounted volume; the internal disk is not a fallback.
"""
from __future__ import annotations

import os
from pathlib import Path


class StorageUnavailable(RuntimeError):
    """Selected external storage is missing or fails placement checks."""


def validate_external_root(root: str | Path, *, volumes_dir: str | Path = "/Volumes",
                           mount_check=None) -> Path:
    """Validate an existing directory on a separately mounted macOS volume.

    The volume must be an immediate child of /Volumes; a nested path inside it
    is permitted. Reject symlinks throughout the selected path. A mounted disk
    is not necessarily an SSD: verify the physical device separately.
    """
    mount_check = mount_check or os.path.ismount
    root = Path(root).expanduser()
    volumes = Path(volumes_dir)
    if ".." in root.parts or ".." in volumes.parts:
        raise StorageUnavailable("parent traversal in storage path refused")
    if not root.is_absolute() or not volumes.is_absolute():
        raise StorageUnavailable("absolute storage and volumes paths required")
    if not volumes.is_dir() or volumes.is_symlink():
        raise StorageUnavailable("volumes directory unavailable")
    try:
        relative = root.relative_to(volumes)
    except ValueError as exc:
        raise StorageUnavailable("storage must be inside the selected external volume") from exc
    if len(relative.parts) < 2 or relative.parts[0] in ("", ".", ".."):
        raise StorageUnavailable("choose an existing subdirectory inside a volume")
    volume = volumes / relative.parts[0]
    for candidate in (volume, *(volumes.joinpath(*relative.parts[:i])
                                  for i in range(2, len(relative.parts) + 1))):
        if candidate.is_symlink():
            raise StorageUnavailable("symlinked storage path refused")
    if not volume.is_dir() or not mount_check(str(volume)):
        raise StorageUnavailable("external volume is not mounted; no internal fallback")
    if not root.is_dir():
        raise StorageUnavailable("storage directory must already exist")
    resolved_volume = volume.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    if resolved_volume not in resolved_root.parents:
        raise StorageUnavailable("storage path escapes selected volume")
    return resolved_root


def proposed_paths(root: str | Path, *, volumes_dir: str | Path = "/Volumes",
                   mount_check=None) -> dict[str, Path]:
    """Return locations without creating them or changing any existing data."""
    base = validate_external_root(root, volumes_dir=volumes_dir, mount_check=mount_check)
    return {
        "ledger": base / "ledger" / "human_model.sqlite3",
        "source_cache": base / "sources",
        "derived_models": base / "models",
        "oss_indexes": base / "indexes",
        "evaluation": base / "evaluation",
        "backups": base / "backups",
    }


def validated_ledger_path(root, **kwargs):
    """Validate database and SQLite sidecars before any connect() call."""
    path = proposed_paths(root, **kwargs)['ledger']
    if not path.parent.is_dir() or path.parent.is_symlink():
        raise StorageUnavailable('external ledger directory is missing')
    for suffix in ('', '-wal', '-shm', '-journal'):
        if Path(str(path) + suffix).is_symlink():
            raise StorageUnavailable('symlinked SQLite file refused')
    return path
