"""CLI entrypoint for a read-only Google Sheets Human Model export preview."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from drive_sheet_preview import main

if __name__ == "__main__":
    raise SystemExit(main())
