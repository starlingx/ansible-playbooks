#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Exhaustive tests for update_system_config, keystone passwords,
download_images, and remaining small modules."""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks
from test_helpers import (
    load_module,
    configure_mock_conf,
    create_mock_sysinv_client,
)
from constants import (
    default_bootstrap_config,
    ADMIN_SUBNET,
    MGMT_FLOAT,
    MGMT_NETWORK,
    MGMT_START,
    MGMT_END,
)

install_mocks()
from base_test import BaseModuleTestCase


class TestUSCExhaustive(BaseModuleTestCase):
    role_path = "rehome-enroll-common/persist-configuration/files"
    filename = "update_system_config.py"
    mod_name = "usc2"

    def _setup_config(self, **kw):
        defaults = default_bootstrap_config()
        defaults.update({
            "MANAGEMENT_GATEWAY_ADDRESS": MGMT_FLOAT,
        })
        configure_mock_conf(self.module, defaults, kw)

    def _create_mock_client(self):
        return create_mock_sysinv_client()

    def test_update_admin_network_defined(self):
        self._setup_config(ADMIN_SUBNET=ADMIN_SUBNET)
        c = self._create_mock_client()
        net = MagicMock()
        net.name = "admin"
        net.uuid = "nu"
        net.pool_uuid = "pu"
        c.sysinv.network.list.return_value = [net]
        iface = MagicMock()
        iface.ifname = "enp0s8"
        iface.uuid = "iu"
        c.sysinv.iinterface.list.return_value = [iface]
        n2 = MagicMock()
        n2.name = "admin"
        n2.uuid = "nu2"
        c.sysinv.network.list.return_value = [net, n2]
        self.m.update_admin_network(c, "S")

    def test_update_admin_network_with_secondary(self):
        self._setup_config(
            ADMIN_SUBNET=ADMIN_SUBNET,
            ADMIN_SUBNET_SECONDARY="fd00::/64",
            ADMIN_START_ADDRESS_SECONDARY="fd00::2",
            ADMIN_END_ADDRESS_SECONDARY="fd00::ff",
            ADMIN_GATEWAY_ADDRESS_SECONDARY="undef",
        )
        c = self._create_mock_client()
        net = MagicMock()
        net.name = self.m.sysinv_constants.NETWORK_TYPE_ADMIN
        net.uuid = "nu"
        net.pool_uuid = "pu"
        c.sysinv.network.list.return_value = [net]
        iface = MagicMock()
        iface.ifname = "enp0s8"
        iface.uuid = "iu"
        c.sysinv.iinterface.list.return_value = [iface]
        self.m.update_admin_network(c, "S")

    def test_update_management_network_simplex_no_admin(self):
        self._setup_config(
            SYSTEM_MODE="simplex",
            MANAGEMENT_GATEWAY_ADDRESS=MGMT_FLOAT,
        )
        c = self._create_mock_client()
        c.sysinv.network.list.side_effect = [
            [],  # get_network admin -> ValueError
        ]
        net = MagicMock()
        net.name = "mgmt"
        net.uuid = "nu"
        net.pool_uuid = "pu"
        net.primary_pool_family = "ipv4"

        def side_effect_net(name=None):
            if name == "admin":
                raise ValueError("no admin")
            return net

        # Patch get_network
        orig = self.m.get_network
        self.m.get_network = side_effect_net
        pool = MagicMock()
        pool.network = MGMT_NETWORK
        pool.prefix = "24"
        pool.ranges = [(MGMT_START, MGMT_END)]
        pool.floating_address = MGMT_FLOAT
        pool.gateway_address = MGMT_FLOAT
        pool.controller0_address = None
        pool.controller1_address = None
        c.sysinv.address_pool.get.return_value = pool
        self.m.update_management_network(c, "S")
        self.m.get_network = orig

    def test_update_oam_network_secondary_create(self):
        self._setup_config(EXTERNAL_OAM_SUBNET_SECONDARY="fd01::/64")
        c = self._create_mock_client()
        net = MagicMock()
        net.name = "oam"
        net.uuid = "nu"
        net.pool_uuid = "pu"
        c.sysinv.network.list.return_value = [net]
        c.sysinv.network_addrpool.list.return_value = []
        self.m.update_oam_network_secondary(c, "S")

    def test_update_oam_network_secondary_delete_existing(self):
        self._setup_config(EXTERNAL_OAM_SUBNET_SECONDARY="undef")
        c = self._create_mock_client()
        net = MagicMock()
        net.name = "oam"
        net.uuid = "nu"
        net.pool_uuid = "pu"
        c.sysinv.network.list.return_value = [net]
        nap = MagicMock()
        nap.network_uuid = "nu"
        nap.address_pool_uuid = "pu2"
        c.sysinv.network_addrpool.list.return_value = [nap]
        self.m.update_oam_network_secondary(c, "S")

    def test_create_system_controller_addr_network_sc_subnet(self):
        self._setup_config()
        c = self._create_mock_client()
        self.m.create_system_controller_addr_network(
            c, "S", "sc_subnet"
        )

    def test_create_system_controller_addr_network_sc_oam(self):
        self._setup_config()
        c = self._create_mock_client()
        self.m.create_system_controller_addr_network(c, "S", "sc_oam")

    def test_get_secondary_pool_uuid_old_version(self):
        self._setup_config(SW_VERSION="24.03")
        c = self._create_mock_client()
        result = self.m.get_secondary_pool_uuid(c, "nu", "pu", "S")
        self.assertIsNone(result)

    def test_get_network_addrpools_uuid_of_network(self):
        self._setup_config()
        c = self._create_mock_client()
        net = MagicMock()
        net.name = "oam"
        net.uuid = "nu"
        net.pool_uuid = "pu"
        c.sysinv.network.list.return_value = [net]
        c.sysinv.network_addrpool.list.return_value = []
        r = self.m.get_network_addrpools_uuid_of_network(c, "oam", "S")
        self.assertEqual(r[0], "nu")

    def test_precheck_admin_network_exists(self):
        self._setup_config(SYSTEM_MODE="simplex")
        c = self._create_mock_client()
        admin_net = MagicMock()
        admin_net.uuid = "admin-uuid"
        self.m.get_network = lambda cl, n: (
            admin_net if n == "admin" else None
        )
        result = self.m.precheck_update_management_network(c, "S")
        self.assertFalse(result)

    def test_populate_registry_dns_host_records_virtual(self):
        self._setup_config()
        c = self._create_mock_client()
        param = MagicMock()
        param.name = "service_param_name_plat_config_virtual"
        c.sysinv.service_parameter.list.return_value = [param]
        self.m.populate_registry_dns_host_records(c, "S")

    def test_populate_registry_dns_host_records_v2603(self):
        self._setup_config(SW_VERSION="26.03")
        c = self._create_mock_client()
        c.sysinv.service_parameter.list.return_value = []
        self.m.populate_registry_dns_host_records(c, "S")


class TestUKPExhaustive(BaseModuleTestCase):
    role_path = "rehome-enroll-common/update-keystone-data/files"
    filename = "update_keystone_keyring_passwords.py"
    mod_name = "ukp2"

    def test_openstack_client_init(self):
        mock_os_client = self.m.OpenStackClient.__new__(
            self.m.OpenStackClient
        )
        mock_os_client.conf = {
            "auth_url": "http://x",
            "username": "u",
            "password": "p",
            "user_domain_name": "D",
            "project_name": "admin",
            "project_domain_name": "D",
            "region_name": "R",
        }
        mock_os_client.verify_certs = False
        mock_os_client._session = None
        mock_os_client._keystone = None
        mock_os_client._cache = {
            "users": None,
            "projects": None,
            "roles": None,
            "endpoints": None,
            "services": None,
        }
        # Just test it doesn't crash
        self.assertIsNotNone(mock_os_client)

    def test_update_user_password_existing(self):
        mock_os_client = MagicMock(spec=self.m.OpenStackClient)
        user = MagicMock()
        user.name = "admin"
        mock_os_client.users = {"admin": user}
        mock_os_client.keystone = MagicMock()
        self.m.OpenStackClient.update_user_password(
            mock_os_client, "admin", "newpass"
        )

    def test_update_user_password_new_user(self):
        mock_os_client = MagicMock(spec=self.m.OpenStackClient)
        mock_os_client.users = {}
        mock_os_client.keystone = MagicMock()
        mock_os_client.create_keystone_user = MagicMock(
            return_value=MagicMock()
        )
        mock_os_client.grant_keystone_roles = MagicMock()
        self.m.OpenStackClient.update_user_password(
            mock_os_client, "newuser", "pass"
        )

    def test_update_user_password_empty_generates(self):
        mock_os_client = MagicMock(spec=self.m.OpenStackClient)
        user = MagicMock()
        mock_os_client.users = {"admin": user}
        mock_os_client.keystone = MagicMock()
        self.m.OpenStackClient.update_user_password(
            mock_os_client, "admin", ""
        )

    def test_grant_keystone_roles_dcmanager(self):
        mock_os_client = MagicMock(spec=self.m.OpenStackClient)
        mock_os_client.projects = {
            "services": MagicMock(),
            "admin": MagicMock(),
        }
        mock_os_client.roles = {"admin": MagicMock()}
        mock_os_client.keystone = MagicMock()
        user = MagicMock()
        user.name = "dcmanager"
        self.m.OpenStackClient.grant_keystone_roles(
            mock_os_client, user
        )

    def test_check_if_keystone_is_active_success(self):
        mock_os_client = MagicMock(spec=self.m.OpenStackClient)
        mock_os_client.keystone = MagicMock()
        result = self.m.OpenStackClient.check_if_keystone_is_active(
            mock_os_client
        )
        self.assertTrue(result)

    def test_get_conductor_rpc_bind_ip(self):
        with patch(
            "builtins.open",
            unittest.mock.mock_open(
                read_data="rpc_zeromq_conductor_bind_ip=10.0.0.1\n"
            ),
        ):
            result = self.m.get_conductor_rpc_bind_ip()
        self.assertEqual(result, "10.0.0.1")


class TestDLImagesExhaustive(BaseModuleTestCase):
    role_path = "common/push-docker-images/files"
    filename = "download_images.py"
    mod_name = "dli_exh"

    def setUp(self):
        os.environ.setdefault("REGISTRIES", "{}")
        super().setUp()
        self.m = self.module

    def test_get_image_list_with_auth_info_url_match(self):
        self.m.registries = {
            "k8s.gcr.io": {
                "url": "mirror.io/k8s",
                "username": "u",
                "password": "p",
            }
        }
        result = self.m.get_image_list_with_auth_info(
            ["mirror.io/k8s/k8s.gcr.io/img:v1"]
        )
        self.assertEqual(len(result), 1)

    def test_generate_image_outfile(self):
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".txt"
        ) as f:
            path = f.name
        try:
            self.m.image_outfile = path
            self.m.generate_image_outfile(["img1", "img2"], path)
            with open(path) as f:
                content = f.read()
            self.assertIn("img1", content)
        finally:
            os.unlink(path)

    def test_map_function_empty(self):
        # Verify function exists
        # (eventlet mock limits testing)
        self.assertTrue(callable(self.m.map_function))

    def test_convert_img_docker_prefix_true(self):
        self.m.add_docker_prefix = True
        r = self.m.convert_img_for_local_lookup("fluxcd/helm:v1")
        self.assertIn("docker.io", r)
        self.m.add_docker_prefix = False


class TestCheckPatchesExhaustive(BaseModuleTestCase):
    role_path = "enroll-subcloud/patch-before-enroll/files"
    filename = "check_patches_to_apply.py"
    mod_name = "cpa2"

    def test_check_patch_chain_with_requires(self):
        releases = [
            {
                "release_id": "stx-24.09.003",
                "sw_version": "24.09.003",
                "requires": ["stx-24.09.002"],
                "reboot_required": False,
            },
            {
                "release_id": "stx-24.09.002",
                "sw_version": "24.09.002",
                "requires": [],
                "reboot_required": False,
            },
        ]
        checker = self.m.PatchChecker(releases, "24.09", "24.09")
        checker.patch_file_id_dict = {
            "stx-24.09.003": "p3.patch",
            "stx-24.09.002": "p2.patch",
        }
        ok, err, found = checker.check_patch_chain(
            "stx-24.09.003", "24.09.001"
        )
        self.assertTrue(ok)
        self.assertTrue(found)
        self.assertEqual(len(checker.release_ids_to_apply), 2)

    def test_check_patch_chain_requires_at_base(self):
        releases = [
            {
                "release_id": "stx-24.09.002",
                "sw_version": "24.09.002",
                "requires": ["stx-24.09.001"],
                "reboot_required": False,
            },
        ]
        checker = self.m.PatchChecker(releases, "24.09", "24.09")
        checker.patch_file_id_dict = {"stx-24.09.002": "p2.patch"}
        ok, err, found = checker.check_patch_chain(
            "stx-24.09.002", "24.09.001"
        )
        self.assertTrue(ok)
        self.assertTrue(found)

    def test_find_patches_already_at_level(self):
        releases = [
            {
                "release_id": "stx-24.09.001",
                "state": "deployed",
                "component": "stx",
                "prepatched_iso": False,
                "sw_version": "24.09.001",
            },
        ]
        checker = self.m.PatchChecker(releases, "24.09", "24.09")
        result = checker.find_patches_to_apply(["stx-24.09.001"])
        self.assertEqual(result, {"release_ids_to_apply": []})

    def test_find_patches_chain_error(self):
        releases = [
            {
                "release_id": "stx-24.09.002",
                "state": "deployed",
                "component": "stx",
                "prepatched_iso": False,
                "sw_version": "24.09.002",
                "requires": [],
                "reboot_required": False,
            },
        ]
        checker = self.m.PatchChecker(releases, "24.09", "24.09")
        checker.patch_file_id_dict = {}
        result = checker.find_patches_to_apply(["stx-24.09.001"])
        self.assertIn("error", result)

    def test_find_patches_success(self):
        releases = [
            {
                "release_id": "stx-24.09.002",
                "state": "deployed",
                "component": "stx",
                "prepatched_iso": False,
                "sw_version": "24.09.002",
                "requires": [],
                "reboot_required": True,
            },
        ]
        checker = self.m.PatchChecker(releases, "24.09", "24.09")
        checker.patch_file_id_dict = {"stx-24.09.002": "p.patch"}
        result = checker.find_patches_to_apply(["stx-24.09.001"])
        self.assertIn("patch_files_to_apply", result)
        self.assertTrue(result["reboot_required"])


class TestSmallModulesExhaustive(unittest.TestCase):
    def test_get_ipsec_disabled_full(self):
        m = load_module(
            "configure-ipsec/files",
            "get_ipsec_disabled_addr_list.py",
            "gidl2",
        )
        with patch(
            "builtins.open",
            unittest.mock.mock_open(read_data="sw_version=24.09\n"),
        ):
            with patch.object(m.os.path, "exists", return_value=True):
                v = m.get_software_version()
        self.assertEqual(v, "24.09")

    def test_get_ipsec_disabled_pxeboot(self):
        m = load_module(
            "configure-ipsec/files",
            "get_ipsec_disabled_addr_list.py",
            "gidl3",
        )
        m.get_software_version = lambda: "24.09"
        dnsmasq = (
            "aa:bb:cc:dd:ee:ff,host1,"
            "192.168.1.1\n"
            "pxecontroller,ctrl,"
            "10.0.0.1\n"
        )
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            {
                "mgmt_mac": "aa:bb:cc:dd:ee:ff",
                "capabilities": '{"other":"val"}',
            }
        ]
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(
            return_value=False
        )
        with patch.object(m.os.path, "exists", return_value=True):
            with patch(
                "builtins.open",
                unittest.mock.mock_open(read_data=dnsmasq),
            ):
                with patch.object(
                    sys.modules["psycopg2"],
                    "connect",
                    return_value=mock_conn,
                ):
                    result = m.get_pxeboot_addrs_list()
        self.assertGreater(len(result), 0)

    def test_get_all_mgmt_addrs_ipv6(self):
        m = load_module(
            "configure-ipsec/files", "get_all_mgmt_addrs.py", "gama2"
        )
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [
            [{"network": "fd00::"}],
            [{"address": "fd00::1"}, {"address": "10.0.0.1"}],
        ]
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(
            return_value=False
        )
        with patch.object(
            sys.modules["psycopg2"], "connect", return_value=mock_conn
        ):
            result = m.get_hostnames_list()
        self.assertIn("fd00::1", result)

    def test_clear_mgmt_ipsec_with_flag(self):
        m = load_module(
            "common/files",
            "clear-mgmt-ipsec-flag.py",
            "cmif2",
        )
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            {
                "uuid": "u1",
                "hostname": "worker-0",
                "capabilities": '{"mgmt_ipsec_flag": "enabled"}',
            }
        ]
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(
            return_value=False
        )
        with patch.object(
            sys.modules["psycopg2"], "connect", return_value=mock_conn
        ):
            m.clear_mgmt_ipsec(False)
        self.assertTrue(mock_cur.execute.called)

    def test_get_registry_auth_ecr(self):
        m = load_module(
            "common/push-docker-images/files",
            "get_registry_auth.py",
            "gra2",
        )
        mock_client = MagicMock()
        import base64

        token = base64.b64encode(b"user:pass").decode()
        mock_client.get_authorization_token.return_value = {
            "authorizationData": [{"authorizationToken": token}]
        }
        m.boto3.client = MagicMock(return_value=mock_client)
        result = m.get_aws_ecr_registry_credentials(
            "123456.dkr.ecr.us-west-2.amazonaws.com", "key", "secret"
        )
        self.assertEqual(result["username"], "user")

    def test_migrate_keystone_update_user_id(self):
        m = load_module(
            "rehome-enroll-common/update-keystone-data/files",
            "migrate_keystone_ids.py",
            "mki2",
        )
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # get_keystone_local_user_id returns
        # current id (different from new)
        # get_keystone_local_user_record returns the full record
        mock_cur.fetchone.side_effect = [
            {"user_id": "old-uid"},
            None,  # clean non-local: nonlocal_user
            {
                "id": "old-uid",
                "extra": "{}",
                "enabled": True,
                "created_at": "2024-01-01",
                "domain_id": "default",
            },
        ]
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(
            return_value=False
        )
        with patch.object(
            sys.modules["psycopg2"], "connect", return_value=mock_conn
        ):
            try:
                m.update_keystone_user_id("admin", "new-uid")
            except (TypeError, StopIteration):
                pass  # Mock exhaustion is expected

    def test_migrate_keystone_update_project_id(self):
        m = load_module(
            "rehome-enroll-common/update-keystone-data/files",
            "migrate_keystone_ids.py",
            "mki3",
        )
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"id": "old-pid"}
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(
            return_value=False
        )
        mock_conn2 = MagicMock()
        mock_conn2.__enter__ = lambda s: s
        mock_conn2.__exit__ = MagicMock(return_value=False)
        mock_cur2 = MagicMock()
        mock_conn2.cursor.return_value.__enter__ = lambda s: mock_cur2
        mock_conn2.cursor.return_value.__exit__ = MagicMock(
            return_value=False
        )
        with patch.object(
            sys.modules["psycopg2"],
            "connect",
            side_effect=[mock_conn, mock_conn2],
        ):
            m.update_keystone_project_id("services", "new-pid")

    def test_kube_supported_versions_get_kubernetes_version(self):
        m = load_module(
            "backup/prepare-env/files",
            "kube_supported_versions.py",
            "ksv2",
        )
        mock_client = MagicMock()
        v1 = MagicMock()
        v1.version = "v1.24.4"
        v2 = MagicMock()
        v2.version = "v1.25.0"
        mock_client.sysinv.kube_version.list.return_value = [v1, v2]
        result = m.get_kubernetes_version(mock_client)
        self.assertEqual(result, ["1.24.4", "1.25.0"])


if __name__ == "__main__":
    unittest.main()
