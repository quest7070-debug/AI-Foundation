from pathlib import Path
import re

ROOT=Path(__file__).parents[1]
DOC=(ROOT/"docs/LONG_TERM_STORAGE_INVENTORY.md").read_text()

WRITE_PATTERNS=(r"sqlite3\.connect",r"\.write_text\(",r"os\.replace\(",r"open\([^\n]*(?:[\"\']a[\"\']|[\"\']w[\"\'])")
IGNORED={"__init__.py","preflight.py","sqlite_lifecycle.py","operator.py"}

def test_every_first_party_persistent_writer_is_in_long_term_inventory():
    writers=[]
    for path in sorted((ROOT/"src/ai_foundation").glob("*.py")):
        if path.name in IGNORED:
            continue
        text=path.read_text()
        if any(re.search(pattern,text) for pattern in WRITE_PATTERNS):
            writers.append(path.name)
    missing=[name for name in writers if f"`{name}`" not in DOC]
    assert not missing, f"undocumented persistent writer modules: {missing}"
