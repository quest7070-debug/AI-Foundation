#!/usr/bin/env python3
"""One M1-only real OpenCode CLI canary. No cloud inference or service switch.

Invoked on the author's exact Draft PR #512 only. The two public base images
are staged once in Docker's existing cache. Neither the original repository,
private files, auth files nor the Docker socket is mounted into any container.
The final child is --network=none; its model gateway is local and synthetic.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ai_foundation.opencode_docker_isolation import accept_container_canary
from build_opencode_offline_canary import build_offline_image

OC_VERSION = "2.2.5"
OC_DIGEST = "0d6f04f619d0e31cb9b02b4512975b89561a9c65317d437be15729b29158a3a4"
OC_REF = f"ghcr.io/anomalyco/opencode:{OC_VERSION}@sha256:{OC_DIGEST}"
OC_CANONICAL = f"ghcr.io/anomalyco/opencode@sha256:{OC_DIGEST}"
PYTHON_TAG = "python:3.12-alpine"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _print(status: str, **fields) -> None:
    report = {"status": status, "acceptance": status == "VERIFIED_OFFLINE_CONTAINER_PUBLIC_FIXTURE",
              **fields}
    line = "M1_OPENCODE_PUBLIC_CLI=" + json.dumps(report, sort_keys=True)
    print(line, flush=True)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as stream:
            stream.write("\n### M1 OpenCode offline CLI\n\n" + line + "\n")
    # We intentionally do not emit Docker output, prompts, auth or env values.


def _run(argv, *, timeout=80, env=None):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, check=False,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0 or len(result.stdout) > 16_384:
        return None
    return result.stdout.decode("ascii", errors="replace").strip()


def _scope_ok() -> bool:
    if (platform.system() != "Darwin" or platform.machine() != "arm64"
            or os.environ.get("GITHUB_REPOSITORY") != "quest7070-dev/AI-Foundation"
            or os.environ.get("GITHUB_EVENT_NAME") != "pull_request"
            or os.environ.get("GITHUB_HEAD_REF") !=
            "feat/isolated-opencode-jules-readback-20261109"
            or os.environ.get("GITHUB_REF") != "refs/pull/512/merge"):
        return False
    try:
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
        return event["pull_request"]["number"] == 512 and (
            event["pull_request"]["user"]["login"] == "quest7070-debug"
            and event["pull_request"]["head"]["repo"]["full_name"]
            == "quest7070-dev/AI-Foundation")
    except (KeyError, OSError, ValueError, TypeError):
        return False


def _inspect(docker, ref):
    raw = _run([docker, "image", "inspect", "--format={{json .}}", ref], timeout=10)
    if raw is None:
        return None
    try:
        item = json.loads(raw)
        return item if type(item) is dict else None
    except ValueError:
        return None


def _offline_net_namespace_probe(docker, image_ref, env):
    """Model-free control: observe the actual netns in a no-network container.

    Never probe an external address; only the kernel's local interface/route
    metadata. No mounts, credentials or Docker socket enter the container.
    """
    script = (
        "import json,socket,pathlib;"
        "names=[n for _,n in socket.if_nameindex()];"
        "raw=pathlib.Path('/proc/net/route').read_text().splitlines()[1:];"
        "nonlo=sum(len(line.split())>=8 and line.split()[0]!='lo' "
        "for line in raw);"
        "print(json.dumps({'interfaces':len(names),"
        "'nonloopback':sum(n!='lo' for n in names),"
        "'nonloopback_ipv4_routes':nonlo}))"
    )
    raw = _run([
        docker, "run", "--rm", "--pull=never", "--network=none",
        "--platform=linux/arm64", "--read-only", "--user=65534:65534",
        "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--pids-limit=16", "--memory=192m", "--cpus=1", "--ipc=none",
        "--tmpfs=/tmp:rw,nosuid,nodev,size=8m",
        "--env=HOME=/tmp", "--entrypoint=python3",
        image_ref, "-c", script,
    ], timeout=15, env=env)
    try:
        result = json.loads(raw) if raw else None
        if (type(result) is dict and set(result) ==
                {"interfaces", "nonloopback", "nonloopback_ipv4_routes"}
                and all(type(v) is int and 0 <= v <= 64 for v in result.values())):
            return {"state": "OBSERVED", **result}
    except (ValueError, TypeError):
        pass
    return {"state": "UNAVAILABLE"}


def main() -> int:
    if not _scope_ok():
        _print("HOLD_WRONG_HOST_OR_PR")
        return 0
    docker = shutil.which("docker")
    if docker not in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker"):
        _print("HOLD_DOCKER_UNAVAILABLE")
        return 0
    if os.environ.get("DOCKER_HOST") or os.environ.get("DOCKER_CONTEXT"):
        _print("HOLD_DOCKER_CONTEXT_OVERRIDE")
        return 0
    if _run([docker, "context", "show"], timeout=6) != "desktop-linux":
        _print("HOLD_DOCKER_CONTEXT_UNVERIFIED")
        return 0
    endpoint = _run([docker, "context", "inspect", "desktop-linux",
                     "--format={{(index .Endpoints \"docker\").Host}}"], timeout=6)
    if not endpoint or not re.fullmatch(r"unix:///[A-Za-z0-9_./-]{8,300}", endpoint):
        _print("HOLD_UNVERIFIED_DOCKER_SOCKET")
        return 0
    if _run([docker, "info", "--format={{.OSType}}/{{.Architecture}}"],
            timeout=8) is None:
        _print("HOLD_DOCKER_ENGINE_UNAVAILABLE")
        return 0
    # Keep the Docker client's context separate from HOME so canary and
    # builder never receive the runner's Docker credentials or home folder.
    os.environ["FOUNDATION_OFFLINE_DOCKER_HOST"] = endpoint
    client_env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                  "HOME": "/tmp", "DOCKER_HOST": endpoint}
    if shutil.disk_usage("/").free < 2 * 1024**3:
        _print("HOLD_M1_LOW_DISK")
        return 0

    # Official public images only. Docker pull is NOT provider inference.
    if _inspect(docker, OC_CANONICAL) is None:
        if _run([docker, "pull", "--platform=linux/arm64", OC_CANONICAL],
                timeout=140, env=client_env) is None:
            _print("HOLD_PINNED_OPENCODE_DOWNLOAD")
            return 0
    if _inspect(docker, PYTHON_TAG) is None:
        if _run([docker, "pull", "--platform=linux/arm64", PYTHON_TAG],
                timeout=120, env=client_env) is None:
            _print("HOLD_OFFICIAL_PYTHON_DOWNLOAD")
            return 0

    upstream = _inspect(docker, OC_CANONICAL)
    python_base = _inspect(docker, PYTHON_TAG)
    if (not upstream or not python_base or
            upstream.get("Os") != "linux" or upstream.get("Architecture") != "arm64" or
            python_base.get("Os") != "linux" or python_base.get("Architecture") != "arm64"):
        _print("HOLD_IMAGE_PLATFORM_MISMATCH")
        return 0
    digests = python_base.get("RepoDigests", [])
    matching = [x.rsplit("@sha256:", 1)[-1] for x in digests
                if re.fullmatch(r"(?:docker\.io/library/)?python@sha256:[a-f0-9]{64}", x)]
    if len(matching) != 1:
        _print("HOLD_PYTHON_DIGEST_NOT_PINNED")
        return 0
    python_ref = PYTHON_TAG + "@sha256:" + matching[0]

    # Run exactly sha256sum from upstream image, never a provider or agent.
    sha_raw = _run([docker, "run", "--rm", "--pull=never", "--network=none",
                   "--platform=linux/arm64", "--read-only", "--cap-drop=ALL",
                   "--security-opt=no-new-privileges", "--pids-limit=32",
                   "--memory=256m", "--cpus=1", "--entrypoint=/bin/sh",
                   OC_CANONICAL, "-c", "sha256sum /usr/local/bin/opencode"],
                   timeout=25, env=client_env)
    binary = (sha_raw or "").split(" ", 1)[0]
    if not _DIGEST.fullmatch(binary):
        _print("HOLD_OFFICIAL_BINARY_DIGEST_UNVERIFIED")
        return 0

    built = build_offline_image(
        opencode_base=OC_REF, python_base=python_ref, cli_sha256=binary,
        docker_binary=docker, root=ROOT)
    if built["status"] != "LOCAL_IMAGE_BUILT_NOT_ACCEPTED":
        _print("HOLD_OFFLINE_IMAGE_BUILD_FAILED", build_stage=built["status"],
               build_failure_class=built.get("failure_class", "UNCLASSIFIED"),
               dockerfile_line=built.get("failure_dockerfile_line"),
               failure_instruction=built.get("failure_instruction"),
               failure_signatures=built.get("failure_signatures", []))
        return 0

    # Independent model-free control against the Python base and canary
    # using the same network-none plan. No control counter grants admission.
    base_namespace = _offline_net_namespace_probe(docker, python_ref, client_env)
    built_namespace = _offline_net_namespace_probe(docker, built["image_id"], client_env)
    verdict = accept_container_canary(
        image_id=built["image_id"], binary_sha256=binary,
        docker_binary=docker)
    _print(verdict["status"], fixture_accepted=verdict["accepted"],
           baseline_netns=base_namespace, canary_netns=built_namespace,
           attempted=verdict["attempted"], gateway_accepted=verdict.get("gateway_accepted", 0),
           gateway_denied=verdict.get("gateway_denied", 0),
           outside_inference_calls=verdict.get("outside_inference_calls", 0),
           worker_status=verdict.get("worker_status", "NOT_REPORTED"),
           sandbox_detail=verdict.get("sandbox_detail", "NOT_REPORTED"),
           cli_failure_class=verdict.get("cli_failure_class", "NOT_REPORTED"),
           cli_exit_code=verdict.get("cli_exit_code"),
           cli_stdout_bytes=verdict.get("cli_stdout_bytes"),
           cli_stderr_bytes=verdict.get("cli_stderr_bytes"),
           cli_text_has_error=verdict.get("cli_text_has_error"),
           cli_diagnostic_tokens=verdict.get("cli_diagnostic_tokens", []),
           cli_stderr_words=verdict.get("cli_stderr_words", []),
           cli_stderr_flag_mentions=verdict.get("cli_stderr_flag_mentions", []),
           cli_stdout_looks_like_help=verdict.get("cli_stdout_looks_like_help"),
           gate_denial_reasons=verdict.get("gate_denial_reasons", {}),
           gate_denied_shapes=verdict.get("gate_denied_shapes", []),
           official_version=OC_VERSION,
           opencode_manifest="sha256:" + OC_DIGEST,
           python_manifest="sha256:" + matching[0],
           native_image_id=built["image_id"],
           binary_sha256=binary)
    if verdict["accepted"] is True:
        # A second distinct fixture checks the new Docker stdio/host-model
        # filter, but NEVER opens a provider network connection or uses keys.
        from m1_opencode_stdio_fixture import accept_stdio_fixture
        result = accept_stdio_fixture(
            image_id=built["image_id"], binary_sha256=binary,
            docker_binary=docker)
        line = "M1_OPENCODE_STDIO=" + json.dumps(result, sort_keys=True)
        print(line, flush=True)
        if path := os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(path, "a", encoding="utf-8") as summary:
                summary.write("\n### M1 OpenCode stdio synthetic E2E\n\n" + line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
