#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Deep coverage tests for populate_initial_config.py (844 stmts)."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks
from base_test import BaseModuleTestCase
from constants import (
    ADMIN_SUBNET,
    ADMIN_START,
    ADMIN_END,
    ADMIN_FLOAT,
    ADMIN_GATEWAY,
)

install_mocks()


class TestPopulateSystemConfig(BaseModuleTestCase):
    """Tests for populate_system_config
    and related network functions.
    """

    role_path = "bootstrap/persist-config/files"
    filename = "populate_initial_config.py"
    mod_name = "pop_init_cfg"

    def setUp(self):
        super().setUp()
        self.mod = self.module

    def _mock_conf(self, overrides=None):
        extra = {
            "NAMESERVERS": "8.8.8.8,8.8.4.4",
            "SYSTEM_CONTROLLER_SUBNET": "None",
            "SYSTEM_CONTROLLER_FLOATING_ADDRESS": "None",
            "SYSTEM_CONTROLLER_OAM_SUBNET": "None",
            "SYSTEM_CONTROLLER_OAM_FLOATING_ADDRESS": "None",
        }
        if overrides:
            extra.update(overrides)
        self.configure_conf(**extra)

    def test_populate_system_config_initial(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_SYSTEM = False
        mock_client = MagicMock()
        mock_system = MagicMock()
        mock_client.sysinv.isystem.list.return_value = [mock_system]
        self.mod.populate_system_config(mock_client)
        mock_client.sysinv.isystem.update.assert_called_once()

    def test_populate_system_config_skip(self):
        self.mod.INITIAL_POPULATION = False
        self.mod.RECONFIGURE_SYSTEM = False
        mock_client = MagicMock()
        self.mod.populate_system_config(mock_client)
        mock_client.sysinv.isystem.list.assert_not_called()

    def test_populate_system_config_subcloud(self):
        self._mock_conf({"DISTRIBUTED_CLOUD_ROLE": "subcloud"})
        self.mod.INITIAL_POPULATION = True
        mock_client = MagicMock()
        mock_system = MagicMock()
        mock_client.sysinv.isystem.list.return_value = [mock_system]
        self.mod.populate_system_config(mock_client)

    def test_populate_system_config_systemcontroller(self):
        self._mock_conf({"DISTRIBUTED_CLOUD_ROLE": "systemcontroller"})
        self.mod.INITIAL_POPULATION = True
        mock_client = MagicMock()
        mock_system = MagicMock()
        mock_client.sysinv.isystem.list.return_value = [mock_system]
        self.mod.populate_system_config(mock_client)

    def test_populate_mgmt_network(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.populate_mgmt_network(mock_client)
        mock_client.sysinv.address_pool.create.assert_called_once()

    def test_populate_oam_network(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.populate_oam_network(mock_client)

    def test_populate_pxeboot_network(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.populate_pxeboot_network(mock_client)

    def test_populate_multicast_network(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.populate_multicast_network(mock_client)

    def test_populate_cluster_host_network(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.populate_cluster_host_network(mock_client)

    def test_populate_cluster_pod_network(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.populate_cluster_pod_network(mock_client)

    def test_populate_cluster_service_network(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.populate_cluster_service_network(mock_client)

    def test_populate_admin_network_undef(self):
        self._mock_conf({"ADMIN_SUBNET": "undef"})
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        self.mod.populate_admin_network(mock_client)
        mock_client.sysinv.address_pool.create.assert_not_called()

    def test_populate_admin_network_defined(self):
        self._mock_conf(
            {
                "ADMIN_SUBNET": ADMIN_SUBNET,
                "ADMIN_START_ADDRESS": ADMIN_START,
                "ADMIN_END_ADDRESS": ADMIN_END,
                "ADMIN_FLOATING_ADDRESS": ADMIN_FLOAT,
                "ADMIN_GATEWAY_ADDRESS": ADMIN_GATEWAY,
            }
        )
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        self.mod.INCOMPLETE_BOOTSTRAP = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        self.mod.populate_admin_network(mock_client)

    def test_populate_network_config(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_NETWORK = False
        mock_client = MagicMock()
        mock_pool = MagicMock()
        mock_pool.uuid = "pool-uuid"
        mock_client.sysinv.address_pool.create.return_value = mock_pool
        mock_client.sysinv.network.list.return_value = []
        mock_client.sysinv.address_pool.list.return_value = []
        self.mod.populate_network_config(mock_client)

    def test_populate_network_config_skip(self):
        self.mod.INITIAL_POPULATION = False
        self.mod.RECONFIGURE_NETWORK = False
        mock_client = MagicMock()
        self.mod.populate_network_config(mock_client)

    def test_populate_dns_config(self):
        self._mock_conf()
        self.mod.INITIAL_POPULATION = True
        mock_client = MagicMock()
        mock_dns = MagicMock()
        mock_dns.uuid = "dns-uuid"
        mock_client.sysinv.idns.list.return_value = [mock_dns]
        self.mod.populate_dns_config(mock_client)

    def test_populate_dns_config_skip(self):
        self.mod.INITIAL_POPULATION = False
        self.mod.RECONFIGURE_SYSTEM = False
        mock_client = MagicMock()
        self.mod.populate_dns_config(mock_client)

    def test_populate_platform_config_virtual(self):
        self._mock_conf({"VIRTUAL_SYSTEM": "True"})
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_platform_config(mock_client)
        mock_client.sysinv.service_parameter.create.assert_called_once()

    def test_populate_platform_config_not_virtual(self):
        self._mock_conf({"VIRTUAL_SYSTEM": "False"})
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_platform_config(mock_client)
        mock_client.sysinv.service_parameter.create.assert_not_called()

    def test_populate_service_parameter_config(self):
        self._mock_conf({"VIRTUAL_SYSTEM": "False"})
        self.mod.INITIAL_POPULATION = True
        self.mod.RECONFIGURE_SERVICE = False
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_service_parameter_config(mock_client)

    def test_populate_service_parameter_config_skip(self):
        self.mod.INITIAL_POPULATION = False
        self.mod.RECONFIGURE_SERVICE = False
        mock_client = MagicMock()
        self.mod.populate_service_parameter_config(mock_client)

    def test_delete_network_and_addrpool(self):
        mock_client = MagicMock()
        net = MagicMock()
        net.name = "mgmt"
        net.uuid = "net-uuid"
        mock_client.sysinv.network.list.return_value = [net]
        mock_client.sysinv.ihost.get.return_value = MagicMock(
            uuid="h-uuid"
        )
        mock_client.sysinv.route.list_by_host.return_value = []
        mock_client.sysinv.address.list_by_host.return_value = []
        mock_client.sysinv.network_addrpool.list.return_value = []
        mock_client.sysinv.address_pool.list.return_value = []
        self.mod.delete_network_and_addrpool(
            mock_client, "mgmt", "management"
        )

    def test_get_addrpools_uuid(self):
        mock_client = MagicMock()
        nap = MagicMock()
        nap.network_uuid = "net-uuid"
        nap.address_pool_uuid = "pool-uuid"
        mock_client.sysinv.network_addrpool.list.return_value = [nap]
        result = self.mod.get_addrpools_uuid(mock_client, "net-uuid")
        self.assertEqual(result, ["pool-uuid"])

    def test_create_network(self):
        mock_client = MagicMock()
        self.mod.create_network(mock_client, {"type": "mgmt"}, "mgmt")

    def test_create_network_addrpool(self):
        mock_client = MagicMock()
        self.mod.INCOMPLETE_BOOTSTRAP = False
        self.mod.create_network_addrpool(
            mock_client, {"network_uuid": "n", "address_pool_uuid": "p"}
        )

    def test_populate_kube_cmd_version_none(self):
        self._mock_conf({"KUBERNETES_VERSION": "none"})
        mock_client = MagicMock()
        self.mod.INCOMPLETE_BOOTSTRAP = False
        self.mod.populate_kube_cmd_version(mock_client)
        mock_client.sysinv.kube_cmd_version.update.assert_not_called()

    def test_populate_kube_cmd_version_set(self):
        self._mock_conf({"KUBERNETES_VERSION": "v1.24.4"})
        mock_client = MagicMock()
        self.mod.INCOMPLETE_BOOTSTRAP = False
        self.mod.populate_kube_cmd_version(mock_client)
        mock_client.sysinv.kube_cmd_version.update.assert_called_once()

    def test_populate_system_controller_network_invalid(self):
        self._mock_conf()
        mock_client = MagicMock()
        self.mod.populate_system_controller_network(mock_client)

    def test_populate_controller_config_skip(self):
        self.mod.INITIAL_POPULATION = False
        mock_client = MagicMock()
        self.mod.populate_controller_config(mock_client)

    def test_inventory_config_complete_wait_skip(self):
        self.mod.INITIAL_POPULATION = False
        mock_client = MagicMock()
        self.mod.inventory_config_complete_wait(mock_client, None)

    def test_populate_platform_drbd(self):
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_platform_drbd(mock_client)
        mock_client.sysinv.service_parameter.create.assert_called_once()

    def test_populate_platform_tls_config(self):
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_platform_tls_config(mock_client)

    def test_populate_docker_kube_config_public_registries(self):
        self._mock_conf(
            {
                "USE_PUBLIC_REGISTRIES": "True",
                "DOCKER_HTTP_PROXY": "undef",
                "DOCKER_HTTPS_PROXY": "undef",
            }
        )
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_docker_kube_config(mock_client)

    def test_populate_docker_kube_config_with_proxy(self):
        self._mock_conf(
            {
                "USE_PUBLIC_REGISTRIES": "True",
                "DOCKER_HTTP_PROXY": "http://proxy:3128",
                "DOCKER_HTTPS_PROXY": "undef",
            }
        )
        mock_client = MagicMock()
        mock_client.sysinv.service_parameter.list.return_value = []
        self.mod.populate_docker_kube_config(mock_client)

    def test_get_orig_install_mode_text(self):
        with patch("subprocess.check_call"):
            result = self.mod.get_orig_install_mode()
        self.assertEqual(result, "text")

    def test_get_orig_install_mode_graphical(self):
        import subprocess

        with patch(
            "subprocess.check_call",
            side_effect=subprocess.CalledProcessError(1, "grep"),
        ):
            result = self.mod.get_orig_install_mode()
        self.assertEqual(result, "graphical")


if __name__ == "__main__":
    unittest.main()
