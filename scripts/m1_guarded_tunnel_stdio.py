"""Separate trusted stdio child for opt-in guarded Foundation MCP tunnel.

Never alter m1_foundation_tunnel_stdio.py (status-only). The control-plane
credential belongs to the tunnel process and is never passed to the bounded
Guard/development subprocess. The Operator owner config is derived locally,
not from a remote MCP argument or clientInfo.
"""
from __future__ import annotations

import os
from pathlib import Path
import platform
import sys

if __package__:
    from .m1_foundation_tunnel import _trusted_bytes
else:
    from m1_foundation_tunnel import _trusted_bytes


def launch(*, execve=None, resolve_config=None, executable=None):
    if (platform.system() != "Darwin"
            or platform.machine() not in ("arm64", "aarch64")
            or os.getuid() != 501 or os.geteuid() != os.getuid()
            or len(sys.argv) != 1):
        raise PermissionError("OWNER_M1_GUARDED_TUNNEL_REQUIRED")
    root = Path(__file__).resolve().parents[1]
    target = root / "scripts" / "m1_owner_delegated_mcp_stdio.py"
    # Verify immutable owner-controlled code before any subprocess/host call.
    for name in ("m1_owner_delegated_mcp_stdio.py",
                 "m1_development_ticket_factory.py",
                 "foundation_mcp_stdio.py"):
        _trusted_bytes(root / "scripts" / name)
    if resolve_config is None:
        from m1_direct_development import installed_config
        resolve_config = installed_config
    config_path, _, _ = resolve_config()
    if (not isinstance(config_path, Path) or not config_path.is_absolute()
            or config_path.is_symlink() or not config_path.is_file()):
        raise PermissionError("INSTALLED_OPERATOR_CONFIG_UNVERIFIED")
    python = "/opt/homebrew/bin/python3.12" if executable is None else executable
    if not Path(python).is_file():
        raise PermissionError("PINNED_OWNER_PYTHON_UNAVAILABLE")
    # Whitelist deliberately excludes tunnel/Strata/GitHub and other secrets.
    clean = {key: os.environ[key] for key in
             ("HOME", "USER", "TMPDIR", "LANG", "LC_ALL")
             if type(os.environ.get(key)) is str and os.environ[key]}
    # Fixed owner tool locations for separately opted-in Draft delivery;
    # never inherit a caller-controlled executable search path.
    clean["PATH"] = "/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    clean["PYTHONDONTWRITEBYTECODE"] = "1"
    runner = os.execve if execve is None else execve
    runner(python, [python, "-B", str(target), "--config", str(config_path),
                    "--enable-local-development"], clean)


if __name__ == "__main__":
    launch()
