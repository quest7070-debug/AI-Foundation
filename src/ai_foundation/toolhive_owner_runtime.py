"""Pinned owner-installed ToolHive OSS, independent of versioned source stages.

A completed archive-SHA-verified bootstrap owns this private executable. No
PATH search, arbitrary environment path, network fetch or new MCP authority.
"""
from __future__ import annotations

from hashlib import sha256
import os
from pathlib import Path
import stat


TOOLHIVE_OWNER_DIR = Path("Library/Application Support/AI-Foundation/toolhive-cli")
TOOLHIVE_ARCHIVE_SHA256 = "b78d8991cb6f3df35a543dd2456c8885ef7e34885517c62051c20443a7a711a0"
# Go binaries can be substantially larger than the signed compressed archive.
# Byte cap is only a resource bound; the exact pinned SHA-256 remains mandatory.
TOOLHIVE_EXECUTABLE_MAX_BYTES = 256_000_000


def owner_toolhive_binary(home=None):
    home = Path.home() if home is None else Path(home)
    directory = home / TOOLHIVE_OWNER_DIR
    executable = directory / "thv"
    archive_receipt = directory / "archive.sha256"
    executable_receipt = directory / "executable.sha256"
    try:
        directory_info = directory.lstat()
        if (not stat.S_ISDIR(directory_info.st_mode)
                or directory_info.st_uid != os.getuid()
                or directory_info.st_mode & 0o077):
            return None
        for path, executable_required in (
                (executable, True),
                (archive_receipt, False),
                (executable_receipt, False)):
            info = path.lstat()
            if (not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_mode & 0o022
                    or executable_required and not info.st_mode & stat.S_IXUSR
                    or info.st_size > (TOOLHIVE_EXECUTABLE_MAX_BYTES if executable_required else 128)):
                return None
        if archive_receipt.read_text().strip() != TOOLHIVE_ARCHIVE_SHA256:
            return None
        expected = executable_receipt.read_text().strip()
        if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
            return None
        with executable.open("rb") as stream:
            digest = sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            return None
    except (OSError, ValueError, UnicodeError):
        return None
    return executable
