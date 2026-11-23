"""Synthetic diskutil contract: no actual volumes accessed."""
import importlib.util
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "human_model_volume_inventory.py"
spec = importlib.util.spec_from_file_location("human_model_volume_inventory", MODULE)
inventory_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory_module)


def test_inventory_excludes_internal_and_unmounted_volumes():
    listing = {"AllDisksAndPartitions": [
        {"DeviceIdentifier": "disk0", "Partitions": [
            {"DeviceIdentifier": "disk0s1"}, {"DeviceIdentifier": "disk2s1"}]}
    ]}
    def fake_diskutil(*args):
        if args == ("list",):
            return listing
        device = args[1]
        if device == "disk0s1":
            return {"MountPoint": "/Volumes/Internal", "Internal": True}
        if device == "disk2s1":
            return {"MountPoint": "/Volumes/External", "Internal": False,
                    "SolidState": True, "VolumeFreeSpace": 1234}
        return {"MountPoint": None}
    with patch.object(inventory_module, "diskutil", side_effect=fake_diskutil), \
         patch.object(inventory_module.Path, "is_dir", return_value=False), \
         patch.object(inventory_module.Path, "exists", return_value=False), \
         patch.object(inventory_module, "free_bytes", return_value=1234):
        result = inventory_module.inventory()
    assert result["candidate_count"] == 1
    assert result["candidates"][0]["solid_state"] is True
    assert result["candidates"][0]["free_bytes"] == 1234
    assert "/Volumes/" not in str(result)
    assert "disk2s1" not in str(result)
