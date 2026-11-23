#!/usr/bin/env python3
"""Exact local-only Codex OSS/9B admission preflight; never starts a model.

Host eligibility is not execution authorization. This read-only probe checks
the actual installed Codex binary, existing Ollama model digest and real
shared compute lease/CPU/RAM. It cannot instantiate a second backend, access
cloud credentials or mutate an owner record. Separate pinned Seatbelt egress
proof remains required before a live Codex child is ever admitted.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
from pathlib import Path
import platform
import pwd
import stat
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ai_foundation.host_compute_lease import (
    HostComputeLease, HostComputeBusy, HostComputeLeaseError)
from ai_foundation.klm_compute_admission import admit_local_9b

CLI_SHA256="61b0194f3bb6534439c8d26a3ed57d0805f84b884588b761795323eeb92fcf70"
MODEL_SHA256="56671c2ab9385f9cfcb404638e32cd62d88e3501d44822208363c010179a3c90"
MODEL="qwen3.5:9b"


def owned_codex():
    home=Path(pwd.getpwuid(os.getuid()).pw_dir)
    for entry in (Path("/opt/homebrew/bin/codex"),Path("/usr/local/bin/codex"),
                  home/".local/bin/codex"):
        try:
            binary=entry.resolve(strict=True)
            info=binary.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0,os.getuid())
                    or info.st_mode&0o022 or not info.st_mode&0o111
                    or not 0<info.st_size<=300*1024*1024):
                continue
            digest=hashlib.sha256()
            with binary.open("rb") as fd:
                for chunk in iter(lambda:fd.read(1024*1024),b""):
                    digest.update(chunk)
            if digest.hexdigest()==CLI_SHA256:
                return binary
        except (OSError,ValueError):
            continue
    return None


def local_model_digest():
    client=http.client.HTTPConnection("127.0.0.1",11434,timeout=3)
    try:
        client.request("GET","/api/tags",headers={"Connection":"close"})
        response=client.getresponse()
        data=response.read(524289)
        if response.status!=200 or len(data)>524288:
            return False
        models=json.loads(data).get("models")
        return (type(models) is list
                and sum(type(m) is dict and m.get("name")==MODEL
                        and m.get("digest")==MODEL_SHA256 for m in models)==1)
    except (OSError,ValueError,http.client.HTTPException):
        return False
    finally:
        client.close()


def preflight(*, lease=None, admit=None, discover=None, model_check=None):
    """Strict source+resource-only evidence, never a grant to spawn Codex."""
    if (platform.system()!="Darwin" or platform.machine() not in ("arm64","aarch64")
            or os.getuid()==0):
        return {"status":"OWNER_M1_REQUIRED","model_calls":0}
    discover=owned_codex if discover is None else discover
    model_check=local_model_digest if model_check is None else model_check
    admit=admit_local_9b if admit is None else admit
    lease=HostComputeLease() if lease is None else lease
    if discover() is None:
        return {"status":"CLI_PIN_MISMATCH","model_calls":0}
    if model_check() is not True:
        return {"status":"LOCAL9B_DIGEST_UNVERIFIED","model_calls":0}
    try:
        # Admission holds the same existing cooperative lease, not another
        # lock domain. Recheck actual pressure; never bypass it to serve Codex.
        with lease.hold():
            ok, reason=admit()
            if ok is not True:
                if reason not in ("CPU_PRESSURE","MEMORY_PRESSURE","RESOURCE_UNKNOWN"):
                    reason="RESOURCE_UNKNOWN"
                return {"status":"DEFER_"+reason,"model_calls":0}
    except HostComputeBusy:
        return {"status":"DEFER_LEASE_BUSY","model_calls":0}
    except HostComputeLeaseError:
        return {"status":"LEASE_UNTRUSTED","model_calls":0}
    return {"status":"LOCAL9B_HOST_ADMISSIBLE_NOT_AUTHORIZED",
            "model_calls":0,"remote_calls":0,"seatbelt_proven":False,
            "codex_activated":False}


def main():
    try:
        result=preflight()
    except Exception:
        result={"status":"UNKNOWN_PRECHECK_ERROR","model_calls":0}
    print("CODEX_OSS9B_HOST_ADMISSION="+json.dumps(result,sort_keys=True))


if __name__=="__main__":
    main()
