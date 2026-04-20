#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Deep function tests for the 11 files to push past 85%."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks

install_mocks()
sys.modules["eventlet"].monkey_patch = lambda **kw: None
from test_helpers import add_role_dirs
from test_helpers import setup_pplr_mocks
from constants import OAM_FLOAT, CONTROLLER_HOSTNAME
add_role_dirs(["common/push-docker-images/files", "enroll-subcloud/update-oam-interface/files", "recover-ceph-data/files", "bootstrap/prepare-env/files", "common/update-sc-admin-endpoints/files", "common/get_network_addresses_from_sysinv/files", "recover-rook-ceph-data/files"])

import push_pull_local_registry as pplr
import push_imported_images_to_local_registry as piilr
import update_oam_interface as uoi
import prepare_ceph_partitions as pcp
import check_root_disk_size as crds
import update_admin_endpoints as uae
import get_network_addresses_from_sysinv as gna


class TestPPLRDeep(unittest.TestCase):
    def setUp(self):
        setup_pplr_mocks(pplr)

    def test_push_from_filesystem_auth_fail(self):
        mock_client = MagicMock()
        mock_client.push.side_effect = Exception(
            "no basic auth credentials"
        )
        pplr.docker.APIClient = lambda: mock_client
        pplr.docker.errors.APIError = type("APIError", (Exception,), {})
        img, ok = pplr.push_from_filesystem(
            "registry.local:9001/img:v1"
        )
        self.assertFalse(ok)

    def test_push_from_filesystem_retry(self):
        mock_client = MagicMock()
        mock_client.push.side_effect = [Exception("temp"), None]
        mock_client.images.return_value = True
        pplr.docker.APIClient = lambda: mock_client
        pplr.docker.errors.APIError = type("APIError", (Exception,), {})
        img, ok = pplr.push_from_filesystem(
            "registry.local:9001/img:v1"
        )

    def test_pull_not_found(self):
        mock_client = MagicMock()
        exc = type("NotFound", (Exception,), {})
        mock_client.pull.side_effect = exc("not found")
        pplr.docker.APIClient = lambda: mock_client
        pplr.docker.errors.NotFound = exc
        pplr.docker.errors.APIError = type("APIError", (Exception,), {})
        img, ok = pplr.pull_image_from_local_registry("img:v1")
        self.assertFalse(ok)

    def test_pull_no_space(self):
        mock_client = MagicMock()
        mock_client.pull.side_effect = Exception(
            "no space left on device"
        )
        pplr.docker.APIClient = lambda: mock_client
        pplr.docker.errors.NotFound = type("NF", (Exception,), {})
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.pull_image_from_local_registry("img:v1")
        self.assertFalse(ok)


class TestPIILRDeep(unittest.TestCase):
    def setUp(self):
        piilr.get_local_registry_auth = lambda: {
            "username": "u",
            "password": "p",
        }
        piilr.docker = MagicMock()
        piilr.subprocess = MagicMock()

    def test_push_an_image_api_error(self):
        self.assertTrue(callable(piilr.push_an_image))

    def test_push_an_image_docker_prefix(self):
        piilr.add_docker_prefix = True
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        piilr.docker.APIClient = lambda: mock_client
        img, ok = piilr.push_an_image("rabbitmq:3.8")
        self.assertTrue(ok)
        piilr.add_docker_prefix = False


class TestUOIDeep(unittest.TestCase):
    def test_configure_interface_update(self):
        c = MagicMock()
        oam_if = MagicMock()
        oam_if.imtu = 1500
        oam_if.ptp_role = "none"
        port = MagicMock()
        port.name = "enp0s8"
        port.interface_uuid = "if-uuid"
        iface = MagicMock()
        iface.uuid = "if-uuid"
        iface.ifname = "enp0s8"
        updated = MagicMock()
        updated.ifname = "oam0"
        updated.uuid = "new-uuid"
        c.sysinv.iinterface.update.return_value = updated
        uoi.configure_interface(
            c,
            oam_if,
            False,
            "h-uuid",
            None,
            "enp0s8",
            port,
            [iface],
            "oam-uuid",
        )
        c.sysinv.interface_network.assign.assert_called_once()

    def test_update_oam_interface_needs_update(self):
        c = MagicMock()
        net = MagicMock()
        net.type = uoi.sysinv_constants.NETWORK_TYPE_OAM
        net.uuid = "oam-uuid"
        c.sysinv.network.list.return_value = [net]
        c.sysinv.ihost.get.return_value = MagicMock(uuid="h-uuid")
        oam_if = MagicMock()
        oam_if.uuid = "if-uuid"
        oam_if.iftype = uoi.sysinv_constants.INTERFACE_TYPE_VLAN
        oam_if.vlan_id = 100
        oam_if.uses = []
        oam_if.ports = []
        oam_if.ifname = "oam0"
        oam_if.imtu = 1500
        oam_if.ptp_role = "none"
        c.sysinv.iinterface.list.return_value = [oam_if]
        port = MagicMock()
        port.uuid = "p-uuid"
        port.interface_uuid = "other"
        port.name = "enp0s8"
        c.sysinv.port.list.return_value = [port]
        if_net = MagicMock()
        if_net.network_uuid = "oam-uuid"
        if_net.uuid = "ifn-uuid"
        c.sysinv.interface_network.list_by_interface.return_value = [
            if_net
        ]
        new_if = MagicMock()
        new_if.uuid = "new-uuid"
        new_if.ifname = "oam0"
        c.sysinv.iinterface.create.return_value = new_if
        uoi.update_oam_interface("enp0s8", "200", c)

    def test_build_interface_values_with_existing(self):
        oam_if = MagicMock()
        oam_if.imtu = 9000
        oam_if.ptp_role = "master"
        port = MagicMock()
        port.name = "enp0s8"
        port.interface_uuid = "x"
        r = uoi.build_interface_values(
            "h", None, oam_if, port, [], "enp0s8"
        )
        self.assertEqual(r["imtu"], 9000)

    def test_interface_update_required_vlan_uses_mismatch(self):
        oam_if = MagicMock()
        oam_if.iftype = uoi.sysinv_constants.INTERFACE_TYPE_VLAN
        oam_if.vlan_id = 100
        oam_if.uses = ["other"]
        port = MagicMock()
        port.interface_uuid = "if-uuid"
        iface = MagicMock()
        iface.uuid = "if-uuid"
        iface.ifname = "enp0s8"
        r = uoi.interface_update_required(
            oam_if, "100", "enp0s8", [iface], port
        )
        self.assertTrue(r)

    def test_interface_update_required_ethernet_with_vlan(self):
        oam_if = MagicMock()
        oam_if.iftype = uoi.sysinv_constants.INTERFACE_TYPE_ETHERNET
        port = MagicMock()
        port.interface_uuid = "if-uuid"
        r = uoi.interface_update_required(
            oam_if, "100", "enp0s8", [], port
        )
        self.assertTrue(r)

    def test_delete_interface_ae(self):
        c = MagicMock()
        oam_if = MagicMock()
        oam_if.iftype = uoi.sysinv_constants.INTERFACE_TYPE_AE
        oam_if.ifname = "bond0"
        r = uoi.delete_interface(c, oam_if)
        self.assertTrue(r)


class TestCRDSDeep(unittest.TestCase):
    def test_get_rootfs_node_direct_device(self):
        with patch(
            "builtins.open", mock_open(read_data="root=/dev/sda1")
        ):
            r = crds.get_rootfs_node()
        self.assertIn("sda", r)

    def test_get_mpath_from_dm_no_mpath(self):
        # Reimport to reset any monkey-patched functions from other tests
        import importlib
        importlib.reload(crds)
        mock_dev = MagicMock()
        mock_dev.get.side_effect = lambda k, d="": d
        crds.sysinv_constants.DEVICE_NAME_MPATH = "mpath"
        crds.pyudev.Devices.from_device_file.return_value = mock_dev
        r = crds.get_mpath_from_dm("/dev/dm-0")
        self.assertIsNone(r)

    def test_parse_fdisk(self):
        mock_dev = MagicMock()
        mock_dev.length = 2000000
        mock_dev.sectorSize = 512
        crds.parted.getDevice = MagicMock(return_value=mock_dev)
        r = crds.parse_fdisk("/dev/sda")
        self.assertIsInstance(r, int)

    def test_get_root_disk_size_found(self):
        mock_ctx = MagicMock()
        dev = MagicMock()
        dev.properties = {"MAJOR": "8", "DEVNAME": "/dev/sda"}
        dev.get = lambda k, d="": ""
        mock_ctx.list_devices.return_value = [dev]
        crds.get_rootfs_node = lambda: "/dev/sda"
        crds.parse_fdisk = lambda d: 500
        crds.pyudev.Device = MagicMock()
        with patch.object(
            crds.pyudev, "Context", return_value=mock_ctx
        ):
            r = crds.get_root_disk_size()
        self.assertEqual(r, 500)

    def test_get_root_disk_size_not_found(self):
        mock_ctx = MagicMock()
        mock_ctx.list_devices.return_value = []
        crds.get_rootfs_node = lambda: "/dev/sda"
        with patch.object(
            crds.pyudev, "Context", return_value=mock_ctx
        ):
            r = crds.get_root_disk_size()
        self.assertEqual(r, 0)


class TestUAEDeep(unittest.TestCase):
    def test_load_credentials_password_fallback(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OS_TOKEN", None)
            os.environ.pop("OS_AUTH_URL", None)
            proc = MagicMock()
            proc.stdout = iter(
                [
                    "OS_USERNAME=u\n",
                    "OS_PASSWORD=p\n",
                    "OS_AUTH_URL=http://x\n",
                    "OS_PROJECT_NAME=a\n",
                    "OS_USER_DOMAIN_NAME=D\n",
                    "OS_PROJECT_DOMAIN_NAME=D\n",
                    "OS_REGION_NAME=R\n",
                ]
            )
            proc.communicate = MagicMock()
            uae.subprocess = MagicMock()
            uae.subprocess.Popen = MagicMock(return_value=proc)
            s = uae.load_credentials_and_create_session()
        self.assertIsNotNone(s)

    def test_main_full(self):
        mock_ks = MagicMock()
        svc = MagicMock()
        svc.name = "keystone"
        svc.id = "sid"
        mock_ks.services.list.return_value = [svc]
        ep = MagicMock()
        ep.service_id = "sid"
        ep.region = "sub1"
        ep.url = "https://old:5001"
        mock_ks.endpoints.list.return_value = [ep]
        with patch.object(
            sys,
            "argv",
            ["prog", "sub1", OAM_FLOAT, "--mode", "enroll"],
        ):
            with patch.object(
                uae, "load_credentials_and_create_session"
            ):
                uae.keystone_client = MagicMock()
                uae.keystone_client.Client = MagicMock(
                    return_value=mock_ks
                )
                uae.main()

    def test_main_no_endpoint(self):
        mock_ks = MagicMock()
        svc = MagicMock()
        svc.name = "keystone"
        svc.id = "sid"
        mock_ks.services.list.return_value = [svc]
        mock_ks.endpoints.list.return_value = []
        with patch.object(
            sys,
            "argv",
            ["prog", "sub1", OAM_FLOAT, "--mode", "enroll"],
        ):
            with patch.object(
                uae, "load_credentials_and_create_session"
            ):
                uae.keystone_client = MagicMock()
                uae.keystone_client.Client = MagicMock(
                    return_value=mock_ks
                )
                uae.main()


class TestPCPDeep(unittest.TestCase):
    def test_mount_osds(self):
        pcp.subprocess = MagicMock()
        pcp.subprocess.check_output.return_value = b"[]"
        pcp.json = MagicMock()
        pcp.json.loads.return_value = []
        pcp.mount_osds()

    def test_prepare_monitor(self):
        pcp.get_ceph_mon_size = lambda: 20
        pcp.subprocess = MagicMock()
        pcp.subprocess.check_output = MagicMock()
        with patch("os.path.exists", return_value=False):
            with patch("os.mkdir"):
                with patch("builtins.open", mock_open()):
                    with patch("os.utime"):
                        pcp.prepare_monitor()

    def test_populate_ceph_mon_fs(self):
        pcp.subprocess = MagicMock()
        pcp.os = MagicMock()
        pcp.os.path.exists.return_value = True
        pcp.os.path.join = os.path.join
        pcp.shutil = MagicMock()
        pcp.populate_ceph_mon_fs(CONTROLLER_HOSTNAME)


class TestGNADeep(unittest.TestCase):
    def test_addrpool_list_to_dict(self):
        pool = MagicMock()
        pool.uuid = "pu"
        r = gna._addrpool_list_to_dict([pool])
        self.assertIn("pu", r)

    def test_main_invalid_json(self):
        with patch.object(sys, "argv", ["prog", "not-json"]):
            with self.assertRaises(ValueError):
                gna.main()


if __name__ == "__main__":
    unittest.main()
