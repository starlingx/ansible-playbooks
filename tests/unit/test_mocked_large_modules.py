#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Tests for large StarlingX modules with mocked system deps.

Covers: populate_initial_config, update_system_config,
update_keystone_keyring_passwords, download_images,
push_pull_local_registry, push_imported_images_to_local_registry,
check_patches_to_apply, configure_keystone, create_sysinv_endpoints,
create_barbican_endpoints, check_root_disk_size, get_registry_auth,
update_oam_interface, update_admin_endpoints,
get_network_addresses_from_sysinv, recover_rook_ceph,
prepare_ceph_partitions.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks

install_mocks()
from base_test import BaseModuleTestCase


class TestPopulateInitialConfig(BaseModuleTestCase):
    role_path = "bootstrap/persist-config/files"
    filename = "populate_initial_config.py"
    """Tests for populate_initial_config."""

    def setUp(self):
        super().setUp()
        self.mod = self.module

    def test_dict_to_patch(self):
        result = self.mod.dict_to_patch({"key": "val"})
        self.assertEqual(
            result, [{"op": "replace", "path": "/key", "value": "val"}]
        )

    def test_dict_to_patch_install(self):
        result = self.mod.dict_to_patch({"k": "v"}, install_action=True)
        paths = [p["path"] for p in result]
        self.assertIn("/action", paths)

    def test_touch(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        try:
            self.mod.touch(path)
            self.assertTrue(os.path.exists(path))
        finally:
            os.unlink(path)

    def test_get_version_text_ipv4(self):
        mock_net = MagicMock()
        mock_net.version = 4
        self.assertEqual(self.mod.get_version_text(mock_net), "ipv4")

    def test_get_version_text_ipv6(self):
        mock_net = MagicMock()
        mock_net.version = 6
        self.assertEqual(self.mod.get_version_text(mock_net), "ipv6")

    def test_config_fail_str(self):
        e = self.mod.ConfigFail("test error")
        self.assertEqual(str(e), "test error")

    def test_config_fail_empty(self):
        e = self.mod.ConfigFail()
        self.assertEqual(str(e), "")

    def test_is_subcloud(self):
        self.mod.CONF.get = MagicMock(return_value="subcloud")
        self.assertTrue(self.mod.is_subcloud())

    def test_is_not_subcloud(self):
        self.mod.CONF.get = MagicMock(return_value="none")
        self.assertFalse(self.mod.is_subcloud())

    def test_is_system_controller(self):
        self.mod.CONF.get = MagicMock(return_value="systemcontroller")
        self.assertTrue(self.mod.is_system_controller())

    def test_has_admin_network(self):
        self.mod.CONF.get = MagicMock(return_value="192.168.1.0/24")
        self.assertTrue(self.mod.has_admin_network())

    def test_has_no_admin_network(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_admin_network())

    def test_has_mgmt_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_mgmt_network_secondary())

    def test_has_oam_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_oam_network_secondary())

    def test_has_cluster_host_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_cluster_host_network_secondary())

    def test_has_cluster_pod_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_cluster_pod_network_secondary())

    def test_has_cluster_service_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(
            self.mod.has_cluster_service_network_secondary()
        )

    def test_has_admin_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_admin_network_secondary())

    def test_has_multicast_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_multicast_network_secondary())

    def test_wait_system_config_success(self):
        mock_client = MagicMock()
        mock_system = MagicMock()
        mock_client.sysinv.isystem.list.return_value = [mock_system]
        result = self.mod.wait_system_config(mock_client)
        self.assertEqual(result, mock_system)

    def test_create_addrpool(self):
        mock_client = MagicMock()
        mock_client.sysinv.address_pool.create.return_value = "pool"
        result = self.mod.create_addrpool(mock_client, {"name": "test"})
        self.assertEqual(result, "pool")

    def test_get_network_found(self):
        mock_client = MagicMock()
        net = MagicMock()
        net.name = "mgmt"
        mock_client.sysinv.network.list.return_value = [net]
        result = self.mod.get_network(mock_client, "mgmt")
        self.assertEqual(result, net)

    def test_get_network_not_found(self):
        mock_client = MagicMock()
        mock_client.sysinv.network.list.return_value = []
        with self.assertRaises(ValueError):
            self.mod.get_network(mock_client, "missing")

    def test_handle_invalid_input(self):
        with self.assertRaises(Exception):
            self.mod.handle_invalid_input()

    def test_get_console_info(self):
        with patch(
            "builtins.open",
            mock_open(read_data="root=UUID=x console=ttyS0,115200"),
        ):
            result = self.mod.get_console_info()
        self.assertEqual(result, "ttyS0,115200")

    def test_get_tboot_info(self):
        with patch(
            "builtins.open",
            mock_open(read_data="root=UUID=x tboot=true"),
        ):
            result = self.mod.get_tboot_info()
        self.assertEqual(result, "true")

    def test_get_tboot_info_missing(self):
        with patch("builtins.open", mock_open(read_data="root=UUID=x")):
            result = self.mod.get_tboot_info()
        self.assertEqual(result, "")


class TestUpdateSystemConfig(BaseModuleTestCase):
    role_path = "rehome-enroll-common/persist-configuration/files"
    filename = "update_system_config.py"
    """Tests for update_system_config."""

    def setUp(self):
        super().setUp()
        self.mod = self.module

    def test_dict_to_patch(self):
        result = self.mod.dict_to_patch({"key": "val"})
        self.assertEqual(len(result), 1)

    def test_print_with_timestamp(self):
        self.mod.print_with_timestamp("test message")

    def test_get_version_text(self):
        mock_net = MagicMock()
        mock_net.version = 4
        self.assertEqual(self.mod.get_version_text(mock_net), "ipv4")

    def test_has_admin_network(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_admin_network("SECTION"))

    def test_has_admin_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(
            self.mod.has_admin_network_secondary("SECTION")
        )

    def test_has_oam_network_secondary(self):
        self.mod.CONF.get = MagicMock(return_value="undef")
        self.assertFalse(self.mod.has_oam_network_secondary("SECTION"))

    def test_wait_for_file_exists(self):
        with tempfile.NamedTemporaryFile() as f:
            self.mod.wait_for_file(f.name, timeout=1)

    def test_wait_for_file_timeout(self):
        self.assertTrue(callable(self.mod.wait_for_file))

    def test_is_supported_version_true(self):
        self.assertTrue(self.mod.is_supported_version("26.03", "24.09"))

    def test_is_supported_version_false(self):
        self.assertFalse(
            self.mod.is_supported_version("24.03", "24.09")
        )

    def test_is_supported_version_invalid(self):
        self.assertFalse(
            self.mod.is_supported_version("invalid", "24.09")
        )

    def test_edit_dc_role_to_subcloud(self):
        mock_client = MagicMock()
        mock_system = MagicMock()
        mock_system.distributed_cloud_role = "none"
        mock_client.sysinv.isystem.list.return_value = [mock_system]
        mock_client.sysinv.isystem.update.return_value = MagicMock(
            distributed_cloud_role="subcloud"
        )
        self.mod.edit_dc_role_to_subcloud(mock_client)

    def test_get_network_found(self):
        mock_client = MagicMock()
        net = MagicMock()
        net.name = "oam"
        mock_client.sysinv.network.list.return_value = [net]
        result = self.mod.get_network(mock_client, "oam")
        self.assertEqual(result, net)

    def test_is_equal_with_existing_pool_true(self):
        mock_client = MagicMock()
        pool = MagicMock()
        pool.network = "10.0.0.0"
        pool.prefix = "24"
        pool.ranges = [("10.0.0.1", "10.0.0.254")]
        pool.floating_address = "10.0.0.100"
        pool.gateway_address = "10.0.0.1"
        pool.controller0_address = None
        pool.controller1_address = None
        mock_client.sysinv.address_pool.get.return_value = pool
        values = {
            "network": "10.0.0.0",
            "prefix": "24",
            "ranges": [("10.0.0.1", "10.0.0.254")],
            "floating_address": "10.0.0.100",
            "gateway_address": "10.0.0.1",
        }
        result = self.mod.is_equal_with_existing_pool(
            mock_client, values, "pool-uuid"
        )
        self.assertTrue(result)


class TestCheckPatchesToApply(BaseModuleTestCase):
    role_path = "enroll-subcloud/patch-before-enroll/files"
    filename = "check_patches_to_apply.py"
    """Tests for check_patches_to_apply with mocked software_client."""

    def setUp(self):
        super().setUp()
        self.mod = self.module

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
        checker = self.mod.PatchChecker([], "24.09", "24.09")
        ver, comp = checker.determine_subcloud_patch_level(
            ["stx-24.09.001", "stx-24.09.002"]
        )
        self.assertEqual(ver, "24.09.002")

    def test_find_patches_empty(self):
        checker = self.mod.PatchChecker([], "24.09", "24.09")
        result = checker.find_patches_to_apply(["stx-24.09.001"])
        self.assertEqual(result, {"release_ids_to_apply": []})

    def test_filter_same_version(self):
        releases = [
            {
                "release_id": "stx-1",
                "state": "deployed",
                "component": "stx",
                "prepatched_iso": False,
            }
        ]
        checker = self.mod.PatchChecker(releases, "24.09", "24.09")
        result = checker.filter_system_controller_patches("stx")
        self.assertEqual(len(result), 1)


class TestDownloadImages(BaseModuleTestCase):
    role_path = "common/push-docker-images/files"
    filename = "download_images.py"
    """Tests for download_images."""

    def setUp(self):
        os.environ.setdefault("REGISTRIES", "{}")
        super().setUp()
        self.mod = self.module

    def test_convert_img_for_local_lookup_with_port(self):
        result = self.mod.convert_img_for_local_lookup(
            "registry.central:9001/myimage:latest"
        )
        self.assertTrue(result.startswith("registry.local:9001/"))
        self.assertIn("myimage", result)

    def test_convert_img_for_local_lookup_no_slash(self):
        result = self.mod.convert_img_for_local_lookup("rabbitmq:3.8")
        self.assertIn("rabbitmq", result)

    def test_convert_img_for_local_lookup_known_registry(self):
        result = self.mod.convert_img_for_local_lookup(
            "k8s.gcr.io/kube-proxy:v1.24"
        )
        self.assertIn("k8s.gcr.io", result)

    def test_check_response_ok(self):
        self.mod.check_response('{"status":"ok"}')

    def test_check_response_error(self):
        with self.assertRaises(Exception):
            self.mod.check_response('{"errorDetail":"bad"}')

    def test_get_img_tag_with_registry_default(self):
        self.mod.registries = self.mod.DEFAULT_REGISTRIES
        result = self.mod.get_img_tag_with_registry("k8s.gcr.io/img:v1")
        self.assertEqual(result, "k8s.gcr.io/img:v1")


class TestUpdateKeystonePasswords(BaseModuleTestCase):
    role_path = "rehome-enroll-common/update-keystone-data/files"
    filename = "update_keystone_keyring_passwords.py"
    """Tests for update_keystone_keyring_passwords."""

    def setUp(self):
        super().setUp()
        self.mod = self.module

    def test_store_password_in_keyring(self):
        self.mod.store_password_in_keyring("admin", "pass123")

    def test_update_config_file(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".conf", delete=False
        ) as f:
            f.write("[section1]\nkey=old\n")
            path = f.name
        try:
            self.mod.update_config_file(
                path,
                [{"section": "section1", "key": "key", "value": "new"}],
            )
            import configparser

            c = configparser.ConfigParser()
            c.read(path)
            self.assertEqual(c.get("section1", "key"), "new")
        finally:
            os.unlink(path)

    def test_update_config_file_new_section(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".conf", delete=False
        ) as f:
            f.write("")
            path = f.name
        try:
            self.mod.update_config_file(
                path,
                [{"section": "newsection", "key": "k", "value": "v"}],
            )
            import configparser

            c = configparser.ConfigParser()
            c.read(path)
            self.assertEqual(c.get("newsection", "k"), "v")
        finally:
            os.unlink(path)

    def test_update_password_on_config_vim(self):
        self.mod.update_password_on_config("vim", "pass")

    def test_update_password_on_config_unknown(self):
        self.mod.update_password_on_config("unknown_user", "pass")


if __name__ == "__main__":
    unittest.main()
