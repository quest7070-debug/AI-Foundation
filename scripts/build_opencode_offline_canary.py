#!/usr/bin/env python3
"""Build a *local-only* immutable OpenCode public canary image from cached bases.

No registry download, tag-based FROM, repository-wide Docker build context,
provider login, credentials, or automatic inference. Exact upstream image
manifest digests and expected CLI binary digest are supplied by trusted host
review; this script does not auto-decide that any downloaded bytes are safe.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile

_REF_OC = re.compile(
    r"ghcr\.io/anomalyco/opencode:[0-9]+\.[0-9]+\.[0-9]+"
    r"@sha256:[0-9a-f]{64}\Z")
_REF_PY = re.compile(r"python:3\.12-alpine@sha256:[0-9a-f]{64}\Z")
_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_FILES = (
    "opencode_docker_isolation.py",
    "opencode_isolated_cli.py",
    "opencode_model_gate.py",
    "opencode_live_stdio.py",
    "opencode_console_egress.py",
    "harness_public_canary.py",
    "model_work_roles.py",
)


def build_offline_image(*, opencode_base, python_base, cli_sha256,
                        docker_binary="/usr/local/bin/docker",
                        runner=subprocess.run,
                        root=None):
    """Return redacted build result, never enable a runtime route."""
    if (type(opencode_base) is not str
            or not _REF_OC.fullmatch(opencode_base)
            or type(python_base) is not str
            or not _REF_PY.fullmatch(python_base)
            or type(cli_sha256) is not str
            or not _SHA.fullmatch(cli_sha256)
            or docker_binary not in ("/usr/local/bin/docker",
                                     "/opt/homebrew/bin/docker")):
        return {"status": "PINNED_BUILD_INPUT_REQUIRED",
                "image_id": None, "execution_authorized": False}
    if not callable(runner):
        return {"status": "TRUSTED_DOCKER_RUNNER_REQUIRED",
                "image_id": None, "execution_authorized": False}
    source_root = (Path(root) if root is not None
                   else Path(__file__).resolve().parents[1])
    dockerfile = source_root / "docker/opencode-offline/Dockerfile"
    src = source_root / "src/ai_foundation"
    if dockerfile.is_symlink() or not dockerfile.is_file():
        return {"status": "REVIEWED_DOCKERFILE_REQUIRED",
                "image_id": None, "execution_authorized": False}
    if any((src / name).is_symlink() or not (src / name).is_file()
           for name in _FILES):
        return {"status": "REVIEWED_PUBLIC_SOURCE_REQUIRED",
                "image_id": None, "execution_authorized": False}

    with tempfile.TemporaryDirectory(prefix="foundation-public-build-") as tmp:
        tmp = Path(tmp)
        context = tmp / "context"
        pkg = context / "ai_foundation"
        pkg.mkdir(parents=True)
        shutil.copyfile(dockerfile, context / "Dockerfile")
        for name in _FILES:
            shutil.copyfile(src / name, pkg / name)
        env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin",
               "HOME": str(tmp)}
        endpoint = os.environ.get("FOUNDATION_OFFLINE_DOCKER_HOST", "")
        if endpoint:
            if not re.fullmatch(r"unix:///[A-Za-z0-9_./-]{8,300}", endpoint):
                return {"status": "UNTRUSTED_DOCKER_ENDPOINT",
                        "image_id": None, "execution_authorized": False}
            env["DOCKER_HOST"] = endpoint

        def call(cmd, timeout):
            try:
                result = runner(cmd, env=env,
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                timeout=timeout, check=False)
            except (OSError, subprocess.SubprocessError):
                return None
            if (type(result.returncode) is not int
                    or type(result.stdout) is not bytes
                    or len(result.stdout) > 1024 * 1024):
                return None
            return result

        # Image inspect is a local metadata read, never pull. Build FROM
        # receives the inspected *content IDs*, not remote registry refs.
        ids = []
        for ref in (opencode_base, python_base):
            result = call([docker_binary, "image", "inspect",
                           "--format={{.Id}}", ref], 8)
            if result is None or result.returncode != 0:
                # Docker records digest pulls as repository@sha256, and
                # may not index the equivalent repository:tag@sha256 form.
                # This fallback keeps the EXACT digest, not a mutable tag.
                tagged, digest = ref.split("@", 1)
                canonical = tagged.rsplit(":", 1)[0] + "@" + digest
                result = call([docker_binary, "image", "inspect",
                               "--format={{.Id}}", canonical], 8)
            if result is None or result.returncode != 0:
                return {"status": "PINNED_BASE_NOT_CACHED",
                        "image_id": None, "execution_authorized": False}
            image_id = result.stdout.decode("ascii", "ignore").strip()
            if not _ID.fullmatch(image_id):
                return {"status": "CACHED_BASE_ID_UNVERIFIED",
                        "image_id": None, "execution_authorized": False}
            ids.append(image_id)

        # Docker BuildKit does not reliably resolve config SHA IDs in FROM.
        # Alias only the independently inspected local image IDs under
        # loopback-only names. Never reference a remote registry in FROM.
        # Existing nonmatching aliases are never overwritten. Remove only
        # tags created by this call, without pruning the base image.
        created_tags = []
        refs = []
        try:
            for scope, image_id in zip(("cli", "python"), ids):
                local_ref = ("localhost/foundation-offline-" + scope +
                             ":sha-" + image_id[7:31])
                before = call([docker_binary, "image", "inspect",
                               "--format={{.Id}}", local_ref], 8)
                if before is None:
                    return {"status": "LOCAL_BUILD_TAG_CHECK_UNAVAILABLE",
                            "image_id": None, "execution_authorized": False}
                if before.returncode == 0:
                    if before.stdout.strip() != image_id.encode():
                        return {"status": "LOCAL_BUILD_TAG_CONFLICT",
                                "image_id": None, "execution_authorized": False}
                else:
                    tagged = call([docker_binary, "image", "tag",
                                   image_id, local_ref], 12)
                    if tagged is None or tagged.returncode != 0:
                        return {"status": "LOCAL_BUILD_TAG_FAILED",
                                "image_id": None, "execution_authorized": False}
                    created_tags.append(local_ref)
                verified = call([docker_binary, "image", "inspect",
                                 "--format={{.Id}}", local_ref], 8)
                if (verified is None or verified.returncode != 0
                        or verified.stdout.strip() != image_id.encode()):
                    return {"status": "LOCAL_BUILD_TAG_UNVERIFIED",
                            "image_id": None, "execution_authorized": False}
                refs.append(local_ref)
            iid = tmp / "built-id"
            args = [
                docker_binary, "build", "--pull=false", "--network=none",
                "--platform=linux/arm64", "--file", str(context / "Dockerfile"),
                "--iidfile", str(iid),
                "--build-arg=OPENCODE_LOCAL_REF=" + refs[0],
                "--build-arg=PYTHON_LOCAL_REF=" + refs[1],
                "--build-arg=EXPECTED_CLI_SHA256=" + cli_sha256,
                str(context),
            ]
            result = call(args, 180)
            if result is None or result.returncode != 0 or not iid.is_file():
                # Docker stderr is intentionally never returned. Categorize
                # only fixed keywords, with no container paths or provider data.
                output = ((getattr(result, "stderr", b"") or b"") +
                          (getattr(result, "stdout", b"") or b""))[-65536:].lower()
                if b"libstdc++" in output or b"libgcc_s" in output:
                    reason = "BINARY_RUNTIME_LIBRARY_COPY"
                elif b"failed to resolve source metadata" in output or b"pull access denied" in output:
                    reason = "LOCAL_BUILD_FROM_RESOLUTION"
                elif b"failed to calculate checksum" in output or b"failed to compute cache key" in output:
                    reason = "OFFLINE_COPY_SOURCE_NOT_FOUND"
                elif b"dockerfile parse error" in output or b"unknown instruction" in output:
                    reason = "OFFLINE_DOCKERFILE_SYNTAX"
                elif b"no space left" in output:
                    reason = "HOST_DISK_CAPACITY"
                elif b"failed to solve" in output and b"not found" in output:
                    reason = "DOCKER_SOURCE_PATH_NOT_FOUND"
                elif b"exit code: 1" in output or b"exit code: 127" in output:
                    reason = "OFFLINE_VERSION_OR_COMPILE_PROBE"
                elif b"network" in output:
                    reason = "BUILD_NETWORK_REFERENCE_UNAVAILABLE"
                elif result is None:
                    reason = "DOCKER_SUBPROCESS_UNAVAILABLE"
                elif result.returncode != 0:
                    reason = "DOCKER_BUILD_NONZERO"
                else:
                    reason = "DOCKER_IIDFILE_MISSING"
                # Docker output may contain host paths; emit only fixed
                # parser signatures and numeric line numbers.
                at = re.findall(
                    rb"(?:dockerfile:|dockerfile parse error on line |"
                    rb"dockerfile parse error near line )([0-9]{1,3})", output)
                line = int(at[-1]) if at else None
                instr = re.findall(
                    rb"unknown instruction\s*:\s*([a-z][a-z0-9_-]{0,30})", output)
                token = instr[-1].decode("ascii").upper() if instr else None
                flags = {
                    "STAGE_REF": b"failed to parse stage name" in output,
                    "FROM_EMPTY": b"base name should not be blank" in output,
                    "COPY_SOURCE": b"failed to calculate checksum" in output,
                    "RUN_NONZERO": b"did not complete successfully" in output,
                    "RESOLVE_META": b"failed to resolve source metadata" in output,
                }
                return {"status": "OPENCODE_OFFLINE_BUILD_FAILED",
                        "failure_class": reason,
                        "failure_dockerfile_line": line,
                        "failure_instruction": token,
                        "failure_signatures": sorted(k for k, v in flags.items() if v),
                        "image_id": None, "execution_authorized": False}
            built_id = iid.read_text(encoding="ascii").strip()
            if not _ID.fullmatch(built_id):
                return {"status": "OPENCODE_BUILT_IMAGE_UNVERIFIED",
                        "image_id": None, "execution_authorized": False}
            return {"status": "LOCAL_IMAGE_BUILT_NOT_ACCEPTED",
                    "image_id": built_id, "cli_sha256": cli_sha256,
                    "execution_authorized": False}
        finally:
            for local_ref in reversed(created_tags):
                call([docker_binary, "image", "rm", "--no-prune", local_ref], 12)



def main():
    parser = argparse.ArgumentParser(description="Offline OpenCode canary builder")
    parser.add_argument("--opencode-base", required=True)
    parser.add_argument("--python-base", required=True)
    parser.add_argument("--cli-sha256", required=True)
    parser.add_argument("--docker-binary", default="/usr/local/bin/docker")
    args = parser.parse_args()
    report = build_offline_image(
        opencode_base=args.opencode_base, python_base=args.python_base,
        cli_sha256=args.cli_sha256, docker_binary=args.docker_binary)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "LOCAL_IMAGE_BUILT_NOT_ACCEPTED" else 3


if __name__ == "__main__":
    raise SystemExit(main())
