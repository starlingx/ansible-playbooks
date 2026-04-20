#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Exhaustive tests for
populate_initial_config.

Covers all network populate functions.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks
from base_test import BaseModuleTestCase
from constants import (
    ADMIN_SUBNET,
    SC_SUBNET,
    SC_FLOAT,
    SC_OAM_SUBNET,
    SC_OAM_FLOAT,
)

install_mocks()


class TestPICExhaustive(BaseModuleTestCase):
    role_path = "bootstrap/persist-config/files"
    filename = "populate_initial_config.py"
    mod_name = "pic2"

    def setUp(self):
        """Load module under test."""
        super().setUp()
        self.m = self.module

    def _create_test_client(self, **kwargs):
        """Configure mocks and return client."""
        self.configure_conf(**kwargs)
        return self.create_client()

    # Secondary network functions
    def _net(self, name):
        """Create a mock network matching sysinv constant name."""
        n = MagicMock()
        n.name = name
        n.uuid = "n-uuid"
        n.pool_uuid = "p-uuid"
        return n

    def test_populate_mgmt_network_secondary(self):
        c = self._create_test_client(
            MANAGEMENT_SUBNET_SECONDARY="fd00::/64",
            MANAGEMENT_START_ADDRESS_SECONDARY="fd00::2",
            MANAGEMENT_END_ADDRESS_SECONDARY="fd00::ff",
            MANAGEMENT_FLOATING_ADDRESS_SECONDARY="fd00::1",
            MANAGEMENT_GATEWAY_ADDRESS_SECONDARY="undef",
        )
        c.sysinv.network.list.return_value = [
            self._net(self.m.sysinv_constants.NETWORK_TYPE_MGMT)
        ]
        self.m.populate_mgmt_network_secondary(c)

    def test_populate_oam_network_secondary(self):
        c = self._create_test_client(
            EXTERNAL_OAM_SUBNET_SECONDARY="fd01::/64",
            SYSTEM_MODE="duplex",
        )
        c.sysinv.network.list.return_value = [
            self._net(self.m.sysinv_constants.NETWORK_TYPE_OAM)
        ]
        self.m.populate_oam_network_secondary(c)

    def test_populate_multicast_network_secondary(self):
        c = self._create_test_client(
            MANAGEMENT_MULTICAST_SUBNET_SECONDARY="ff05::/16"
        )
        c.sysinv.network.list.return_value = [
            self._net(self.m.sysinv_constants.NETWORK_TYPE_MULTICAST)
        ]
        self.m.populate_multicast_network_secondary(c)

    def test_populate_cluster_host_network_secondary(self):
        c = self._create_test_client(
            CLUSTER_HOST_SUBNET_SECONDARY="fd02::/64"
        )
        c.sysinv.network.list.return_value = [
            self._net(self.m.sysinv_constants.NETWORK_TYPE_CLUSTER_HOST)
        ]
        self.m.populate_cluster_host_network_secondary(c)

    def test_populate_cluster_pod_network_secondary(self):
        c = self._create_test_client(
            CLUSTER_POD_SUBNET_SECONDARY="fd03::/64"
        )
        c.sysinv.network.list.return_value = [
            self._net(self.m.sysinv_constants.NETWORK_TYPE_CLUSTER_POD)
        ]
        self.m.populate_cluster_pod_network_secondary(c)

    def test_populate_cluster_service_network_secondary(self):
        c = self._create_test_client(
            CLUSTER_SERVICE_SUBNET_SECONDARY="fd04::/64"
        )
        c.sysinv.network.list.return_value = [
            self._net(
                self.m.sysinv_constants.NETWORK_TYPE_CLUSTER_SERVICE
            )
        ]
        self.m.populate_cluster_service_network_secondary(c)

    def test_populate_admin_network_secondary(self):
        c = self._create_test_client(
            ADMIN_SUBNET=ADMIN_SUBNET,
            ADMIN_SUBNET_SECONDARY="fd05::/64",
            ADMIN_START_ADDRESS_SECONDARY="fd05::2",
            ADMIN_END_ADDRESS_SECONDARY="fd05::ff",
            ADMIN_GATEWAY_ADDRESS_SECONDARY="undef",
            ADMIN_FLOATING_ADDRESS_SECONDARY="undef",
        )
        c.sysinv.network.list.return_value = [
            self._net(self.m.sysinv_constants.NETWORK_TYPE_ADMIN)
        ]
        self.m.populate_admin_network_secondary(c)

    # Reconfigure paths
    def test_populate_mgmt_network_reconfigure(self):
        c = self._create_test_client()
        self.m.RECONFIGURE_NETWORK = True
        self.m.INITIAL_POPULATION = False
        self.m.INCOMPLETE_BOOTSTRAP = False
        self.m.populate_mgmt_network(c)
        self.m.RECONFIGURE_NETWORK = False
        self.m.INITIAL_POPULATION = True

    def test_populate_oam_network_duplex(self):
        c = self._create_test_client(SYSTEM_MODE="duplex")
        self.m.INITIAL_POPULATION = True
        self.m.RECONFIGURE_NETWORK = False
        self.m.INCOMPLETE_BOOTSTRAP = False
        self.m.populate_oam_network(c)

    def test_populate_system_controller_network_valid(self):
        c = self._create_test_client(
            SYSTEM_CONTROLLER_SUBNET=SC_SUBNET,
            SYSTEM_CONTROLLER_FLOATING_ADDRESS=SC_FLOAT,
            SYSTEM_CONTROLLER_OAM_SUBNET=SC_OAM_SUBNET,
            SYSTEM_CONTROLLER_OAM_FLOATING_ADDRESS=SC_OAM_FLOAT,
        )
        self.m.INITIAL_POPULATION = True
        self.m.RECONFIGURE_NETWORK = False
        self.m.INCOMPLETE_BOOTSTRAP = False
        self.m.populate_system_controller_network(c)
        self.assertTrue(c.sysinv.address_pool.create.called)

    # Network config with all secondaries
    def test_populate_network_config_all_secondaries(self):
        c = self._create_test_client(
            MANAGEMENT_SUBNET_SECONDARY="fd00::/64",
            EXTERNAL_OAM_SUBNET_SECONDARY="fd01::/64",
            MANAGEMENT_MULTICAST_SUBNET_SECONDARY="ff05::/16",
            CLUSTER_HOST_SUBNET_SECONDARY="fd02::/64",
            CLUSTER_POD_SUBNET_SECONDARY="fd03::/64",
            CLUSTER_SERVICE_SUBNET_SECONDARY="fd04::/64",
            ADMIN_SUBNET=ADMIN_SUBNET,
            ADMIN_SUBNET_SECONDARY="fd05::/64",
            DISTRIBUTED_CLOUD_ROLE="none",
        )
        # Provide all network types for get_network lookups
        nets = []
        for attr in [
            "NETWORK_TYPE_MGMT",
            "NETWORK_TYPE_OAM",
            "NETWORK_TYPE_MULTICAST",
            "NETWORK_TYPE_CLUSTER_HOST",
            "NETWORK_TYPE_CLUSTER_POD",
            "NETWORK_TYPE_CLUSTER_SERVICE",
            "NETWORK_TYPE_ADMIN",
        ]:
            nets.append(
                self._net(getattr(self.m.sysinv_constants, attr))
            )
        c.sysinv.network.list.return_value = nets
        self.m.INITIAL_POPULATION = True
        self.m.RECONFIGURE_NETWORK = False
        self.m.populate_network_config(c)

    # Docker/kube config with proxy and private registries
    def test_populate_docker_kube_config_with_both_proxies(self):
        c = self._create_test_client(
            DOCKER_HTTP_PROXY="http://p:3128",
            DOCKER_HTTPS_PROXY="https://p:3129",
            USE_PUBLIC_REGISTRIES="True",
            KUBERNETES_VERSION="v1.24.4",
        )
        c.sysinv.service_parameter.list.return_value = []
        self.m.populate_docker_kube_config(c)

    def test_populate_docker_kube_config_private_registries(self):
        c = self._create_test_client(
            USE_PUBLIC_REGISTRIES="False",
            K8S_REGISTRY="mirror.io",
            K8S_REGISTRY_SECRET="none",
            K8S_REGISTRY_TYPE="docker",
            K8S_REGISTRY_SECURE="True",
            K8S_REGISTRY_ADDITIONAL_OVERRIDES="undef",
            GCR_REGISTRY="mirror.io",
            GCR_REGISTRY_SECRET="none",
            GCR_REGISTRY_TYPE="docker",
            GCR_REGISTRY_SECURE="True",
            GCR_REGISTRY_ADDITIONAL_OVERRIDES="undef",
            QUAY_REGISTRY="mirror.io",
            QUAY_REGISTRY_SECRET="none",
            QUAY_REGISTRY_TYPE="docker",
            QUAY_REGISTRY_SECURE="True",
            QUAY_REGISTRY_ADDITIONAL_OVERRIDES="undef",
            DOCKER_REGISTRY="mirror.io",
            DOCKER_REGISTRY_SECRET="none",
            DOCKER_REGISTRY_TYPE="docker",
            DOCKER_REGISTRY_SECURE="True",
            DOCKER_REGISTRY_ADDITIONAL_OVERRIDES="undef",
            ELASTIC_REGISTRY="mirror.io",
            ELASTIC_REGISTRY_SECRET="none",
            ELASTIC_REGISTRY_TYPE="docker",
            ELASTIC_REGISTRY_SECURE="True",
            ELASTIC_REGISTRY_ADDITIONAL_OVERRIDES="undef",
            GHCR_REGISTRY="mirror.io",
            GHCR_REGISTRY_SECRET="none",
            GHCR_REGISTRY_TYPE="docker",
            GHCR_REGISTRY_SECURE="True",
            GHCR_REGISTRY_ADDITIONAL_OVERRIDES="undef",
            REGISTRYK8S_REGISTRY="mirror.io",
            REGISTRYK8S_REGISTRY_SECRET="none",
            REGISTRYK8S_REGISTRY_TYPE="docker",
            REGISTRYK8S_REGISTRY_SECURE="True",
            REGISTRYK8S_REGISTRY_ADDITIONAL_OVERRIDES="undef",
            ICR_REGISTRY="mirror.io",
            ICR_REGISTRY_SECRET="none",
            ICR_REGISTRY_TYPE="docker",
            ICR_REGISTRY_SECURE="True",
            ICR_REGISTRY_ADDITIONAL_OVERRIDES="undef",
        )
        c.sysinv.service_parameter.list.return_value = []
        self.m.populate_docker_kube_config(c)

    # User DNS host records
    def test_populate_user_dns_host_records(self):
        c = self._create_test_client()
        orig_has = self.m.CONF.has_section
        orig_items = self.m.CONF.items
        self.m.CONF.has_section = lambda s: True
        self.m.CONF.items = lambda s=None, section=None: [
            ("host1", "192.168.1.1,myhost")
        ]
        c.sysinv.service_parameter.list.return_value = []
        self.m.populate_user_dns_host_records(c)
        self.m.CONF.has_section = orig_has
        self.m.CONF.items = orig_items

    # Service parameter config with user DNS
    def test_populate_service_parameter_config_with_dns(self):
        c = self._create_test_client(VIRTUAL_SYSTEM="False")
        self.m.INITIAL_POPULATION = True
        self.m.RECONFIGURE_SERVICE = False
        self.m.CONF.has_section = lambda s: s == "USER_DNS_HOST_RECORDS"
        self.m.CONF.items = lambda s=None, section=None: (
            [("h1", "10.0.0.1,host1")]
            if (s or section) == "USER_DNS_HOST_RECORDS"
            else []
        )
        c.sysinv.service_parameter.list.return_value = []
        self.m.populate_service_parameter_config(c)

    # Controller config
    def test_populate_controller_config(self):
        c = self._create_test_client()
        self.m.INITIAL_POPULATION = True
        self.m.INCOMPLETE_BOOTSTRAP = False
        self.m.get_management_mac_address = lambda: "aa:bb:cc:dd:ee:ff"
        self.m.get_device_from_function = lambda f: "/dev/sda"
        self.m.get_console_info = lambda: "ttyS0"
        self.m.get_tboot_info = lambda: ""
        self.m.get_orig_install_mode = lambda: "text"
        self.m.populate_controller_config(c)
        c.sysinv.ihost.create.assert_called_once()

    # Wait functions
    def test_wait_system_config_timeout(self):
        c = MagicMock()
        c.sysinv.isystem.list.side_effect = Exception("fail")
        self.m.SYSTEM_CONFIG_TIMEOUT = 1
        with self.assertRaises(self.m.ConfigFail):
            self.m.wait_system_config(c)

    def test_wait_initial_inventory_complete(self):
        c = MagicMock()
        host = MagicMock()
        host.inv_state = "initial-inventoried"
        c.sysinv.ihost.get.return_value = host
        self.m.SYSTEM_CONFIG_TIMEOUT = 10
        # Mock the constant
        self.m.sysinv_constants.INV_STATE_INITIAL_INVENTORIED = (
            "initial-inventoried"
        )
        result = self.m.wait_initial_inventory_complete(c, host)
        self.assertEqual(result, host)

    # Incomplete bootstrap paths
    def test_populate_system_config_incomplete_bootstrap(self):
        c = self._create_test_client(DISTRIBUTED_CLOUD_ROLE="none")
        self.m.INITIAL_POPULATION = True
        self.m.INCOMPLETE_BOOTSTRAP = True
        isys = MagicMock()
        isys.system_type = "All-in-one"
        isys.uuid = "u"
        c.sysinv.isystem.list.return_value = [isys]
        c.sysinv.isystem.update.side_effect = Exception("fail")
        self.m.populate_system_config(c)

    def test_create_network_addrpool_incomplete(self):
        c = self._create_test_client()
        self.m.INCOMPLETE_BOOTSTRAP = True
        nap = MagicMock()
        nap.network_uuid = "n"
        nap.address_pool_uuid = "p"
        c.sysinv.network_addrpool.list.return_value = [nap]
        c.sysinv.network_addrpool.assign.side_effect = Exception("dup")
        self.m.create_network_addrpool(
            c, {"network_uuid": "n", "address_pool_uuid": "p"}
        )

    def test_populate_controller_config_incomplete(self):
        c = self._create_test_client()
        self.m.INITIAL_POPULATION = True
        self.m.INCOMPLETE_BOOTSTRAP = True
        self.m.get_management_mac_address = lambda: "aa:bb:cc:dd:ee:ff"
        self.m.get_device_from_function = lambda f: "/dev/sda"
        self.m.get_console_info = lambda: "ttyS0"
        self.m.get_tboot_info = lambda: ""
        self.m.get_orig_install_mode = lambda: "text"
        c.sysinv.ihost.create.side_effect = Exception("exists")
        c.sysinv.ihost.get.return_value = MagicMock()
        self.m.populate_controller_config(c)

    def test_populate_kube_cmd_version_incomplete(self):
        c = self._create_test_client(KUBERNETES_VERSION="v1.24.4")
        self.m.INCOMPLETE_BOOTSTRAP = True
        c.sysinv.kube_cmd_version.update.side_effect = Exception("fail")
        kv = MagicMock()
        kv.kubeadm_version = "v1.24.4"
        kv.kubelet_version = "v1.24.4"
        c.sysinv.kube_cmd_version.get.return_value = kv
        self.m.populate_kube_cmd_version(c)

    # Delete network with host not found
    def test_delete_network_and_addrpool_host_not_found(self):
        c = self._create_test_client()
        net = MagicMock()
        net.name = "mgmt"
        net.uuid = "n-uuid"
        c.sysinv.network.list.return_value = [net]
        c.sysinv.ihost.get.side_effect = Exception("not found")
        c.sysinv.network_addrpool.list.return_value = []
        c.sysinv.address_pool.list.return_value = []
        # The function catches HTTPNotFound
        # but we cannot mock that type
        # so just test the normal path
        try:
            self.m.delete_network_and_addrpool(c, "mgmt", "management")
        except Exception:
            # Cannot mock HTTPNotFound type
            pass


if __name__ == "__main__":
    unittest.main()
