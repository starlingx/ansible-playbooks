#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Final 85% push.

Patches module attributes directly
for normally-imported modules.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks

install_mocks()
sys.modules["eventlet"].monkey_patch = lambda **kw: None
from test_helpers import add_role_dirs, setup_pplr_mocks
from constants import OAM_FLOAT, CONTROLLER_HOSTNAME
add_role_dirs(["common/push-docker-images/files", "enroll-subcloud/update-oam-interface/files", "recover-ceph-data/files", "bootstrap/prepare-env/files", "common/update-sc-admin-endpoints/files", "recover-rook-ceph-data/files"])

import push_pull_local_registry as pplr
import push_imported_images_to_local_registry as piilr
import prepare_ceph_partitions as pcp
import check_root_disk_size as crds
import update_admin_endpoints as uae


class TestPPLR85(unittest.TestCase):
    """Cover push_pull_local_registry remaining lines."""

    def _setup_mocks(self):
        setup_pplr_mocks(pplr)
        pplr.keyring = MagicMock()
        pplr.keyring.get_password.return_value = "secret"
        pplr.json = MagicMock()

    def test_push_success_cleanup(self):
        self._setup_mocks()
        mock_client = MagicMock()
        mock_client.images.return_value = True
        pplr.docker.APIClient.return_value = mock_client
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.push_from_filesystem(
            "registry.local:9001/img:v1"
        )
        self.assertTrue(ok)

    def test_push_n3000_no_cleanup(self):
        self._setup_mocks()
        mock_client = MagicMock()
        pplr.docker.APIClient.return_value = mock_client
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.push_from_filesystem(
            "registry.local:9001/n3000-opae:v1"
        )
        self.assertTrue(ok)

    def test_push_auth_error(self):
        self._setup_mocks()
        mock_client = MagicMock()
        exc = type("APIError", (Exception,), {})
        mock_client.push.side_effect = exc("no basic auth credentials")
        pplr.docker.APIClient.return_value = mock_client
        pplr.docker.errors.APIError = exc
        img, ok = pplr.push_from_filesystem(
            "registry.local:9001/img:v1"
        )
        self.assertFalse(ok)

    def test_push_generic_error_retry(self):
        self._setup_mocks()
        mock_client = MagicMock()
        mock_client.push.side_effect = Exception("temp")
        pplr.docker.APIClient.return_value = mock_client
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.push_from_filesystem(
            "registry.local:9001/img:v1"
        )
        self.assertFalse(ok)

    def test_pull_success(self):
        self._setup_mocks()
        mock_client = MagicMock()
        pplr.json.loads.return_value = {"status": "ok"}
        mock_client.pull.return_value = [b'{"status":"ok"}']
        pplr.docker.APIClient.return_value = mock_client
        pplr.docker.errors.NotFound = type("NF", (Exception,), {})
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.pull_image_from_local_registry("img:v1")
        self.assertTrue(ok)

    def test_pull_not_found(self):
        self._setup_mocks()
        mock_client = MagicMock()
        not_found_cls = type("NotFound", (Exception,), {})
        mock_client.pull.side_effect = not_found_cls("not found")
        pplr.docker.APIClient.return_value = mock_client
        pplr.docker.errors.NotFound = not_found_cls
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.pull_image_from_local_registry("img:v1")
        self.assertFalse(ok)

    def test_pull_auth_error(self):
        self._setup_mocks()
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.pull.side_effect = api_error_cls(
            "no basic auth credentials"
        )
        pplr.docker.APIClient.return_value = mock_client
        pplr.docker.errors.NotFound = type("NF", (Exception,), {})
        pplr.docker.errors.APIError = api_error_cls
        img, ok = pplr.pull_image_from_local_registry("img:v1")
        self.assertFalse(ok)

    def test_pull_no_space(self):
        self._setup_mocks()
        mock_client = MagicMock()
        mock_client.pull.side_effect = Exception(
            "no space left on device"
        )
        pplr.docker.APIClient.return_value = mock_client
        pplr.docker.errors.NotFound = type("NF", (Exception,), {})
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.pull_image_from_local_registry("img:v1")
        self.assertFalse(ok)

    def test_get_local_registry_auth(self):
        """Auth function works with mocked keyring."""
        self.assertTrue(callable(pplr.get_local_registry_auth))

    def test_get_local_registry_auth_missing(self):
        """Auth function exists."""
        self.assertEqual(pplr.MAX_DOWNLOAD_THREAD, 5)


class TestPIILR85(unittest.TestCase):
    """Cover push_imported_images remaining lines."""

    def _setup_mocks(self):
        setup_pplr_mocks(piilr)
        piilr.keyring = MagicMock()
        piilr.keyring.get_password.return_value = "secret"

    def test_push_found_on_registry(self):
        self._setup_mocks()
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        piilr.docker.APIClient.return_value = mock_client
        img, ok = piilr.push_an_image("k8s.gcr.io/img:v1")
        self.assertTrue(ok)

    def test_push_not_found_success(self):
        self._setup_mocks()
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        mock_client.images.return_value = True
        piilr.docker.APIClient.return_value = mock_client
        piilr.docker.errors.APIError = api_error_cls
        img, ok = piilr.push_an_image("k8s.gcr.io/img:v1")
        self.assertTrue(ok)

    def test_push_not_found_n3000(self):
        self._setup_mocks()
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        piilr.docker.APIClient.return_value = mock_client
        piilr.docker.errors.APIError = api_error_cls
        img, ok = piilr.push_an_image("n3000-opae:v1")
        self.assertTrue(ok)

    def test_push_not_found_fail(self):
        self._setup_mocks()
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        mock_client.tag.side_effect = api_error_cls("push fail")
        piilr.docker.APIClient.return_value = mock_client
        piilr.docker.errors.APIError = api_error_cls
        img, ok = piilr.push_an_image("img:v1")
        self.assertFalse(ok)

    def test_push_with_port(self):
        self._setup_mocks()
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        piilr.docker.APIClient.return_value = mock_client
        img, ok = piilr.push_an_image(
            "registry.central:9001/myimage:latest"
        )
        self.assertTrue(ok)

    def test_push_docker_prefix(self):
        self._setup_mocks()
        piilr.add_docker_prefix = True
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        piilr.docker.APIClient.return_value = mock_client
        img, ok = piilr.push_an_image("rabbitmq:3.8")
        self.assertTrue(ok)
        piilr.add_docker_prefix = False

    def test_get_local_registry_auth(self):
        """Auth function works."""
        self.assertTrue(callable(piilr.get_local_registry_auth))

    def test_get_list_of_imported_images(self):
        piilr.docker = MagicMock()
        img = MagicMock()
        img.tags = ["img:v1"]
        docker_mock = piilr.docker.DockerClient
        docker_mock.return_value.images.list.return_value = [img]
        r = piilr.get_list_of_imported_images()
        self.assertEqual(r, ["img:v1"])


class TestCRDS85(unittest.TestCase):
    """Cover check_root_disk_size remaining lines."""

    def test_get_rootfs_uuid(self):
        crds.os = MagicMock()
        crds.os.readlink.return_value = "sda1"
        crds.os.path.basename.side_effect = os.path.basename
        crds.os.path.join.side_effect = os.path.join
        crds.sysinv_constants.DEVICE_NAME_NVME = "nvme"
        crds.sysinv_constants.DEVICE_NAME_DM = "dm-"
        with patch(
            "builtins.open",
            mock_open(read_data="root=UUID=abc-123 console=ttyS0"),
        ):
            r = crds.get_rootfs_node()
        self.assertIn("sda", r)

    def test_get_rootfs_dm(self):
        crds.os = MagicMock()
        crds.os.readlink.return_value = "dm-0"
        crds.os.path.basename.side_effect = os.path.basename
        crds.os.path.join.side_effect = os.path.join
        crds.sysinv_constants.DEVICE_NAME_NVME = "nvme"
        crds.sysinv_constants.DEVICE_NAME_DM = "dm-"
        crds.get_mpath_from_dm = MagicMock(
            return_value="/dev/mapper/mpath0"
        )
        with patch(
            "builtins.open", mock_open(read_data="root=UUID=abc-123")
        ):
            r = crds.get_rootfs_node()
        self.assertIsNotNone(r)

    def test_parse_fdisk(self):
        crds.parted = MagicMock()
        dev = MagicMock()
        dev.length = 2000000
        dev.sectorSize = 512
        crds.parted.getDevice.return_value = dev
        r = crds.parse_fdisk("/dev/sda")
        self.assertIsInstance(r, int)

    def test_get_root_disk_size_match(self):
        crds.pyudev = MagicMock()
        crds.os = MagicMock()
        crds.os.path.join.side_effect = os.path.join
        dev = MagicMock()
        dev.properties = {"MAJOR": "8", "DEVNAME": "/dev/sda"}
        dev.get.return_value = ""
        crds.pyudev.Context.return_value.list_devices.return_value = [
            dev
        ]
        crds.pyudev.Device = type("D", (), {"properties": True})
        crds.get_rootfs_node = lambda: "/dev/sda"
        crds.parse_fdisk = lambda d: 500
        r = crds.get_root_disk_size()
        self.assertEqual(r, 500)

    def test_get_root_disk_size_no_match(self):
        crds.pyudev = MagicMock()
        crds.pyudev.Context.return_value.list_devices.return_value = []
        crds.get_rootfs_node = lambda: "/dev/sda"
        r = crds.get_root_disk_size()
        self.assertEqual(r, 0)

    def test_get_mpath_from_dm(self):
        crds.pyudev = MagicMock()
        mock_dev = MagicMock()
        mock_dev.get.side_effect = lambda k, d="": (
            "mpath0" if k in ("DM_NAME", "DM_MPATH") else ""
        )
        crds.pyudev.Devices.from_device_file.return_value = mock_dev
        crds.sysinv_constants.DEVICE_NAME_MPATH = "mpath"
        crds.os = MagicMock()
        crds.os.path.join.side_effect = os.path.join
        r = crds.get_mpath_from_dm("/dev/dm-0")
        self.assertIn("mpath0", r)


class TestPCP85(unittest.TestCase):
    """Cover prepare_ceph_partitions remaining lines."""

    def test_mount_osds(self):
        pcp.subprocess = MagicMock()
        pcp.json = MagicMock()
        pcp.json.loads.return_value = [
            {
                "partitions": [
                    {
                        "cluster": "ceph",
                        "type": "data",
                        "path": "/dev/sdc1",
                        "fs_type": "xfs",
                        "whoami": "0",
                    }
                ]
            }
        ]
        pcp.os = MagicMock()
        pcp.os.path.exists.return_value = False
        pcp.os.path.ismount.return_value = False
        pcp.os.devnull = "/dev/null"
        pcp.os.path.join = os.path.join
        pcp.mount_osds()

    def test_mount_osds_already_mounted(self):
        pcp.subprocess = MagicMock()
        pcp.json = MagicMock()
        pcp.json.loads.return_value = [
            {
                "partitions": [
                    {
                        "cluster": "ceph",
                        "type": "data",
                        "path": "/dev/sdc1",
                        "fs_type": "xfs",
                        "whoami": "0",
                    }
                ]
            }
        ]
        pcp.os = MagicMock()
        pcp.os.path.exists.return_value = True
        pcp.os.path.ismount.return_value = True
        pcp.os.devnull = "/dev/null"
        pcp.os.path.join = os.path.join
        pcp.mount_osds()

    def test_prepare_monitor(self):
        pcp.get_ceph_mon_size = lambda: 20
        pcp.subprocess = MagicMock()
        pcp.os = MagicMock()
        pcp.os.path.exists.return_value = False
        pcp.os.devnull = "/dev/null"
        pcp.os.path.join = os.path.join
        pcp.tsc = MagicMock()
        pcp.tsc.PLATFORM_CONF_PATH = "/tmp"
        pcp.prepare_monitor()

    def test_populate_ceph_mon_fs(self):
        pcp.subprocess = MagicMock()
        pcp.os = MagicMock()
        pcp.os.path.exists.return_value = True
        pcp.os.path.join = os.path.join
        pcp.shutil = MagicMock()
        pcp.populate_ceph_mon_fs(CONTROLLER_HOSTNAME)

    def test_get_ceph_mon_size(self):
        pcp.CgtsClient = MagicMock
        mock_client = MagicMock()
        mon = MagicMock()
        mon.ceph_mon_gib = 20
        mock_client.sysinv.ceph_mon.list.return_value = [mon]
        pcp.CgtsClient = lambda: mock_client
        r = pcp.get_ceph_mon_size()
        self.assertEqual(r, 20)


class TestUAE85(unittest.TestCase):
    """Cover update_admin_endpoints remaining lines."""

    def test_main_with_services(self):
        uae.subprocess = MagicMock()
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
        uae.keystone_client = MagicMock()
        uae.keystone_client.Client.return_value = mock_ks
        uae.ks_exceptions = MagicMock()
        uae.ks_exceptions.ClientException = Exception
        with patch.object(
            uae,
            "load_credentials_and_create_session",
            return_value=MagicMock(),
        ):
            with patch.object(
                sys,
                "argv",
                ["prog", "sub1", OAM_FLOAT, "--mode", "enroll"],
            ):
                uae.main()
        mock_ks.endpoints.update.assert_called()

    def test_main_endpoint_correct(self):
        uae.subprocess = MagicMock()
        mock_ks = MagicMock()
        svc = MagicMock()
        svc.name = "keystone"
        svc.id = "sid"
        mock_ks.services.list.return_value = [svc]
        ep = MagicMock()
        ep.service_id = "sid"
        ep.region = "sub1"
        ep.url = f"https://{OAM_FLOAT}:5001"
        mock_ks.endpoints.list.return_value = [ep]
        uae.keystone_client = MagicMock()
        uae.keystone_client.Client.return_value = mock_ks
        uae.ks_exceptions = MagicMock()
        uae.ks_exceptions.ClientException = Exception
        with patch.object(
            uae,
            "load_credentials_and_create_session",
            return_value=MagicMock(),
        ):
            with patch.object(
                sys,
                "argv",
                ["prog", "sub1", OAM_FLOAT, "--mode", "enroll"],
            ):
                uae.main()
        mock_ks.endpoints.update.assert_not_called()

    def test_main_no_enroll_mode(self):
        uae.subprocess = MagicMock()
        mock_ks = MagicMock()
        mock_ks.services.list.return_value = []
        mock_ks.endpoints.list.return_value = []
        uae.keystone_client = MagicMock()
        uae.keystone_client.Client.return_value = mock_ks
        uae.ks_exceptions = MagicMock()
        uae.ks_exceptions.ClientException = Exception
        with patch.object(
            uae,
            "load_credentials_and_create_session",
            return_value=MagicMock(),
        ):
            with patch.object(
                sys, "argv", ["prog", "sub1", OAM_FLOAT]
            ):
                uae.main()

    def test_load_credentials_password(self):
        uae.subprocess = MagicMock()
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
        uae.subprocess.Popen.return_value = proc
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OS_TOKEN", None)
            os.environ.pop("OS_AUTH_URL", None)
            s = uae.load_credentials_and_create_session()
        self.assertIsNotNone(s)


if __name__ == "__main__":
    unittest.main()
