#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib import request

from ai_foundation.containment import ToolHiveContainmentPort
from ai_foundation.external_log_maintenance import (
    ExternalLogMaintenanceStateStore,
    MaintenanceStatus,
    build_production_external_log_campaign,
)
from ai_foundation.llama_swap_adapter import LlamaSwapExecution
from ai_foundation.productization import load_config
from ai_foundation.toolhive import ToolHiveMCPClient


def _json_get(url: str, timeout: float = 5.0):
    with request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def operator_readback() -> bool:
    try:
        row = _json_get("http://127.0.0.1:8766/api/human")
        return (
            isinstance(row, dict)
            and isinstance(row.get("routes"), list)
            and isinstance(row.get("providers"), list)
        )
    except Exception:
        return False


def chat_gateway_readback() -> bool:
    try:
        row = _json_get("http://127.0.0.1:8767/v1/models")
        ids = {
            item.get("id")
            for item in row.get("data", [])
            if isinstance(item, dict)
        }
        return {
            "foundation-auto",
            "foundation-search",
            "foundation-code",
            "foundation-data",
            "foundation-files",
            "foundation-vision",
        }.issubset(ids)
    except Exception:
        return False


def llama_readback() -> bool:
    try:
        answer = LlamaSwapExecution(
            model="local-general",
            timeout=120,
        ).chat("Reply with exactly: LT05_READY")
        return isinstance(answer, str) and bool(answer.strip())
    except Exception:
        return False


def build_campaign(config_path: Path, repo_root: Path):
    config = load_config(config_path)
    repo_root = repo_root.resolve()
    thv = repo_root / ".tools" / "toolhive" / "thv"
    toolhive_script = repo_root / "scripts" / "toolhive-filesystem.sh"

    if not thv.is_file():
        raise RuntimeError("canonical ToolHive binary unavailable")
    if not toolhive_script.is_file():
        raise RuntimeError("canonical ToolHive lifecycle script unavailable")

    base_env = dict(os.environ)

    def lifecycle_factory(name: str):
        env = dict(base_env)
        env["AI_FOUNDATION_TOOLHIVE_NAME"] = name
        env["AI_FOUNDATION_THV"] = str(thv)
        return ToolHiveContainmentPort(toolhive_script, env=env)

    def readback_factory(name: str):
        client = ToolHiveMCPClient(thv, name)

        def readback() -> bool:
            try:
                return bool(client.discover())
            except Exception:
                return False

        return readback

    return build_production_external_log_campaign(
        data_dir=Path(config.data_dir),
        repo_root=repo_root,
        toolhive_lifecycle_factory=lifecycle_factory,
        toolhive_readback_factory=readback_factory,
        operator_readback=operator_readback,
        chat_readback=chat_gateway_readback,
        llama_readback=llama_readback,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[1]),
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))
    campaign = build_campaign(
        Path(args.config),
        Path(args.repo_root),
    )
    result = campaign.run_once()

    ExternalLogMaintenanceStateStore(
        Path(config.data_dir) / "external-log-maintenance.json"
    ).save(result, checked_at=__import__("time").time())

    print(
        json.dumps(
            {
                "status": result.status.value,
                "detail": result.detail,
                "groups": [
                    {
                        "name": name,
                        "status": group.status.value,
                        "detail": group.detail,
                    }
                    for name, group in result.groups
                ],
            },
            sort_keys=True,
        )
    )

    return (
        2
        if result.status is MaintenanceStatus.FAILED_UNRECOVERED
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
