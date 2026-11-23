"""Host-owned offline OpenCode V2 CLI acceptance inside a Docker network namespace.

This is deliberately NOT the OpenCode Console Free inference adapter.
A locally present, independently reviewed image SHA is required. The image
must embed Python, Foundation's fixture modules, and a fixed OpenCode V2 CLI.
No local source, keys, volumes, Docker socket, credentials, or user HOME are
mounted. --network=none is the kernel egress boundary; the loopback gate and
CLI both run inside the same container. Without the pinned image or a running
daemon, fail closed. Nothing auto-downloads or installs.
"""
from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
import tempfile

from .opencode_isolated_cli import (
    NativeIsolationReceipt, accept_public_cli_once,
)
from .opencode_model_gate import GATE_DIAGNOSTIC_CODES

_IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_VERSION = re.compile(r"2\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?\Z")
_DO_WELL_KNOWN = frozenset({
    "VERIFIED_OFFLINE_CLI_PUBLIC_FIXTURE",
    "OPENCODE_FIXTURE_NOT_ACCEPTED",
    "OPENCODE_FIXTURE_EXECUTION_UNCERTAIN",
    "OPENCODE_FIXTURE_RESPONSE_UNUSABLE",
    "HOST_OS_SANDBOX_NOT_ATTESTED",
    "NATIVE_SANDBOX_RUNNER_REQUIRED",
})
_BINARY = "/usr/local/bin/opencode"


def docker_offline_plan(image_id: str, binary_sha256: str,
                        *, docker_binary="/usr/local/bin/docker"):
    """Produce only a non-executed, argument-safe, no-host-mount OS plan."""
    if type(image_id) is not str or not _IMAGE.fullmatch(image_id):
        raise ValueError("OPENCODE_PINNED_LOCAL_IMAGE_REQUIRED")
    if type(binary_sha256) is not str or not _SHA.fullmatch(binary_sha256):
        raise ValueError("OPENCODE_PINNED_V2_BINARY_REQUIRED")
    if docker_binary not in ("/usr/local/bin/docker",
                             "/opt/homebrew/bin/docker"):
        raise ValueError("OPENCODE_DOCKER_BINARY_NOT_REVIEWED")
    argv = [
        docker_binary, "run", "--rm", "--pull=never",
        "--network=none", "--platform=linux/arm64",
        "--read-only", "--user=65534:65534",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=64", "--memory=768m", "--cpus=1",
        "--ipc=none", "--tmpfs=/tmp:rw,nosuid,nodev,size=128m",
        "--workdir=/tmp", "--env=HOME=/tmp",
        "--env=PYTHONDONTWRITEBYTECODE=1",
        "--env=FOUNDATION_OFFLINE_DOCKER_CANARY=1",
        "--entrypoint=python3",
        image_id, "-m", "ai_foundation.opencode_docker_isolation",
        "--worker", binary_sha256,
    ]
    return {"argv": argv, "execution_authorized": False,
            "isolation": "DOCKER_NETWORK_NONE_NO_HOST_MOUNTS"}


def _run_checked(runner, args, *, timeout, env):
    try:
        result = runner(args, stdin=subprocess.DEVNULL, capture_output=True,
                        check=False, timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if (type(result.returncode) is not int or
            type(result.stdout) is not bytes or
            len(result.stdout) > 8192):
        return None
    return result


def accept_container_canary(image_id=None, binary_sha256=None, *,
                            docker_binary="/usr/local/bin/docker",
                            runner=subprocess.run):
    """One bounded native-container attempt; cannot invoke an actual cloud model.

    A fake runner is suitable only for unit tests, NEVER external admission.
    The real host must independently pin and approve the local image before
    calling. No Docker registry pull, no credentials, no host file access.
    """
    try:
        plan = docker_offline_plan(image_id, binary_sha256,
                                   docker_binary=docker_binary)
    except ValueError as exc:
        return {"status": str(exc), "accepted": False, "attempted": False}
    if not callable(runner):
        return {"status": "OPENCODE_RUNNER_REQUIRED", "accepted": False,
                "attempted": False}
    with tempfile.TemporaryDirectory(prefix="foundation-docker-readonly-") as tmp:
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
               "HOME": tmp}
        endpoint = os.environ.get("FOUNDATION_OFFLINE_DOCKER_HOST", "")
        if endpoint:
            if not re.fullmatch(r"unix:///[A-Za-z0-9_./-]{8,300}", endpoint):
                return {"status": "UNTRUSTED_DOCKER_ENDPOINT",
                        "accepted": False, "attempted": False}
            env["DOCKER_HOST"] = endpoint
        # Inspect the *locally stored* content ID; do not read mutable tags.
        inspect = _run_checked(runner, [docker_binary, "image", "inspect",
                    "--format={{.Id}}", image_id], timeout=6, env=env)
        if (inspect is None or inspect.returncode != 0 or
                inspect.stdout.strip() != image_id.encode()):
            return {"status": "OPENCODE_PINNED_IMAGE_NOT_LOCAL",
                    "accepted": False, "attempted": False}
        result = _run_checked(runner, plan["argv"], timeout=55, env=env)
        if result is None or result.returncode != 0:
            return {"status": "OPENCODE_CONTAINER_RUN_UNCERTAIN",
                    "accepted": False, "attempted": True}
        try:
            report = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            report = None
        if (type(report) is not dict or
                report.get("status") not in _DO_WELL_KNOWN or
                type(report.get("accepted")) is not bool or
                type(report.get("gateway_accepted")) is not int or
                type(report.get("gateway_denied")) is not int or
                report.get("outside_inference_calls") != 0 or
                report.get("binary_sha256") != binary_sha256 or
                report.get("version") is None or
                not _VERSION.fullmatch(str(report["version"]))):
            # Worker can reject before it has a version or request counts.
            # Return only an allowlisted rejection code; never echo stdout,
            # container output or any untrusted payload.
            early = frozenset({
                "HOST_OS_SANDBOX_NOT_ATTESTED",
                "PINNED_BINARY_DIGEST_REQUIRED",
                "BINARY_DIGEST_MISMATCH",
                "OPENCODE_V2_BINARY_REQUIRED",
                "OPENCODE_IMAGE_BINARY_UNAVAILABLE",
            })
            worker_status = (
                report.get("status") if type(report) is dict
                and report.get("status") in early else "UNRECOGNIZED")
            detail = (report.get("sandbox_detail") if type(report) is dict
                      and report.get("sandbox_detail") in {
                          "NOT_LINUX", "UID_MISMATCH", "IFACE_UNREADABLE",
                          "NONLO_NETWORK_INTERFACE", "ROUTE_CHECK_UNAVAILABLE",
                          "NONLO_IPV4_ROUTE", "NONLO_IPV6_ROUTE",
                          "NONLO_IPV6_ADDRESS", "IPV6_CHECK_UNAVAILABLE",
                          "NONLO_DEVICE_UP", "NONLO_IPV4_ADDRESS",
                          "IPV4_ADDRESS_CHECK_UNAVAILABLE",
                          "NETWORK_NAMESPACE_UNVERIFIED"}
                      else "NOT_REPORTED")
            return {"status": "OPENCODE_CONTAINER_REPORT_UNVERIFIED",
                    "worker_status": worker_status, "sandbox_detail": detail,
                    "accepted": False, "attempted": True}
        passed = (report["status"] == "VERIFIED_OFFLINE_CLI_PUBLIC_FIXTURE"
                  and report["accepted"] is True
                  and report["gateway_accepted"] == 1
                  and report["gateway_denied"] == 0)
        # A dependency-injected runner can forge both docker inspect and the
        # child report. Synthetic tests may exercise this branch but MUST
        # never produce a real-world verification receipt.
        if runner is not subprocess.run:
            return {"status": "OPENCODE_SYNTHETIC_RUNNER_ONLY",
                    "accepted": False, "attempted": True,
                    "gateway_accepted": report["gateway_accepted"],
                    "gateway_denied": report["gateway_denied"],
                    "outside_inference_calls": 0}
        verdict = {"status": ("VERIFIED_OFFLINE_CONTAINER_PUBLIC_FIXTURE"
                             if passed else "OPENCODE_CONTAINER_NOT_ACCEPTED"),
                   "accepted": passed, "attempted": True,
                   "gateway_accepted": report["gateway_accepted"],
                   "gateway_denied": report["gateway_denied"],
                   "outside_inference_calls": 0}
        if not passed:
            allowed = frozenset({
                "CLI_LOG_UNAVAILABLE", "CLI_UNSUPPORTED_FLAG",
                "CLI_CONFIG_INVALID", "CLI_SDK_PACKAGE_MISSING", "CLI_RUNTIME_PANIC",
                "CLI_PROVIDER_UNRESOLVED", "CLI_NETWORK_OR_SDK_UNAVAILABLE",
                "CLI_SANDBOX_FILE_ACCESS", "CLI_EXIT_OR_OUTPUT_UNCLASSIFIED",
                "CLI_GATE_REQUEST_REJECTED", "CLI_OUTPUT_UNUSABLE",
            })
            code = report.get("cli_exit_code")
            verdict["cli_exit_code"] = (
                code if type(code) is int and -255 <= code <= 255 else None)
            category = report.get("cli_failure_class")
            verdict["cli_failure_class"] = (
                category if type(category) is str and category in allowed
                else "CLI_UNCLASSIFIED")
            for field in ("cli_stdout_bytes", "cli_stderr_bytes"):
                n = report.get(field)
                verdict[field] = n if type(n) is int and 0 <= n <= 131072 else None
            verdict["cli_text_has_error"] = (
                report.get("cli_text_has_error")
                if type(report.get("cli_text_has_error")) is bool else None)
            # The worker only emits a fixed vocabulary; enforce it again
            # on the host before including any receipt value.
            vocabulary = frozenset((
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
            v = report.get("cli_diagnostic_tokens")
            verdict["cli_diagnostic_tokens"] = (
                v if type(v) is list and len(v) <= len(vocabulary)
                and all(type(x) is str and x in vocabulary for x in v)
                and len(v) == len(set(v)) else [])
            grammar = frozenset((
                "argument", "command", "error", "expected", "flag", "help",
                "invalid", "missing", "model", "option", "provider",
                "required", "supported", "unknown", "unrecognized",
                "usage", "value", "warning",
            ))
            safe_flags = frozenset((
                "pure", "print-logs", "log-level", "standalone", "model", "format"))
            for field, allowed in (("cli_stderr_words", grammar),
                                   ("cli_stderr_flag_mentions", safe_flags)):
                tags = report.get(field)
                verdict[field] = (
                    tags if type(tags) is list and len(tags) <= len(allowed)
                    and all(type(x) is str and x in allowed for x in tags)
                    and len(tags) == len(set(tags)) else [])
            verdict["cli_stdout_looks_like_help"] = (
                report.get("cli_stdout_looks_like_help")
                if type(report.get("cli_stdout_looks_like_help")) is bool else None)
            reasons = report.get("gate_denial_reasons")
            valid = (
                type(reasons) is dict
                and len(reasons) <= len(GATE_DIAGNOSTIC_CODES)
                and all(type(k) is str and k in GATE_DIAGNOSTIC_CODES
                        and type(v) is int and 0 < v <= 32
                        for k, v in reasons.items())
                and sum(reasons.values()) == report["gateway_denied"])
            verdict["gate_denial_reasons"] = reasons if valid else {}

            # Metadata-only schema observation, validated again on the host.
            shapes = report.get("gate_denied_shapes")
            roles_allowed = frozenset(("system", "user", "assistant", "tool",
                                       "UNKNOWN", "NON_OBJECT"))
            types_allowed = frozenset(("ABSENT", "STRING", "PARTS", "OTHER"))
            expected = frozenset((
                "body_type", "unsupported_fields", "has_tools",
                "has_tool_choice", "has_metadata", "has_response_format",
                "has_system", "message_count", "message_roles",
                "public_prompt_present", "public_prompt_in_user",
                "user_content_length", "user_prefix_tags",
                "user_suffix_tags", "user_trimmed_exact",
                "system_fingerprint", "system_length",
                "tools_fingerprint", "tools_count", "user_content_type"))
            def safe_shape(row):
                if type(row) is not dict or frozenset(row) != expected:
                    return False
                count, n = row["unsupported_fields"], row["message_count"]
                if (row["body_type"] != "OBJECT"
                        or type(count) is not int or not 0 <= count <= 30
                        or n is not None and (type(n) is not int or not 0 <= n <= 64)
                        or any(type(row[k]) is not bool for k in (
                            "has_tools", "has_tool_choice", "has_metadata",
                            "has_response_format", "has_system",
                            "public_prompt_present",
                            "public_prompt_in_user", "user_trimmed_exact"))
                        or row["user_content_type"] not in types_allowed
                        or (row["user_content_length"] is not None and
                            (type(row["user_content_length"]) is not int or
                             not 0 <= row["user_content_length"] <= 65535))):
                    return False
                for key in ("system_fingerprint", "tools_fingerprint"):
                    digest = row[key]
                    if digest is not None and (type(digest) is not str or
                            not re.fullmatch(r"[a-f0-9]{64}", digest)):
                        return False
                for key, limit in (("system_length", 65535), ("tools_count", 64)):
                    number = row[key]
                    if number is not None and (type(number) is not int or
                            not 0 <= number <= limit):
                        return False
                allowed_tags = {"LF", "CR", "SPACE", "QUOTE",
                                "APOSTROPHE", "BACKTICK", "TAB", "OTHER", "LONG"}
                for key in ("user_prefix_tags", "user_suffix_tags"):
                    tags = row[key]
                    if (type(tags) is not list or len(tags) > 4
                            or any(type(x) is not str or x not in allowed_tags
                                   for x in tags)):
                        return False
                roles = row["message_roles"]
                return (type(roles) is list and len(roles) <= 64
                        and (n is None or len(roles) == n)
                        and all(type(role) is str and role in roles_allowed
                                for role in roles))
            verdict["gate_denied_shapes"] = (
                shapes if type(shapes) is list and len(shapes) <= 4
                and all(safe_shape(x) for x in shapes) else [])

        return verdict



# Linux may expose built-in tunnel links in a network-none namespace. Those
# are not external endpoints when DOWN, unaddressed and unrouted. Never allow
# an arbitrary non-loopback link (including eth0), and never test egress by
# sending packets outside the isolated container.
_DEFAULT_DOWN_TUNNELS = frozenset({
    "tunl0", "gre0", "gretap0", "erspan0", "sit0",
    "ip_vti0", "ip6_vti0", "ip6tnl0", "ip6gre0",
})


def _netns_isolated():
    """Fail closed on unexpected links, routes, addresses, or ioctl failures."""
    try:
        names = [name for _, name in socket.if_nameindex()]
        if (len(names) > 24 or len(names) != len(set(names))
                or "lo" not in names):
            return False, "IFACE_UNREADABLE"
        extras = set(names) - {"lo"}
        if not extras.issubset(_DEFAULT_DOWN_TUNNELS):
            return False, "NONLO_NETWORK_INTERFACE"

        # Procfs entries are kernel network-namespace state, not files from
        # the mounted host /sys. Bounded reads only; no route targets logged.
        def lines(path):
            with open(path, "rb") as stream:
                raw = stream.read(16385)
            if len(raw) > 16384:
                raise ValueError("NET_METADATA_TOO_LARGE")
            return raw.decode("ascii").splitlines()

        ipv4 = lines("/proc/net/route")
        if not ipv4 or not ipv4[0].startswith("Iface"):
            return False, "ROUTE_CHECK_UNAVAILABLE"
        if any(len(row.split()) < 8 or row.split()[0] != "lo"
               for row in ipv4[1:]):
            return False, "NONLO_IPV4_ROUTE"
        try:
            ipv6_routes = lines("/proc/net/ipv6_route")
            ipv6_addrs = lines("/proc/net/if_inet6")
        except FileNotFoundError:
            # Linux without the IPv6 stack exposes neither procfs file.
            if (os.path.exists("/proc/net/ipv6_route")
                    or os.path.exists("/proc/net/if_inet6")):
                return False, "IPV6_CHECK_UNAVAILABLE"
            ipv6_routes, ipv6_addrs = [], []
        if any(len(row.split()) < 10 or row.split()[-1] != "lo"
               for row in ipv6_routes):
            return False, "NONLO_IPV6_ROUTE"
        if any(len(row.split()) != 6 or row.split()[-1] != "lo"
               for row in ipv6_addrs):
            return False, "NONLO_IPV6_ADDRESS"

        # Every nonloopback interface must remain administratively DOWN and
        # have no IPv4 address. Unprivileged / cap-drop=ALL is still required.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for name in extras:
                ifreq = struct.pack("16sH14s", name.encode("ascii"), 0, b"\0" * 14)
                flags = fcntl.ioctl(sock.fileno(), 0x8913, ifreq)
                if struct.unpack_from("H", flags, 16)[0] & 0x1:
                    return False, "NONLO_DEVICE_UP"
                try:
                    fcntl.ioctl(sock.fileno(), 0x8915, ifreq)
                except OSError as exc:
                    if exc.errno == errno.EADDRNOTAVAIL:
                        continue
                    return False, "IPV4_ADDRESS_CHECK_UNAVAILABLE"
                return False, "NONLO_IPV4_ADDRESS"
        return True, "NO_ACTIVE_EXTERNAL_LINK"
    except (OSError, ValueError, UnicodeError, struct.error):
        return False, "NETWORK_NAMESPACE_UNVERIFIED"



def _worker(binary_sha256):
    """Runs only inside the pre-approved network-none, no-mount image."""
    if os.environ.get("FOUNDATION_OFFLINE_DOCKER_CANARY") != "1":
        return {"status": "HOST_OS_SANDBOX_NOT_ATTESTED"}
    # The host launch contract is --network=none, --user=65534:65534.
    # An environment flag alone is never a proof of kernel isolation.
    if sys.platform != "linux":
        return {"status": "HOST_OS_SANDBOX_NOT_ATTESTED",
                "sandbox_detail": "NOT_LINUX"}
    if os.getuid() != 65534:
        return {"status": "HOST_OS_SANDBOX_NOT_ATTESTED",
                "sandbox_detail": "UID_MISMATCH"}
    isolated, detail = _netns_isolated()
    if not isolated:
        return {"status": "HOST_OS_SANDBOX_NOT_ATTESTED",
                "sandbox_detail": detail}
    if type(binary_sha256) is not str or not _SHA.fullmatch(binary_sha256):
        return {"status": "PINNED_BINARY_DIGEST_REQUIRED"}
    target = Path(_BINARY)
    try:
        if not target.is_file() or target.is_symlink():
            raise ValueError("not a fixed binary")
        digest = hashlib.sha256()
        with target.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != binary_sha256:
            return {"status": "BINARY_DIGEST_MISMATCH"}
        version_result = subprocess.run([_BINARY, "--version"],
            stdin=subprocess.DEVNULL, capture_output=True, check=False,
            timeout=5, env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
        version_banner = version_result.stdout.decode("ascii", errors="ignore").strip()
        # The real upstream 2.2.5 binary reports "opencode v2.2.5".
        # Normalize only that exact official banner; reject all other text.
        match = re.fullmatch(r"opencode v(2\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)",
                             version_banner)
        version = match.group(1) if match else version_banner
        if version_result.returncode != 0 or not _VERSION.fullmatch(version):
            return {"status": "OPENCODE_V2_BINARY_REQUIRED"}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "OPENCODE_IMAGE_BINARY_UNAVAILABLE"}
    # Only the outer docker run --network=none makes this receipt meaningful.
    # Never offer this worker as a standalone native host command.
    receipt = NativeIsolationReceipt(
        binary_sha256=binary_sha256, verified_sha256=digest.hexdigest(),
        version=version, native_network_denies_all_external=True,
        only_loopback_gateway_allowed=True,
        filesystem_isolation_verified=True,
        shared_credentials_inaccessible=True,
        no_background_server_verified=True,
    )
    def namespace_runner(*args, **kwargs):
        return subprocess.run(*args, **kwargs)
    result = accept_public_cli_once(native_receipt=receipt,
                                    executable=_BINARY,
                                    runner=namespace_runner)
    report = {
        "status": result.get("status"),
        "accepted": result.get("accepted", False),
        "gateway_accepted": result.get("gateway_accepted", 0),
        "gateway_denied": result.get("gateway_denied", 0),
        "outside_inference_calls": 0,
        "binary_sha256": binary_sha256,
        "version": version,
    }
    if report["accepted"] is not True:
        report["cli_failure_class"] = result.get("cli_failure_class")
        report["cli_exit_code"] = result.get("cli_exit_code")
        for field in ("cli_stdout_bytes", "cli_stderr_bytes", "cli_text_has_error",
                      "cli_diagnostic_tokens", "cli_stderr_words",
                      "cli_stderr_flag_mentions", "cli_stdout_looks_like_help",
                      "gate_denial_reasons", "gate_denied_shapes"):
            report[field] = result.get(field)
    return report


class OfflineOpenCodeContainerCanaryAgent:
    """Existing proposal-only AgentPort, disabled without image+binary pins."""

    def __init__(self, *, image_id=None, binary_sha256=None,
                 docker_binary="/usr/local/bin/docker",
                 runner=subprocess.run):
        self.image_id = image_id
        self.binary_sha256 = binary_sha256
        self.docker_binary = docker_binary
        self.runner = runner

    def run(self, request):
        from .agent import AgentRequest, AgentResult
        from .harness_public_canary import (
            PUBLIC_CANARY_PROMPT, PUBLIC_CANARY_SOURCE,
        )
        if (not isinstance(request, AgentRequest)
                or request.instruction != PUBLIC_CANARY_PROMPT
                or request.message_history):
            raise ValueError("OPENCODE_PUBLIC_FIXTURE_ONLY")
        verdict = accept_container_canary(
            self.image_id, self.binary_sha256,
            docker_binary=self.docker_binary, runner=self.runner)
        if verdict["status"] != "VERIFIED_OFFLINE_CONTAINER_PUBLIC_FIXTURE":
            raise RuntimeError("OPENCODE_CONTAINER_CANARY_NOT_ACCEPTED")
        return AgentResult(PUBLIC_CANARY_SOURCE)


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "--worker":
        print("OPENCODE_OFFLINE_WORKER_ONLY", file=sys.stderr)
        return 2
    print(json.dumps(_worker(args[1]), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
