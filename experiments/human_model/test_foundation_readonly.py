"""Read-only adapter contracts with synthetic mounted volume."""
import tempfile
import unittest
from pathlib import Path
from human_model_ledger import Ledger
from foundation_readonly import read_view

class FoundationReadOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.volumes = Path(self.temp.name) / "Volumes"
        self.root = self.volumes / "USB" / "HumanModel"
        (self.root / "ledger").mkdir(parents=True)
        self.opts = {"volumes_dir": self.volumes,
                     "mount_check": lambda p: p == str(self.volumes / "USB")}
        self.ledger = Ledger.open_external(self.root, **self.opts)
        self.addCleanup(self.ledger.close)
        self.ledger.add(source_uri="synthetic:1", source_revision="1",
                        kind="observation", scope="work", content="synthetic only")
        self.ledger.define_view(view_id="foundation-work", purpose="test",
                                audience="foundation", allowed_scopes=["work"])
        self.ledger.rebuild_view(view_id="foundation-work")

    def test_approved_view_returns_evidence(self):
        rows = read_view(self.root, view_id="foundation-work", scope="work", **self.opts)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "synthetic only")

    def test_unapproved_scope_refused(self):
        with self.assertRaises(PermissionError):
            read_view(self.root, view_id="foundation-work", scope="personal", **self.opts)

    def test_missing_view_refused(self):
        with self.assertRaises(PermissionError):
            read_view(self.root, view_id="missing", scope="work", **self.opts)

    def test_wildcard_scope_refused(self):
        with self.assertRaises(ValueError):
            read_view(self.root, view_id="foundation-work", scope="*", **self.opts)

    def test_stale_view_refused(self):
        self.ledger.add(source_uri="synthetic:2", source_revision="1",
                        kind="observation", scope="work", content="new")
        with self.assertRaises(PermissionError):
            read_view(self.root, view_id="foundation-work", scope="work", **self.opts)

    def test_no_internal_fallback(self):
        with self.assertRaises(Exception):
            read_view(Path(self.temp.name), view_id="foundation-work", scope="work", **self.opts)

    def test_canonical_privacy_levels(self):
        self.ledger.define_view(view_id="public-work", purpose="test",
                                audience="foundation", allowed_scopes=["work"],
                                max_privacy="shareable")
        self.ledger.rebuild_view(view_id="public-work")
        self.assertEqual(read_view(self.root, view_id="public-work", scope="work",
                                   max_privacy="shareable", **self.opts), [])
        with self.assertRaises(PermissionError):
            read_view(self.root, view_id="public-work", scope="work",
                      max_privacy="private", **self.opts)

    def test_invalid_legacy_privacy_rejected(self):
        with self.assertRaises(ValueError):
            read_view(self.root, view_id="foundation-work", scope="work",
                      max_privacy="public", **self.opts)

if __name__ == "__main__":
    unittest.main()
