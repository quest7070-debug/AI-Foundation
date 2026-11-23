"""Host-side OpenCode V2 CLI fixture acceptance, isolated by contract.

No automatic installation or model inference. Only a separately verified
host OS network sandbox may launch an actual binary. The CLI receives no
provider keys; a loopback fake model alone cannot charge an external API.
A custom command runner may be used for deterministic CI tests. The caller
cannot authorize arbitrary prompts, model changes, tools or other providers.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import tempfile

from .harness_public_canary import (
    PUBLIC_CANARY_PROMPT, PUBLIC_CANARY_SOURCE,
    independent_public_canary_review,
)
from .opencode_model_gate import (
    CONTAINER_MODEL, opencode_v2_isolated_config,
    run_fixture_gate_for_test,
)


@dataclass(frozen=True)
class NativeIsolationReceipt:
    """Evidence supplied by trusted native host, not by OpenCode."""
    binary_sha256: str
    verified_sha256: str
    version: str
    native_network_denies_all_external: bool
    only_loopback_gateway_allowed: bool
    filesystem_isolation_verified: bool
    shared_credentials_inaccessible: bool
    no_background_server_verified: bool


def admission(receipt):
    if not isinstance(receipt, NativeIsolationReceipt):
        return "HOST_OS_SANDBOX_NOT_ATTESTED"
    if not re.fullmatch(r"[a-f0-9]{64}", receipt.binary_sha256):
        return "PINNED_BINARY_DIGEST_REQUIRED"
    if receipt.verified_sha256 != receipt.binary_sha256:
        return "BINARY_DIGEST_MISMATCH"
    if not (receipt.version.startswith("2.") and
            re.fullmatch(r"2\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
                         receipt.version)):
        return "OPENCODE_V2_BINARY_REQUIRED"
    gates = (
        ("native_network_denies_all_external", "EXTERNAL_EGRESS_NOT_BLOCKED"),
        ("only_loopback_gateway_allowed", "GATEWAY_NOT_ISOLATED"),
        ("filesystem_isolation_verified", "FILESYSTEM_SANDBOX_MISSING"),
        ("shared_credentials_inaccessible", "SHARED_SECRETS_ACCESSIBLE"),
        ("no_background_server_verified", "SHARED_SERVER_RISK"),
    )
    for field, error in gates:
        if getattr(receipt, field) is not True:
            return error
    return "HOST_OS_SANDBOX_ATTESTED"


def safe_cli_plan(gateway_port, *, executable="/usr/local/bin/opencode"):
    if type(executable) is not str or not executable.startswith(
            ("/usr/local/bin/", "/opt/homebrew/bin/")):
        raise ValueError("UNREVIEWED_OPENCODE_PATH")
    if not re.fullmatch(r"/[a-zA-Z0-9_/.+-]{4,200}", executable):
        raise ValueError("UNREVIEWED_OPENCODE_PATH")
    return {
        "argv": [
            executable, "run", "--standalone",
            "--title", "Foundation public canary",
            "--model", CONTAINER_MODEL,
            "--format", "default",
            PUBLIC_CANARY_PROMPT,
        ],
        "config": opencode_v2_isolated_config(gateway_port),
        "execution_authorized": False,
        "mode": "HOST_OS_ISOLATION_REQUIRED",
    }


def _isolated_env(config, temp_root):
    root = Path(temp_root)
    # None of the user's normal home, cloud credentials, project or session
    # state can flow via environment variables. The native OS sandbox must
    # independently deny filesystem and network access.
    return {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(root),
        "XDG_CONFIG_HOME": str(root / "config"),
        "XDG_DATA_HOME": str(root / "data"),
        "XDG_CACHE_HOME": str(root / "cache"),
        "TMPDIR": str(root),
        "OPENCODE_CONFIG_CONTENT": json.dumps(
            config, separators=(",", ":"), ensure_ascii=True),
        "OPENCODE_PURE": "1",
        "OPENCODE_DISABLE_PROJECT_CONFIG": "1",
        "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_TERMINAL_TITLE": "1",
        "OPENCODE_DISABLE_PRUNE": "1",
        "NO_COLOR": "1",
    }


def _cli_failure_class(result):
    """Fixed safe categories only; never return any portion of CLI logs."""
    stderr = getattr(result, "stderr", b"")
    stdout = getattr(result, "stdout", b"")
    if (type(stderr) is not bytes or type(stdout) is not bytes
            or len(stderr) > 131072 or len(stdout) > 32768):
        return "CLI_LOG_UNAVAILABLE"
    output = (stderr + b"\n" + stdout).lower()
    signatures = (
        ("CLI_UNSUPPORTED_FLAG", (b"unknown option", b"unknown argument",
                                  b"unknown flag", b"unrecognized argument")),
        ("CLI_CONFIG_INVALID", (b"invalid config", b"configuration error",
                                b"config invalid", b"invalid configuration",
                                b"configvalidation", b"failed to load config")),
        ("CLI_PROVIDER_UNRESOLVED", (b"provider not found", b"model not found",
                                     b"unknown model", b"modelnotfound",
                                     b"provider unavailable", b"no model is available")),
        ("CLI_SDK_PACKAGE_MISSING", (b"module not found", b"cannot find package",
                                     b"failed to resolve module", b"bun install",
                                     b"missing package", b"package not found")),
        ("CLI_NETWORK_OR_SDK_UNAVAILABLE", (b"enotfound", b"enetunreach",
                                             b"fetch failed", b"network error",
                                             b"connection refused", b"econnrefused")),
        ("CLI_SANDBOX_FILE_ACCESS", (b"eacces", b"permission denied",
                                     b"read-only file system", b"erofs",
                                     b"sqlite_cantopen")),
        ("CLI_RUNTIME_PANIC", (b"panic:", b"segmentation fault", b"bun fatal",
                               b"runtimeerror", b"unhandled exception")),
    )
    for label, patterns in signatures:
        if any(x in output for x in patterns):
            return label
    return "CLI_EXIT_OR_OUTPUT_UNCLASSIFIED"


def _cli_failure_signal(result):
    """Summary metadata only; no user content, error message, or raw paths."""
    stdout = getattr(result, "stdout", None)
    stderr = getattr(result, "stderr", None)
    def length(value):
        return len(value) if type(value) is bytes and len(value) <= 131072 else None
    # Only known *single words* may leave the host. Never return errors,
    # full stdout/stderr, paths, model text or arbitrary substrings.
    tokens = frozenset((
        "api", "auth", "bun", "catalog", "cli", "config", "connect",
        "credential", "database", "denied", "error", "failed", "file",
        "flag", "format", "gateway", "import", "init", "invalid",
        "json", "key", "login", "mcp", "missing", "model", "module",
        "network", "option", "package", "permission", "plugin",
        "policy", "project", "provider", "registry", "resolve",
        "runtime", "server", "session", "sqlite", "standalone",
        "system", "timeout", "token", "tool", "unknown", "unavailable",
        "unsupported", "usage", "warning", "workspace",
    ))
    raw = (stdout + b"\\n" + stderr).lower() if (
        type(stdout) is bytes and type(stderr) is bytes
        and len(stdout) <= 32768 and len(stderr) <= 131072) else b""
    detected = [term for term in sorted(tokens)
                if re.search(rb"(?<![a-z])" + term.encode() + rb"(?![a-z])", raw)]
    stderr_data = stderr.lower() if type(stderr) is bytes and len(stderr) <= 131072 else b""
    grammar = frozenset((
        "argument", "command", "error", "expected", "flag", "help",
        "invalid", "missing", "model", "option", "provider", "required",
        "supported", "unknown", "unrecognized", "usage", "value", "warning",
    ))
    stderr_words = [word for word in sorted(grammar)
                    if re.search(rb"(?<![a-z])" + word.encode() + rb"(?![a-z])",
                                 stderr_data)]
    safe_flags = ("pure", "print-logs", "log-level", "standalone", "model", "format")
    stderr_flags = [flag for flag in safe_flags
                    if b"--" + flag.encode() in stderr_data]
    stdout_help = (type(stdout) is bytes and
                   b"usage:" in stdout.lower() and
                   b"run" in stdout.lower())
    return {"cli_stdout_bytes": length(stdout),
            "cli_stderr_bytes": length(stderr),
            "cli_text_has_error": b"error" in raw,
            "cli_diagnostic_tokens": detected,
            "cli_stderr_words": stderr_words,
            "cli_stderr_flag_mentions": stderr_flags,
            "cli_stdout_looks_like_help": stdout_help}




def accept_public_cli_once(*, native_receipt=None,
                           executable="/usr/local/bin/opencode",
                           runner=None):
    """At most one synthetic model call. Never perform an external inference.

    Without trusted native OS isolation this function does not spawn a
    process. An actual CLI may be run only after the host has enforced
    external-network and private-fs denies *outside* this Python process.
    If the binary makes unknown internal or background requests, the
    local model gate returns denial rather than escalating to a paid model.
    """
    gate_state = admission(native_receipt)
    if gate_state != "HOST_OS_SANDBOX_ATTESTED":
        return {"status": gate_state, "attempted": False,
                "outside_inference_calls": 0, "accepted": False}
    # Intentionally no direct subprocess.run path. A signed native host
    # runner must enforce the OS sandbox before process creation; recording
    # booleans in a receipt does NOT itself impose kernel restrictions.
    if runner is None or runner is subprocess.run or not callable(runner):
        return {"status": "NATIVE_SANDBOX_RUNNER_REQUIRED", "attempted": False,
                "outside_inference_calls": 0, "accepted": False}

    def _run(port, gate):
        with tempfile.TemporaryDirectory(prefix="foundation-opencode-fixture-") as tmp:
            plan = safe_cli_plan(port, executable=executable)
            argv, config = plan["argv"], plan["config"]
            try:
                # Host runner must independently confirm the pinned executable
                # hash and apply an external-deny OS network/filesystem sandbox.
                result = runner(argv, cwd=tmp, env=_isolated_env(config, tmp),
                                stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=35, check=False)
            except (subprocess.SubprocessError, OSError):
                return {"status": "OPENCODE_FIXTURE_EXECUTION_UNCERTAIN",
                        "attempted": True, "outside_inference_calls": 0,
                        "accepted": False}
            raw = result.stdout
            if type(raw) is not bytes or len(raw) > 32768:
                return {"status": "OPENCODE_FIXTURE_RESPONSE_UNUSABLE",
                        "attempted": True, "outside_inference_calls": 0,
                        "accepted": False}
            try:
                source = raw.decode("utf-8")
            except UnicodeError:
                source = ""
            # Every attempted helper/paid/unknown request invalidates the
            # complete CLI acceptance, even if the one public response passed.
            passed = (result.returncode == 0 and gate.accepted == 1
                      and gate.denied == 0
                      and independent_public_canary_review(
                          PUBLIC_CANARY_PROMPT, source))
            report = {
                "status": ("VERIFIED_OFFLINE_CLI_PUBLIC_FIXTURE"
                           if passed else "OPENCODE_FIXTURE_NOT_ACCEPTED"),
                "attempted": True,
                "gateway_accepted": gate.accepted,
                "gateway_denied": gate.denied,
                "outside_inference_calls": 0,
                "accepted": passed,
            }
            if not passed:
                code = getattr(result, "returncode", None)
                report["cli_exit_code"] = (
                    code if type(code) is int and -255 <= code <= 255 else None)
                report["cli_failure_class"] = (
                    "CLI_GATE_REQUEST_REJECTED" if gate.denied
                    else "CLI_OUTPUT_UNUSABLE" if gate.accepted
                    else _cli_failure_class(result))
                report.update(_cli_failure_signal(result))
                report["gate_denial_reasons"] = dict(sorted(gate.denial_reasons.items()))
                report["gate_denied_shapes"] = list(gate.denied_shapes)
            return report
    return run_fixture_gate_for_test(_run)


class OfflineOpenCodeCanaryAgent:
    """Proposal-only AgentPort plugged into the existing Guarded development host.

    Test fixture only. A native OS sandbox must be verified outside Python;
    this class has no filesystem tools, Git API, paid model, or write authority.
    The default runner None *always denies* a real CLI invocation.
    """
    def __init__(self, *, native_receipt=None, runner=None,
                 executable="/usr/local/bin/opencode"):
        self.native_receipt = native_receipt
        self.runner = runner
        self.executable = executable

    def run(self, request):
        from .agent import AgentRequest, AgentResult
        if (not isinstance(request, AgentRequest)
                or request.instruction != PUBLIC_CANARY_PROMPT
                or request.message_history):
            raise ValueError("OPENCODE_PUBLIC_FIXTURE_ONLY")
        evidence = accept_public_cli_once(
            native_receipt=self.native_receipt,
            executable=self.executable, runner=self.runner)
        if evidence["status"] != "VERIFIED_OFFLINE_CLI_PUBLIC_FIXTURE":
            raise RuntimeError("OPENCODE_CLI_NOT_ACCEPTED")
        # The source is not taken from a mutable external CLI response:
        # accepted verification compared the complete known public source.
        return AgentResult(PUBLIC_CANARY_SOURCE)
