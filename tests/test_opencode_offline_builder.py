"""No-registry and no-execution tests for OpenCode fixture image staging."""
from pathlib import Path
from types import SimpleNamespace
import importlib.util

_MODULE = (Path(__file__).resolve().parents[1] /
           "scripts/build_opencode_offline_canary.py")
spec = importlib.util.spec_from_file_location("offline_canary_builder", _MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

OC = "ghcr.io/anomalyco/opencode:2.2.5@sha256:" + "a" * 64
PY = "python:3.12-alpine@sha256:" + "b" * 64
BIN = "c" * 64
IMAGE_ID = "sha256:" + "d" * 64


def test_missing_trusted_pins_never_touches_docker():
    seen = []
    def runner(*args, **kwargs):
        seen.append(args)
        raise AssertionError("should not call")
    for args in (
        {"opencode_base": "ghcr.io/anomalyco/opencode:latest",
         "python_base": PY, "cli_sha256": BIN},
        {"opencode_base": OC, "python_base": "python:latest",
         "cli_sha256": BIN},
        {"opencode_base": OC, "python_base": PY, "cli_sha256": "unknown"},
    ):
        result = module.build_offline_image(**args, runner=runner)
        assert result["status"] == "PINNED_BUILD_INPUT_REQUIRED"
        assert not result["execution_authorized"]
    assert not seen


def test_minimal_local_context_and_content_ids_only(tmp_path):
    # Synthetic source files: no private parent repo ever copied to daemon.
    root = tmp_path / "repo"
    source = root / "src/ai_foundation"
    source.mkdir(parents=True)
    for name in module._FILES:
        (source / name).write_text("x = 1\n", encoding="utf-8")
    (source / "PRIVATE_SECRET.txt").write_text("NEVER_COPY", encoding="utf-8")
    (root / "docker/opencode-offline").mkdir(parents=True)
    (root / "docker/opencode-offline/Dockerfile").write_text(
        "ARG OPENCODE_LOCAL_ID\nFROM ${OPENCODE_LOCAL_ID}\n", encoding="utf-8")
    images = {OC: "sha256:" + "a" * 64, PY: "sha256:" + "b" * 64}
    local_tags = {}
    calls = []
    def runner(cmd, **kw):
        calls.append(cmd)
        assert kw["env"].keys() == {"PATH", "HOME"}
        if cmd[1:3] == ["image", "inspect"]:
            image_id = images.get(cmd[-1], local_tags.get(cmd[-1]))
            if image_id is None:
                return SimpleNamespace(returncode=1, stdout=b"")
            return SimpleNamespace(returncode=0, stdout=(image_id + "\n").encode())
        if cmd[1:3] == ["image", "tag"]:
            image_id, tag = cmd[-2:]
            assert image_id in images.values()
            assert tag.startswith("localhost/foundation-offline-")
            local_tags[tag] = image_id
            return SimpleNamespace(returncode=0, stdout=b"")
        if cmd[1:3] == ["image", "rm"]:
            assert "--no-prune" in cmd
            assert cmd[-1] in local_tags
            del local_tags[cmd[-1]]
            return SimpleNamespace(returncode=0, stdout=b"")
        assert cmd[1] == "build"
        assert "--pull=false" in cmd and "--network=none" in cmd
        assert "--platform=linux/arm64" in cmd
        assert not any("ghcr.io" in x or "python:3.12-alpine@" in x
                       for x in cmd)
        staged = Path(cmd[-1])
        assert {x.name for x in (staged / "ai_foundation").iterdir()} == (
            set(module._FILES))
        assert "PRIVATE_SECRET.txt" not in {
            p.name for p in staged.rglob("*") if p.is_file()}
        assert any(x.startswith("--build-arg=OPENCODE_LOCAL_REF=localhost/foundation-offline-cli:")
                   for x in cmd)
        assert any(x.startswith("--build-arg=PYTHON_LOCAL_REF=localhost/foundation-offline-python:")
                   for x in cmd)
        Path(cmd[cmd.index("--iidfile") + 1]).write_text(IMAGE_ID)
        return SimpleNamespace(returncode=0, stdout=b"offline build fixture")

    result = module.build_offline_image(
        opencode_base=OC, python_base=PY, cli_sha256=BIN,
        runner=runner, root=root)
    assert result == {"status": "LOCAL_IMAGE_BUILT_NOT_ACCEPTED",
                      "image_id": IMAGE_ID, "cli_sha256": BIN,
                      "execution_authorized": False}
    assert not local_tags
    assert len([c for c in calls if c[1] == "build"]) == 1
    assert len([c for c in calls if c[1:3] == ["image", "rm"]]) == 2


def test_missing_local_base_stops_before_build(tmp_path):
    root = tmp_path / "repo"
    p = root / "src/ai_foundation"
    p.mkdir(parents=True)
    for name in module._FILES:
        (p / name).write_text("pass\n")
    p = root / "docker/opencode-offline"
    p.mkdir(parents=True)
    (p / "Dockerfile").write_text("FROM scratch\n")
    calls = []
    def runner(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=1, stdout=b"")
    result = module.build_offline_image(
        opencode_base=OC, python_base=PY, cli_sha256=BIN,
        root=root, runner=runner)
    assert result["status"] == "PINNED_BASE_NOT_CACHED"
    # Docker caches repository@digest; builder retries that exact immutable pin.
    assert len(calls) == 2


def test_pinned_offline_dockerfile_has_one_parseable_run_continuation():
    """Guard against a truncated RUN regex or duplicated dangling shell tail."""
    dockerfile = (_MODULE.parents[1] / "docker/opencode-offline/Dockerfile")
    content = dockerfile.read_text(encoding="utf-8")
    lines = content.splitlines()
    assert sum(line.startswith("FROM ") for line in lines) == 2
    assert sum(line.startswith("RUN ") for line in lines) == 1
    assert sum("python3 -m compileall" in line for line in lines) == 1
    assert sum("/usr/local/bin/opencode --version" in line for line in lines) == 1
    assert 'grep -Eq ' in content
    assert "'^opencode v2\\.[0-9]+\\.[0-9]+$'" in content
    # Logical RUN is a single shell instruction; no orphan backslash or
    # unrecognized top-level instruction following its continuation.
    start = next(i for i, line in enumerate(lines) if line.startswith("RUN "))
    assert lines[start].rstrip().endswith("\\")
    assert lines[start + 1].lstrip().startswith("&& ")
    assert lines[start + 1].rstrip().endswith("\\")
    assert lines[start + 2].lstrip().startswith("&& ")
    assert not lines[start + 2].rstrip().endswith("\\")
    assert all(not line.lstrip().startswith("&& ") for line in lines[start + 3:])
