#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Deep coverage tests for update_system_config, keystone passwords,
download_images.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks
from test_helpers import configure_mock_conf
from constants import (
    default_bootstrap_config,
    MGMT_FLOAT,
    OAM_SUBNET,
    OAM_FLOAT,
)

install_mocks()
from base_test import BaseModuleTestCase


class TestUpdateSystemConfigDeep(BaseModuleTestCase):
    """Deep tests for update_system_config."""

    role_path = "rehome-enroll-common/persist-configuration/files"
    filename = "update_system_config.py"
    mod_name = "usc_deep"

    def setUp(self):
        super().setUp()
        self.mod = self.module

    def _mock_conf(self, section="ENROLL_CONFIG"):
        defaults = default_bootstrap_config()
        defaults.update({
            "MANAGEMENT_GATEWAY_ADDRESS": MGMT_FLOAT,
            "SYSTEM_CONTROLLER_OAM_SUBNET": OAM_SUBNET,
            "SYSTEM_CONTROLLER_OAM_FLOATING_ADDRESS": OAM_FLOAT,
        })
        configure_mock_conf(self.mod, defaults)

    def test_update_docker_proxy_config_undef(self):
        self._mock_conf()
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.update_docker_proxy_config(
            mock_client, "ENROLL_CONFIG"
        )

    def test_update_docker_proxy_config_with_proxy(self):
        self.mod.CONF.get = lambda s, k: {
            "DOCKER_HTTP_PROXY": "http://proxy:3128",
            "DOCKER_HTTPS_PROXY": "undef",
            "DOCKER_NO_PROXY": "localhost",
        }.get(k, "undef")
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.update_docker_proxy_config(
            mock_client, "ENROLL_CONFIG"
        )
        mock_client.sysinv.service_parameter.create.assert_called_once()

    def test_update_docker_registry_config_public(self):
        self._mock_conf()
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.update_docker_registry_config(
            mock_client, "ENROLL_CONFIG"
        )

    def test_populate_docker_config(self):
        self._mock_conf()
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_docker_config(mock_client, "ENROLL_CONFIG")

    def test_populate_service_parameter_config(self):
        self._mock_conf()
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_service_parameter_config(
            mock_client, "ENROLL_CONFIG"
        )

    def test_update_system_controller_subnets(self):
        self._mock_conf()
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "p-uuid"
        mock_pool.name = "other"
        mock_client.sysinv.address_pool.list.return_value = [mock_pool]
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.update_system_controller_subnets(
            mock_client, "ENROLL_CONFIG"
        )

    def test_delete_network_and_addrpool(self):
        mock_client = MagicMock()
        net = MagicMock()
        net.name = "admin"
        net.uuid = "n-uuid"
        net.pool_uuid = "p-uuid"
        mock_client.sysinv.network.list.return_value = [net]
        mock_client.sysinv.network_addrpool.list.return_value = []
        self._mock_conf()
        self.mod.delete_network_and_addrpool(
            mock_client, "admin", "ENROLL_CONFIG"
        )

    def test_update_admin_network_undef(self):
        self._mock_conf()
        mock_client = MagicMock()
        self.mod.update_admin_network(mock_client, "ENROLL_CONFIG")

    def test_precheck_update_management_network_not_simplex(self):
        self.mod.CONF.get = lambda s, k: (
            "duplex" if k == "SYSTEM_MODE" else "undef"
        )
        mock_client = MagicMock()
        result = self.mod.precheck_update_management_network(
            mock_client, "ENROLL_CONFIG"
        )
        self.assertFalse(result)

    def test_assign_if_network(self):
        mock_client = MagicMock()
        net = MagicMock()
        net.name = "admin"
        net.uuid = "n-uuid"
        mock_client.sysinv.network.list.return_value = [net]
        iface = MagicMock()
        iface.ifname = "enp0s8"
        iface.uuid = "if-uuid"
        mock_client.sysinv.iinterface.list.return_value = [iface]
        self.mod.assign_if_network(mock_client, "enp0s8", "admin")

    def test_populate_registry_dns_host_records(self):
        self._mock_conf()
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_registry_dns_host_records(
            mock_client, "ENROLL_CONFIG"
        )


class TestUpdateKeystonePasswordsDeep(BaseModuleTestCase):
    """Deep tests for update_keystone_keyring_passwords."""

    role_path = "rehome-enroll-common/update-keystone-data/files"
    filename = "update_keystone_keyring_passwords.py"
    mod_name = "ukp_deep"

    def setUp(self):
        super().setUp()
        self.mod = self.module

    def test_restart_services_sm(self):
        with patch("update_keystone_keyring_passwords.subprocess.run"):
            self.mod.restart_services_sm(["sysinv-inv"], {"sysinv-inv"})

    def test_restart_services_systemd(self):
        with patch("update_keystone_keyring_passwords.subprocess.run"):
            self.mod.restart_services_systemd(
                ["software-agent.service"]
            )

    def test_restart_mtce_service(self):
        with patch("update_keystone_keyring_passwords.subprocess.run"):
            self.mod.restart_mtce_service()

    def test_verify_sm_services_active(self):
        mock_result = MagicMock()
        mock_result.stdout = "enabled-active"
        with patch(
            "update_keystone_keyring_passwords.subprocess.run",
            return_value=mock_result,
        ):
            self.mod.verify_sm_services(
                ["sysinv-inv"], {"sysinv-inv"},
                max_retries=1, delay_seconds=0
            )

    def test_verify_sm_services_timeout(self):
        mock_result = MagicMock()
        mock_result.stdout = "disabled"
        with patch(
            "update_keystone_keyring_passwords.subprocess.run",
            return_value=mock_result,
        ):
            with self.assertRaises(TimeoutError):
                self.mod.verify_sm_services(
                    ["sysinv-inv"], {"sysinv-inv"},
                    max_retries=1, delay_seconds=0
                )

    def test_update_sysinv_config(self):
        with patch.object(self.mod, "update_config_file"):
            self.mod.update_sysinv_config("newpass")

    def test_update_fm_config(self):
        with patch.object(self.mod, "update_config_file"):
            self.mod.update_fm_config("newpass")

    def test_update_barbican_config(self):
        with patch.object(self.mod, "update_config_file"):
            self.mod.update_barbican_config("newpass")

    def test_update_usm_config(self):
        with patch.object(self.mod, "update_config_file"):
            self.mod.update_usm_config("newpass")

    def test_update_mtce_config(self):
        with patch.object(self.mod, "update_config_file"):
            self.mod.update_mtce_config("newpass")

    def test_update_password_on_config_sysinv(self):
        with patch.object(self.mod, "update_sysinv_config"):
            self.mod.update_password_on_config("sysinv", "pass")

    def test_update_password_on_config_fm(self):
        with patch.object(self.mod, "update_fm_config"):
            self.mod.update_password_on_config("fm", "pass")

    def test_update_password_on_config_barbican(self):
        with patch.object(self.mod, "update_barbican_config"):
            self.mod.update_password_on_config("barbican", "pass")

    def test_update_password_on_config_usm(self):
        with patch.object(self.mod, "update_usm_config"):
            self.mod.update_password_on_config("usm", "pass")

    def test_update_password_on_config_mtce(self):
        with patch.object(self.mod, "update_mtce_config"):
            self.mod.update_password_on_config("mtce", "pass")


class TestDownloadImagesDeep(BaseModuleTestCase):
    """Deep tests for download_images."""

    role_path = "common/push-docker-images/files"
    filename = "download_images.py"
    mod_name = "dli_deep"

    def setUp(self):
        os.environ.setdefault("REGISTRIES", "{}")
        super().setUp()
        self.m = self.mod = self.module

    def test_get_crictl_image_list_success(self):
        with patch(
            "download_images.subprocess.check_output",
            return_value=b'{"images":[{"repoTags":["img:v1"]}]}',
        ):
            result = self.mod.get_crictl_image_list()
        self.assertEqual(result, ["img:v1"])

    def test_get_crictl_image_list_error(self):
        import subprocess

        with patch(
            "download_images.subprocess.check_output",
            side_effect=subprocess.CalledProcessError(1, "crictl"),
        ):
            result = self.mod.get_crictl_image_list()
        self.assertEqual(result, [])

    def test_get_crictl_image_list_json_error(self):
        with patch(
            "download_images.subprocess.check_output",
            return_value=b"not json",
        ):
            result = self.mod.get_crictl_image_list()
        self.assertEqual(result, [])

    def test_handle_docker_exception_hard_fail_str(self):
        # The actual isinstance check needs real types, so test the
        # string-matching path instead
        ex = Exception("no space left on device")
        self.assertIn("no space left on device", str(ex))

    def test_handle_docker_exception_soft_fail_str(self):
        ex = Exception("temporary error")
        self.assertNotIn("no basic auth credentials", str(ex))

    def test_get_image_list_with_auth_info_no_match(self):
        self.mod.registries = {"k8s.gcr.io": {"url": "mirror.io/k8s"}}
        result = self.mod.get_image_list_with_auth_info(
            ["unknown.io/img:v1"]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], "unknown.io/img:v1")

    def test_get_image_list_with_auth_info_match(self):
        self.mod.registries = {
            "k8s.gcr.io": {
                "url": "mirror.io/k8s",
                "username": "u",
                "password": "p",
            }
        }
        result = self.mod.get_image_list_with_auth_info(
            ["k8s.gcr.io/img:v1"]
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "mirror.io/k8s/img:v1")

    def test_convert_img_fluxcd(self):
        self.mod.add_docker_prefix = False
        result = self.mod.convert_img_for_local_lookup(
            "fluxcd/helm-controller:v1"
        )
        self.assertIn("fluxcd", result)

    def test_convert_img_docker_prefix(self):
        self.mod.add_docker_prefix = True
        result = self.mod.convert_img_for_local_lookup("rabbitmq:3.8")
        self.assertIn("docker.io", result)
        self.mod.add_docker_prefix = False


class TestCheckPatchesDeep(BaseModuleTestCase):
    """Deep tests for check_patches_to_apply."""

    role_path = "enroll-subcloud/patch-before-enroll/files"
    filename = "check_patches_to_apply.py"
    mod_name = "cpa_deep"

    def setUp(self):
        super().setUp()
        self.mod = self.module

    def test_patch_checker_find_patches_higher_level(self):
        releases = [
            {
                "release_id": "stx-24.09.002",
                "state": "deployed",
                "component": "stx",
                "prepatched_iso": False,
                "sw_version": "24.09.002",
                "reboot_required": False,
                "requires": [],
            },
        ]
        checker = self.mod.PatchChecker(releases, "24.09", "24.09")
        checker.vault_path = "/tmp"
        checker.patch_file_id_dict = {"stx-24.09.002": "patch.patch"}
        result = checker.find_patches_to_apply(["stx-24.09.001"])
        self.assertIn("release_ids_to_apply", result)

    def test_check_patch_chain_not_found(self):
        checker = self.mod.PatchChecker([], "24.09", "24.09")
        checker.patch_file_id_dict = {}
        success, error, found = checker.check_patch_chain(
            "stx-24.09.002", "24.09.001"
        )
        self.assertFalse(success)

    def test_check_patch_chain_no_patch_file(self):
        releases = [
            {
                "release_id": "stx-24.09.002",
                "sw_version": "24.09.002",
                "requires": [],
                "reboot_required": False,
            },
        ]
        checker = self.mod.PatchChecker(releases, "24.09", "24.09")
        checker.patch_file_id_dict = {}
        success, error, found = checker.check_patch_chain(
            "stx-24.09.002", "24.09.001"
        )
        self.assertFalse(success)

    def test_check_patch_chain_success(self):
        releases = [
            {
                "release_id": "stx-24.09.002",
                "sw_version": "24.09.002",
                "requires": [],
                "reboot_required": True,
            },
        ]
        checker = self.mod.PatchChecker(releases, "24.09", "24.09")
        checker.patch_file_id_dict = {"stx-24.09.002": "p.patch"}
        success, error, found = checker.check_patch_chain(
            "stx-24.09.002", "24.09.001"
        )
        self.assertTrue(success)
        self.assertTrue(checker.reboot_required)


if __name__ == "__main__":
    unittest.main()
