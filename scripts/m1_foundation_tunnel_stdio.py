"""Fixed owner-only stdio child for a *separate* Foundation MCP tunnel.

The tunnel client may hold a restricted control-plane credential in its own
environment. execve deliberately drops EVERY such credential before starting
the existing no-effect foundation_status-only server. Never add owner grants,
development tickets, HumanModel, or Guard decisions to this entrypoint.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import stat
import sys


def launch(*, environ=None, execve=None, executable=None, root=None):
    if (platform.system() != "Darwin"
            or platform.machine() not in ("arm64", "aarch64")
            or os.getuid() != 501 or os.geteuid() != os.getuid()
            or len(sys.argv) != 1):
        raise PermissionError("OWNER_M1_FIXED_TUNNEL_COMMAND_REQUIRED")
    root = Path(__file__).resolve().parents[1] if root is None else Path(root)
    source = root / "scripts" / "foundation_mcp_stdio.py"
    info = source.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or not 0 < info.st_size <= 131072):
        raise PermissionError("TRUSTED_READONLY_MCP_SOURCE_REQUIRED")
    exe = "/opt/homebrew/bin/python3.12" if executable is None else executable
    if not Path(exe).is_file():
        raise PermissionError("PINNED_PYTHON_NOT_INSTALLED")
    incoming = os.environ if environ is None else environ
    # No API keys, GitHub token, tunnel id, Keychain material or model routing
    # reach the stdio child through the parent process environment.
    clean = {name: incoming[name]
             for name in ("HOME", "USER", "TMPDIR", "LANG", "LC_ALL")
             if type(incoming.get(name)) is str and incoming[name]}
    clean["PYTHONDONTWRITEBYTECODE"] = "1"
    runner = os.execve if execve is None else execve
    runner(exe, [exe, "-B", str(source)], clean)


if __name__ == "__main__":
    launch()
