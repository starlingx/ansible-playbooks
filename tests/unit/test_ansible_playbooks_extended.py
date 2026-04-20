#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Extended coverage tests targeting remaining uncovered paths."""

import os
import sys
import tempfile
import textwrap
import unittest
from io import StringIO
from unittest.mock import MagicMock, patch

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from base_test import SimpleModuleTestCase


class TestParseDualStackExtended(SimpleModuleTestCase):
    """Extended tests for parse_dual_stack edge cases."""

    module_name = "parse_dual_stack"

    def test_is_valid_cidr_single_slash(self):
        self.assertFalse(self.mod.is_valid_cidr("/"))

    def test_is_valid_ipv4_none_like(self):
        """Test is_valid_ipv4 with non-string-like input."""
        self.assertFalse(self.mod.is_valid_ipv4("abc.def.ghi.jkl"))

    def test_is_valid_ipv6_empty(self):
        self.assertFalse(self.mod.is_valid_ipv6(""))

    def test_validate_single_ipv6_cidr(self):
        captured = StringIO()
        sys.stdout = captured
        self.mod.validate("fd00::/64")
        sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("primary=fd00::/64", output)
        self.assertIn("secondary=False", output)

    def test_validate_single_ipv6_address(self):
        captured = StringIO()
        sys.stdout = captured
        self.mod.validate("fd00::1")
        sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("primary=fd00::1", output)

    def test_validate_dual_stack_ipv6_first(self):
        """Test dual-stack with IPv6 first."""
        captured = StringIO()
        sys.stdout = captured
        self.mod.validate("fd00::1,192.168.1.1")
        sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("primary=fd00::1", output)
        self.assertIn("secondary=192.168.1.1", output)

    def test_validate_dual_stack_ipv6_cidr_first(self):
        """Test dual-stack CIDR with IPv6 first."""
        captured = StringIO()
        sys.stdout = captured
        self.mod.validate("fd00::/64,192.168.1.0/24")
        sys.stdout = sys.__stdout__
        output = captured.getvalue()
        self.assertIn("primary=fd00::/64", output)
        self.assertIn("secondary=192.168.1.0/24", output)

    def test_validate_same_family_ipv6_raises(self):
        """Test same IPv6 family dual-stack raises."""
        with self.assertRaises(ValueError):
            self.mod.validate("fd00::1,fd01::1")


class TestValidateDualStackExtended(SimpleModuleTestCase):
    """Extended tests for validate_dual_stack_address_vs_subnet."""

    module_name = "validate_dual_stack_address_vs_subnet"

    def test_ipv6_matching(self):
        self.mod.validate("fd00::1", "fd00::/64")

    def test_dual_stack_ipv6_first(self):
        """Test dual-stack with IPv6 first."""
        self.mod.validate("fd00::1,10.0.0.1", "fd00::/64,10.0.0.0/24")


class TestGetSwDeploymentsInfoExtended(SimpleModuleTestCase):
    """Extended tests for get_sw_deployments_info."""

    module_name = "get_sw_deployments_info"

    @patch("get_sw_deployments_info.subprocess")
    def test_check_if_backup_patched_true(self, mock_subprocess):
        mock_subprocess.call.return_value = 0
        mock_subprocess.DEVNULL = -1
        # Clear lru_cache
        self.mod.check_if_backup_patched.cache_clear()
        result = self.mod.check_if_backup_patched("test.tar")
        self.assertTrue(result)

    @patch("get_sw_deployments_info.subprocess")
    def test_check_if_backup_patched_false(self, mock_subprocess):
        mock_subprocess.call.return_value = 1
        mock_subprocess.DEVNULL = -1
        self.mod.check_if_backup_patched.cache_clear()
        result = self.mod.check_if_backup_patched("test2.tar")
        self.assertFalse(result)

    def test_get_target_commit_single_deployed(self):
        xml = textwrap.dedent(
            """\
            <patch>
                <sw_version>24.9</sw_version>
                <contents>
                    <ostree>
                        <commit1><commit>abc123</commit></commit1>
                    </ostree>
                </contents>
            </patch>
        """
        )
        deployed_groups = [
            {"sw_version": (24, 9), "metapackages": ["base"],
             "paths": ["path/to/patch.xml"]}
        ]
        with patch.object(self.mod, "read_file", return_value=xml):
            result = self.mod.get_target_commit("backup.tar", deployed_groups)
        self.assertEqual(result, "abc123")

    def test_get_target_commit_multiple_deployed(self):
        xml = (
            "<patch><sw_version>24.9</sw_version>"
            "<contents><ostree><commit1><commit>abc123</commit>"
            "</commit1></ostree></contents></patch>"
        )
        deployed_groups = [
            {"sw_version": (24, 9), "metapackages": ["base"],
             "paths": ["p1.xml", "p2.xml"]}
        ]
        with patch.object(self.mod, "read_file", return_value=xml):
            result = self.mod.get_target_commit("backup.tar", deployed_groups)
        self.assertEqual(result, "abc123")

    def test_get_target_commit_no_deployed_raises(self):
        result = self.mod.get_target_commit("backup.tar", [])
        self.assertIsNone(result)

    @patch("get_sw_deployments_info.read_file")
    def test_get_target_reboot_required(self, mock_read):
        mock_read.side_effect = [
            "<patch><reboot_required>Y</reboot_required></patch>",
        ]
        deployments = [
            {"sw_version": "24.9", "metapackages": ["patch1"],
             "paths": ["patch1.xml"]}
        ]
        result = self.mod.get_target_reboot_required(
            "backup.tar", deployments
        )
        self.assertTrue(result)

    @patch("get_sw_deployments_info.read_file")
    def test_get_target_reboot_not_required(self, mock_read):
        mock_read.side_effect = [
            "<patch><reboot_required>N</reboot_required></patch>",
        ]
        deployments = [
            {"sw_version": "24.9", "metapackages": ["patch1"],
             "paths": ["patch1.xml"]}
        ]
        result = self.mod.get_target_reboot_required(
            "backup.tar", deployments
        )
        self.assertFalse(result)

    @patch("get_sw_deployments_info.read_file")
    def test_get_tar_excludes(self, mock_read):
        mock_read.return_value = (
            "<patch><sw_version>22.6</sw_version></patch>"
        )
        metadata = {"committed": ["old.xml"]}
        excludes = self.mod.get_tar_excludes("backup.tar", metadata)
        self.assertEqual(excludes, ["old.xml"])

    @patch("get_sw_deployments_info.read_file")
    def test_get_tar_excludes_new_version(self, mock_read):
        mock_read.return_value = (
            "<patch><sw_version>25.3</sw_version></patch>"
        )
        metadata = {"committed": ["new.xml"]}
        excludes = self.mod.get_tar_excludes("backup.tar", metadata)
        self.assertEqual(excludes, [])

    @patch("get_sw_deployments_info.subprocess")
    def test_get_metadata_empty(self, mock_subprocess):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_subprocess.run.return_value = mock_result
        mock_subprocess.DEVNULL = -1
        self.mod.get_metadata.cache_clear()
        result = self.mod.get_metadata("empty_backup.tar")
        self.assertEqual(result, {})

    @patch("get_sw_deployments_info.read_file")
    @patch("get_sw_deployments_info.subprocess")
    def test_get_metadata_with_entries(
        self, mock_subprocess, mock_read
    ):
        """Test get_metadata with entries."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = (
            "opt/software/metadata/deployed/p1-metadata.xml\n"
        )
        mock_subprocess.run.return_value = mock_result
        mock_subprocess.DEVNULL = -1
        mock_read.return_value = (
            "<patch><sw_version>24.9</sw_version></patch>"
        )
        self.mod.get_metadata.cache_clear()
        result = self.mod.get_metadata("test_backup.tar")
        self.assertIn("deployed", result)


class TestRemoveDockerRegistryExtended(SimpleModuleTestCase):
    """Extended tests for remove_docker_registry_service_params."""

    module_name = "remove_docker_registry_service_params"

    def test_main_function(self):
        """Test main function processes multi-doc YAML."""
        yaml_content = textwrap.dedent(
            """\
            ---
            kind: System
            apiVersion: starlingx.windriver.com/v1
            metadata:
              name: test-system
              namespace: deployment
            spec:
              serviceParameters:
                - service: docker
                  section: docker-registry-k8s
                  paramname: url
                - service: kubernetes
                  section: config
                  paramname: version
            ---
            kind: ConfigMap
            metadata:
              name: test-config
            data:
              key: value
        """
        )
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
            output = captured_stdout.getvalue()
            docs = list(yaml.safe_load_all(output))
            for doc in docs:
                if doc and doc.get("kind") == "System":
                    params = doc["spec"]["serviceParameters"]
                    self.assertEqual(len(params), 1)
                    self.assertEqual(params[0]["service"], "kubernetes")
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            os.unlink(path)

    def test_clean_non_dict_param_entry(self):
        """Test non-dict param entry is kept."""
        doc = {
            "kind": "System",
            "apiVersion": "starlingx.windriver.com/v1",
            "metadata": {"name": "test", "namespace": "deployment"},
            "spec": {
                "serviceParameters": [
                    "not-a-dict",
                    {
                        "service": "docker",
                        "section": "docker-registry-k8s",
                    },
                ]
            },
        }
        result = self.mod.clean_system_service_params(doc)
        params = result["spec"]["serviceParameters"]
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0], "not-a-dict")


class TestFixRookBackendNetworkExtended(SimpleModuleTestCase):
    """Extended tests for fix_rook_backend_network."""

    module_name = "fix_rook_backend_network"

    def test_main_function(self):
        yaml_content = textwrap.dedent(
            """\
            ---
            kind: System
            metadata:
              name: test
            spec:
              storage:
                backends:
                  - type: ceph-rook
                    network: ""
            ---
            kind: ConfigMap
            metadata:
              name: other
            data:
              key: value
        """
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            path = f.name
        try:
            captured = StringIO()
            sys.stdout = captured
            with patch.object(sys, "argv", ["prog", path]):
                self.mod.main()
            sys.stdout = sys.__stdout__
            output = captured.getvalue()
            docs = list(yaml.safe_load_all(output))
            for doc in docs:
                if doc and doc.get("kind") == "System":
                    backend = doc["spec"]["storage"]["backends"][0]
                    self.assertEqual(backend["network"], "cluster-host")
        finally:
            sys.stdout = sys.__stdout__
            os.unlink(path)

    def test_multiple_backends(self):
        """Test fixing multiple ceph-rook backends."""
        doc = {
            "kind": "System",
            "metadata": {"name": "test"},
            "spec": {
                "storage": {
                    "backends": [
                        {"type": "ceph-rook", "network": ""},
                        {"type": "ceph-rook", "network": None},
                        {"type": "ceph", "network": ""},
                    ]
                }
            },
        }
        result = self.mod.fix_system_rook_network(doc)
        backends = result["spec"]["storage"]["backends"]
        self.assertEqual(backends[0]["network"], "cluster-host")
        self.assertEqual(backends[1]["network"], "cluster-host")
        self.assertEqual(backends[2]["network"], "")


class TestRemoveIncompleteSecretsExtended(SimpleModuleTestCase):
    """Extended tests for remove_incomplete_secrets."""

    module_name = "remove_incomplete_secrets"

    def test_is_incomplete_secret_empty_data(self):
        doc = {"kind": "Secret", "data": {}, "stringData": {}}
        self.assertFalse(self.mod.is_incomplete_secret(doc))

    def test_is_incomplete_secret_no_data_key(self):
        doc = {"kind": "Secret"}
        self.assertFalse(self.mod.is_incomplete_secret(doc))

    def test_main_all_kept(self):
        yaml_content = textwrap.dedent(
            """\
            ---
            kind: Secret
            metadata:
              name: good
              namespace: default
            data:
              key: valid-data
        """
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            path = f.name
        try:
            captured_stdout = StringIO()
            sys.stdout = captured_stdout
            sys.stderr = StringIO()
            self.mod.main(path)
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            output = captured_stdout.getvalue()
            docs = list(yaml.safe_load_all(output))
            self.assertEqual(len([d for d in docs if d]), 1)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            os.unlink(path)


class TestCleanKubevirtDvExtended(SimpleModuleTestCase):
    """Extended tests for clean_kubevirt_dv."""

    module_name = "clean_kubevirt_dv"

    def test_clean_dv_all_metadata_fields(self):
        dv_data = {
            "metadata": {
                "name": "test",
                "uid": "u1",
                "resourceVersion": "rv1",
                "creationTimestamp": "ct1",
                "generation": 1,
                "selfLink": "/api/v1/test",
                "managedFields": [{"manager": "test"}],
                "ownerReferences": [{"name": "owner"}],
                "finalizers": ["fin1"],
                "annotations": {"a": "b"},
            },
            "spec": {"pvc": {"volumeName": "pvc-1", "size": "5Gi"}},
            "status": {"phase": "Bound"},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(dv_data, f)
            path = f.name
        try:
            self.mod.clean_dv(path)
            with open(path) as f:
                result = yaml.safe_load(f)
            for key in [
                "uid",
                "resourceVersion",
                "creationTimestamp",
                "generation",
                "selfLink",
                "managedFields",
                "ownerReferences",
                "finalizers",
                "annotations",
            ]:
                self.assertNotIn(key, result["metadata"])
            self.assertNotIn("volumeName", result["spec"]["pvc"])
            self.assertNotIn("status", result)
        finally:
            os.unlink(path)

    def test_clean_dv_no_pvc(self):
        dv_data = {
            "metadata": {"name": "test"},
            "spec": {"other": "val"},
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(dv_data, f)
            path = f.name
        try:
            self.mod.clean_dv(path)
            with open(path) as f:
                result = yaml.safe_load(f)
            self.assertEqual(result["spec"]["other"], "val")
        finally:
            os.unlink(path)

    def test_clean_dv_write_error(self):
        dv_data = {"metadata": {"name": "test"}, "spec": {}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(dv_data, f)
            path = f.name
        try:
            # Make file read-only to trigger write error
            os.chmod(path, 0o444)
            with self.assertRaises(SystemExit):
                self.mod.clean_dv(path)
        finally:
            os.chmod(path, 0o644)
            os.unlink(path)


class TestMergeUserOverridesExtended(SimpleModuleTestCase):
    """Extended tests for merge_user_overrides."""

    module_name = "merge_user_overrides"

    def test_parse_sql_updates_e_quoted(self):
        """Test parse_sql_updates with E-quoted strings."""
        sql = (
            "update helm_overrides set "
            "system_overrides=E'sys\\\\val', "
            "user_overrides=E'user\\\\val' "
            "where name='chart1'"
        )
        result = self.mod.parse_sql_updates(sql)
        self.assertIn("chart1", result)

    def test_parse_sql_updates_multiple(self):
        sql = (
            "update helm_overrides set system_overrides='s1', "
            "user_overrides='u1' where name='c1'\n"
            "update helm_overrides set system_overrides='s2', "
            "user_overrides='u2' where name='c2'"
        )
        result = self.mod.parse_sql_updates(sql)
        self.assertIn("c1", result)
        self.assertIn("c2", result)

    def test_deep_merge_empty_base(self):
        result = self.mod.deep_merge({}, {"a": 1})
        self.assertEqual(result, {"a": 1})

    def test_deep_merge_empty_override(self):
        result = self.mod.deep_merge({"a": 1}, {})
        self.assertEqual(result, {"a": 1})

    def test_main_no_current_chart(self):
        incoming_sql = (
            "update helm_overrides set system_overrides='sys: val', "
            "user_overrides='key1: incoming' where name='chart1'"
        )
        current_sql = ""
        with tempfile.TemporaryDirectory() as tmpdir:
            inc_path = os.path.join(tmpdir, "incoming.sql")
            cur_path = os.path.join(tmpdir, "current.sql")
            out_path = os.path.join(tmpdir, "output.sql")
            with open(inc_path, "w") as f:
                f.write(incoming_sql)
            with open(cur_path, "w") as f:
                f.write(current_sql)
            with patch.object(
                sys, "argv", ["prog", inc_path, cur_path, out_path]
            ):
                self.mod.main()
            with open(out_path) as f:
                output = f.read()
            self.assertIn("chart1", output)


class TestStripPatchContentsExtended(SimpleModuleTestCase):
    """Extended tests for strip_patch_contents."""

    module_name = "strip_patch_contents"

    def test_main_preserves_other_elements(self):
        """Test main preserves non-contents elements."""
        xml_content = textwrap.dedent(
            """\
            <patch>
                <id>test-patch</id>
                <sw_version>24.9</sw_version>
                <reboot_required>N</reboot_required>
                <contents>
                    <data>remove-me</data>
                </contents>
            </patch>
        """
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xml_content)
            path = f.name
        try:
            self.mod.main([path])
            import defusedxml.ElementTree as ET

            tree = ET.parse(path)
            root = tree.getroot()
            self.assertIsNotNone(root.find("./id"))
            self.assertIsNotNone(root.find("./sw_version"))
            self.assertIsNotNone(root.find("./reboot_required"))
            self.assertIsNone(root.find("./contents"))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
