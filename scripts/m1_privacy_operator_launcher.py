"""Owner-private Operator-only launcher with PID-bound readback.

Verifies the complete staged package before importing it. No extra daemon.
"""
from __future__ import annotations
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import sys
from urllib.parse import urlparse


def main():
    release = Path(__file__).resolve().parent
    raw = (release / "manifest.json").read_bytes()
    spec = json.loads(raw)
    if sha256(Path(__file__).read_bytes()).hexdigest() != spec.get("launcher_sha256"):
        raise RuntimeError("RELEASE_LAUNCHER_DRIFT")
    if spec.get("schema") != 1 or not re.fullmatch("[a-f0-9]{40}", spec.get("candidate_sha", "")):
        raise RuntimeError("INVALID_OPERATOR_RELEASE")
    sources = spec.get("files")
    if not isinstance(sources, dict) or not 1 <= len(sources) <= 512:
        raise RuntimeError("INVALID_OPERATOR_RELEASE")
    for name, digest in sources.items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or path.parts[:2] != ("src", "ai_foundation"):
            raise RuntimeError("INVALID_RELEASE_SOURCE")
        target = release / path
        if target.is_symlink() or sha256(target.read_bytes()).hexdigest() != digest:
            raise RuntimeError("RELEASE_SOURCE_DRIFT")
    sys.path.insert(0, str(release / "src"))
    from ai_foundation import operator_server
    if Path(operator_server.__file__).resolve() != release / "src/ai_foundation/operator_server.py":
        raise RuntimeError("OPERATOR_SOURCE_SHADOWED")
    if sys.argv[1:] == ["--self-check"]:
        # Import every changed module under the *existing production interpreter*.
        # This cannot start a model, service or Guard effect.
        from ai_foundation import guard, human_model_context, inference_service
        from ai_foundation import routed_agent_model, sensitive_input_scan
        for module in (guard, human_model_context, inference_service,
                       routed_agent_model, sensitive_input_scan):
            if Path(module.__file__).resolve().parent != release / "src/ai_foundation":
                raise RuntimeError("STAGED_IMPORT_SHADOWED")
        print("PRIVATE_OPERATOR_RELEASE_VERIFIED")
        return
    proof = {"candidate_sha": spec["candidate_sha"], "pid": os.getpid(),
             "manifest_sha256": sha256(raw).hexdigest(),
             "startup_nonce": secrets.token_hex(16),
             "startup_sources_verified": True}
    original = operator_server.make_handler
    def make_handler(app):
        base = original(app)
        class Handler(base):
            def do_GET(self):
                if urlparse(self.path).path == "/internal/privacy-fastpath-release":
                    host = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]").lower()
                    if host not in {"127.0.0.1", "localhost", "::1"}:
                        self._send(403, "forbidden\n", "text/plain")
                    else:
                        self._send(200, json.dumps(proof) + "\n", "application/json")
                    return
                return super().do_GET()
        return Handler
    operator_server.make_handler = make_handler
    script = Path(spec["prior_entry"])
    if not script.is_absolute() or script.name != "operator_server.py" or script.is_symlink():
        raise RuntimeError("PRIOR_ENTRY_UNTRUSTED")
    sys.argv = [str(script), *sys.argv[1:]]
    runpy.run_path(str(script), run_name="__main__")


if __name__ == "__main__":
    main()
