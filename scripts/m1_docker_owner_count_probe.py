"""Fixed read-only M1 Mongo server account-count probe.

Only a bounded count band leaves the host. No account identifier, names, emails,
configuration, credentials, container logs or unbounded shell is exported.
No Docker start, restart, write, model call, or Native dispatch is performed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

if __package__:
    from .m1_development_bridge import require_m1
    from .m1_human_model_activation_readiness import _owner_service_state
else:
    from m1_development_bridge import require_m1
    from m1_human_model_activation_readiness import _owner_service_state

_OWNER_QUERY = (
    "const n=db.users.find({},{_id:1}).limit(2).toArray().length;"
    "print(JSON.stringify({count:n}));"
)


def owner_count_status(*, docker=None):
    require_m1()
    if docker is None:
        docker = shutil.which("docker") or next(
            (p for p in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker")
             if Path(p).is_file()), None)
    common = {"service_mutations": 0, "native_dispatches": 0,
              "account_count_band": None, "single_server_account": None}
    if not docker:
        return {**common, "status": "BLOCKED", "owner_service_state": "DOCKER_CLI_UNAVAILABLE"}
    try:
        result = subprocess.run(
            [docker, "exec", "chat-mongodb", "mongosh", "--quiet",
             "LibreChat", "--eval", _OWNER_QUERY],
            capture_output=True, text=True, timeout=12, check=True,
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) != 1:
            return {**common, "status": "BLOCKED", "owner_service_state": "QUERY_UNVERIFIED"}
        row = json.loads(lines[0])
        if type(row) is not dict or set(row) != {"count"} or type(row.get("count")) is not int:
            return {**common, "status": "BLOCKED", "owner_service_state": "QUERY_UNVERIFIED"}
        count = row["count"]
        if count not in (0, 1, 2):
            return {**common, "status": "BLOCKED", "owner_service_state": "QUERY_UNVERIFIED"}
        band = ("ZERO", "ONE", "MULTIPLE")[count]
        return {**common, "status": "OBSERVED", "owner_service_state": "QUERY_OK",
                "account_count_band": band, "single_server_account": count == 1,
                "note": "Bounded LibreChat account count only; HumanModel binding/View not inspected"}
    except subprocess.CalledProcessError:
        state = _owner_service_state(docker)
        return {**common, "status": "BLOCKED", "owner_service_state": state}
    except (subprocess.TimeoutExpired, OSError, ValueError, TypeError):
        return {**common, "status": "BLOCKED", "owner_service_state": "QUERY_UNVERIFIED"}
