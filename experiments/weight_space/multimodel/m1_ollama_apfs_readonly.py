#!/usr/bin/env python3
"""Read-only Ollama manifest/blob validation, extracted verbatim from PR #199.

Canonical source: quest7070-dev/AI-Foundation
scripts/m1_ollama_apfs_stage.py at d10c9653932945e41eeafd0f1f27b6b43a559b4f.
Only manifest_blobs, digest_file, validate_staged are included.
There is no copy, stage, install, symlink, daemon, or write action.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re

DIGEST=re.compile(r"sha256:([a-f0-9]{64})\Z")
MAX_MANIFEST=256*1024

def manifest_blobs(raw: bytes) -> tuple[dict, tuple[tuple[str, int], ...]]:
    if not raw or len(raw) > MAX_MANIFEST:
        raise ValueError("OLLAMA_MANIFEST_SIZE_UNVERIFIED")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("OLLAMA_MANIFEST_DUPLICATE_KEY")
            result[key] = value
        return result

    doc = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(doc, dict) or not isinstance(doc.get("config"), dict):
        raise ValueError("OLLAMA_MANIFEST_UNTRUSTED")
    layers = doc.get("layers")
    if not isinstance(layers, list) or not 1 <= len(layers) <= 12:
        raise ValueError("OLLAMA_LAYERS_UNVERIFIED")
    blobs = {}
    for item in [doc["config"], *layers]:
        if not isinstance(item, dict):
            raise ValueError("OLLAMA_LAYER_INVALID")
        digest = item.get("digest")
        size = item.get("size")
        if (not isinstance(digest, str) or DIGEST.fullmatch(digest) is None
                or type(size) is not int or size < 0 or size > 9 * 1024**3):
            raise ValueError("OLLAMA_BLOB_UNVERIFIED")
        if digest in blobs and blobs[digest] != size:
            raise ValueError("OLLAMA_BLOB_CONFLICT")
        blobs[digest] = size
    if sum(blobs.values()) > 12 * 1024**3:
        raise ValueError("OLLAMA_MODEL_SIZE_LIMIT")
    return doc, tuple(sorted(blobs.items()))

def digest_file(path: Path, size: int) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
        raise ValueError("OLLAMA_BLOB_IDENTITY_CHANGED")
    digest = hashlib.sha256()
    with path.open("rb", buffering=0) as source:
        while buf := source.read(4 * 1024 * 1024):
            digest.update(buf)
    return digest.hexdigest()

def validate_staged(root: Path, manifest: bytes, blobs, relative: Path) -> None:
    if root.is_symlink() or not root.is_dir() or root.stat().st_uid != os.getuid():
        raise ValueError("OLLAMA_STAGE_ROOT_UNVERIFIED")
    models = root / "models"
    mf = models / relative
    if mf.is_symlink() or not mf.is_file() or mf.read_bytes() != manifest:
        raise ValueError("OLLAMA_STAGE_MANIFEST_CHANGED")
    for identifier, size in blobs:
        name = "sha256-" + DIGEST.fullmatch(identifier).group(1)
        if digest_file(models / "blobs" / name, size) != identifier.removeprefix("sha256:"):
            raise ValueError("OLLAMA_STAGE_CONTENT_CHANGED")

