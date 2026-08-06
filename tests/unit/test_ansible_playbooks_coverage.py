#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Coverage-focused tests for ansible-playbooks modules."""

import os
import sys
import tempfile
import textwrap
import unittest
from io import StringIO
from unittest.mock import patch

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from base_test import SimpleModuleTestCase


class TestStripPatchContents(SimpleModuleTestCase):
    """Tests for strip_patch_contents module."""

    module_name = "strip_patch_contents"

    def test_strip_patch_contents_removes_contents(self):
        xml_content = textwrap.dedent(
            """\
            <patch>
                <id>test-patch</id>
                <contents>
                    <ostree>
                        <commit1><commit>abc123</commit></commit1>
                    </ostree>
                </contents>
            </patch>
        """
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xml_content)
            f.flush()
            path = f.name
        try:
            self.mod.strip_patch_contents(path)
            import defusedxml.ElementTree as ET

            tree = ET.parse(path)
            root = tree.getroot()
            self.assertIsNone(root.find("./contents"))
            self.assertIsNotNone(root.find("./id"))
        finally:
            os.unlink(path)

    def test_main_with_args(self):
        xml_content = textwrap.dedent(
            """\
            <patch>
                <id>test</id>
                <contents><data>x</data></contents>
            </patch>
        """
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False
        ) as f:
            f.write(xml_content)
            f.flush()
            path = f.name
        try:
            self.mod.main([path])
        finally:
            os.unlink(path)


class TestCleanKubevirtDv(SimpleModuleTestCase):
    """Tests for clean_kubevirt_dv module."""

    module_name = "clean_kubevirt_dv"

    def test_clean_dv_removes_metadata_fields(self):
        dv_data = {
            "metadata": {
                "name": "test-dv",
                "uid": "abc-123",
                "resourceVersion": "999",
                "creationTimestamp": "2024-01-01",
                "generation": 1,
                "annotations": {"key": "val"},
            },
            "spec": {"pvc": {"volumeName": "pvc-123", "size": "10Gi"}},
            "status": {"phase": "Succeeded"},
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
            self.assertNotIn("uid", result["metadata"])
            self.assertNotIn("resourceVersion", result["metadata"])
            self.assertNotIn("annotations", result["metadata"])
            self.assertNotIn("volumeName", result["spec"]["pvc"])
            self.assertNotIn("status", result)
            self.assertEqual(result["metadata"]["name"], "test-dv")
        finally:
            os.unlink(path)

    def test_clean_dv_minimal(self):
        dv_data = {"metadata": {"name": "min"}, "spec": {}}
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(dv_data, f)
            path = f.name
        try:
            self.mod.clean_dv(path)
            with open(path) as f:
                result = yaml.safe_load(f)
            self.assertEqual(result["metadata"]["name"], "min")
        finally:
            os.unlink(path)

    def test_clean_dv_bad_file(self):
        """Test clean_dv with non-existent file exits."""
        with self.assertRaises(SystemExit):
            self.mod.clean_dv("/nonexistent/path.yaml")


class TestRemoveIncompleteSecrets(SimpleModuleTestCase):
    """Tests for remove_incomplete_secrets module."""

    module_name = "remove_incomplete_secrets"

    def test_is_incomplete_secret_true(self):
        doc = {
            "kind": "Secret",
            "data": {"key": "Warning: Incomplete data"},
        }
        self.assertTrue(self.mod.is_incomplete_secret(doc))

    def test_is_incomplete_secret_false_no_warning(self):
        """Test non-incomplete secret."""
        doc = {
            "kind": "Secret",
            "data": {"key": "valid-data"},
        }
        self.assertFalse(self.mod.is_incomplete_secret(doc))

    def test_is_incomplete_secret_false_not_secret(self):
        """Test non-Secret document."""
        doc = {
            "kind": "ConfigMap",
            "data": {"key": "Warning: Incomplete"},
        }
        self.assertFalse(self.mod.is_incomplete_secret(doc))

    def test_is_incomplete_secret_none(self):
        self.assertFalse(self.mod.is_incomplete_secret(None))

    def test_is_incomplete_secret_string_data(self):
        doc = {
            "kind": "Secret",
            "data": {},
            "stringData": {"key": "Warning: Incomplete value"},
        }
        self.assertTrue(self.mod.is_incomplete_secret(doc))

    def test_main_removes_incomplete(self):
        yaml_content = textwrap.dedent(
            """\
            ---
            kind: Secret
            metadata:
              name: good-secret
              namespace: default
            data:
              key: valid
            ---
            kind: Secret
            metadata:
              name: bad-secret
              namespace: default
            data:
              key: "Warning: Incomplete data"
            ---
            kind: ConfigMap
            metadata:
              name: my-config
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
            names = [d["metadata"]["name"] for d in docs if d]
            self.assertIn("good-secret", names)
            self.assertIn("my-config", names)
            self.assertNotIn("bad-secret", names)
        finally:
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            os.unlink(path)


class TestFixRookBackendNetwork(SimpleModuleTestCase):
    """Tests for fix_rook_backend_network module."""

    module_name = "fix_rook_backend_network"

    def test_fix_empty_network(self):
        doc = {
            "kind": "System",
            "metadata": {"name": "test-system"},
            "spec": {
                "storage": {
                    "backends": [{"type": "ceph-rook", "network": ""}]
                }
            },
        }
        result = self.mod.fix_system_rook_network(doc)
        self.assertEqual(
            result["spec"]["storage"]["backends"][0]["network"],
            "cluster-host",
        )

    def test_fix_none_network(self):
        doc = {
            "kind": "System",
            "metadata": {"name": "test-system"},
            "spec": {
                "storage": {
                    "backends": [{"type": "ceph-rook", "network": None}]
                }
            },
        }
        result = self.mod.fix_system_rook_network(doc)
        self.assertEqual(
            result["spec"]["storage"]["backends"][0]["network"],
            "cluster-host",
        )

    def test_skip_non_system(self):
        """Test non-System documents are skipped."""
        doc = {"kind": "ConfigMap", "metadata": {"name": "test"}}
        result = self.mod.fix_system_rook_network(doc)
        self.assertEqual(result, doc)

    def test_skip_non_ceph_rook(self):
        """Test non-ceph-rook backends are skipped."""
        doc = {
            "kind": "System",
            "metadata": {"name": "test"},
            "spec": {
                "storage": {
                    "backends": [{"type": "ceph", "network": ""}]
                }
            },
        }
        result = self.mod.fix_system_rook_network(doc)
        self.assertEqual(
            result["spec"]["storage"]["backends"][0]["network"], ""
        )

    def test_already_set_network(self):
        """Test already-set network is not changed."""
        doc = {
            "kind": "System",
            "metadata": {"name": "test"},
            "spec": {
                "storage": {
                    "backends": [
                        {"type": "ceph-rook", "network": "custom-net"}
                    ]
                }
            },
        }
        result = self.mod.fix_system_rook_network(doc)
        self.assertEqual(
            result["spec"]["storage"]["backends"][0]["network"],
            "custom-net",
        )

    def test_no_backends(self):
        doc = {
            "kind": "System",
            "metadata": {"name": "test"},
            "spec": {"storage": {}},
        }
        result = self.mod.fix_system_rook_network(doc)
        self.assertEqual(result, doc)

    def test_non_dict_input(self):
        """Test non-dict input returns as-is."""
        self.assertEqual(
            self.mod.fix_system_rook_network("string"), "string"
        )

    def test_non_list_backends(self):
        """Test non-list backends returns doc unchanged."""
        doc = {
            "kind": "System",
            "metadata": {"name": "test"},
            "spec": {"storage": {"backends": "not-a-list"}},
        }
        result = self.mod.fix_system_rook_network(doc)
        self.assertEqual(result, doc)

    def test_non_dict_backend_entry(self):
        """Test non-dict backend entry is skipped."""
        doc = {
            "kind": "System",
            "metadata": {"name": "test"},
            "spec": {"storage": {"backends": ["not-a-dict"]}},
        }
        result = self.mod.fix_system_rook_network(doc)
        self.assertEqual(result, doc)


class TestRemoveDockerRegistryServiceParams(SimpleModuleTestCase):
    """Tests for remove_docker_registry_service_params module."""

    module_name = "remove_docker_registry_service_params"

    def test_clean_removes_docker_registry(self):
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
                    {"service": "kubernetes", "section": "config"},
                ]
            },
        }
        result = self.mod.clean_system_service_params(doc)
        params = result["spec"]["serviceParameters"]
        self.assertEqual(len(params), 1)
        self.assertEqual(params[0]["service"], "kubernetes")

    def test_clean_no_match(self):
        doc = {
            "kind": "System",
            "apiVersion": "starlingx.windriver.com/v1",
            "metadata": {"name": "test", "namespace": "deployment"},
            "spec": {
                "serviceParameters": [
                    {"service": "kubernetes", "section": "config"},
                ]
            },
        }
        result = self.mod.clean_system_service_params(doc)
        self.assertEqual(len(result["spec"]["serviceParameters"]), 1)

    def test_clean_non_system(self):
        """Test non-System document is unchanged."""
        doc = {"kind": "ConfigMap", "data": {}}
        result = self.mod.clean_system_service_params(doc)
        self.assertEqual(result, doc)

    def test_clean_non_dict(self):
        """Test non-dict input returns as-is."""
        self.assertEqual(
            self.mod.clean_system_service_params("string"), "string"
        )

    def test_clean_wrong_namespace(self):
        doc = {
            "kind": "System",
            "apiVersion": "starlingx.windriver.com/v1",
            "metadata": {"name": "test", "namespace": "other"},
            "spec": {
                "serviceParameters": [
                    {
                        "service": "docker",
                        "section": "docker-registry-k8s",
                    },
                ]
            },
        }
        result = self.mod.clean_system_service_params(doc)
        self.assertEqual(len(result["spec"]["serviceParameters"]), 1)

    def test_clean_non_list_params(self):
        """Test non-list serviceParameters is unchanged."""
        doc = {
            "kind": "System",
            "apiVersion": "starlingx.windriver.com/v1",
            "metadata": {"name": "test", "namespace": "deployment"},
            "spec": {"serviceParameters": "not-a-list"},
        }
        result = self.mod.clean_system_service_params(doc)
        self.assertEqual(
            result["spec"]["serviceParameters"], "not-a-list"
        )

    def test_clean_non_dict_spec(self):
        """Test non-dict spec is unchanged."""
        doc = {
            "kind": "System",
            "apiVersion": "starlingx.windriver.com/v1",
            "metadata": {"name": "test", "namespace": "deployment"},
            "spec": "not-a-dict",
        }
        result = self.mod.clean_system_service_params(doc)
        self.assertEqual(result["spec"], "not-a-dict")


class TestMergeUserOverrides(SimpleModuleTestCase):
    """Tests for merge_user_overrides module."""

    module_name = "merge_user_overrides"

    def test_parse_yaml_empty(self):
        self.assertEqual(self.mod.parse_yaml(""), {})

    def test_parse_yaml_null(self):
        self.assertEqual(self.mod.parse_yaml("NULL"), {})

    def test_parse_yaml_none(self):
        self.assertEqual(self.mod.parse_yaml(None), {})

    def test_parse_yaml_valid(self):
        result = self.mod.parse_yaml("key: value")
        self.assertEqual(result, {"key": "value"})

    def test_parse_yaml_invalid(self):
        result = self.mod.parse_yaml("{{invalid}}")
        self.assertEqual(result, {})

    def test_deep_merge_simple(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = self.mod.deep_merge(base, override)
        self.assertEqual(result, {"a": 1, "b": 3, "c": 4})

    def test_deep_merge_nested(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3, "z": 4}}
        result = self.mod.deep_merge(base, override)
        self.assertEqual(result, {"a": {"x": 1, "y": 3, "z": 4}})

    def test_deep_merge_override_non_dict(self):
        """Test deep_merge: override replaces
        dict with non-dict.
        """
        base = {"a": {"x": 1}}
        override = {"a": "string"}
        result = self.mod.deep_merge(base, override)
        self.assertEqual(result, {"a": "string"})

    def test_escape_sql(self):
        self.assertEqual(self.mod.escape_sql("it's"), "it''s")
        self.assertEqual(self.mod.escape_sql("normal"), "normal")

    def test_unwrap_null(self):
        self.assertIsNone(self.mod.unwrap("NULL"))

    def test_unwrap_none(self):
        self.assertIsNone(self.mod.unwrap(None))

    def test_unwrap_empty(self):
        self.assertIsNone(self.mod.unwrap(""))

    def test_unwrap_plain_quoted(self):
        self.assertEqual(self.mod.unwrap("'hello'"), "hello")

    def test_unwrap_e_quoted(self):
        """Test unwrap with E-quoted string."""
        self.assertEqual(self.mod.unwrap("E'hello'"), "hello")

    def test_unwrap_escaped_quotes(self):
        self.assertEqual(self.mod.unwrap("'it''s'"), "it's")

    def test_unwrap_e_quoted_backslash(self):
        """Test unwrap with E-quoted backslash."""
        self.assertEqual(self.mod.unwrap("E'a\\\\b'"), "a\\b")

    def test_parse_sql_updates_basic(self):
        sql = (
            "update helm_overrides set system_overrides='sys_val', "
            "user_overrides='user_val' where name='chart1'"
        )
        result = self.mod.parse_sql_updates(sql)
        self.assertIn("chart1", result)
        self.assertEqual(
            result["chart1"]["system_overrides"], "sys_val"
        )
        self.assertEqual(result["chart1"]["user_overrides"], "user_val")

    def test_parse_sql_updates_null(self):
        sql = (
            "update helm_overrides set system_overrides=NULL, "
            "user_overrides=NULL where name='chart1'"
        )
        result = self.mod.parse_sql_updates(sql)
        self.assertIn("chart1", result)
        self.assertIsNone(result["chart1"]["system_overrides"])
        self.assertIsNone(result["chart1"]["user_overrides"])

    def test_main_merges_overrides(self):
        incoming_sql = (
            "update helm_overrides set system_overrides='sys: val', "
            "user_overrides='key1: incoming' where name='chart1'"
        )
        current_sql = (
            "update helm_overrides set "
            "system_overrides='sys: current', "
            "user_overrides='key2: current' where name='chart1'"
        )
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
            self.assertIn("update helm_overrides", output)


class TestGetSwDeploymentsInfo(SimpleModuleTestCase):
    """Tests for get_sw_deployments_info module."""

    module_name = "get_sw_deployments_info"

    def test_get_sw_version(self):
        xml = "<patch><sw_version>24.9</sw_version></patch>"
        result = self.mod.get_sw_version(xml)
        self.assertEqual(result, (24, 9))

    def test_get_commit(self):
        xml = textwrap.dedent(
            """\
            <patch>
                <contents>
                    <ostree>
                        <commit1><commit>abc123</commit></commit1>
                    </ostree>
                </contents>
            </patch>
        """
        )
        self.assertEqual(self.mod.get_commit(xml), "abc123")

    def test_get_commit_missing(self):
        xml = "<patch><contents><ostree></ostree></contents></patch>"
        self.assertIsNone(self.mod.get_commit(xml))

    def test_get_reboot_required_yes(self):
        xml = "<patch><reboot_required>Y</reboot_required></patch>"
        self.assertTrue(self.mod.get_reboot_required_patch(xml))

    def test_get_reboot_required_no(self):
        xml = "<patch><reboot_required>N</reboot_required></patch>"
        self.assertFalse(self.mod.get_reboot_required_patch(xml))

    def test_get_reboot_required_missing(self):
        xml = "<patch></patch>"
        self.assertFalse(self.mod.get_reboot_required_patch(xml))

    def test_get_target_commit_no_metadata(self):
        self.assertIsNone(self.mod.get_target_commit("dummy", []))

    def test_get_deployments_to_restore_single_group(self):
        deployed_groups = [
            {"sw_version": (24, 9), "metapackages": ["base"], "paths": ["p1"]}
        ]
        self.assertEqual(self.mod.get_deployments_to_restore(deployed_groups), [])

    def test_get_deployments_to_restore_multiple_groups(self):
        deployed_groups = [
            {"sw_version": (24, 9), "metapackages": ["base"], "paths": ["p1"]},
            {"sw_version": (24, 9), "metapackages": ["patch1"], "paths": ["p2"]},
        ]
        result = self.mod.get_deployments_to_restore(deployed_groups)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["metapackages"], ["patch1"])

    def test_get_tar_transforms(self):
        deployments = [
            {"sw_version": "24.9", "metapackages": ["p1"],
             "paths": ["opt/software/metadata/deployed/p1-metadata.xml"]},
        ]
        transforms = self.mod.get_tar_transforms(deployments)
        self.assertEqual(len(transforms), 1)
        self.assertIn("deployed", transforms[0])
        self.assertIn("available", transforms[0])

    def test_get_tar_transforms_empty(self):
        self.assertEqual(self.mod.get_tar_transforms([]), [])


class TestCheckPatchesToApply(unittest.TestCase):
    """Tests for check_patches_to_apply module."""

    def setUp(self):
        """Import module under test with mock for missing deps."""
        # pylint: disable=import-outside-toplevel
        try:
            import check_patches_to_apply as mod

            self.mod = mod
        except (ImportError, TypeError):
            self.skipTest("check_patches_to_apply not importable")

    def test_compare_versions_equal(self):
        self.assertEqual(
            self.mod.compare_versions("24.09.001", "24.09.001"), 0
        )

    def test_compare_versions_greater(self):
        self.assertEqual(
            self.mod.compare_versions("24.09.002", "24.09.001"), 1
        )

    def test_compare_versions_lesser(self):
        self.assertEqual(
            self.mod.compare_versions("24.09.001", "24.09.002"), -1
        )

    def test_determine_subcloud_patch_level(self):
        releases = [
            {"release_id": "stx-24.09.001", "sw_version": "24.09.001"},
            {"release_id": "stx-24.09.002", "sw_version": "24.09.002"},
        ]
        checker = self.mod.PatchChecker(releases, "24.09", "24.09")
        version, component = checker.determine_subcloud_patch_level(
            ["stx-24.09.001", "stx-24.09.002"]
        )
        self.assertEqual(version, "24.09.002")
        self.assertEqual(component, "stx")

    def test_filter_system_controller_patches_same_version(self):
        releases = [
            {
                "release_id": "stx-24.09.001",
                "state": "deployed",
                "component": "stx",
                "prepatched_iso": False,
            },
            {
                "release_id": "stx-24.09.002",
                "state": "committed",
                "component": "stx",
                "prepatched_iso": False,
            },
            {
                "release_id": "other-24.09.001",
                "state": "deployed",
                "component": "other",
                "prepatched_iso": False,
            },
        ]
        checker = self.mod.PatchChecker(releases, "24.09", "24.09")
        filtered = checker.filter_system_controller_patches("stx")
        self.assertEqual(len(filtered), 2)

    def test_filter_system_controller_patches_diff_version(self):
        releases = [
            {
                "release_id": "stx-24.09.001",
                "state": "deployed",
                "component": "stx",
                "prepatched_iso": False,
            },
        ]
        checker = self.mod.PatchChecker(releases, "24.09", "25.03")
        filtered = checker.filter_system_controller_patches("stx")
        self.assertEqual(len(filtered), 1)

    def test_find_patches_no_filtered(self):
        checker = self.mod.PatchChecker([], "24.09", "24.09")
        result = checker.find_patches_to_apply(["stx-24.09.001"])
        self.assertEqual(result, {"release_ids_to_apply": []})

    def test_filter_excludes_prepatched_iso(self):
        releases = [
            {
                "release_id": "stx-24.09.001",
                "state": "deployed",
                "component": "stx",
                "prepatched_iso": True,
            },
        ]
        checker = self.mod.PatchChecker(releases, "24.09", "24.09")
        filtered = checker.filter_system_controller_patches("stx")
        self.assertEqual(len(filtered), 0)


if __name__ == "__main__":
    unittest.main()
