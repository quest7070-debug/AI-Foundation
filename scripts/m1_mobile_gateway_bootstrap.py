#!/usr/bin/env python3
"""One-time M1 owner bootstrap: existing Operator Guard -> separately Guarded mobile gateway.

Exactly one locally initiated owner session, two independent human Guard
approvals, no model, no generic shell/API effect, no arbitrary source input.
All calls to launchd remain inside the bounded, rollback-capable host adapter.
After this one-time migration, normal releases use the authenticated /release
smartphone UI rather than owner terminal copy/paste.
"""
from __future__ import annotations
import hashlib
import http.client
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from scripts import m1_operator_release_cli as cli
from ai_foundation.release_gate import ImmutableReleaseScope

# Existing, already PREPARED, owner-requested PR #1502. No new request or ref
# is fabricated, and this script never approves either Guard request.
OPERATOR_HEAD = "425e6d4a0dfe80eb50b9d18554286682fba57c3f"
OPERATOR_RUN = "release-59a238b6b90d10e6aabb7b7e"
OPERATOR_REF = "4a253d427f850e7724c4bc3a6e00c2ceff639b3f2a418b9c813e3ad69fb2c6c2"
OPERATOR_SCOPE = "4ebdd05052882b589d193a937ae7ba2026ab1cb4ab1c79264c35ea65c156b38c"
LABEL = "dev.quest7070.ai-foundation.remote-gateway"
PORT = 8793
WAIT_SECONDS = 900
ROOT = Path(__file__).resolve().parents[1]
_SHA = re.compile(r"[a-f0-9]{40}\Z")


class BootstrapDenied(RuntimeError):
    pass


def report(state, **details):
    print(json.dumps({"status": state, **details}, sort_keys=True), flush=True)


def _cmd(*args, timeout=16):
    return subprocess.run(args, capture_output=True, text=True,
                          timeout=timeout, check=False)


def _commit(root):
    row = _cmd("/usr/bin/git", "-C", str(root), "rev-parse", "HEAD", timeout=6)
    head = row.stdout.strip()
    if row.returncode or not _SHA.fullmatch(head):
        raise BootstrapDenied("OWNER_STAGED_HEAD_UNVERIFIED")
    cli._owner_staged_source(head, Path.home(), root)
    if cli._release_canon(root).get("status") != "CANON_SOURCE_VERIFIED":
        raise BootstrapDenied("STAGED_CANON_UNVERIFIED")
    return head


def _owner_confirm(text, expected):
    if not cli._tty_confirm(text, expected):
        raise BootstrapDenied("EXACT_OWNER_TERMINAL_CONFIRMATION_REQUIRED")


def _wait_approval(scope, run, ref):
    """Read the exact existing owner authority; never approve for the owner."""
    end = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < end:
        verification = cli._guard_gate(Path.home(), readonly=True,
                                       scope=scope if getattr(scope, "path", None) == "m1-operator" else None).verify(scope, run, ref)
        if (verification.get("status") == "APPROVED"
                and verification.get("approved") is True
                and verification.get("scope_ref") == scope.scope_ref):
            return
        if verification.get("status") not in ("OWNER_APPROVAL_REQUIRED", "PENDING"):
            raise BootstrapDenied("EXACT_GUARD_STATE_CHANGED")
        time.sleep(3)
    raise BootstrapDenied("OWNER_APPROVAL_STILL_PENDING")


def observe_existing_operator_guard():
    """Classify the frozen PR1502 release using ONLY scoped read-only M1 state.

    Does not create a request, claim approval, choose a new release or
    access the running service for a mutation. Never returns private paths,
    run IDs, secret values or raw Guard exception messages.
    """
    home = Path.home()
    staged = home / ".ai-foundation-tunnel-sources" / OPERATOR_HEAD
    # After a successful release, calculating a *new* immutable scope
    # against the now-loaded incumbent cannot reproduce the old scope.
    # First read the exact installed VERIFIED receipt with physical PID/API
    # proof. Never interpret scope rotation as a failed deployment.
    incumbent_gate = cli._guard_gate(home, readonly=True)
    loaded = incumbent_gate.registry.get("m1-operator")
    if (loaded is not None and loaded.status == "VERIFIED"
            and loaded.release_scope_ref == OPERATOR_SCOPE
            and loaded.release_run_id == OPERATOR_RUN
            and loaded.release_request_ref == OPERATOR_REF):
        installed = cli.FixedOperatorHost(staged, home=home)
        return ("EXACT_OPERATOR_ALREADY_LOADED" if
                installed.verified_current_release(loaded) is True
                else "OPERATOR_LEDGER_ONLY_NOT_LOADED")
    # Before first cutover, the original candidate scope is still
    # derived from the unchanged incumbent. Exact Guard approval remains
    # separate from the release and needs a further owner action.
    scope = cli._release_scope(staged, OPERATOR_HEAD, home)
    if scope.scope_ref != OPERATOR_SCOPE:
        return "OPERATOR_SOURCE_SCOPE_CHANGED"
    gate = cli._guard_gate(home, readonly=True, scope=scope)
    prior = gate.registry.get(scope.path)
    if prior is None:
        return "EXACT_OPERATOR_RELEASE_NOT_FOUND"
    if (prior.release_scope_ref != OPERATOR_SCOPE
            or prior.release_run_id != OPERATOR_RUN
            or prior.release_request_ref != OPERATOR_REF):
        return "EXACT_OPERATOR_RELEASE_BINDING_CHANGED"
    if prior.status == "VERIFIED":
        installed = cli.FixedOperatorHost(staged, home=home)
        return ("EXACT_OPERATOR_ALREADY_LOADED" if
                installed.verified_current_release(prior) is True
                else "OPERATOR_LEDGER_ONLY_NOT_LOADED")
    if prior.status != "PREPARED":
        return "EXACT_OPERATOR_RELEASE_RECONCILE_REQUIRED"
    verification = gate.verify(scope, OPERATOR_RUN, OPERATOR_REF)
    if (verification.get("status") == "APPROVED"
            and verification.get("approved") is True
            and verification.get("scope_ref") == OPERATOR_SCOPE):
        return "EXACT_GUARD_APPROVED_OWNER_APPLY_REQUIRED"
    if verification.get("status") == "OWNER_APPROVAL_REQUIRED":
        return "EXACT_GUARD_NOT_APPROVED"
    return "EXACT_GUARD_DECISION_UNVERIFIED"


def _operator_release():
    home = Path.home()
    staged = home / ".ai-foundation-tunnel-sources" / OPERATOR_HEAD
    scope = cli._release_scope(staged, OPERATOR_HEAD, home)
    if scope.scope_ref != OPERATOR_SCOPE:
        raise BootstrapDenied("EXACT_OPERATOR_SCOPE_CHANGED")
    gate = cli._guard_gate(home, readonly=True, scope=scope)
    prior = gate.registry.get(scope.path)
    if (prior is None or prior.release_scope_ref != OPERATOR_SCOPE
            or prior.release_run_id != OPERATOR_RUN
            or prior.release_request_ref != OPERATOR_REF
            or prior.status not in ("PREPARED", "VERIFIED")):
        raise BootstrapDenied("EXACT_OPERATOR_RELEASE_NOT_PREPARED")
    if prior.status == "VERIFIED":
        installed = cli.FixedOperatorHost(staged, home=home)
        if installed.verified_current_release(prior) is not True:
            raise BootstrapDenied("OPERATOR_VERIFIED_NOT_LOADED")
        report("OPERATOR_PREVIOUSLY_VERIFIED")
        return

    _owner_confirm("One-time installation: existing Guard-scoped Operator release.\n"
                   "This does NOT authorize the separate gateway switch.",
                   "APPLY " + OPERATOR_SCOPE[:16])
    report("AUTHORIZE_EXISTING_OPERATOR_IN_PHONE", run_id=OPERATOR_RUN,
           scope_ref=OPERATOR_SCOPE, phone_port=8454)
    _wait_approval(scope, OPERATOR_RUN, OPERATOR_REF)
    # Reuse the original installed host adapter, not a new service executor.
    result = cli.run(
        SimpleNamespace(operation="apply", expected_head=OPERATOR_HEAD,
                        canon_revision=None, run_id=OPERATOR_RUN,
                        request_ref=OPERATOR_REF),
        trusted_source_root=staged,
        confirmer=lambda _prompt, phrase: phrase == "APPLY " + OPERATOR_SCOPE[:16],
    )
    if (result.get("status") != "VERIFIED" or
            result.get("scope_ref") != OPERATOR_SCOPE or
            result.get("guard_approved") is not True):
        raise BootstrapDenied("OPERATOR_RELEASE_READBACK_UNVERIFIED")
    report("OPERATOR_VERIFIED", scope_ref=OPERATOR_SCOPE)


def _owned_plist():
    folder = Path.home() / "Library/LaunchAgents"
    if folder.is_symlink():
        raise BootstrapDenied("LAUNCHD_ROOT_UNTRUSTED")
    candidates = list(folder.glob("*.plist"))
    if len(candidates) > 200:
        raise BootstrapDenied("LAUNCHD_INVENTORY_UNBOUNDED")
    found = []
    for p in candidates:
        try:
            st = p.lstat()
            if (not stat.S_ISREG(st.st_mode) or st.st_uid != os.getuid()
                    or st.st_mode & 0o022 or st.st_size > 65536
                    or p.is_symlink()):
                continue
            raw = p.read_bytes()
            doc = plistlib.loads(raw)
            if type(doc) is dict and doc.get("Label") == LABEL:
                found.append((p, raw, doc, stat.S_IMODE(st.st_mode)))
        except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
            continue
    if len(found) != 1:
        raise BootstrapDenied("EXACT_GATEWAY_LAUNCHAGENT_UNAVAILABLE")
    return found[0]


def _opt(args, name, default=None):
    matches = [i for i, value in enumerate(args)
               if value == name or value.startswith(name + "=")]
    if len(matches) > 1:
        raise BootstrapDenied("AMBIGUOUS_GATEWAY_ARGUMENTS")
    if not matches:
        return default
    at = matches[0]
    if args[at] == name:
        if at + 1 == len(args):
            raise BootstrapDenied("INCOMPLETE_GATEWAY_ARGUMENTS")
        return args[at + 1]
    return args[at].split("=", 1)[1]


def _launcher_kind(argv):
    """Return only a bounded class, never an owner-private executable path."""
    if type(argv) is not list or not argv or type(argv[0]) is not str:
        return "MALFORMED"
    launcher = Path(argv[0])
    if not launcher.is_absolute():
        return "RELATIVE"
    name = launcher.name.lower()
    if name in ("sh", "bash", "zsh", "fish", "env"):
        return "SHELL_OR_WRAPPER"
    # Python.app and venv 'python' are legitimate installed aliases.
    # Do not accept arbitrary wrappers, PATH lookup, -c, or -m.
    if re.fullmatch(r"python(?:3(?:\.1[2-5])?)?", name):
        return "PYTHON"
    return "OTHER"


def _candidate_plist(old, staged):
    doc = dict(old)
    argv = doc.get("ProgramArguments")
    env = doc.get("EnvironmentVariables")
    if (type(argv) is not list or len(argv) > 32 or
            any(type(x) is not str or len(x) > 4096 for x in argv)
            or type(env) is not dict
            or not isinstance(env.get("FOUNDATION_REMOTE_ALLOWED_HOSTS"), str)
            or ".ts.net" not in env["FOUNDATION_REMOTE_ALLOWED_HOSTS"]):
        raise BootstrapDenied("GATEWAY_LAUNCH_SHAPE_UNVERIFIED")
    # Preserve the already installed and PID-proven Python executable.
    # Its owner path may be a Homebrew symlink, Cellar alias or a Python.app
    # launcher; forcing one symlink spelling would reject a healthy service.
    # Never accept shells, env wrappers, -c, -m or a relative command.
    # The installed owner-controlled LaunchAgent can use a venv's
    # absolute .../bin/python alias. Preserve that already running
    # executable; never replace it with a guessed Homebrew interpreter.
    if _launcher_kind(argv) != "PYTHON":
        raise BootstrapDenied("GATEWAY_PYTHON_LAUNCHER_MISMATCH")
    if any(key in env for key in ("PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE")):
        raise BootstrapDenied("GATEWAY_PYTHON_ENV_UNTRUSTED")
    if (_opt(argv, "--port", "8793") != "8793"
            or _opt(argv, "--upstream-port", "8766") != "8766"):
        raise BootstrapDenied("GATEWAY_PORT_CHANGED")
    if not _opt(argv, "--cert") or not _opt(argv, "--key"):
        raise BootstrapDenied("GATEWAY_TLS_ARGS_UNVERIFIED")
    scripts = [i for i, val in enumerate(argv)
               if val.endswith("/scripts/run_remote_gateway.py")]
    if (len(scripts) != 1 or any(v in ("-c", "-m") for v in argv)
            or scripts[0] not in (1, 2)
            or argv[1:scripts[0]] not in ([], ["-B"])):

        raise BootstrapDenied("GATEWAY_RUNNER_IDENTITY_UNVERIFIED")
    new_args = list(argv)
    new_args[scripts[0]] = str(staged / "scripts/run_remote_gateway.py")
    if any(v == "--listen" or v.startswith("--listen=") for v in new_args):
        pos = next(i for i, v in enumerate(new_args)
                   if v == "--listen" or v.startswith("--listen="))
        if new_args[pos] == "--listen":
            if pos + 1 >= len(new_args):
                raise BootstrapDenied("GATEWAY_LISTEN_OPTION_INVALID")
            new_args[pos + 1] = "127.0.0.1"
        else:
            new_args[pos] = "--listen=127.0.0.1"
    else:
        new_args += ["--listen", "127.0.0.1"]
    if _opt(new_args, "--listen") != "127.0.0.1":
        raise BootstrapDenied("GATEWAY_LOOPBACK_NOT_PINNED")
    new_env = dict(env)
    new_env["FOUNDATION_REMOTE_SERVE_OWNER_ENABLED"] = "1"
    new_env["FOUNDATION_REMOTE_MOBILE_RELEASE_ENABLED"] = "1"
    new_env["PYTHONPATH"] = str(staged / "src") + ":" + str(staged)
    doc["EnvironmentVariables"] = new_env
    doc["ProgramArguments"] = new_args
    doc["WorkingDirectory"] = str(staged)
    return plistlib.dumps(doc, sort_keys=True)


def _running():
    result = _cmd("/bin/launchctl", "print",
                  "gui/" + str(os.getuid()) + "/" + LABEL, timeout=7)
    if result.returncode:
        return None
    match = re.search(r"^\s*pid = ([0-9]+)\s*$", result.stdout, re.M)
    return int(match[1]) if match else None


def _port_owned(pid, *, strict_local):
    row = _cmd("/usr/sbin/lsof", "-nP", "-iTCP:" + str(PORT),
               "-sTCP:LISTEN", timeout=8)
    if row.returncode or pid is None:
        return False
    entries = [x.split() for x in row.stdout.splitlines()[1:] if x.strip()]
    if not entries or any(len(x) < 9 or x[1] != str(pid) for x in entries):
        return False
    if strict_local:
        # On macOS lsof NAME renders "TCP 127.0.0.1:8793 (LISTEN)".
        # The last token is (LISTEN), so read the address immediately
        # before it. Fail closed for unexpected/ambiguous output shapes.
        addresses = [
            row[-2] if row[-1] == "(LISTEN)" else row[-1]
            for row in entries]
        return all(
            addr in ("127.0.0.1:" + str(PORT), "[::1]:" + str(PORT))
            for addr in addresses)
    return True


def _gateway_http():
    context = ssl._create_unverified_context()
    conn = http.client.HTTPSConnection("127.0.0.1", PORT,
                                       context=context, timeout=4)
    try:
        conn.request("GET", "/health", headers={"Host": "127.0.0.1"})
        res = conn.getresponse()
        data = res.read(2048)
        return res.status == 200 and b'"ok":true' in data
    finally:
        conn.close()


def _write_plist(path, content, mode):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=".mobile-gw-", suffix=".plist")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _stop_and_start(path, new, mode):
    if _running() is not None:
        r = _cmd("/bin/launchctl", "bootout",
                 "gui/" + str(os.getuid()) + "/" + LABEL, timeout=25)
        if r.returncode:
            raise BootstrapDenied("GATEWAY_BOOTOUT_REJECTED")
    for _ in range(40):
        if _running() is None:
            break
        time.sleep(.25)
    else:
        raise BootstrapDenied("GATEWAY_BOOTOUT_NOT_SETTLED")
    _write_plist(path, new, mode)
    r = _cmd("/bin/launchctl", "bootstrap", "gui/" + str(os.getuid()),
             str(path), timeout=25)
    if r.returncode:
        raise BootstrapDenied("GATEWAY_BOOTSTRAP_REJECTED")


def _gateway_readback(path, expected, *, strict_local):
    if path.read_bytes() != expected:
        return False
    for _ in range(40):
        pid = _running()
        if pid is not None and _port_owned(pid, strict_local=strict_local):
            try:
                if _gateway_http():
                    return True
            except (OSError, ValueError, http.client.HTTPException, ssl.SSLError):
                pass
        time.sleep(.5)
    return False


def _backup(home, raw, suffix):
    folder = home / "Library/Application Support/AI-Foundation/mobile-gateway-backups"
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    st = folder.lstat()
    if folder.is_symlink() or st.st_uid != os.getuid() or st.st_mode & 0o077:
        raise BootstrapDenied("BACKUP_ROOT_UNTRUSTED")
    path = folder / ("gateway-prior-" + suffix + ".plist")
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        try: path.unlink()
        except OSError: pass
        raise
    if path.read_bytes() != raw:
        raise BootstrapDenied("GATEWAY_ROLLBACK_SNAPSHOT_UNVERIFIED")
    return path


def _gateway_release(head):
    home = Path.home()
    path, old, doc, mode = _owned_plist()
    new = _candidate_plist(doc, ROOT)
    if new == old:
        raise BootstrapDenied("GATEWAY_ALREADY_RUNNING_NEW_SOURCE")
    if _running() is None or not _port_owned(_running(), strict_local=False):
        raise BootstrapDenied("ORIGINAL_GATEWAY_UNVERIFIED")
    try:
        if not _gateway_http():
            raise BootstrapDenied("ORIGINAL_GATEWAY_HEALTH_UNVERIFIED")
    except (OSError, ssl.SSLError, http.client.HTTPException):
        raise BootstrapDenied("ORIGINAL_GATEWAY_HEALTH_UNVERIFIED") from None
    scope = ImmutableReleaseScope(
        path="m1-remote-gateway", source_sha=head,
        previous_authority="launchd:" + LABEL + ":sha256:" +
            hashlib.sha256(old).hexdigest(),
        previous_endpoint="https://127.0.0.1:8793",
        candidate_authority="github-commit:" + head,
        candidate_endpoint="https://127.0.0.1:8793/mobile-owner",
        rollback_procedure="RESTORE_EXACT_PREVIOUS_GATEWAY_LAUNCHAGENT_AND_PID_READBACK",
        switch_target=LABEL, readback_target="PID_BOUND_127.0.0.1_8793",
        rollback_readback_target="PRIOR_PLIST_AND_8793_HEALTH",
    )
    _owner_confirm("Independent remote-gateway service release. This modifies ONLY " +
                   LABEL + ", not the separate HumanReview gateway or other Serve routes.",
                   "GATEWAY " + scope.scope_ref[:16])
    source = cli._release_canon(ROOT)
    gate = cli._guard_gate(home)
    prepared = gate.prepare(scope, canon_revision=source["canon_revision"])
    if (prepared.get("status") != "WAITING_HUMAN"
            or prepared.get("scope_ref") != scope.scope_ref
            or prepared.get("ok") is not True):
        raise BootstrapDenied("GATEWAY_GUARD_PREPARE_FAILED")
    run, ref = prepared["run_id"], prepared["request_ref"]
    report("AUTHORIZE_SEPARATE_GATEWAY_IN_PHONE", run_id=run, scope_ref=scope.scope_ref,
           phone_port=8454)
    _wait_approval(scope, run, ref)
    if (cli._release_canon(ROOT)["canon_revision"] != source["canon_revision"]
            or _commit(ROOT) != head
            or _owned_plist()[1] != old
            or cli._guard_gate(home, readonly=True).verify(
                scope, run, ref).get("status") != "APPROVED"):
        raise BootstrapDenied("GATEWAY_RELEASE_DRIFT_OR_NO_APPROVAL")
    _backup(home, old, scope.scope_ref[:16])
    # A remote approval may be revoked or source/listener drift between
    # snapshot and actual launchctl. Recheck the exact prior at the effect edge.
    if (_owned_plist()[1] != old or _commit(ROOT) != head
            or cli._guard_gate(home, readonly=True).verify(
                scope, run, ref).get("status") != "APPROVED"):
        raise BootstrapDenied("GATEWAY_RELEASE_CHANGED_BEFORE_CUTOVER")
    gate.registry.transition(scope.path, "PREPARED", "CUTOVER")
    try:
        _stop_and_start(path, new, mode)
        if not _gateway_readback(path, new, strict_local=True):
            raise BootstrapDenied("NEW_GATEWAY_PID_AND_HTTP_UNVERIFIED")
        gate.registry.transition(scope.path, "CUTOVER", "VERIFIED")
    except BaseException:
        try:
            _stop_and_start(path, old, mode)
            if not _gateway_readback(path, old, strict_local=False):
                raise BootstrapDenied("GATEWAY_ROLLBACK_READBACK_FAILED")
            gate.registry.transition(scope.path, "CUTOVER", "ROLLED_BACK")
        except BaseException as exc:
            raise BootstrapDenied("GATEWAY_MANUAL_RECOVERY_REQUIRED") from exc
        raise
    report("MOBILE_GATEWAY_VERIFIED", scope_ref=scope.scope_ref,
           port=PORT, loopback_only=True, serve_port=8454)


def main():
    try:
        cli._owner_session()
        head = _commit(ROOT)
        report("OWNER_BOOTSTRAP_SOURCE_VERIFIED", head=head, service_mutations=0)
        _operator_release()
        _gateway_release(head)
        report("MOBILE_RELEASE_BOOTSTRAP_VERIFIED", service="remote-gateway",
               expected_url="https://owner-m1.example.ts.net:8454/release")
        return 0
    except (BootstrapDenied, cli.OwnerReleaseDenied, OSError, ValueError,
            RuntimeError, KeyError, TypeError) as exc:
        if type(exc) is BootstrapDenied:
            reason = str(exc)
        elif type(exc) is cli.OwnerReleaseDenied:
            reason = cli._safe_failure_reason(exc)
        else:
            reason = "BOOTSTRAP_PRECONDITION_OR_SERVICE_UNVERIFIED"
        report("BLOCKED", reason=reason)
        return 2


if __name__ == "__main__":
    sys.exit(main())
