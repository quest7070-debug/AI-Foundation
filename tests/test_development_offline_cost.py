"""No remote API calls; finite trusted catalog and observed license bytes."""
from dataclasses import replace
from hashlib import sha256
import unittest

from ai_foundation.development_offline_cost import (
    AuditedOfflinePackage, OfflineObservation, cost_from_pinned_offline_source,
)

NOW = 1794230000.0
LICENSE = (b"MIT License\n\nCopyright 2026 example authors\n\n"
           b"Permission is hereby granted, free of charge, to any person "
           b"obtaining a copy of this software and associated documentation files.")
COMMIT = "a"*40
SHA = sha256(LICENSE).hexdigest()


class TestOfflineCost(unittest.TestCase):
    def setUp(self):
        self.package = AuditedOfflinePackage(
            "local-safe-tool", "https://github.com/example/safe-tool",
            COMMIT, "MIT", SHA, False, False, False)
        self.catalog = {"local-safe-tool": self.package}
        self.observation = OfflineObservation(
            NOW, COMMIT, LICENSE, False, False, False, True, True)

    def get(self):
        return cost_from_pinned_offline_source(
            "local-safe-tool", catalogue=self.catalog,
            observed=self.observation, now=NOW)

    def test_preapproved_exact_source_and_sandbox(self):
        receipt = self.get()
        self.assertTrue(receipt.license_free)
        self.assertEqual((receipt.initial_yen, receipt.recurring_yen), (0, 0))
        self.assertEqual(receipt.billing, "NOT_APPLICABLE_LOCAL")
        self.assertEqual(receipt.proof, self.package.repository + "/commit/" + COMMIT)

    def test_model_only_candidate_not_catalogued(self):
        self.catalog = {}
        self.assertIsNone(self.get())

    def test_mismatched_license_digest(self):
        self.observation = replace(self.observation, license_bytes=LICENSE + b"extra")
        self.assertIsNone(self.get())

    def test_missing_license_text(self):
        self.observation = replace(self.observation, license_bytes=b"")
        self.assertIsNone(self.get())

    def test_different_checkout_revision(self):
        self.observation = replace(self.observation, observed_commit="b"*40)
        self.assertIsNone(self.get())

    def test_stale_host_observation(self):
        self.observation = replace(self.observation, checked_at=NOW - 86401)
        self.assertIsNone(self.get())

    def test_host_did_not_verify_checkout(self):
        self.observation = replace(self.observation, source_readback_verified=False)
        self.assertIsNone(self.get())

    def test_sandbox_network_not_denied(self):
        self.observation = replace(self.observation, sandbox_network_denied=False)
        self.assertIsNone(self.get())

    def test_account_required_rejected(self):
        self.package = replace(self.package, account_required=True)
        self.catalog["local-safe-tool"] = self.package
        self.assertIsNone(self.get())

    def test_maybe_paid_dependencies_rejected(self):
        self.observation = replace(self.observation, paid_dependencies=True)
        self.assertIsNone(self.get())

    def test_network_runtime_required_rejected(self):
        self.package = replace(self.package, network_runtime_required=True)
        self.catalog["local-safe-tool"] = self.package
        self.assertIsNone(self.get())

    def test_unreviewed_license_rejected(self):
        self.package = replace(self.package, license_spdx="custom-free")
        self.catalog["local-safe-tool"] = self.package
        self.assertIsNone(self.get())

    def test_malformed_host_clock_is_a_hold_not_exception(self):
        for now in (True, "not-a-clock", float("nan"), float("inf"), -float("inf")):
            with self.subTest(now=repr(now)):
                self.assertIsNone(cost_from_pinned_offline_source(
                    "local-safe-tool", catalogue=self.catalog,
                    observed=self.observation, now=now))

    def test_malformed_observation_clock_is_a_hold_not_exception(self):
        for checked_at in (True, "not-a-clock", float("nan"), float("inf")):
            with self.subTest(checked_at=repr(checked_at)):
                self.observation = replace(self.observation, checked_at=checked_at)
                self.assertIsNone(self.get())

    def test_unhashable_spdx_is_a_hold_not_exception(self):
        for spdx in ([], {}, None):
            with self.subTest(spdx=repr(spdx)):
                self.catalog["local-safe-tool"] = replace(
                    self.package, license_spdx=spdx)
                self.assertIsNone(self.get())

    def test_ambiguous_repository_dot_segments_rejected(self):
        for repository in ("https://github.com/./safe-tool",
                           "https://github.com/../safe-tool",
                           "https://github.com/example/.",
                           "https://github.com/example/.."):
            with self.subTest(repository=repository):
                self.catalog["local-safe-tool"] = replace(
                    self.package, repository=repository)
                self.assertIsNone(self.get())

    def test_external_cloud_free_tier_is_not_offline(self):
        self.observation = replace(self.observation, network_runtime_required=True)
        self.assertIsNone(self.get())


if __name__ == "__main__":
    unittest.main()
