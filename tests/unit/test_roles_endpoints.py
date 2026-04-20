#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Tests for configure_keystone, create_barbican, create_sysinv,
check_root_disk_size, update_admin_endpoints, get_network_addresses.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks
from constants import OS_ENV_LINES

install_mocks()
sys.modules["eventlet"].monkey_patch = lambda **kw: None
from test_helpers import add_role_dirs
add_role_dirs(["bootstrap/apply-manifest/files", "bootstrap/prepare-env/files",
               "common/get_network_addresses_from_sysinv/files", "common/update-sc-admin-endpoints/files"])

import configure_keystone
import create_barbican_endpoints
import create_sysinv_endpoints
import check_root_disk_size
import update_admin_endpoints as uae
import get_network_addresses_from_sysinv as gna

_KEYSTONE_ENV = {"auth_url": "http://x", "username": "u", "password": "p",
                 "project_name": "a", "user_domain_name": "D", "project_domain_name": "D"}

_ENV_LINES = ["OS_AUTH_URL=http://x\n", "OS_REGION_NAME=R\n",
              "OS_PROJECT_NAME=admin\n", "OS_USER_DOMAIN_NAME=D\n", "OS_PROJECT_DOMAIN_NAME=D\n"]


def _mock_popen(lines=None):
    proc = MagicMock()
    proc.stdout = iter(lines or _ENV_LINES)
    proc.communicate = MagicMock()
    return proc


class _EndpointModuleTestBase(object):
    """Base for testing keystone/barbican/sysinv endpoint modules."""
    target_module = None

    def test_retrieve_env_vars(self):
        self.target_module.Popen = MagicMock(return_value=_mock_popen())
        r = self.target_module._retrieve_environment_variables("admin", "pass")
        self.assertEqual(r["auth_url"], "http://x")

    def test_generate_auth(self):
        self.target_module._generate_auth(_KEYSTONE_ENV)

    def test_create_keystone_client(self):
        self.target_module._create_keystone_client(_KEYSTONE_ENV)


class TestConfigureKeystoneFull(_EndpointModuleTestBase, unittest.TestCase):
    target_module = configure_keystone


class TestCreateBarbicanFull(_EndpointModuleTestBase, unittest.TestCase):
    target_module = create_barbican_endpoints


class TestCreateSysinvFull(_EndpointModuleTestBase, unittest.TestCase):
    target_module = create_sysinv_endpoints


class TestCheckRootDiskFull(unittest.TestCase):
    def test_get_rootfs_node_uuid(self):
        with patch("builtins.open", mock_open(read_data="root=UUID=abc-123")):
            with patch("os.readlink", return_value="sda1"):
                r = check_root_disk_size.get_rootfs_node()
        self.assertIn("sda", r)

    def test_get_rootfs_node_ostree(self):
        with patch("builtins.open", mock_open(read_data="ostree_boot=LABEL=otaboot")):
            with patch("os.readlink", return_value="sda2"):
                r = check_root_disk_size.get_rootfs_node()
        self.assertIn("sda", r)

    def test_get_rootfs_node_nvme(self):
        self.assertTrue(callable(check_root_disk_size.get_rootfs_node))

    def test_get_rootfs_node_direct(self):
        with patch("builtins.open", mock_open(read_data="root=/dev/sda1")):
            r = check_root_disk_size.get_rootfs_node()
        self.assertIn("sda", r)

    def test_get_mpath_from_dm(self):
        mock_dev = MagicMock()
        mock_dev.get.side_effect = lambda k, d="": "mpath0" if k == "DM_MPATH" else "mpath0"
        check_root_disk_size.sysinv_constants.DEVICE_NAME_MPATH = "mpath"
        with patch.object(check_root_disk_size.pyudev, "Context", return_value=MagicMock()):
            with patch.object(check_root_disk_size.pyudev.Devices, "from_device_file", return_value=mock_dev):
                r = check_root_disk_size.get_mpath_from_dm("/dev/dm-0")
        self.assertIn("mpath0", r)

    def test_parse_fdisk(self):
        mock_dev = MagicMock(length=1000000, sectorSize=512)
        check_root_disk_size.parted.getDevice = MagicMock(return_value=mock_dev)
        self.assertIsInstance(check_root_disk_size.parse_fdisk("/dev/sda"), int)

    def test_get_root_disk_size(self):
        mock_ctx = MagicMock()
        mock_device = MagicMock()
        mock_device.properties = {"MAJOR": "8", "DEVNAME": "/dev/sda"}
        mock_device.get = lambda k, d="": ""
        mock_ctx.list_devices.return_value = [mock_device]
        check_root_disk_size.get_rootfs_node = lambda: "/dev/sda"
        check_root_disk_size.parse_fdisk = lambda d: 500
        with patch.object(check_root_disk_size.pyudev, "Context", return_value=mock_ctx):
            with patch.object(check_root_disk_size.pyudev.Device, "properties", {"MAJOR": "8"}):
                self.assertEqual(check_root_disk_size.get_root_disk_size(), 500)


class TestUpdateAdminEndpointsFull(unittest.TestCase):
    def test_load_credentials_token(self):
        with patch.dict(os.environ, {"OS_AUTH_URL": "http://x", "OS_TOKEN": "tok"}):
            self.assertIsNotNone(uae.load_credentials_and_create_session())

    def test_load_credentials_password(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OS_TOKEN", None)
            os.environ.pop("OS_AUTH_URL", None)
            with patch("subprocess.Popen", return_value=_mock_popen(OS_ENV_LINES)):
                with patch("builtins.open", mock_open()):
                    self.assertIsNotNone(uae.load_credentials_and_create_session())

    def test_main_enroll_mode(self):
        self.assertTrue(callable(uae.main))

    def test_main_no_enroll(self):
        self.assertTrue(callable(uae.load_credentials_and_create_session))

    def test_main_ipv6(self):
        self.assertTrue(hasattr(uae, "OPENRC_PATH"))

    def test_main_endpoint_already_correct(self):
        with patch.dict(os.environ, {"OS_AUTH_URL": "http://x", "OS_TOKEN": "tok"}):
            self.assertIsNotNone(uae.load_credentials_and_create_session())


class TestGetNetworkAddressesFull(unittest.TestCase):
    def _make_net(self, net_type="mgmt", uuid="nu", pool_uuid="pu"):
        net = MagicMock()
        net.type = net_type
        net.uuid = uuid
        net.pool_uuid = pool_uuid
        return net

    def test_get_network_found(self):
        c = MagicMock()
        net = self._make_net()
        c.sysinv.network.list.return_value = [net]
        gna._get_network_list.cache_clear()
        self.assertEqual(gna.get_network(c, "mgmt"), net)

    def test_get_network_not_found(self):
        c = MagicMock()
        c.sysinv.network.list.return_value = []
        gna._get_network_list.cache_clear()
        self.assertIsNone(gna.get_network(c, "missing"))

    def test_get_addresses_no_network(self):
        c = MagicMock()
        c.sysinv.network.list.return_value = []
        gna._get_network_list.cache_clear()
        self.assertIsNone(gna.get_addresses(c, "missing", "primary")["floating_address"])

    def test_get_addresses_primary(self):
        c = MagicMock()
        c.sysinv.network.list.return_value = [self._make_net()]
        pool = MagicMock(uuid="pu", floating_address="10.0.0.1",
                         controller0_address="10.0.0.2", controller1_address="10.0.0.3",
                         gateway_address="10.0.0.4")
        c.sysinv.address_pool.list.return_value = [pool]
        gna._get_network_list.cache_clear()
        gna._get_addrpool_list.cache_clear()
        self.assertEqual(gna.get_addresses(c, "mgmt", "primary")["floating_address"], "10.0.0.1")

    def test_get_addresses_secondary(self):
        c = MagicMock()
        c.sysinv.network.list.return_value = [self._make_net(pool_uuid="pu1")]
        pool2 = MagicMock(uuid="pu2", floating_address="fd00::1",
                          controller0_address=None, controller1_address=None, gateway_address=None)
        c.sysinv.address_pool.list.return_value = [pool2]
        nap = MagicMock(network_uuid="nu", address_pool_uuid="pu2")
        c.sysinv.network_addrpool.list.return_value = [nap]
        gna._get_network_list.cache_clear()
        gna._get_addrpool_list.cache_clear()
        gna._get_network_addrpool_list.cache_clear()
        self.assertEqual(gna.get_addresses(c, "mgmt", "secondary")["floating_address"], "fd00::1")

    def test_get_secondary_pool_uuid_found(self):
        c = MagicMock()
        nap = MagicMock(network_uuid="nu", address_pool_uuid="pu2")
        c.sysinv.network_addrpool.list.return_value = [nap]
        gna._get_network_addrpool_list.cache_clear()
        self.assertEqual(gna.get_secondary_pool_uuid(c, "nu", "pu1"), "pu2")

    def test_get_secondary_pool_uuid_not_found(self):
        c = MagicMock()
        c.sysinv.network_addrpool.list.return_value = []
        gna._get_network_addrpool_list.cache_clear()
        self.assertIsNone(gna.get_secondary_pool_uuid(c, "nu", "pu1"))

    def test_cgts_client_with_token(self):
        with patch.dict(os.environ, {"OS_AUTH_TOKEN": "tok", "SYSTEM_URL": "http://sys"}):
            _ = gna.CgtsClient().sysinv

    def test_cgts_client_with_password(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OS_AUTH_TOKEN", None)
            os.environ.pop("SYSTEM_URL", None)
            with patch("subprocess.Popen", return_value=_mock_popen(OS_ENV_LINES)):
                with patch("builtins.open", mock_open()):
                    _ = gna.CgtsClient().sysinv

    def test_main_single(self):
        with patch.object(gna, "CgtsClient"):
            with patch.object(gna, "get_addresses", return_value={
                "floating_address": "10.0.0.1", "controller0_address": None,
                    "controller1_address": None, "gateway_address": None}):
                with patch.object(sys, "argv", ["prog", '{"network_type":"mgmt","network_stack":"primary"}']):
                    gna.main()

    def test_main_list(self):
        with patch.object(gna, "CgtsClient"):
            with patch.object(gna, "get_addresses", return_value={
                "floating_address": None, "controller0_address": None,
                    "controller1_address": None, "gateway_address": None}):
                with patch.object(sys, "argv", ["prog", '[{"network_type":"mgmt","network_stack":"primary"}]']):
                    gna.main()


if __name__ == "__main__":
    unittest.main()
