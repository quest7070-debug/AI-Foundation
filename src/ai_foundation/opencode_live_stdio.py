"""Bounded native OpenCode CLI host port, using Docker stdio as the ONLY egress.

Staged only. No Operator installs this by default. The CLI has no network,
mounts, user files or credentials; it can contact a loopback HTTP gate inside
its own Docker --network=none namespace. The gate exchanges one binary frame
over the Docker stdin/stdout attachment with the trusted host, which checks
the exact request and owns the Console credential. A pinned local image,
independently observed account budget, owner route selection, Guard release,
and real host acceptance are prerequisites outside this module.
"""
from __future__ import annotations

import asyncio
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import urllib.request
from urllib.error import HTTPError

from .opencode_console_egress import (
    FREE_MODEL_ID, UPSTREAM, OneShotOpenCodeModelFence, ReviewedOutboundCodeScope,
)
# The container owns no account or Harness service registry, so this module
# imports account review only when the trusted host constructs a live port.
OPENCODE_MODEL = "opencode/" + FREE_MODEL_ID

_IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_MAX_FRAME = 262144
_MAX_SOURCE = 262144
_VERSION = "opencode v2.2.5"


def _write_frame(stream, kind, payload):
    if kind not in (b"P", b"R", b"S", b"E", b"O") or type(payload) is not bytes or len(payload) > _MAX_FRAME:
        raise ValueError("OPENCODE_FRAME_DENIED")
    stream.write(kind + len(payload).to_bytes(4, "big") + payload)
    stream.flush()


def _read_frame(stream):
    header = stream.read(5)
    if len(header) != 5:
        raise ValueError("OPENCODE_FRAME_EOF")
    size = int.from_bytes(header[1:], "big")
    if size > _MAX_FRAME:
        raise ValueError("OPENCODE_FRAME_OVERSIZE")
    payload = stream.read(size)
    if len(payload) != size:
        raise ValueError("OPENCODE_FRAME_SHORT")
    return header[:1], payload


class _StdioGateway(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True

    def __init__(self):
        self.lock = threading.RLock()
        self.accepted = 0
        self.denied = 0
        super().__init__(("127.0.0.1", 0), _Handler)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _reply(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def _deny(self):
        self.server.denied += 1
        self._reply(403, b'{"error":"DENIED"}')

    do_GET = _deny
    do_HEAD = _deny
    do_PUT = _deny
    do_PATCH = _deny
    do_DELETE = _deny
    do_OPTIONS = _deny

    def do_POST(self):
        n = self.headers.get("Content-Length", "")
        if (self.path != "/v1/chat/completions" or not n.isdecimal()
                or not 0 < int(n) <= 65536
                or self.headers.get("Transfer-Encoding")
                or self.headers.get("Content-Encoding")):
            self._deny()
            return
        raw = self.rfile.read(int(n))
        if len(raw) != int(n):
            self._deny()
            return
        with self.server.lock:
            if self.server.accepted or self.server.denied:
                self._deny()
                return
            try:
                # Even a malformed request reaches only the trusted host, never
                # an upstream network path from the container itself.
                _write_frame(sys.stdout.buffer, b"R", raw)
                kind, reply = _read_frame(sys.stdin.buffer)
                if kind != b"S":
                    self._deny()
                    return
                self.server.accepted += 1
            except (OSError, ValueError):
                self._deny()
                return
        is_stream = json.loads(raw).get("stream") is True
        self._reply(200, reply, "text/event-stream" if is_stream else "application/json")


def _worker(binary_sha256):
    # Inside the container only. A Python unit test cannot attest the Docker
    # kernel contract; the host must independently inspect the pinned image.
    from .opencode_docker_isolation import _netns_isolated
    from .opencode_isolated_cli import _isolated_env, safe_cli_plan
    if (sys.platform != "linux" or os.getuid() != 65534
            or not _SHA.fullmatch(binary_sha256)
            or not _netns_isolated()[0]):
        return 2
    binary = "/usr/local/bin/opencode"
    try:
        with open(binary, "rb") as f:
            digest = hashlib.sha256()
            for chunk in iter(lambda: f.read(1048576), b""):
                digest.update(chunk)
        if digest.hexdigest() != binary_sha256:
            return 2
        ver = subprocess.run([binary, "--version"], capture_output=True,
                             stdin=subprocess.DEVNULL, timeout=5,
                             env={"PATH": "/usr/bin:/bin", "HOME": "/tmp"})
        if ver.returncode != 0 or ver.stdout.strip() != _VERSION.encode():
            return 2
        kind, raw_prompt = _read_frame(sys.stdin.buffer)
        if kind != b"P":
            return 2
        prompt = raw_prompt.decode("utf-8", "strict")
        scope = ReviewedOutboundCodeScope(prompt)
    except (OSError, UnicodeError, ValueError, subprocess.SubprocessError):
        return 2
    server = _StdioGateway()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix="public-") as tmp:
            plan = safe_cli_plan(server.server_port, executable=binary)
            argv = list(plan["argv"])
            # Only the host's bounded public prompt replaces the fixed fixture.
            argv[-1] = scope.prompt
            try:
                done = subprocess.run(argv, cwd=tmp,
                    env=_isolated_env(plan["config"], tmp),
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, timeout=40, check=False)
                source = done.stdout
                ok = (done.returncode == 0 and server.accepted == 1
                      and server.denied == 0 and len(source) <= _MAX_SOURCE)
            except (OSError, subprocess.SubprocessError):
                source, ok = b"", False
        result = {"ok": bool(ok), "accepted": server.accepted,
                  "denied": server.denied}
        if ok:
            try:
                result["source"] = source.decode("utf-8", "strict")
            except UnicodeError:
                result["ok"] = False
        _write_frame(sys.stdout.buffer, b"O",
                     json.dumps(result, separators=(",", ":")).encode())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    return 0


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        return None


def console_sender(api_key_supplier):
    """Make exactly one TLS request, no proxy, redirect, retry or key logging."""
    if not callable(api_key_supplier):
        raise ValueError("HOST_CREDENTIAL_SUPPLIER_REQUIRED")

    def send(url, payload):
        if url != UPSTREAM or type(payload) is not bytes:
            raise PermissionError("OPENCODE_UPSTREAM_NOT_ALLOWED")
        key = api_key_supplier()
        if type(key) is not str or not 8 <= len(key) <= 4096 or "\n" in key or "\r" in key:
            raise PermissionError("OPENCODE_HOST_CREDENTIAL_UNAVAILABLE")
        req = urllib.request.Request(
            UPSTREAM, payload, method="POST",
            headers={"Authorization": "Bearer " + key,
                     "Content-Type": "application/json",
                     "Accept": "text/event-stream, application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(req, timeout=30) as response:
                if response.status != 200:
                    raise RuntimeError("OPENCODE_UPSTREAM_NON_SUCCESS")
                raw = response.read(_MAX_FRAME + 1)
        except HTTPError as exc:
            # Official Console restricts Free models to OpenCode itself.
            # A 403 means STOP, not a reason to spoof a client, change the
            # model, activate BYOK or fall back to a charged route. A 429
            # can be the workspace's enforced $0 policy: never retry it.
            fixed = {
                402: "OPENCODE_UPSTREAM_NO_CREDITS",
                403: "OPENCODE_FREE_ONLY_CLIENT_DENIED",
                429: "OPENCODE_WORKSPACE_BUDGET_OR_RATE_DENIED",
            }
            raise PermissionError(fixed.get(
                exc.code, "OPENCODE_UPSTREAM_HTTP_DENIED")) from None
        if not raw or len(raw) > _MAX_FRAME:
            raise RuntimeError("OPENCODE_UPSTREAM_RESPONSE_UNUSABLE")
        return raw
    return send


class PinnedStdioOpenCodeHostPort:
    """Opt-in native port. Not registered by default or proof of billing safety."""

    def __init__(self, *, image_id, binary_sha256, docker_binary, review,
                 api_key_supplier, release_gate_permitted=False):
        from .next_service_preflight import OpenCodeReviewEvidence, opencode_readiness
        if (type(image_id) is not str or not _IMAGE.fullmatch(image_id)
                or type(binary_sha256) is not str or not _SHA.fullmatch(binary_sha256)
                or docker_binary not in ("/usr/local/bin/docker", "/opt/homebrew/bin/docker")
                or not isinstance(review, OpenCodeReviewEvidence)
                or opencode_readiness(review)["stage"] != "PREPARED_FOR_HOST_REVIEW"
                or review.model != OPENCODE_MODEL
                or release_gate_permitted is not True):
            raise PermissionError("OPENCODE_NATIVE_RELEASE_NOT_APPROVED")
        # Legacy stdio transport is pinned to GLM. A ranked alternative must
        # supply its own independently verified, exact-model host execution port.
        self.pinned_model = OPENCODE_MODEL
        self.image_id = image_id
        self.binary_sha256 = binary_sha256
        self.docker_binary = docker_binary
        self.send = console_sender(api_key_supplier)

    async def _run_once(self, prompt, timeout):
        # Reject missing/mutable images. No pull, no bind mounts, no shared
        # HOME, no CLI network, no Docker socket passed into the child.
        env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "HOME": "/tmp"}
        # Use only the host-selected Unix Docker socket. Never leak the
        # caller's HOME, plugin settings, proxies or arbitrary Docker context.
        docker_host = os.environ.get("FOUNDATION_OFFLINE_DOCKER_HOST", "")
        if docker_host:
            if not re.fullmatch(r"unix:///[A-Za-z0-9_./-]{8,300}", docker_host):
                raise PermissionError("OPENCODE_DOCKER_SOCKET_NOT_REVIEWED")
            env["DOCKER_HOST"] = docker_host
        proc = await asyncio.create_subprocess_exec(
            self.docker_binary, "image", "inspect", "--format={{.Id}}",
            self.image_id, stdin=subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env)
        inspection, _ = await asyncio.wait_for(proc.communicate(), timeout=8)
        if proc.returncode != 0 or inspection.strip() != self.image_id.encode():
            raise PermissionError("OPENCODE_NATIVE_IMAGE_NOT_PINNED")
        container = "foundation-opencode-once-" + secrets.token_hex(8)
        args = [
            self.docker_binary, "run", "--rm", "-i", "--pull=never",
            "--name=" + container, "--network=none", "--platform=linux/arm64",
            "--read-only", "--user=65534:65534", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=64",
            "--memory=768m", "--cpus=1", "--ipc=none",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=128m", "--workdir=/tmp",
            "--env=HOME=/tmp", "--env=PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint=python3", self.image_id,
            "-m", "ai_foundation.opencode_live_stdio", "--worker", self.binary_sha256,
        ]
        child = await asyncio.create_subprocess_exec(
            *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env)
        fence = OneShotOpenCodeModelFence(
            ReviewedOutboundCodeScope(prompt), upstream_sender=self.send)
        async def write(kind, raw):
            if len(raw) > _MAX_FRAME:
                raise PermissionError("OPENCODE_FRAME_OVERSIZE")
            child.stdin.write(kind + len(raw).to_bytes(4, "big") + raw)
            await child.stdin.drain()
        async def read():
            header = await child.stdout.readexactly(5)
            size = int.from_bytes(header[1:], "big")
            if size > _MAX_FRAME:
                raise PermissionError("OPENCODE_FRAME_OVERSIZE")
            return header[:1], await child.stdout.readexactly(size)
        try:
            async def transact():
                await write(b"P", prompt.encode())
                seen_request = False
                while True:
                    kind, raw = await read()
                    if kind == b"R":
                        if seen_request:
                            await write(b"E", b"DENIED")
                            raise PermissionError("OPENCODE_EXTRA_REQUEST_DENIED")
                        seen_request = True
                        # Blocking network send has its own 30-second timeout,
                        # and never retries after uncertainty.
                        try:
                            response = fence.send_once(
                                method="POST", url=UPSTREAM, raw=raw)
                        except Exception:
                            await write(b"E", b"DENIED")
                            raise RuntimeError("OPENCODE_UPSTREAM_OR_GATE_DENIED") from None
                        await write(b"S", response)
                    elif kind == b"O":
                        record = json.loads(raw)
                        if (type(record) is not dict
                                or record.get("ok") is not True
                                or record.get("accepted") != 1
                                or record.get("denied") != 0
                                or fence.accepted != 1 or fence.denied != 0
                                or not seen_request
                                or type(record.get("source")) is not str
                                or not 0 < len(record["source"].encode()) <= _MAX_SOURCE):
                            raise RuntimeError("OPENCODE_NATIVE_NOT_ACCEPTED")
                        return record["source"]
                    else:
                        raise RuntimeError("OPENCODE_FRAME_UNEXPECTED")
            result = await asyncio.wait_for(transact(), timeout=timeout)
            await asyncio.wait_for(child.wait(), timeout=5)
            if child.returncode != 0:
                raise RuntimeError("OPENCODE_NATIVE_CONTAINER_EXIT")
            return result
        finally:
            if child.returncode is None:
                child.kill()
                await child.wait()
            # Cleanup is only for the unique OpenCode child, not 9B or any
            # other model/job. A detached child must never survive uncertainty.
            cleanup = await asyncio.create_subprocess_exec(
                self.docker_binary, "rm", "-f", container,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, env=env)
            try:
                await asyncio.wait_for(cleanup.wait(), timeout=5)
            except asyncio.TimeoutError:
                cleanup.kill()
                await cleanup.wait()

    def run_bounded_public_code(self, *, model, prompt):
        if model != OPENCODE_MODEL:
            raise PermissionError("OPENCODE_MODEL_NOT_PINNED")
        ReviewedOutboundCodeScope(prompt)
        return asyncio.run(self._run_once(prompt, 70))


def main():
    args = sys.argv[1:]
    if len(args) != 2 or args[0] != "--worker" or not _SHA.fullmatch(args[1]):
        return 2
    return _worker(args[1])


if __name__ == "__main__":
    raise SystemExit(main())
