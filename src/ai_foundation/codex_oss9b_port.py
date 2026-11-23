"""Optional Codex OSS CLI front end for existing Harness role ports.

This is a *host-bound command description*, not a provider, model allocator,
scheduler or authorization. Only an independently approved host may call the
returned port after verifying the pinned CLI/Seatbelt binary and model digest,
acquiring the existing development lease, and proving kernel WAN denial.
Never inherit ambient HOME, Codex login, cloud tokens or paid API credentials.
"""
from __future__ import annotations

from pathlib import PurePosixPath

from .development_harness_roles import HostBoundHarnessAgent


MODEL = "qwen3.5:9b"
OLLAMA_HOST = "127.0.0.1:11434"
SANDBOX = "/usr/bin/sandbox-exec"


def _absolute_private_path(value: str, name: str) -> str:
    if (type(value) is not str or not value.startswith("/")
            or len(value) > 1024 or "\x00" in value
            or any(part in ("", ".", "..") for part in value[1:].split("/"))):
        raise ValueError("CODEX_OSS_UNTRUSTED_" + name)
    normalized = str(PurePosixPath(value))
    if normalized != value:
        raise ValueError("CODEX_OSS_UNTRUSTED_" + name)
    return value


def host_bound_codex_oss9b(*, codex_binary: str, seatbelt_profile: str,
                          private_home: str, workdir: str,
                          timeout_s: int = 900) -> HostBoundHarnessAgent:
    """Build one already-reviewable role port, without invoking a model.

    An outer macOS Seatbelt MUST be pinned by the caller; Codex's own sandbox
    is defense-in-depth, never a substitute. No ambient environment is read.
    This intentionally cannot set API credentials or select a second model.
    """
    executable = _absolute_private_path(codex_binary, "BINARY")
    profile = _absolute_private_path(seatbelt_profile, "SEATBELT")
    home = _absolute_private_path(private_home, "HOME")
    directory = _absolute_private_path(workdir, "WORKDIR")
    if home in ("/", "/Users", "/tmp", "/var", "/private", "/private/tmp"):
        raise ValueError("CODEX_OSS_PRIVATE_HOME_REQUIRED")
    if type(timeout_s) is not int or not 1 <= timeout_s <= 3600:
        raise ValueError("CODEX_OSS_TIMEOUT_INVALID")
    # No API/provider keys, remote fallback, inherited user Codex home, second
    # local backend, process termination or prompt-selected tool route.
    env = {
        "HOME": home,
        "CODEX_HOME": home,
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
        "OLLAMA_HOST": OLLAMA_HOST,
        "NO_PROXY": "localhost,127.0.0.1",
        "no_proxy": "localhost,127.0.0.1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "NO_COLOR": "1",
    }
    argv = (
        SANDBOX, "-f", profile, executable,
        # OSS flags must be owned by the noninteractive exec subcommand.
        # Placing them before "exec" can silently route the wrong provider.
        "exec", "--ephemeral", "--oss", "--local-provider", "ollama",
        "--model", MODEL, "--sandbox", "read-only",
        "--skip-git-repo-check",
    )
    return HostBoundHarnessAgent(argv, directory, env, timeout_s)
