#!/usr/bin/env python3
"""One-shot owner setup of optional MainPC Strata; GitHub is not in the edit loop.

Never starts a service, sends source, or wakes the PC. Existing endpoint
changes require an exact pinned owner operation and an explicit --apply;
other endpoints, credentials and host routing are preserved. Credentials are never stored in this JSON.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
from pathlib import Path
import stat
import sys
import tempfile

_ALLOWED_PORTS = (8080, 18080)
_TEMPLATE = Path(__file__).resolve().parents[1] / "docs/configs/mainpc-strata-endpoints.example.json"


def _reviewed_retarget(old, target):
    """A direct-link retarget, never an arbitrary endpoint or model rewrite."""
    from urllib.parse import urlsplit
    if (old.get("name") != "mainpc-strata" or
            old.get("optional") is not True or
            old.get("api_key_env") != "STRATA_API_KEY" or
            target.get("base_url") != "http://10.0.1.1:18080"):
        return False
    source = old.get("base_url")
    allowed_sources = ("http://10.0.1.1:8080",
                       "http://10.0.1.1:18080",
                       "http://100.80.11.110:8080")
    if type(source) is not str or source.rstrip("/") not in allowed_sources:
        return False
    hosts = old.get("allowed_hosts")
    if (type(hosts) is not list or not hosts
            or urlsplit(source).hostname not in hosts or
            any(h not in ("10.0.1.1", "100.80.11.110") for h in hosts)):
        return False
    models = old.get("models")
    if type(models) is not list or len(models) != 1 or type(models[0]) is not dict:
        return False
    m = models[0]
    return (m.get("alias") == "code-agent" and
            m.get("runtime_model") == "qwen3.8-flash-next-coder-iq1_m" and
            type(m.get("capabilities")) is list and "CODE" in m["capabilities"] and
            type(m.get("roles")) is list and "DEVELOPMENT_AGENT" in m["roles"])


def retarget_blocker(row):
    """Report fixed nonsecret reason category; never export URL, model or key."""
    from urllib.parse import urlsplit
    if type(row) is not dict or row.get("name") != "mainpc-strata":
        return "ENDPOINT_SCHEMA"
    if row.get("optional") is not True:
        return "OPTIONAL_GUARD"
    if row.get("api_key_env") != "STRATA_API_KEY":
        return "KEY_BINDING"
    source = row.get("base_url")
    if (type(source) is not str or source.rstrip("/") not in
            ("http://10.0.1.1:8080", "http://10.0.1.1:18080",
             "http://100.80.11.110:8080")):
        return "URL_POLICY"
    hosts = row.get("allowed_hosts")
    if (type(hosts) is not list or not hosts or
            urlsplit(source).hostname not in hosts or
            any(h not in ("10.0.1.1", "100.80.11.110") for h in hosts)):
        return "HOST_ALLOWLIST"
    models = row.get("models")
    if type(models) is not list or len(models) != 1 or type(models[0]) is not dict:
        return "CODE_MODEL_POLICY"
    m = models[0]
    if (m.get("alias") != "code-agent" or
            m.get("runtime_model") != "qwen3.8-flash-next-coder-iq1_m" or
            type(m.get("capabilities")) is not list or "CODE" not in m["capabilities"] or
            type(m.get("roles")) is not list or "DEVELOPMENT_AGENT" not in m["roles"]):
        return "CODE_MODEL_POLICY"
    return "NO_POLICY_BLOCKER"


def configure_strata(data_root, *, port=8080, apply=False,
                     repair_invalid_key=False, retarget_existing=False,
                     expand_text_roles=False, template=_TEMPLATE):
    """Add optional endpoint or explicitly widen only pinned CODE to CHAT."""
    if (port not in _ALLOWED_PORTS or type(port) is not int
            or type(apply) is not bool or type(repair_invalid_key) is not bool
            or type(retarget_existing) is not bool
            or type(expand_text_roles) is not bool):
        raise ValueError("UNSUPPORTED_STRATA_SETUP_REQUEST")
    root = Path(data_root).resolve(strict=True)
    location = root / "local-compute"
    config = location / "endpoints.json"
    if location.is_symlink() or config.is_symlink():
        raise PermissionError("LOCAL_ENDPOINT_ALIAS_REJECTED")
    if config.exists():
        info = config.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 65536):
            raise PermissionError("LOCAL_ENDPOINT_FILE_NOT_PRIVATE")
        data = json.loads(config.read_text(encoding="utf-8"))
    else:
        data = {"version": 1, "endpoints": []}
    if (type(data) is not dict or data.get("version") != 1
            or type(data.get("endpoints")) is not list):
        raise ValueError("LOCAL_ENDPOINT_CONFIG_SCHEMA_INVALID")
    endpoint = json.loads(Path(template).read_text(encoding="utf-8"))["endpoints"][0]
    # Portproxy 18080 is an existing fixed historical path, not an arbitrary URL.
    endpoint["base_url"] = f"http://10.0.1.1:{port}"
    matches = [row for row in data["endpoints"] if type(row) is dict
               and row.get("name") == endpoint["name"]]
    if len(matches) > 1:
        raise ValueError("DUPLICATE_MAINPC_STRATA_ENDPOINT")
    if any(type(row) is not dict for row in data["endpoints"]):
        raise ValueError("LOCAL_ENDPOINT_CONFIG_SCHEMA_INVALID")
    repairing = False
    retargeting = False
    expanding = False
    if matches:
        if matches[0] == endpoint:
            return "ALREADY_CONFIGURED"
        old = matches[0]
        if expand_text_roles and not retarget_existing and not repair_invalid_key:
            # Never replace a live owner's endpoint, credentials, or address.
            # Accept only exactly the already-pinned CODE capability.
            rows = old.get("models")
            model = rows[0] if type(rows) is list and len(rows) == 1 else None
            if not (_reviewed_retarget(old, {"base_url": "http://10.0.1.1:18080"})
                    and old.get("base_url") == endpoint["base_url"]
                    and old.get("allowed_hosts") == endpoint["allowed_hosts"]
                    and type(model) is dict
                    and type(model.get("capabilities")) is list
                    and all(type(cap) is str for cap in model["capabilities"])
                    and set(model["capabilities"]) in ({"CODE"}, {"CODE", "CHAT"})):
                return "EXISTING_ENDPOINT_REVIEW_REQUIRED"
            if set(model["capabilities"]) == {"CODE", "CHAT"}:
                return "ALREADY_TEXT_ENABLED"
            expanding = True
        if retarget_existing and _reviewed_retarget(old, endpoint):
            if (old.get("base_url") == endpoint["base_url"] and
                    old.get("allowed_hosts") == endpoint["allowed_hosts"]):
                return "ALREADY_TARGETED"
            retargeting = True
        alias = old.get("api_key_env")
        # Explicit repair only for a canonical entry whose *sole* mismatch is
        # an unsafe/invalid credential variable name. Never replace an already
        # valid STRATA-scoped alias or an endpoint with an unknown URL/model.
        fixed = {**old, "api_key_env": "STRATA_API_KEY"}
        valid_alias = (type(alias) is str and re.fullmatch(
            r"(?:STRATA|MAINPC_STRATA)_[A-Z0-9_]{2,63}", alias) is not None)
        if not retargeting and not expanding:
            if not (repair_invalid_key and not valid_alias and fixed == endpoint):
                return "EXISTING_ENDPOINT_REVIEW_REQUIRED"
            repairing = True
    if not apply:
        return ("READY_TO_EXPAND_TEXT" if expanding else
                "READY_TO_RETARGET" if retargeting else
                "READY_TO_REPAIR_KEY_BINDING" if repairing else "READY_TO_APPLY")
    if not location.exists():
        location.mkdir(mode=0o700)
    info = location.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o077):
        raise PermissionError("LOCAL_ENDPOINT_DIRECTORY_NOT_PRIVATE")
    new_data = dict(data)
    new_data["endpoints"] = ([
        ({**row, "models": [{**row["models"][0],
            "capabilities": ["CODE", "CHAT"],
            "roles": list(dict.fromkeys(row["models"][0]["roles"] + [
                "PUBLIC_TEXT_ANALYSIS", "PUBLIC_SUMMARIZATION", "PUBLIC_PLANNING"
            ]))}]} if expanding else
         {**row, "base_url": endpoint["base_url"],
          "allowed_hosts": endpoint["allowed_hosts"]} if retargeting else endpoint)
        if row is matches[0] else row for row in data["endpoints"]
    ] if (repairing or retargeting or expanding) else data["endpoints"] + [endpoint])
    encoded = (json.dumps(new_data, indent=2, ensure_ascii=False) + "\n").encode()
    if len(encoded) > 65536:
        raise ValueError("LOCAL_ENDPOINT_CONFIG_TOO_LARGE")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=location, prefix=".endpoints-",
                                         delete=False) as out:
            temp_path = Path(out.name)
            os.fchmod(out.fileno(), 0o600)
            out.write(encoded)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp_path, config)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    if expanding:
        return "TEXT_ROLES_EXPANDED"
    if repairing:
        return ("KEY_BINDING_REPAIRED_KEY_REQUIRED" if not os.environ.get("STRATA_API_KEY")
                else "KEY_BINDING_REPAIRED")
    if retargeting:
        return "RETARGETED_TO_18080"
    return "CONFIGURED_KEY_REQUIRED" if not os.environ.get("STRATA_API_KEY") else "CONFIGURED"


def read_owner_key_stdin(_prompt):
    """Bounded SSH pipe input; no echo, argv, environment or persistent copy."""
    return sys.stdin.readline(258).rstrip("\r\n")


def register_owner_key(data_root, *, port=18080, secret_prompt=getpass.getpass,
                       diagnostics=None):
    """Only save a bearer after live server auth and exact M1 inference pass."""
    if port != 18080:
        return "AUTH_ENDPOINT_REVIEW_REQUIRED"
    path = Path(data_root) / "local-compute" / "endpoints.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    rows = [r for r in entries.get("endpoints", [])
            if type(r) is dict and r.get("name") == "mainpc-strata"]
    if len(rows) != 1 or not _reviewed_retarget(rows[0], {
            "base_url": "http://10.0.1.1:18080"}):
        return "AUTH_ENDPOINT_REVIEW_REQUIRED"
    if rows[0]["base_url"] != "http://10.0.1.1:18080":
        return "AUTH_ENDPOINT_REVIEW_REQUIRED"
    # A bearer sent to an unauthenticated public-facing server proves nothing.
    # Health is observed over the fixed, existing direct cable portproxy only.
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request("http://10.0.1.1:18080/health")
    try:
        with opener.open(req, timeout=5) as response:
            raw = response.read(4097)
            if response.status != 200 or len(raw) > 4096:
                return "STRATA_AUTH_NOT_READY"
        health = json.loads(raw)
    except (OSError, ValueError, TypeError):
        return "STRATA_AUTH_NOT_READY"
    if type(health) is not dict or health.get("api_key") is not True:
        return "STRATA_AUTH_NOT_READY"
    secret = secret_prompt("Strata API key (hidden): ")
    if (type(secret) is not str or not 16 <= len(secret) <= 256
            or any(ord(c) < 33 or ord(c) > 126 for c in secret)):
        return "KEY_FORMAT_REJECTED"
    previous = os.environ.get("STRATA_API_KEY")
    os.environ["STRATA_API_KEY"] = secret
    try:
        from mainpc_strata_preflight import verify_strata
        result = verify_strata(path, wake=False, smoke=True, diagnostics=diagnostics)
    finally:
        if previous is None:
            os.environ.pop("STRATA_API_KEY", None)
        else:
            os.environ["STRATA_API_KEY"] = previous
    if result.get("status") != "INFERENCE_VERIFIED":
        if diagnostics is not None and "reason_code" not in diagnostics:
            code = result.get("status")
            diagnostics["reason_code"] = (code if code in {
                "CONFIG_UNAVAILABLE", "MAINPC_STRATA_NOT_CONFIGURED",
                "MAINPC_MODEL_NOT_BOUND", "MAINPC_UNAVAILABLE",
                "INFERENCE_UNAVAILABLE", "INFERENCE_NOT_VERIFIED"
            } else "PREFLIGHT_UNVERIFIED")
        return "AUTHENTICATED_INFERENCE_UNVERIFIED"
    from ai_foundation.native_credentials import MacOSNativeCredentialStore
    MacOSNativeCredentialStore().save("local:mainpc-strata:api-key", secret)
    return "KEYCHAIN_REGISTERED_INFERENCE_VERIFIED"


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from m1_development_bridge import require_m1
    from ai_foundation.productization import load_config
    from ai_foundation.authority_manifest import verify as verify_authority_manifest
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise SystemExit("M1_OWNER_SESSION_REQUIRED")
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Installed owner Foundation config")
    parser.add_argument("--port", type=int, choices=_ALLOWED_PORTS, default=8080)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--repair-invalid-key-binding", action="store_true")
    parser.add_argument("--retarget-existing", action="store_true")
    parser.add_argument("--expand-text-roles", action="store_true",
                        help="Enable public CHAT on the reviewed Strata endpoint")
    parser.add_argument("--register-api-key", action="store_true",
                        help="Verify authenticated 18080 inference and save to owner Keychain")
    parser.add_argument("--key-stdin", action="store_true",
                        help="Read owner key from an authenticated SSH stdin pipe, never argv")
    args = parser.parse_args()
    if args.key_stdin and not args.register_api_key:
        parser.error("KEY_STDIN_REQUIRES_REGISTRATION")
    cfg = load_config(args.config)
    root = Path(cfg.data_dir).resolve(strict=True)
    verify_authority_manifest(root, cfg)
    stage = "PREPARE"
    diagnostics = {}
    if args.register_api_key:
        if (args.apply or args.retarget_existing or args.repair_invalid_key_binding
                or args.expand_text_roles):
            raise SystemExit("KEY_REGISTRATION_MUST_BE_SEPARATE")
        # Registration must never depend on the caller having run a separate
        # prepare invocation. Retarget ONLY a reviewed existing CODE endpoint,
        # never an arbitrary URL; absent key still leaves this route disabled.
        stage = "AUTH_PREFLIGHT"
        preliminary = configure_strata(root, port=args.port, apply=True,
                                       retarget_existing=True)
        if preliminary not in {"ALREADY_CONFIGURED", "ALREADY_TARGETED",
                               "RETARGETED_TO_18080"}:
            result = "AUTH_ENDPOINT_REVIEW_REQUIRED"
        else:
            stage = "AUTH_CHECK"
            prompt = read_owner_key_stdin if args.key_stdin else getpass.getpass
            result = register_owner_key(root, port=args.port,
                                        diagnostics=diagnostics, secret_prompt=prompt)
    else:
        result = configure_strata(root, port=args.port, apply=args.apply,
                                  repair_invalid_key=args.repair_invalid_key_binding,
                                  retarget_existing=args.retarget_existing,
                                  expand_text_roles=args.expand_text_roles)
    report = {"stage": stage, "status": result}
    if "reason_code" in diagnostics:
        report["reason_code"] = diagnostics["reason_code"]
    if result in {"EXISTING_ENDPOINT_REVIEW_REQUIRED",
                  "AUTH_ENDPOINT_REVIEW_REQUIRED"}:
        try:
            path = root / "local-compute" / "endpoints.json"
            doc = json.loads(path.read_text(encoding="utf-8"))
            rows = [r for r in doc.get("endpoints", [])
                    if type(r) is dict and r.get("name") == "mainpc-strata"]
            report["reason_code"] = (retarget_blocker(rows[0]) if len(rows) == 1
                                     else "ENDPOINT_COUNT")
        except (OSError, ValueError, TypeError, KeyError):
            report["reason_code"] = "CONFIG_UNREADABLE"
    print(json.dumps(report, sort_keys=True))
    return 0 if result in {"ALREADY_CONFIGURED", "READY_TO_APPLY", "CONFIGURED",
                           "CONFIGURED_KEY_REQUIRED", "READY_TO_REPAIR_KEY_BINDING",
                           "KEY_BINDING_REPAIRED", "KEY_BINDING_REPAIRED_KEY_REQUIRED",
                           "ALREADY_TARGETED", "READY_TO_RETARGET", "RETARGETED_TO_18080",
                           "KEYCHAIN_REGISTERED_INFERENCE_VERIFIED",
                           "READY_TO_EXPAND_TEXT", "TEXT_ROLES_EXPANDED",
                           "ALREADY_TEXT_ENABLED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

