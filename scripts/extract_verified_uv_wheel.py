"""Extract only the uv executable from a pre-SHA256-verified official wheel.

Caller MUST verify the complete wheel's pinned SHA256 before invoking. No
package installer, import, execution, network request, symlink or other member
is permitted here. Run-scoped output only.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import zipfile


def extract_uv(wheel: Path, destination: Path) -> None:
    if destination.exists() or destination.is_symlink():
        raise ValueError("uv output already exists")
    with zipfile.ZipFile(wheel) as archive:
        names = [name for name in archive.namelist()
                 if name == "uv/uv" or name.endswith(".data/scripts/uv")]
        if len(names) != 1:
            raise ValueError("verified wheel must contain exactly one uv binary")
        entry = archive.getinfo(names[0])
        if entry.is_dir() or entry.file_size > 50 * 1024 * 1024:
            raise ValueError("invalid uv wheel executable entry")
        payload = archive.read(entry)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
    with os.fdopen(fd, "wb") as out:
        out.write(payload)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: extract_verified_uv_wheel.py WHEEL OUTPUT")
    extract_uv(Path(sys.argv[1]), Path(sys.argv[2]))
