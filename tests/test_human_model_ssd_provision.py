"""Provisioning must refuse ambiguous mounts and existing data."""
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "human_model_ssd_provision.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("human_model_ssd_provision", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_refuses_existing_target():
    with patch.object(module, "select_mount", return_value=Path("/Volumes/USB")), \
         patch.object(module.Path, "exists", return_value=True):
        with pytest.raises(RuntimeError, match="already exists"):
            module.provision()

def test_refuses_unmounted_target():
    with patch.object(module, "select_mount", return_value=Path("/Volumes/USB")), \
         patch.object(module.Path, "exists", return_value=False), \
         patch.object(module.Path, "is_symlink", return_value=False), \
         patch.object(module.os, "statvfs") as stat, \
         patch.object(module.os.path, "ismount", return_value=False):
        stat.return_value.f_bavail = 2 * 1024**3
        stat.return_value.f_frsize = 1
        with pytest.raises(RuntimeError, match="unmounted"):
            module.provision()
