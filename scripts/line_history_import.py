"""Local-only owner-operated intake for LINE TXT and Android JSONL export."""
import argparse
import json
from pathlib import Path

from ai_foundation.line_history import LineHistoryArchive


def _unique_keys(pairs):
    # A source event must have one unambiguous owner, direction and message ID.
    record = {}
    for key, value in pairs:
        if key in record:
            raise ValueError("LINE_CAPTURE_DUPLICATE_JSON_KEY")
        record[key] = value
    return record


def main():
    parser = argparse.ArgumentParser(description="Import user-supplied LINE history locally")
    parser.add_argument("--db", type=Path, required=True,
                        help="Private local database path (never put this in Git)")
    parser.add_argument("--owner", required=True, help="Private owner scope")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--txt", type=Path, help="LINE native conversation TXT")
    inputs.add_argument("--manifest", type=Path,
                        help="JSON {chats:[{file,conversation_key,self_names?}]} for multiple TXT exports")
    inputs.add_argument("--jsonl", type=Path, help="Android app JSONL capture")
    parser.add_argument("--chat", help="Explicit stable conversation key for one TXT")
    parser.add_argument("--self-name", action="append", default=[],
                        help="Exact sender label for your own messages; repeat for aliases")
    parser.add_argument("--tz", default="Asia/Tokyo")
    args = parser.parse_args()
    archive = LineHistoryArchive(args.db, owner=args.owner)
    if args.txt:
        if not args.chat or not args.self_name:
            parser.error("--txt requires --chat and at least one --self-name")
        # Enforce byte bound before parsing; never partially import a huge file.
        with args.txt.open("rb") as handle:
            raw = handle.read(32 * 1024 * 1024 + 1)
        result = archive.import_txt(raw, conversation_key=args.chat,
                                    self_names=args.self_name, tz=args.tz)
    elif args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"),
                              object_pairs_hook=_unique_keys)
        chats = manifest.get("chats") if isinstance(manifest, dict) else None
        if not isinstance(chats, list) or not 1 <= len(chats) <= 500:
            raise ValueError("manifest requires 1..500 explicitly mapped chats")
        # Parse and ingest one owner-supplied export at a time inside a single
        # SQLite transaction: a malformed late room cannot leave a half import.
        # Keep all file reads inside the explicit manifest directory.
        parent = args.manifest.parent.resolve(strict=True)

        def exports():
            for item in chats:
                if (type(item) is not dict or set(item) not in (
                        {"file", "conversation_key"},
                        {"file", "conversation_key", "self_names"})
                        or type(item.get("file")) is not str
                        or not item["file"].strip()):
                    raise ValueError("manifest entries need file and conversation_key")
                names = item.get("self_names", args.self_name)
                if type(names) is not list or not all(type(n) is str for n in names):
                    raise ValueError("self_names must be an explicit list")
                relative = Path(item["file"])
                if (relative.is_absolute() or not relative.parts
                        or any(part in (".", "..") for part in relative.parts)):
                    raise ValueError("manifest file must be inside manifest directory")
                file_path = parent / relative
                if (file_path.is_symlink() or
                        not file_path.resolve(strict=True).is_relative_to(parent)):
                    raise ValueError("manifest export path outside approved directory")
                with file_path.open("rb") as handle:
                    raw = handle.read(32 * 1024 * 1024 + 1)
                yield raw, item["conversation_key"], names

        result = archive.import_txt_batch(exports(), tz=args.tz)
    else:
        def events():
            with args.jsonl.open("rb") as handle:
                for count, line in enumerate(handle, 1):
                    if len(line) > 256 * 1024:
                        raise ValueError("oversized Android capture event")
                    if count > 200_000:
                        raise ValueError("too many capture events; split the source file")
                    yield json.loads(line, object_pairs_hook=_unique_keys)

        # One bounded event in memory at a time. SQLite rolls back the whole
        # import if a late capture is malformed or reuses an ID in conflict.
        result = archive.ingest(events())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
