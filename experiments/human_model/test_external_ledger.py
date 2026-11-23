"""External SSD ledger integration contract; synthetic mount, no real Mac changes."""
import tempfile
import unittest
from pathlib import Path

from human_model_ledger import Ledger
from storage_location import StorageUnavailable


class ExternalLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.volumes = Path(self.tmp.name) / "Volumes"
        self.volumes.mkdir()
        self.volume = self.volumes / "TestSSD"
        self.volume.mkdir()
        self.root = self.volume / "HumanModel"
        (self.root / "ledger").mkdir(parents=True)

    def test_external_ledger_writes_and_reads(self):
        from storage_location import validated_ledger_path
        path = validated_ledger_path(
            self.root, volumes_dir=self.volumes,
            mount_check=lambda p: p == str(self.volume))
        ledger = Ledger(path)
        try:
            eid = ledger.add(source_uri="synthetic:test", source_revision="1",
                             kind="observation", scope="test", content="架空の記録")
            self.assertTrue(eid)
        finally:
            ledger.close()
        reopened = Ledger(path)
        try:
            self.assertEqual(reopened.db.execute(
                "SELECT COUNT(*) FROM evidence").fetchone()[0], 1)
        finally:
            reopened.close()

    def test_rejects_symlinked_sqlite_sidecar(self):
        from storage_location import validated_ledger_path
        target = Path(self.tmp.name) / "outside.db"
        target.write_text("outside")
        sidecar = self.root / "ledger" / "human_model.sqlite3-wal"
        sidecar.symlink_to(target)
        with self.assertRaises(StorageUnavailable):
            validated_ledger_path(
                self.root, volumes_dir=self.volumes,
                mount_check=lambda p: p == str(self.volume))

    def test_rejects_sqlite_database_symlink(self):
        from storage_location import validated_ledger_path
        outside = Path(self.tmp.name) / "outside.sqlite3"
        outside.write_text("untouched")
        (self.root / "ledger" / "human_model.sqlite3").symlink_to(outside)
        with self.assertRaises(StorageUnavailable):
            validated_ledger_path(
                self.root, volumes_dir=self.volumes,
                mount_check=lambda p: p == str(self.volume))
        self.assertEqual(outside.read_text(), "untouched")

    def test_rejects_sqlite_shm_and_journal_symlinks(self):
        from storage_location import validated_ledger_path
        for suffix in ("-shm", "-journal"):
            with self.subTest(suffix=suffix):
                outside = Path(self.tmp.name) / ("outside" + suffix)
                outside.write_text("untouched")
                sidecar = self.root / "ledger" / ("human_model.sqlite3" + suffix)
                sidecar.symlink_to(outside)
                with self.assertRaises(StorageUnavailable):
                    validated_ledger_path(
                        self.root, volumes_dir=self.volumes,
                        mount_check=lambda p: p == str(self.volume))
                self.assertEqual(outside.read_text(), "untouched")
                sidecar.unlink()

    def test_rejects_parent_traversal_even_when_target_exists(self):
        from storage_location import validated_ledger_path
        disguised = self.volume / "HumanModel" / ".." / "HumanModel"
        with self.assertRaises(StorageUnavailable):
            validated_ledger_path(
                disguised, volumes_dir=self.volumes,
                mount_check=lambda p: p == str(self.volume))

    def test_rejects_disconnected_volume(self):
        from storage_location import validated_ledger_path
        with self.assertRaises(StorageUnavailable):
            validated_ledger_path(
                self.root, volumes_dir=self.volumes,
                mount_check=lambda p: False)

    def test_rejects_symlinked_ledger_directory(self):
        from storage_location import validated_ledger_path
        (self.root / "ledger").rmdir()
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (self.root / "ledger").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(StorageUnavailable):
            validated_ledger_path(
                self.root, volumes_dir=self.volumes,
                mount_check=lambda p: p == str(self.volume))

    def test_external_open_on_simulated_mount(self):
        options = dict(volumes_dir=self.volumes,
                       mount_check=lambda p: p == str(self.volume))
        ledger = Ledger.open_external(self.root, **options)
        try:
            ledger.add(source_uri="synthetic:external", source_revision="1",
                       kind="observation", scope="test", content="外付けの記録")
        finally:
            ledger.close()
        reopened = Ledger.open_external(self.root, **options)
        try:
            self.assertEqual(reopened.db.execute(
                "SELECT COUNT(*) FROM evidence").fetchone()[0], 1)
        finally:
            reopened.close()

    def test_external_open_rejects_internal_path(self):
        with self.assertRaises(StorageUnavailable):
            Ledger.open_external(Path(self.tmp.name) / "internal")

    def test_external_open_rejects_missing_mount(self):
        with self.assertRaises(StorageUnavailable):
            Ledger.open_external(self.root)


if __name__ == "__main__":
    unittest.main()
