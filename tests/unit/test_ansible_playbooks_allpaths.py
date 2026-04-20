#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""All-paths coverage tests for remaining uncovered lines."""

import os
import sys
import tempfile
import unittest
from io import StringIO
from unittest.mock import patch

import netaddr

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from base_test import SimpleModuleTestCase


class TestParseDualStackAllPaths(SimpleModuleTestCase):
    """Tests targeting exception paths in parse_dual_stack."""

    module_name = "parse_dual_stack"

    @patch(
        "parse_dual_stack.netaddr.IPNetwork",
        side_effect=netaddr.core.AddrFormatError("bad"),
    )
    def test_is_valid_cidr_addr_format_error(self, _mock):
        self.assertFalse(self.mod.is_valid_cidr("bad/24"))

    @patch(
        "parse_dual_stack.netaddr.IPNetwork",
        side_effect=UnboundLocalError("bug"),
    )
    def test_is_valid_cidr_unbound_local_error(self, _mock):
        """Test is_valid_cidr with UnboundLocalError (netaddr bug)."""
        self.assertFalse(self.mod.is_valid_cidr("bad/24"))

    @patch(
        "parse_dual_stack.netaddr.valid_ipv4",
        side_effect=Exception("unexpected"),
    )
    def test_is_valid_ipv4_exception(self, _mock):
        self.assertFalse(self.mod.is_valid_ipv4("10.0.0.1"))

    @patch(
        "parse_dual_stack.netaddr.valid_ipv6",
        side_effect=Exception("unexpected"),
    )
    def test_is_valid_ipv6_exception(self, _mock):
        self.assertFalse(self.mod.is_valid_ipv6("fd00::1"))

    @patch(
        "parse_dual_stack.netaddr.IPNetwork",
        side_effect=Exception("unexpected"),
    )
    def test_is_valid_ipv6_cidr_exception(self, _mock):
        self.assertFalse(self.mod.is_valid_ipv6_cidr("fd00::/64"))


class TestGetSwDeploymentsInfoAllPaths(SimpleModuleTestCase):
    """Tests targeting collect_sw_deployments_info and main."""

    module_name = "get_sw_deployments_info"

    @patch("get_sw_deployments_info.subprocess")
    def test_read_file(self, mock_subprocess):
        mock_subprocess.check_output.return_value = "file content"
        mock_subprocess.DEVNULL = -1
        self.mod.read_file.cache_clear()
        result = self.mod.read_file("backup.tar", "some/path")
        self.assertEqual(result, "file content")

    @patch("get_sw_deployments_info.get_tar_excludes", return_value=[])
    @patch(
        "get_sw_deployments_info.get_tar_transforms", return_value=[]
    )
    @patch(
        "get_sw_deployments_info.get_target_reboot_required",
        return_value=False,
    )
    @patch(
        "get_sw_deployments_info.get_deployments_to_restore",
        return_value=[{"sw_version": "24.9", "metapackages": ["p2"], "paths": ["p2.xml"]}],
    )
    @patch(
        "get_sw_deployments_info.get_target_commit",
        return_value="abc123",
    )
    @patch(
        "get_sw_deployments_info.check_if_backup_patched",
        return_value=True,
    )
    @patch(
        "get_sw_deployments_info.get_deployed_groups",
        return_value=[
            {"sw_version": (24, 9), "metapackages": ["base"], "paths": ["p1.xml"]},
            {"sw_version": (24, 9), "metapackages": ["p2"], "paths": ["p2.xml"]},
        ],
    )
    @patch(
        "get_sw_deployments_info.get_metadata",
        return_value={"deployed": ["p1.xml", "p2.xml"]},
    )
    @patch("get_sw_deployments_info.read_file")
    def test_collect_sw_deployments_info_patched(
        self,
        mock_read,
        mock_meta,
        mock_groups,
        mock_patched,
        mock_commit,
        mock_deployments,
        mock_reboot,
        mock_transforms,
        mock_excludes,
    ):
        """Test collect_sw_deployments_info with patched backup."""
        result = self.mod.collect_sw_deployments_info("backup.tar")
        self.assertTrue(result["backup_patched"])
        self.assertEqual(result["target_commit"], "abc123")

    @patch(
        "get_sw_deployments_info.get_target_commit",
        return_value="abc123",
    )
    @patch(
        "get_sw_deployments_info.check_if_backup_patched",
        return_value=False,
    )
    @patch(
        "get_sw_deployments_info.get_deployed_groups",
        return_value=[
            {"sw_version": (24, 9), "metapackages": ["base"], "paths": ["p1.xml"]},
        ],
    )
    @patch(
        "get_sw_deployments_info.get_metadata",
        return_value={"deployed": ["p1.xml"]},
    )
    @patch("get_sw_deployments_info.read_file")
    def test_collect_sw_deployments_info_not_patched(
        self, mock_read, mock_meta, mock_groups, mock_patched, mock_commit
    ):
        """Test collect_sw_deployments_info with unpatched backup."""
        result = self.mod.collect_sw_deployments_info("backup.tar")
        self.assertFalse(result["backup_patched"])

    @patch("get_sw_deployments_info.read_file")
    @patch("get_sw_deployments_info.get_metadata")
    def test_collect_committed_above_minimum_raises(
        self, mock_meta, mock_read
    ):
        """Test committed patches above minimum raise error."""
        mock_meta.return_value = {
            "committed": ["committed.xml"],
            "deployed": ["deployed.xml"],
        }
        mock_read.return_value = (
            "<patch><sw_version>25.3</sw_version></patch>"
        )
        with self.assertRaises(NotImplementedError):
            self.mod.collect_sw_deployments_info("backup.tar")

    @patch("get_sw_deployments_info.collect_sw_deployments_info")
    def test_main_function(self, mock_collect):
        mock_collect.return_value = {"backup_patched": False}
        result = self.mod.main(["backup.tar"])
        self.assertEqual(result, {"backup_patched": False})


class TestRemoveDockerRegistryAllPaths(SimpleModuleTestCase):
    """Tests for remaining uncovered line in remove_docker_registry."""

    module_name = "remove_docker_registry_service_params"

    def test_clean_all_docker_registry_params(self):
        doc = {
            "kind": "System",
            "apiVersion": "starlingx.windriver.com/v1",
            "metadata": {"name": "test", "namespace": "deployment"},
            "spec": {
                "serviceParameters": [
                    {
                        "service": "docker",
                        "section": "docker-registry-k8s",
                    },
                    {
                        "service": "docker",
                        "section": "docker-registry-gcr",
                    },
                ]
            },
        }
        result = self.mod.clean_system_service_params(doc)
        self.assertEqual(len(result["spec"]["serviceParameters"]), 0)


class TestRemoveIncompleteSecretsAllPaths(SimpleModuleTestCase):
    """Tests for remaining uncovered line
    in remove_incomplete_secrets.
    """

    module_name = "remove_incomplete_secrets"

    def test_main_with_empty_docs(self):
        yaml_content = "---\n---\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            path = f.name
        try:
            captured_stdout, captured_stderr = StringIO(), StringIO()

            sys.stdout, sys.stderr = captured_stdout, captured_stderr
            self.mod.main(path)
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            stderr_output = captured_stderr.getvalue()
            self.assertIn("Removed 0", stderr_output)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
