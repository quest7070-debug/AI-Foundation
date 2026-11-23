#!/usr/bin/env python3
"""Read existing GGUF metadata only (never weight tensors or model execution)."""
from collections import Counter
import json
import os
from pathlib import Path
import struct
import sys

MAX_HEADER_BYTES = 80 * 1024 * 1024
MAX_TENSORS = 12000
MAX_METADATA = 10000
MAX_STRING_BYTES = 16 * 1024 * 1024
MAX_ARRAY_ENTRIES = 400000


class HeaderUnverified(ValueError):
    pass


def inspect(path: Path) -> dict:
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise HeaderUnverified("INVALID_GGUF_FILE")
    with path.open("rb") as fp:
        def read(n: int) -> bytes:
            if n < 0 or fp.tell() + n > MAX_HEADER_BYTES:
                raise HeaderUnverified("HEADER_BUDGET")
            data = fp.read(n)
            if len(data) != n:
                raise HeaderUnverified("HEADER_TRUNCATED")
            return data

        def integer(width: int) -> int:
            return int.from_bytes(read(width), "little")

        def string() -> str:
            n = integer(8)
            if n > MAX_STRING_BYTES:
                raise HeaderUnverified("STRING_BUDGET")
            return read(n).decode("utf-8", errors="strict")

        def field(kind: int, depth: int = 0):
            if depth > 2:
                raise HeaderUnverified("ARRAY_NESTING_BUDGET")
            fmt = {0:"B",1:"b",2:"H",3:"h",4:"I",5:"i",
                   6:"f",7:"?",10:"Q",11:"q",12:"d"}
            if kind in fmt:
                return struct.unpack("<" + fmt[kind], read(struct.calcsize(fmt[kind])))[0]
            if kind == 8:
                return string()
            if kind == 9:
                element = integer(4)
                n = integer(8)
                if n > MAX_ARRAY_ENTRIES:
                    raise HeaderUnverified("ARRAY_BUDGET")
                for _ in range(n):
                    field(element, depth + 1)
                return f"ARRAY({n})"
            raise HeaderUnverified("UNKNOWN_GGUF_VALUE_TYPE")

        if read(4) != b"GGUF":
            raise HeaderUnverified("INVALID_GGUF_MAGIC")
        version = integer(4)
        if version != 3:
            raise HeaderUnverified("UNKNOWN_GGUF_VERSION")
        tensors = integer(8)
        metadata = integer(8)
        if tensors > MAX_TENSORS or metadata > MAX_METADATA:
            raise HeaderUnverified("MODEL_HEADER_COUNT_BUDGET")
        chosen = {}
        for _ in range(metadata):
            key = string()
            kind = integer(4)
            value = field(kind)
            if key in (
                "general.architecture", "general.file_type",
                "general.quantization_version",
                "qwen35.context_length", "qwen35.block_count",
                "qwen3_5.context_length", "qwen3_5.block_count",
                "general.name",
            ):
                chosen[key] = value
        kinds = Counter()
        draft_names = []
        example_names = []
        for _ in range(tensors):
            name = string()
            dimensions = integer(4)
            if dimensions > 8:
                raise HeaderUnverified("TENSOR_DIMENSION_BUDGET")
            for _ in range(dimensions):
                integer(8)
            kind = integer(4)
            integer(8)  # data offset, not dereferenced
            kinds[str(kind)] += 1
            if len(example_names) < 8:
                example_names.append(name)
            if any(token in name.lower() for token in (
                "mtp", "nextn", "draft_head", "draft_model",
                "d2t_mapping", "draft_vocab",
            )):
                draft_names.append(name[:160])
        return {
            "status":"GGUF_HEADER_READ_ONLY_VERIFIED",
            "version":version,
            "tensor_count":tensors,
            "metadata_kv_count":metadata,
            "header_bytes_read":fp.tell(),
            "tensor_ggml_type_counts":dict(kinds),
            "selected_general_metadata":chosen,
            "mtp_or_draft_tensor_names_found":len(draft_names),
            "mtp_or_draft_tensor_name_examples":draft_names[:10],
            "mtp_not_available_without_compatible_weights":
                len(draft_names) == 0,
            "model_weights_read":False,
            "model_loaded":False,
            "production_modified":False,
        }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("requires a pre-existing pinned GGUF path")
    try:
        print(json.dumps(inspect(Path(sys.argv[1])),sort_keys=True))
    except (HeaderUnverified, OSError) as err:
        print(json.dumps({"status":"HEADER_BLOCKED",
                          "error_type":type(err).__name__}))
        raise SystemExit(75)
