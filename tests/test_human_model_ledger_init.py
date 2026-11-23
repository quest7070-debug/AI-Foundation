"""External ledger init refuses pre-existing database before writing."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "human_model_ledger_init.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("human_model_ledger_init", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_existing_database_refused():
    with patch.object(module, "select_mount", return_value=Path("/Volumes/USB")), \
         patch.object(module, "validated_ledger_path", return_value=Path("/tmp/test-ledger.sqlite3")), \
         patch.object(module.Path, "exists", return_value=True):
        with pytest.raises(RuntimeError, match="already exists"):
            module.initialize()
