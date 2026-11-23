#!/usr/bin/env python3
"""Install once, then use local MCP development without GitHub in the run loop.

The first admitted real task fixes nonfinite provider quota reporting. Its
source is reviewed public code; its independent test stays on M1. No model
fallback, publisher, daemon, listener, or alternate Guard/Work store is added.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from m1_development_ticket_factory import MAX_OWNER_DEVELOPMENT_TICKETS, _owner_manifest
TICKET = "strata-quota-finite-20261114-r2"
TARGET = "src/ai_foundation/provider_quota.py"
TEST = "tests/test_provider_quota_finite_mcp.py"
INSTRUCTION = ("Fix provider_quota._pct: return None when remaining or limit is "
               "NaN or infinite. Preserve conversion, positive-limit validation, "
               "clamping and public function signatures. Return the complete Python file.")
FIXED_TEST = '''from ai_foundation.provider_quota import _pct, groq_quota, mistral_short_quota

def test_nonfinite_quota_inputs_are_unknown():
    for bad in ("nan", "NaN", "inf", "-inf", float("nan"), float("inf")):
        assert _pct(bad, 100) is None
        assert _pct(10, bad) is None

def test_finite_quota_behavior_is_preserved():
    assert _pct("25", "100") == 25.0
    assert _pct(-3, 100) == 0.0
    assert _pct(200, 100) == 100.0
    assert _pct(10, 0) is None
    assert _pct(None, 100) is None
    assert groq_quota({"x-ratelimit-remaining-tokens":"nan", "x-ratelimit-limit-tokens":"100",
                       "x-ratelimit-remaining-requests":"2", "x-ratelimit-limit-requests":"4"}) is None
    assert mistral_short_quota({"x-ratelimit-remaining":"1", "x-ratelimit-limit":"inf"}) is None
'''
# Exact source reviewed for public MainPC transfer; unrelated owner files are
# never classified public merely because they are in this repository.
SOURCE_SHA = "d903ee70e2136c1f0690f3e416d29c563e641bef4b0ed1e3a975d571980dec9d"
# Independently recorded on owner M1 in the successful r2 fixed-test receipt.
VERIFIED_R2_SHA = "75da93dd064a49590fb41644b97c6e0fb8170c6076c995737b500d7baf99a3fc"


def git(repo, *args):
    return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-C", str(repo), *args],
                                   stderr=subprocess.DEVNULL, text=True, timeout=30).strip()


def installed_config():
    from ai_foundation.productization import load_config
    from ai_foundation.authority_manifest import verify
    path = Path.home() / "Library/LaunchAgents/dev.quest7070.ai-foundation.operator.plist"
    row = plistlib.loads(path.read_bytes())
    args = row["ProgramArguments"]
    config_path = Path(args[args.index("--config") + 1])
    if not config_path.is_absolute():
        config_path = Path(row.get("WorkingDirectory", "/")) / config_path
    config_path = config_path.resolve(strict=True)
    config = load_config(config_path)
    root = Path(config.data_dir).resolve(strict=True)
    verify(root, config)
    return config_path, config, root


def private_dir(path):
    from m1_development_ticket_factory import _private_dir
    return _private_dir(path)


def write_private(path, text):
    if path.is_symlink():
        raise ValueError("INSTALL_ALIAS_REJECTED")
    temp = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            temp = Path(out.name)
            os.fchmod(out.fileno(), 0o600)
            out.write(text.encode())
            out.flush()
            os.fsync(out.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def ensure_strata_timeout(root):
    """Raise only the reviewed MainPC Strata execution timeout; preserve all other bindings."""
    from m1_development_ticket_factory import _owner_file
    path = root / "local-compute/endpoints.json"
    document = json.loads(_owner_file(path))
    if (type(document) is not dict or document.get("version") != 1
            or type(document.get("endpoints")) is not list):
        raise ValueError("STRATA_TIMEOUT_CONFIG_UNVERIFIED")
    matches = [row for row in document["endpoints"] if type(row) is dict and row.get("name") == "mainpc-strata"]
    if len(matches) != 1:
        raise ValueError("STRATA_TIMEOUT_BINDING_UNVERIFIED")
    row = matches[0]
    if row.get("optional") is not True or row.get("base_url") != "http://10.0.1.1:18080":
        raise ValueError("STRATA_TIMEOUT_BINDING_UNVERIFIED")
    old = row.get("timeout", 120)
    if type(old) is not int or old not in (120, 300):
        raise ValueError("STRATA_TIMEOUT_REVIEW_REQUIRED")
    if old == 120:
        row["timeout"] = 300
        write_private(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return 300


def manifest_ticket(base, source):
    if sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError("REVIEWED_PUBLIC_SOURCE_CHANGED")
    return {"ticket_id": TICKET, "base_sha": base, "instruction": INSTRUCTION,
            "target": TARGET, "test": TEST, "test_sha256": sha256(FIXED_TEST.encode()).hexdigest(),
            "source_sha256": SOURCE_SHA, "model": "strata",
            "public_source_sha256": SOURCE_SHA,
            "public_instruction_sha256": sha256(INSTRUCTION.encode()).hexdigest()}


def install():
    import fcntl
    import shlex
    config_path, config, root = installed_config()
    development = private_dir(root / "development")
    lock = development / "direct-install.lock"
    if lock.is_symlink():
        raise ValueError("INSTALL_ALIAS_REJECTED")
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        revision = git(ROOT, "rev-parse", "HEAD")
        owner_repo = (Path.home() / "Develop/AI-Foundation").resolve(strict=True)
        if Path(git(owner_repo, "rev-parse", "--show-toplevel")).resolve() != owner_repo:
            raise ValueError("OWNER_REPOSITORY_UNVERIFIED")
        try:
            present = git(owner_repo, "cat-file", "-t", revision) == "commit"
        except subprocess.CalledProcessError:
            present = False
        if not present:
            # Import the reviewed release's objects locally once. Worktrees
            # must be owned by the persistent owner repo, never a runner's
            # disposable checkout. No branch, main, remote or FETCH_HEAD moves.
            git(owner_repo, "fetch", "--no-tags", "--no-write-fetch-head", str(ROOT), revision)
        runtime = private_dir(development / "runtime") / revision
        if not runtime.exists():
            git(owner_repo, "worktree", "add", "--detach", str(runtime), revision)
        if runtime.is_symlink() or git(runtime, "rev-parse", "HEAD") != revision or git(runtime, "status", "--porcelain"):
            raise ValueError("RUNTIME_CHECKOUT_UNVERIFIED")
        baseline = private_dir(development / "baselines") / TICKET
        if not baseline.exists():
            git(owner_repo, "worktree", "add", "--detach", str(baseline), revision)
            source = (baseline / TARGET).read_bytes()
            if sha256(source).hexdigest() != SOURCE_SHA:
                raise ValueError("REVIEWED_PUBLIC_SOURCE_CHANGED")
            test = baseline / TEST
            if test.exists():
                raise ValueError("ACCEPTANCE_PATH_ALREADY_PRESENT")
            test.write_text(FIXED_TEST)
            git(baseline, "add", "--", TEST)
            git(baseline, "-c", "user.name=Foundation Owner", "-c", "user.email=owner@localhost",
                "commit", "-m", "Local independent acceptance for nonfinite provider quotas")
        if baseline.is_symlink() or git(baseline, "status", "--porcelain") or (baseline / TEST).read_text() != FIXED_TEST:
            raise ValueError("LOCAL_ACCEPTANCE_BASE_UNVERIFIED")
        record = manifest_ticket(git(baseline, "rev-parse", "HEAD"), (baseline / TARGET).read_bytes())
        manifest = development / "tickets.json"
        if manifest.exists():
            from m1_development_ticket_factory import _owner_file, _strict_json, _validate_ticket
            data = _strict_json(_owner_manifest(manifest))
            if type(data) is not dict or set(data) != {"version", "tickets"} or type(data["version"]) is not int or data["version"] != 1 or type(data["tickets"]) is not list:
                raise ValueError("EXISTING_MANIFEST_REVIEW_REQUIRED")
            for row in data["tickets"]:
                _validate_ticket(row)
            if len({r["ticket_id"] for r in data["tickets"]}) != len(data["tickets"]):
                raise ValueError("EXISTING_MANIFEST_REVIEW_REQUIRED")
        else:
            data = {"version": 1, "tickets": []}
        matching = [r for r in data["tickets"] if type(r) is dict and r.get("ticket_id") == TICKET]
        if matching and matching not in ([record], [{**record, "allow_draft_delivery": True}]):
            raise ValueError("EXISTING_TICKET_CHANGED")
        if not matching:
            if len(data["tickets"]) >= MAX_OWNER_DEVELOPMENT_TICKETS:
                raise ValueError("EXISTING_TICKET_CAPACITY")
            data["tickets"].append(record)
            write_private(manifest, json.dumps(data, indent=2) + "\n")
        python = Path.home() / "Develop/AI-Foundation/.venv/bin/python"
        if not python.is_file():
            raise ValueError("OWNER_PYTHON_UNAVAILABLE")
        launcher = Path.home() / "foundation"
        header = "#!/bin/bash\n# Foundation owner direct development launcher v1\n"
        if launcher.exists() and (launcher.is_symlink() or launcher.stat().st_uid != os.getuid()
                                  or not launcher.read_text().startswith(header)):
            raise ValueError("EXISTING_LAUNCHER_REVIEW_REQUIRED")
        write_private(launcher, header + "exec " + shlex.quote(str(python)) + " -B " +
                      shlex.quote(str(runtime / "scripts/m1_direct_development.py")) + ' "$@"\n')
        launcher.chmod(0o700)
        timeout_seconds = ensure_strata_timeout(root)
        return {"status": "DIRECT_DEVELOPMENT_INSTALLED", "revision": revision,
                "ticket_id": TICKET, "github_in_run_loop": False, "model_calls": 0,
                "execution_timeout_seconds": timeout_seconds,
                "launcher": str(launcher)}
    finally:
        os.close(fd)


class NoM1Fallback:
    def chat(self, *args, **kwargs):
        raise RuntimeError("THIS_PUBLIC_ACCEPTANCE_DOES_NOT_START_M1_MODELS")


def diagnose():
    """Read only fixed ticket metadata; no model, tests, Work claim or reset."""
    import ast
    import sqlite3
    _, config, root = installed_config()
    job = "mcp-local-development:" + sha256(json.dumps(
        ["macos-owner-local", TICKET], separators=(",", ":")).encode()).hexdigest()
    result = {"status": "DIRECT_DEVELOPMENT_OBSERVED", "model_calls": 0}
    db = root / config.work_db
    if db.is_file() and not db.is_symlink():
        with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            row = connection.execute("SELECT status,result FROM work_steps WHERE job_id=? AND position=0", (job,)).fetchone()
        if row:
            result["work_state"] = row[0] if row[0] in {"PLANNED", "RUNNING", "VERIFIED", "FAILED", "WAITING_HUMAN", "CANCELLED"} else "OTHER"
            known = {"LOCAL_ACCEPTANCE_NOT_VERIFIED", "RuntimeError", "ValueError", "PermissionError", "TimeoutError", "SyntaxError", "OSError", "KeyError", "TypeError", "ModuleNotFoundError"}
            result["failure_code"] = row[1] if row[1] in known else "NOT_A_FIXED_FAILURE_CODE"
    source = root / "development/worktrees" / TICKET / TARGET
    if source.is_file() and not source.is_symlink() and source.stat().st_size <= 262144:
        raw = source.read_bytes()
        result["source_changed"] = sha256(raw).hexdigest() != SOURCE_SHA
        result["source_sha256"] = sha256(raw).hexdigest()
        try:
            tree = ast.parse(raw)
            compile(raw, "<reviewed-diagnostic-source>", "exec")
            result["source_compiles"] = True
            result["finite_check_present"] = any(isinstance(node, ast.Attribute) and node.attr == "isfinite" for node in ast.walk(tree))
        except (SyntaxError, ValueError):
            result["source_compiles"] = False
    guard = root / config.guard_db
    if guard.is_file() and not guard.is_symlink():
        with sqlite3.connect(guard.resolve().as_uri() + "?mode=ro", uri=True) as connection:
            rows = connection.execute("SELECT status,count(*) FROM effects WHERE target=? GROUP BY status", (str(source.resolve()),)).fetchall()
        result["guard_effect_states"] = {state if state in {"PLANNED", "AUTHORIZED", "EXECUTING", "OBSERVED", "VERIFIED", "UNCERTAIN", "FAILED"} else "OTHER": count for state, count in rows}
    path = root / "local-compute/endpoints.json"
    if path.is_file() and not path.is_symlink():
        doc = json.loads(path.read_text())
        for row in doc.get("endpoints", []):
            if type(row) is dict and row.get("name") == "mainpc-strata":
                value = row.get("timeout", 120)
                if value is None:
                    value = 120
                if type(value) in {int, float} and 0 < value <= 3600:
                    result["execution_timeout_seconds"] = value
                defaults = row.get("request_defaults", {})
                if type(defaults) is dict and type(defaults.get("max_tokens")) is int:
                    result["max_tokens"] = defaults["max_tokens"]
    return result


def owner_gh_authenticated():
    """Inspect owner-native gh login, never inherit the runner's bot token."""
    env = {key: value for key, value in os.environ.items()
           if key in {"PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL"}}
    try:
        result = subprocess.run(["gh", "api", "user", "--jq", ".login"],
                                capture_output=True, text=True, timeout=15, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and result.stdout.strip() == "quest7070-debug"


def authorize_verified_delivery():
    """Owner-only, exact-r2, verified-source Draft grant; no model or delivery itself."""
    import sqlite3
    from m1_development_ticket_factory import _owner_file, _strict_json, _validate_ticket
    _, config, root = installed_config()
    path = root / "development/tickets.json"
    document = _strict_json(_owner_manifest(path))
    if (type(document) is not dict or set(document) != {"version", "tickets"}
            or document["version"] != 1 or type(document["tickets"]) is not list):
        raise ValueError("DELIVERY_MANIFEST_UNVERIFIED")
    matches = [row for row in document["tickets"]
               if type(row) is dict and row.get("ticket_id") == TICKET]
    if len(matches) != 1:
        raise ValueError("DELIVERY_TICKET_NOT_UNIQUE")
    record = matches[0]
    _validate_ticket(record)
    if (record["model"] != "strata" or record["target"] != TARGET
            or record["test"] != TEST or record["source_sha256"] != SOURCE_SHA
            or record["test_sha256"] != sha256(FIXED_TEST.encode()).hexdigest()
            or record.get("allow_draft_delivery", False) not in (False, True)):
        raise ValueError("DELIVERY_SCOPE_UNVERIFIED")
    source = root / "development/worktrees" / TICKET / TARGET
    if (source.is_symlink() or not source.is_file()
            or source.stat().st_size > 262144
            or sha256(source.read_bytes()).hexdigest() != VERIFIED_R2_SHA):
        raise ValueError("DELIVERY_SOURCE_NOT_VERIFIED")
    from ai_foundation.development_host import HostBoundLocalDevelopmentPort
    job = HostBoundLocalDevelopmentPort._job_id(TICKET, "macos-owner-local")
    db = root / config.work_db
    if db.is_symlink() or not db.is_file():
        raise ValueError("DELIVERY_WORK_UNAVAILABLE")
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=3) as conn:
        row = conn.execute(
            "SELECT status,result FROM work_steps WHERE job_id=? AND position=0",
            (job,)).fetchone()
    if not row or row[0] != "VERIFIED":
        raise ValueError("DELIVERY_WORK_NOT_VERIFIED")
    try:
        receipt = json.loads(row[1])
    except (TypeError, ValueError):
        raise ValueError("DELIVERY_RECEIPT_UNVERIFIED") from None
    if (type(receipt) is not dict or receipt.get("status") != "TESTED_CHANGE"
            or receipt.get("sha256") != VERIFIED_R2_SHA
            or receipt.get("execution_binding") != "local:mainpc-strata:code-agent"):
        raise ValueError("DELIVERY_RECEIPT_UNVERIFIED")
    if record.get("allow_draft_delivery") is not True:
        record["allow_draft_delivery"] = True
        write_private(path, json.dumps(document, ensure_ascii=False, indent=2) + "\n")
    return {"status": "EXACT_DRAFT_DELIVERY_GRANTED", "ticket_id": TICKET,
            "source_sha256": VERIFIED_R2_SHA, "model_calls": 0}


def deliver_client():
    """Use existing owner MCP Draft writer; verify again in a fresh session."""
    from m1_p4_mcp_stdio_e2e import _request
    def session(deliver):
        calls = [_request(1, "server/discover"), _request(2, "tools/list"),
                 _request(3, "tools/call", name="development_status",
                          arguments={"ticket_id": TICKET})]
        if deliver:
            calls.append(_request(4, "tools/call", name="development_deliver",
                                  arguments={"ticket_id": TICKET}))
        env = {key: value for key, value in os.environ.items()
               if key in {"PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "GH_TOKEN"}}
        child = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "stdio"],
                               input="\n".join(json.dumps(row) for row in calls) + "\n",
                               capture_output=True, text=True, timeout=240, env=env)
        if child.returncode:
            raise ValueError("DELIVERY_MCP_HOST_UNVERIFIED")
        rows = [json.loads(line) for line in child.stdout.splitlines()]
        if len(rows) != len(calls) or [row.get("id") for row in rows] != list(range(1, len(calls)+1)):
            raise ValueError("DELIVERY_MCP_FRAMING_UNVERIFIED")
        def decode(row):
            result = row.get("result", {})
            if result.get("isError") is not False:
                raise ValueError("DELIVERY_MCP_CALL_UNVERIFIED")
            return json.loads(result["content"][0]["text"])
        return [decode(row) for row in rows[2:]]
    before, written = session(True)
    if (before.get("state") != "VERIFIED_LOCAL"
            or before.get("source_sha256") != VERIFIED_R2_SHA):
        return {"status": "DRAFT_DELIVERY_UNVERIFIED"}
    if (written.get("github_published") is not True
            or not str(written.get("draft_pr_url", "")).startswith(
                "https://github.com/quest7070-dev/AI-Foundation/pull/")):
        return {"status": "DRAFT_DELIVERY_UNVERIFIED"}
    readback, replay = session(True)
    verified = (readback == replay == written and readback.get("state") == "VERIFIED_LOCAL"
                and readback.get("source_sha256") == VERIFIED_R2_SHA)
    return {"status": "DRAFT_DELIVERY_VERIFIED" if verified else "DRAFT_DELIVERY_UNVERIFIED",
            "ticket_id": TICKET, "source_sha256": VERIFIED_R2_SHA,
            "github_published": verified, "replay_readonly": readback == replay,
            "durable_readback_matches": written == readback,
            "draft_pr_url": readback.get("draft_pr_url") if verified else None,
            "model_calls": 0}


def strata_ready(root):
    from ai_foundation.local_endpoint_config import load_local_endpoints
    try:
        rows = [(d, x) for prefix, d, x in load_local_endpoints(root / "local-compute/endpoints.json")
                if prefix == "local:mainpc-strata" and getattr(x, "api_key", None)
                and x.models.get("code-agent") == "qwen3.8-flash-next-coder-iq1_m"]
        return len(rows) == 1 and any(c.binding == "local:mainpc-strata:code-agent"
                                     and c.health == "ONLINE" and c.same_host is False
                                     and "CODE" in c.capabilities for c in rows[0][0].candidates())
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return False


def strata_configured(root):
    """Read the fixed host binding without a network probe or PC wake."""
    from ai_foundation.local_endpoint_config import load_local_endpoints
    try:
        rows = [(d, x) for prefix, d, x in
                load_local_endpoints(Path(root) / "local-compute/endpoints.json")
                if prefix == "local:mainpc-strata"
                and getattr(x, "api_key", None)
                and x.models.get("code-agent") == "qwen3.8-flash-next-coder-iq1_m"]
        return len(rows) == 1
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return False


def wake_strata_once(root, ticket_id):
    """One owner-initiated wake per reviewed ticket; before any Work claim.

    Never wake on status/list, failed or verified tickets, or an unknown
    CLI/model binding. A persisted intent prevents double WoL after an
    ambiguous response or process crash. Only the existing owner script runs.
    """
    from m1_development_bridge import require_m1
    from m1_development_ticket_factory import _ID
    if type(ticket_id) is not str or not _ID.fullmatch(ticket_id):
        return False
    require_m1()
    if os.getuid() != 501 or os.geteuid() != 501:
        return False
    if not strata_configured(root):
        return False
    if strata_ready(root):
        return True
    root = Path(root).resolve(strict=True)
    from mainpc_strata_preflight import verify_strata
    # Do not burn the one-shot wake intent for an authentication or model
    # failure. Only an independently observed connection failure may wake.
    diagnostics = {}
    discovery = verify_strata(
        root / "local-compute/endpoints.json", wake=False, smoke=False,
        diagnostics=diagnostics)
    if discovery.get("status") == "MODEL_DISCOVERED":
        return strata_ready(root)
    if diagnostics.get("reason_code") not in {
            "DISCOVERY_URLError", "DISCOVERY_TimeoutError"}:
        return False
    intents = private_dir(root / "development" / "strata-wake-intents")
    marker = intents / (ticket_id + ".intent")
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        return False
    try:
        os.fsync(fd)  # Claim the single wake attempt *before* doing the effect.
    finally:
        os.close(fd)
    # Waking the Windows host and seeing a model in /v1/models is not
    # enough to route public CODE. The existing fixed synthetic prompt
    # additionally proves that Strata can actually return inference.
    # No task/user text is sent during wake acceptance.
    observed = verify_strata(root / "local-compute/endpoints.json",
                             wake=True, smoke=True)
    return observed.get("status") == "INFERENCE_VERIFIED" and strata_ready(root)


class StrataReadyPort:
    """Reuse owner-pinned capacity admission before the first Work claim."""
    def __init__(self, port, ready, strict_tickets=(TICKET,), *,
                 waiting_state="WAITING_STRATA", wake=None,
                 wake_first_tickets=(), wake_tickets=()):
        if waiting_state not in {"WAITING_STRATA", "WAITING_M1"}:
            raise ValueError("INVALID_CAPACITY_WAIT_STATE")
        self.waiting_state = waiting_state
        self.port, self.ready, self.wake = port, ready, wake
        self.strict_tickets = frozenset(strict_tickets)
        self.wake_first_tickets = frozenset(wake_first_tickets)
        self.wake_tickets = frozenset(wake_tickets)
        if (not self.wake_tickets <= self.strict_tickets
                or not self.wake_first_tickets <= self.wake_tickets):
            raise ValueError("INVALID_WAKE_TICKET_SCOPE")
    def __getattr__(self, name):
        return getattr(self.port, name)
    def run(self, principal, ticket_id):
        if ticket_id in self.strict_tickets:
            current = self.port.status(principal, ticket_id)
            if current.get("state") != "READY":
                return current
            # For reviewed auto CODE, prefer a one-shot PC wake even when
            # shared9B is available. If the PC stays offline, the original
            # M1 fallback/capacity admission is unchanged.
            if ticket_id in self.wake_first_tickets and self.wake is not None:
                self.wake(ticket_id)
            if not self.ready(ticket_id):
                # Only the strict, READY Strata lane may wake. Even a wake
                # receipt is not authority: recheck capacity, then Guard/Work.
                if (ticket_id not in self.wake_tickets
                        or ticket_id in self.wake_first_tickets or self.wake is None
                        or not self.wake(ticket_id) or not self.ready(ticket_id)):
                    return {"ticket_id": ticket_id, "state": self.waiting_state,
                            "github_published": False}
        return self.port.run(principal, ticket_id)


def stdio():
    from ai_foundation.store import SQLiteGuardStore
    from ai_foundation.storage_admission import StorageAdmission
    from m1_development_ticket_factory import build_development_port
    from m1_owner_delegated_mcp_stdio import build_owner_mcp
    from foundation_mcp_stdio import serve_stdio
    _, config, root = installed_config()
    guard_path = root / config.guard_db
    if not guard_path.is_file() or guard_path.is_symlink():
        raise ValueError("OWNER_GUARD_UNAVAILABLE")
    def factory(guard):
        from m1_development_ticket_factory import _owner_file, _strict_json
        port = build_development_port(root=root, config=config, repo=ROOT, guard=guard)
        # The existing factory has already validated all source/test/public
        # hashes. A caller may select a ticket ID, never its model or target.
        records = _strict_json(_owner_manifest(root / "development/tickets.json"))["tickets"]
        strict = {record["ticket_id"] for record in records
                  if record["model"] == "strata"}
        for ticket_id in strict:
            task = port.tasks[ticket_id]
            task.proposal_agent.m1 = NoM1Fallback()
            port.tasks[ticket_id] = replace(task, max_repairs=0)
        return StrataReadyPort(
            port, lambda ticket_id: port.tasks[ticket_id].proposal_agent.remote is not None
                                   and strata_ready(root), strict,
            wake=lambda ticket_id: wake_strata_once(root, ticket_id), wake_tickets=strict)
    server = build_owner_mcp(SQLiteGuardStore(guard_path, storage_admission=StorageAdmission(root)),
                             development_port_factory=factory)
    serve_stdio(server)


def verified_code_receipt(written, readback, replay, model):
    if type(model) is not str:
        return False
    allowed = {
        "m1": {"local:ollama-shared9b:general"},
        "strata": {"local:mainpc-strata:code-agent"},
        "auto": {"local:ollama-shared9b:general", "local:mainpc-strata:code-agent"},
    }
    return (written == readback == replay and type(written) is dict
            and written.get("state") == "VERIFIED_LOCAL"
            and written.get("execution_binding") in allowed.get(model, ()))


def client(run=False, ticket_id=TICKET):
    from m1_p4_mcp_stdio_e2e import _request
    model = "strata"
    if run:
        from m1_development_ticket_factory import _owner_file, _strict_json, _ID
        if type(ticket_id) is not str or not _ID.fullmatch(ticket_id):
            raise ValueError("DEVELOPMENT_TICKET_NOT_ADMITTED")
        _, _, root = installed_config()
        # Preserve the existing fixed-ticket preflight for already installed
        # r2 clients. All subsequent tickets must exist in the private host
        # manifest before they can even enter an MCP session.
        strict = ticket_id == TICKET
        if ticket_id != TICKET:
            manifest = _strict_json(_owner_manifest(root / "development/tickets.json"))
            matches = [r for r in manifest["tickets"] if r["ticket_id"] == ticket_id]
            if len(matches) != 1:
                raise ValueError("DEVELOPMENT_TICKET_NOT_ADMITTED")
            model = matches[0]["model"]
            if model not in ("m1", "auto", "strata"):
                raise ValueError("DEVELOPMENT_MODEL_NOT_ADMITTED")
            strict = model == "strata"
        # A configured but sleeping MainPC is handled only by the guarded
        # READY-ticket port below. Do not preemptively wake on CLI entry:
        # verified/failed/review-required tickets must remain read-only.
        if strict and not strata_ready(root) and not strata_configured(root):
            return {"status": "STRATA_CREDENTIAL_OR_MODEL_UNAVAILABLE", "model_calls": 0,
                    "ticket_started": False, "github_in_run_loop": False}
    calls = [_request(1, "server/discover"), _request(2, "tools/list"),
             _request(3, "tools/call", name="development_status", arguments={"ticket_id": ticket_id})]
    if run:
        calls += [_request(4, "tools/call", name="development_run", arguments={"ticket_id": ticket_id})]
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "USER", "TMPDIR", "LANG", "LC_ALL", "STRATA_API_KEY"}}
    child = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "stdio"],
                           input="\n".join(json.dumps(c) for c in calls) + "\n", capture_output=True,
                           text=True, timeout=650, env=env)
    if child.returncode:
        return {"status": "MCP_HOST_UNAVAILABLE", "github_in_run_loop": False}
    rows = [json.loads(line) for line in child.stdout.splitlines()]
    if len(rows) != len(calls) or [r.get("id") for r in rows] != [c["id"] for c in calls]:
        return {"status": "MCP_FRAMING_UNVERIFIED"}
    def result(row):
        data = row.get("result", {})
        if data.get("isError") is not False:
            raise ValueError("MCP_CALL_UNVERIFIED")
        return json.loads(data["content"][0]["text"])
    before = result(rows[2])
    if not run:
        return {"status": "OBSERVED", "ticket": before, "github_in_run_loop": False}
    written = result(rows[3])
    if written.get("state") != "VERIFIED_LOCAL":
        return {"status": "MCP_CODE_NOT_VERIFIED", "ticket": written,
                "github_in_run_loop": False,
                "cloud_chatgpt_muse_connection_verified": False}
    # A 300s inference plus fixed acceptance can outlive the first session.
    # Reconnect only for durable verification/replay, never rerun an uncertain
    # first attempt. The canonical Work claim makes the replay read-only.
    followup = [_request(1, "server/discover"), _request(2, "tools/list"),
                _request(3, "tools/call", name="development_status", arguments={"ticket_id": ticket_id}),
                _request(4, "tools/call", name="development_run", arguments={"ticket_id": ticket_id})]
    child = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()), "stdio"],
                           input="\n".join(json.dumps(c) for c in followup) + "\n", capture_output=True,
                           text=True, timeout=90, env=env)
    refreshed = [json.loads(line) for line in child.stdout.splitlines()]
    if child.returncode or len(refreshed) != 4 or [r.get("id") for r in refreshed] != [1, 2, 3, 4]:
        return {"status": "MCP_POSTRUN_READBACK_UNVERIFIED", "ticket": written}
    readback, replay = map(result, refreshed[2:])
    verified = verified_code_receipt(written, readback, replay, model)
    return {"status": "MCP_CODE_VERIFIED" if verified else "MCP_CODE_NOT_VERIFIED",
            "ticket": readback, "durable_readback_matches": written == readback,
            "replay_readonly": readback == replay, "github_in_run_loop": False,
            "cloud_chatgpt_muse_connection_verified": False}


def main():
    from m1_development_bridge import require_m1
    require_m1()
    if os.getuid() != 501 or os.geteuid() != os.getuid():
        raise SystemExit("M1_OWNER_SESSION_REQUIRED")
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("install", "install-run", "run", "status", "diagnose", "deliver", "stdio", "admit"))
    parser.add_argument("ticket_id", nargs="?", default=TICKET)
    args = parser.parse_args()
    if args.mode == "stdio":
        return stdio()
    try:
        if args.mode in {"install", "install-run"}:
            result = install()
            if args.mode == "install-run":
                installation = result
                # The local acceptance commit lives in the persistent owner's
                # object database. Never run the child from the disposable
                # bootstrap clone, which cannot resolve that commit.
                child = subprocess.run([installation["launcher"], "run"],
                                       capture_output=True, text=True, timeout=750)
                result = {"installation": installation, **json.loads(child.stdout)}
        elif args.mode == "diagnose":
            result = diagnose()
        elif args.mode == "admit":
            from m1_strata_owner_ticket_admission import admit
            result = admit(args.ticket_id)
        elif args.mode == "deliver":
            if args.ticket_id != TICKET:
                # The historical r2 publisher is not a general publication
                # grant. Never silently publish r2 for a different requested ID.
                result = {"status": "DELIVERY_TICKET_REVIEW_REQUIRED",
                          "ticket_id": args.ticket_id, "model_calls": 0}
            elif not owner_gh_authenticated():
                result = {"status": "OWNER_GITHUB_AUTH_UNAVAILABLE", "model_calls": 0}
            else:
                authorize_verified_delivery()
                result = deliver_client()
        else:
            result = client(args.mode == "run", args.ticket_id)
    except Exception as exc:
        result = {"status": "DIRECT_DEVELOPMENT_BLOCKED", "error_type": type(exc).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in {"DIRECT_DEVELOPMENT_INSTALLED", "MCP_CODE_VERIFIED", "OBSERVED", "DIRECT_DEVELOPMENT_OBSERVED", "DRAFT_DELIVERY_VERIFIED", "TICKET_ADMITTED", "ALREADY_ADMITTED"} else 2


if __name__ == "__main__":
    raise SystemExit(main())

