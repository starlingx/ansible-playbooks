#!/usr/bin/python3
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import unittest
import sys
from unittest.mock import patch, MagicMock

# Mock the software_client module before importing
sys.modules["software_client"] = MagicMock()
sys.modules["software_client.client"] = MagicMock()

from check_patches_to_apply import PatchChecker, compare_versions  # noqa: E402


class TestPatchChecker(unittest.TestCase):
    """Test cases for PatchChecker class."""

    def setUp(self):
        """Set up test fixtures."""
        self.releases = [
            {
                "release_id": "starlingx-1.0.0",
                "sw_version": "1.0.0",
                "state": "committed",
                "component": "starlingx",
                "requires": [],
                "prepatched_iso": True,
                "reboot_required": True,
            },
            {
                "release_id": "starlingx-1.0.1",
                "sw_version": "1.0.1",
                "state": "committed",
                "component": "starlingx",
                "requires": ["starlingx-1.0.0"],
                "prepatched_iso": False,
                "reboot_required": True,
            },
            {
                "release_id": "starlingx-1.0.2",
                "sw_version": "1.0.2",
                "state": "committed",
                "component": "starlingx",
                "requires": ["starlingx-1.0.1"],
                "prepatched_iso": False,
                "reboot_required": False,
            },
            {
                "release_id": "starlingx-1.0.3",
                "sw_version": "1.0.3",
                "state": "deployed",
                "component": "starlingx",
                "requires": ["starlingx-1.0.2"],
                "prepatched_iso": False,
                "reboot_required": False,
            },
            {
                "release_id": "starlingx-1.0.3",
                "sw_version": "1.0.3",
                "state": "deployed",
                "component": "starlingx",
                "requires": [],
                "prepatched_iso": True,
                "reboot_required": True,
            },
        ]
        self.checker = PatchChecker(self.releases, "1.0.0", "1.0.0")

    def test_find_patches_to_apply_no_filtered_releases(self):
        """Test when all releases are filtered out."""
        # All releases have prepatched_iso=True
        releases = [{"prepatched_iso": True, "state": "deployed", "component": "other"}]
        checker = PatchChecker(releases, "1.0", "1.0")
        result = checker.find_patches_to_apply(["starlingx-1.0.0"])
        self.assertEqual(result, {"release_ids_to_apply": []})

    def test_find_patches_to_apply_sc_version_too_high(self):
        """Test when subcloud patch level is too high."""
        result = self.checker.find_patches_to_apply(["starlingx-1.0.3"])
        self.assertEqual(result, {"release_ids_to_apply": []})

    @patch.object(PatchChecker, "_build_patch_file_mapping")
    def test_find_patches_to_apply_prepatched_iso_filtered(self, mock_mapping):
        """Test filtering of prepatched ISO releases."""
        mock_mapping.return_value = {
            "starlingx-1.0.1": "starlingx-1.0.1.patch",
            "starlingx-1.0.2": "starlingx-1.0.2.patch",
            "starlingx-1.0.3": "starlingx-1.0.3.patch",
        }
        result = self.checker.find_patches_to_apply(["starlingx-1.0.0"])
        self.assertEqual(result["target_release_id"], "starlingx-1.0.3")
        self.assertEqual(result["target_sw_version"], "1.0.3")
        self.assertEqual(result["reboot_required"], True)
        self.assertEqual(
            result["patch_files_to_apply"],
            ["starlingx-1.0.1.patch", "starlingx-1.0.2.patch", "starlingx-1.0.3.patch"],
        )
        self.assertEqual(
            result["release_ids_to_apply"],
            ["starlingx-1.0.1", "starlingx-1.0.2", "starlingx-1.0.3"],
        )

    @patch.object(PatchChecker, "_build_patch_file_mapping")
    def test_find_patches_to_apply_different_versions(self, mock_mapping):
        """Test with different software versions."""
        mock_mapping.return_value = {
            "starlingx-1.0.1": "starlingx-1.0.1.patch",
            "starlingx-1.0.2": "starlingx-1.0.2.patch",
            "starlingx-1.0.3": "starlingx-1.0.3.patch",
        }
        checker = PatchChecker(self.releases, "1.0.0", "1.1.0")
        result = checker.find_patches_to_apply(["starlingx-1.0.0"])
        self.assertEqual(result["target_release_id"], "starlingx-1.0.3")
        self.assertEqual(result["target_sw_version"], "1.0.3")
        self.assertEqual(result["reboot_required"], True)
        self.assertEqual(
            result["patch_files_to_apply"],
            ["starlingx-1.0.1.patch", "starlingx-1.0.2.patch", "starlingx-1.0.3.patch"],
        )
        self.assertEqual(
            result["release_ids_to_apply"],
            ["starlingx-1.0.1", "starlingx-1.0.2", "starlingx-1.0.3"],
        )

    @patch.object(PatchChecker, "_build_patch_file_mapping")
    def test_check_patch_chain_success(self, mock_mapping):
        """Test successful patch chain validation."""
        mock_mapping.return_value = {
            "starlingx-1.0.1": "starlingx-1.0.1.patch",
            "starlingx-1.0.2": "starlingx-1.0.2.patch",
            "starlingx-1.0.3": "starlingx-1.0.3.patch",
        }
        self.checker.patch_files_to_apply = []
        self.checker.release_ids_to_apply = []

        success, error, found = self.checker.check_patch_chain(
            "starlingx-1.0.1", "1.0.0"
        )
        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertTrue(found)
        self.assertEqual(
            self.checker.patch_files_to_apply,
            ["starlingx-1.0.1.patch"],
        )
        self.assertEqual(self.checker.release_ids_to_apply, ["starlingx-1.0.1"])

    def test_check_patch_chain_release_not_found(self):
        """Test when release is not found."""
        success, error, found = self.checker.check_patch_chain("nonexistent", "1.0.0")
        self.assertFalse(success)
        self.assertIn("not found", error)
        self.assertFalse(found)

    @patch.object(PatchChecker, "_build_patch_file_mapping")
    def test_check_patch_chain_patch_file_missing(self, mock_mapping):
        """Test when patch file is missing."""
        mock_mapping.return_value = {}
        success, error, found = self.checker.check_patch_chain(
            "starlingx-1.0.1", "1.0.0"
        )
        self.assertFalse(success)
        self.assertIn("not uploaded", error)
        self.assertFalse(found)

    @patch.object(PatchChecker, "_build_patch_file_mapping")
    def test_check_patch_chain_with_dependencies(self, mock_mapping):
        """Test patch chain with dependencies."""
        mock_mapping.return_value = {
            "starlingx-1.0.1": "starlingx-1.0.1.patch",
            "starlingx-1.0.2": "starlingx-1.0.2.patch",
            "starlingx-1.0.3": "starlingx-1.0.3.patch",
        }
        self.checker.patch_files_to_apply = []
        self.checker.release_ids_to_apply = []

        success, error, found = self.checker.check_patch_chain(
            "starlingx-1.0.3", "1.0.0"
        )
        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertTrue(found)
        expected_patch_files = [
            "starlingx-1.0.3.patch",
            "starlingx-1.0.2.patch",
            "starlingx-1.0.1.patch",
        ]
        self.assertEqual(self.checker.patch_files_to_apply, expected_patch_files)
        self.assertEqual(
            self.checker.release_ids_to_apply,
            ["starlingx-1.0.3", "starlingx-1.0.2", "starlingx-1.0.1"],
        )
        self.assertEqual(self.checker.reboot_required, True)

    @patch.object(PatchChecker, "_build_patch_file_mapping")
    def test_check_patch_chain_with_dependencies_reboot_not_required(
        self, mock_mapping
    ):
        """Test patch chain with dependencies."""
        mock_mapping.return_value = {
            "starlingx-1.0.1": "starlingx-1.0.1.patch",
            "starlingx-1.0.2": "starlingx-1.0.2.patch",
            "starlingx-1.0.3": "starlingx-1.0.3.patch",
        }
        self.checker.patch_files_to_apply = []
        self.checker.release_ids_to_apply = []

        success, error, found = self.checker.check_patch_chain(
            "starlingx-1.0.3", "1.0.2"
        )
        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertTrue(found)
        self.assertEqual(
            self.checker.patch_files_to_apply,
            ["starlingx-1.0.3.patch"],
        )
        self.assertEqual(
            self.checker.release_ids_to_apply,
            ["starlingx-1.0.3"],
        )
        self.assertEqual(self.checker.reboot_required, False)

    def test_determine_subcloud_patch_level(self):
        """Test determine_subcloud_patch_level method."""
        # Test with multiple releases
        subcloud_releases = ["starlingx-1.0.1", "starlingx-1.0.2"]
        patch_level, component = self.checker.determine_subcloud_patch_level(
            subcloud_releases
        )
        self.assertEqual(patch_level, "1.0.2")
        self.assertEqual(component, "starlingx")

        # Test with single release
        subcloud_releases = ["starlingx-1.0.2"]
        patch_level, component = self.checker.determine_subcloud_patch_level(
            subcloud_releases
        )
        self.assertEqual(patch_level, "1.0.2")
        self.assertEqual(component, "starlingx")

    def test_filter_system_controller_patches(self):
        """Test filter_system_controller_patches method."""
        # Add component field to test releases
        releases_with_component = [
            {
                "release_id": "starlingx-1.0.1",
                "sw_version": "1.0.1",
                "state": "committed",
                "component": "starlingx",
                "prepatched_iso": False,
            },
            {
                "release_id": "starlingx-1.0.2",
                "sw_version": "1.0.2",
                "state": "deployed",
                "component": "other",
                "prepatched_iso": False,
            },
        ]
        checker = PatchChecker(releases_with_component, "1.0.0", "1.0.0")

        # Test filtering by component
        filtered = checker.filter_system_controller_patches("starlingx")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["component"], "starlingx")

        # Test with different component
        filtered = checker.filter_system_controller_patches("other")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["component"], "other")

    @patch.object(PatchChecker, "_build_patch_file_mapping")
    def test_check_patch_chain_missing_dependency(self, mock_mapping):
        """Test when required dependency is missing."""
        mock_mapping.return_value = {"starlingx-1.0.5": "starlingx-1.0.5.patch"}
        releases_with_missing_dep = self.releases + [
            {
                "release_id": "starlingx-1.0.5",
                "sw_version": "1.0.5",
                "state": "deployed",
                "requires": ["starlingx-1.0.4"],
                "prepatched_iso": False,
            }
        ]
        checker = PatchChecker(releases_with_missing_dep, "1.0.0", "1.0.0")
        success, error, found = checker.check_patch_chain("starlingx-1.0.5", "1.0.0")
        self.assertFalse(found)
        self.assertFalse(success)
        self.assertIn("starlingx-1.0.4 not found", error)

    @patch.object(PatchChecker, "_build_patch_file_mapping")
    def test_check_patch_chain_insufficient_patches(self, mock_mapping):
        """Test when there are insufficient patches uploaded."""
        mock_mapping.return_value = {"starlingx-1.0.6": "starlingx-1.0.6.patch"}
        releases_no_deps = self.releases + [
            {
                "release_id": "starlingx-1.0.6",
                "sw_version": "1.0.6",
                "state": "deployed",
                "requires": [],
                "prepatched_iso": False,
            }
        ]
        checker = PatchChecker(releases_no_deps, "1.0.0", "1.0.0")
        success, error, found = checker.check_patch_chain("starlingx-1.0.6", "1.0.0")
        self.assertTrue(success)
        self.assertEqual(error, "")
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()


class TestCompareVersions(unittest.TestCase):
    """Test cases for compare_versions function."""

    def test_compare_versions_equal(self):
        """Test comparing equal versions."""
        self.assertEqual(compare_versions("1.0.0", "1.0.0"), 0)
        self.assertEqual(compare_versions("1.0.1", "1.0.100"), 0)

    def test_compare_versions_greater(self):
        """Test comparing greater versions."""
        self.assertEqual(compare_versions("1.0.1", "1.0.0"), 1)
        self.assertEqual(compare_versions("1.1.0", "1.0.9"), 1)
        self.assertEqual(compare_versions("2.0.1", "1.0.0"), 1)
        # Third part compared lexicographically: "2" > "100"
        self.assertEqual(compare_versions("1.0.2", "1.0.100"), 1)

    def test_compare_versions_lesser(self):
        """Test comparing lesser versions."""
        self.assertEqual(compare_versions("1.0.0", "1.0.1"), -1)
        self.assertEqual(compare_versions("1.0.9", "1.1.0"), -1)
        self.assertEqual(compare_versions("1.0.1", "2.0.0"), -1)
        # Third part compared lexicographically: "100" < "2"
        self.assertEqual(compare_versions("1.0.100", "1.0.2"), -1)


if __name__ == "__main__":
    unittest.main()
