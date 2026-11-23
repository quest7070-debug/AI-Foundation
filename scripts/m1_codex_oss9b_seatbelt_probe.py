#!/usr/bin/env python3
"""M1 no-model Codex OSS sandbox kernel canary; no credentials or user files.

An ephemeral fixed Seatbelt profile denies all external network and owner-home
reads, permits only local Ollama 11434, and confines writes to a disposable
private root. The exact same profile is used to invoke the pinned Codex
binary with --help only. Does not infer real inference E2E acceptance.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import pwd
import stat
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"scripts"))
from m1_codex_oss9b_host_admission import owned_codex

PUBLIC_NET_DENY = ("import socket,errno,sys; "
                   "s=socket.socket();s.settimeout(1); "
                   "code=s.connect_ex(('198.51.100.1',443));s.close(); "
                   "sys.exit(0 if code in (errno.EPERM,errno.EACCES) else 9)")
LOCAL_HOST_OK = ("import socket,sys; "
                 "s=socket.create_connection(('127.0.0.1',11434),timeout=2); "
                 "s.sendall(b'GET /api/version HTTP/1.0\\r\\n"
                 "Host: 127.0.0.1\\r\\n\\r\\n'); "
                 "x=s.recv(256);s.close(); "
                 "sys.exit(0 if x.startswith(b'HTTP/1.0 200') "
                 "or x.startswith(b'HTTP/1.1 200') else 7)")
MAX_OUTPUT=262144


def policy_for(*, owner_home: Path, workspace: Path) -> str:
    """Build no-secret, no-WAN SBPL for a disposable path only."""
    owner=str(owner_home.resolve(strict=True))
    temp=str(workspace.resolve(strict=True))
    if (not owner.startswith("/Users/") or owner==temp
            or not temp.startswith("/private/tmp/")):
        raise ValueError("CODEX_SANDBOX_BOUNDARY_INVALID")
    return ("(version 1)\n"
            "(allow default)\n"
            "(deny network*)\n"
            '(allow network-outbound (remote ip "localhost:11434"))\n'
            "(deny file-read* (subpath "+json.dumps(owner)+"))\n"
            "(deny file-write*)\n"
            "(allow file-write* (subpath "+json.dumps(temp)+"))\n"
            '(allow file-write* (literal "/dev/null"))\n')


def run_fixed(profile: Path, work: Path, program: tuple[str,...]):
    env={"HOME":str(work),"CODEX_HOME":str(work),
         "TMPDIR":str(work)+"/",
         "PATH":"/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
         "NO_COLOR":"1","PYTHONDONTWRITEBYTECODE":"1",
         "GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"/dev/null",
         "GIT_TERMINAL_PROMPT":"0","OLLAMA_HOST":"127.0.0.1:11434",
         "NO_PROXY":"localhost,127.0.0.1","no_proxy":"localhost,127.0.0.1"}
    try:
        result=subprocess.run(["/usr/bin/sandbox-exec","-f",str(profile),
                               *program],cwd=work,env=env,
                              stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE,timeout=15,check=False)
    except (OSError,subprocess.TimeoutExpired):
        return False
    return result.returncode==0 and len(result.stdout)+len(result.stderr)<MAX_OUTPUT


def inspect():
    if (platform.system()!="Darwin" or platform.machine() not in ("arm64","aarch64")
            or os.getuid()==0):
        return {"status":"OWNER_M1_REQUIRED","model_calls":0}
    codex=owned_codex()
    if codex is None:
        return {"status":"CODEX_BINARY_UNPINNED","model_calls":0}
    owner=Path(pwd.getpwuid(os.getuid()).pw_dir)
    # Never use an owner's existing CODEX_HOME, keys or repo checkout.
    with tempfile.TemporaryDirectory(prefix="foundation-codex9b-",
                                     dir="/private/tmp") as directory:
        work=Path(directory).resolve(strict=True)
        work.chmod(0o700)
        policy=work/"local.sb"
        policy.write_text(policy_for(owner_home=owner,workspace=work))
        policy.chmod(0o600)
        binary="/usr/bin/python3"
        deny=run_fixed(policy,work,(binary,"-B","-c",PUBLIC_NET_DENY))
        if not deny:
            return {"status":"KERNEL_WAN_DENY_UNVERIFIED","model_calls":0}
        local=run_fixed(policy,work,(binary,"-B","-c",LOCAL_HOST_OK))
        if not local:
            return {"status":"KERNEL_LOCAL_OLLAMA_UNVERIFIED","model_calls":0}
        help_ok=run_fixed(policy,work,(str(codex),"--help"))
        if not help_ok:
            return {"status":"CODEX_SANDBOX_START_UNVERIFIED","model_calls":0}
        return {"status":"SEATBELT_WAN_DENIED_LOCAL11434_ALLOWED",
                "codex_help_in_same_sandbox":True,"model_calls":0,
                "remote_calls":0,"credentials_read":False,
                "actual_9b_inference_proven":False}


def main():
    try:
        result=inspect()
    except (OSError,ValueError):
        result={"status":"SANDBOX_PROBE_UNAVAILABLE","model_calls":0}
    print("CODEX_OSS9B_SEATBELT="+json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
