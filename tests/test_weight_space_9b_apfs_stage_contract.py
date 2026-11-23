"""9B APFS stage readback helper: tiny fake blobs only, no model or host probes."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

MODULE_DIR = Path(__file__).resolve().parents[1] / "experiments/weight_space/multimodel"
sys.path.insert(0, str(MODULE_DIR))
from m1_ollama_apfs_readonly import manifest_blobs, validate_staged

REL = Path("manifests/registry.ollama.ai/library/qwen3.5/9b")


def fixture(root):
    blobs = [b'{"fixture":"config"}', b'FAKE_9B_TEST_BYTES_NO_GGUF']
    def entry(raw, kind):
        return {"mediaType": kind, "digest": "sha256:" + hashlib.sha256(raw).hexdigest(), "size": len(raw)}
    manifest = json.dumps({
        "schemaVersion": 2,
        "config": entry(blobs[0], "application/vnd.ollama.image.config"),
        "layers": [entry(blobs[1], "application/vnd.ollama.image.model")]
    }, sort_keys=True).encode()
    models = root / "models"
    file = models / REL
    file.parent.mkdir(parents=True)
    file.write_bytes(manifest)
    folder = models / "blobs"
    folder.mkdir()
    for data in blobs:
        (folder / ("sha256-" + hashlib.sha256(data).hexdigest())).write_bytes(data)
    _, entries = manifest_blobs(manifest)
    return manifest, entries, blobs


class StageReadbackContracts(unittest.TestCase):
    def test_verified_staged_manifest_9b_fixture_succeeds(self):
        # Previously raised NameError: os not imported in validate_staged().
        with tempfile.TemporaryDirectory(prefix="fixture9b-") as td:
            root = Path(td)
            manifest, blobs, _ = fixture(root)
            validate_staged(root, manifest, blobs, REL)

    def test_tampered_staged_model_blob_refused(self):
        with tempfile.TemporaryDirectory(prefix="fixture9b-") as td:
            root = Path(td)
            manifest, entries, raw = fixture(root)
            name = "sha256-" + hashlib.sha256(raw[1]).hexdigest()
            (root / "models/blobs" / name).write_bytes(b"X" * len(raw[1]))
            with self.assertRaisesRegex(ValueError, "OLLAMA_STAGE_CONTENT_CHANGED"):
                validate_staged(root, manifest, entries, REL)

    def test_staged_manifest_mismatch_refused(self):
        with tempfile.TemporaryDirectory(prefix="fixture9b-") as td:
            root = Path(td)
            manifest, entries, _ = fixture(root)
            (root / "models" / REL).write_bytes(b"not the original manifest")
            with self.assertRaisesRegex(ValueError, "OLLAMA_STAGE_MANIFEST_CHANGED"):
                validate_staged(root, manifest, entries, REL)

    def test_symlinked_model_blob_refused(self):
        with tempfile.TemporaryDirectory(prefix="fixture9b-") as td:
            root = Path(td)
            manifest, entries, raw = fixture(root)
            name = "sha256-" + hashlib.sha256(raw[1]).hexdigest()
            blob = root / "models/blobs" / name
            blob.unlink()
            target = root / "harmless-fixture-target"
            target.write_bytes(raw[1])
            blob.symlink_to(target)
            with self.assertRaisesRegex(ValueError, "OLLAMA_BLOB_IDENTITY_CHANGED"):
                validate_staged(root, manifest, entries, REL)


if __name__ == "__main__":
    unittest.main()
