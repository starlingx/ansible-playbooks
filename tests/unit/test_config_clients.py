#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Covers client classes, main functions, and remaining gaps."""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks
from test_helpers import configure_mock_conf
from constants import default_bootstrap_config, OS_ENV_LINES, MGMT_FLOAT

install_mocks()
from base_test import BaseModuleTestCase, Psycopg2MockTestCase

TOKEN_ENV = {"OS_AUTH_URL": "http://x", "OS_TOKEN": "tok", "SYSTEM_URL": "http://sys"}


def _mock_popen():
    """Create a mock Popen returning OS_ENV_LINES."""
    proc = MagicMock()
    proc.stdout = iter(OS_ENV_LINES)
    proc.communicate = MagicMock()
    return proc


def _password_client(mod, cls_name="OpenStackClient", *args):
    """Create a client using password auth (Popen mock)."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OS_TOKEN", None)
        os.environ.pop("OS_AUTH_URL", None)
        with patch("subprocess.Popen", return_value=_mock_popen()):
            with patch("builtins.open", mock_open()):
                return getattr(mod, cls_name)(*args)


class TestUSCClients(BaseModuleTestCase):
    """Test BaseClient, CgtsClient, OpenStackClient in update_system_config."""

    role_path = "rehome-enroll-common/persist-configuration/files"
    filename = "update_system_config.py"
    mod_name = "usc_cl"

    def _token_client(self, cls_name="OpenStackClient"):
        with patch.dict(os.environ, TOKEN_ENV):
            return getattr(self.m, cls_name)()

    def test_base_client_with_token(self):
        bc = self._token_client("BaseClient")
        self.assertEqual(bc.auth_token, "tok")

    def test_base_client_source_credentials(self):
        bc = _password_client(self.m, "BaseClient")
        self.assertEqual(bc.conf.get("username"), "admin")

    def test_cgts_client_sysinv_with_token(self):
        _ = self._token_client("CgtsClient").sysinv

    def test_cgts_client_sysinv_with_password(self):
        _ = _password_client(self.m, "CgtsClient").sysinv

    def test_openstack_client_with_token(self):
        _ = self._token_client().barbican

    def test_openstack_client_keystone_session_password(self):
        c = _password_client(self.m)
        _ = c._get_new_keystone_session(c.conf)

    def test_openstack_client_list_secrets(self):
        c = self._token_client()
        c._barbican = MagicMock()
        c._barbican.secrets.list.return_value = [MagicMock()]
        self.assertEqual(len(c.list_secrets("test")), 1)

    def test_openstack_client_delete_secret(self):
        c = self._token_client()
        c._barbican = MagicMock()
        c.delete_secret("secret-id")

    def test_openstack_client_create_secret(self):
        c = self._token_client()
        c._barbican = MagicMock()
        c._barbican.secrets.create.return_value = MagicMock()
        self.assertIsNotNone(c.create_secret("name", "payload"))

    def test_main_no_args(self):
        with patch.object(sys, "argv", ["prog"]):
            with self.assertRaises(SystemExit):
                self.m.main()

    def test_main_no_file(self):
        with patch.object(sys, "argv", ["prog", "/nonexistent"]):
            with self.assertRaises(SystemExit):
                self.m.main()

    def test_main_no_operation(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".conf", delete=False) as f:
            f.write("[DEFAULT]\nkey=val\n")
            path = f.name
        try:
            with patch.object(sys, "argv", ["prog", path]):
                with self.assertRaises(SystemExit):
                    self.m.main()
        finally:
            os.unlink(path)

    def test_update_admin_network_secondary(self):
        defaults = {"ADMIN_SUBNET_SECONDARY": "fd00::/64", "ADMIN_START_ADDRESS_SECONDARY": "fd00::2",
                    "ADMIN_END_ADDRESS_SECONDARY": "fd00::ff", "ADMIN_GATEWAY_ADDRESS_SECONDARY": "undef"}
        self.m.CONF.get = lambda s, k: defaults.get(k, "undef")
        c = MagicMock()
        p = MagicMock()
        p.uuid = "pu"
        c.sysinv.address_pool.create.return_value = p
        net = MagicMock()
        net.name = self.m.sysinv_constants.NETWORK_TYPE_ADMIN
        net.uuid = "nu"
        c.sysinv.network.list.return_value = [net]
        self.m.update_admin_network_secondary(c, "S")


class TestUKPClients(BaseModuleTestCase):
    """Test OpenStackClient in update_keystone_keyring_passwords."""

    role_path = "rehome-enroll-common/update-keystone-data/files"
    filename = "update_keystone_keyring_passwords.py"
    mod_name = "ukp_cl"

    def _make_client(self, load_openrc=False):
        return _password_client(self.m, "OpenStackClient", load_openrc)

    def test_openstack_client_load_openrc(self):
        c = self._make_client(True)
        self.assertIn("username", c.conf)

    def test_keystone_property(self):
        _ = self._make_client(False).keystone

    def test_check_if_keystone_unauthorized(self):
        c = self._make_client(False)
        c._keystone = MagicMock()
        c._keystone.services.list.return_value = []
        self.assertTrue(c.check_if_keystone_is_active())

    def test_verify_sm_services_cmd_fail(self):
        self.m.subprocess = MagicMock()
        result = MagicMock(stdout="disabled")
        self.m.subprocess.run.return_value = result
        with self.assertRaises(TimeoutError):
            self.m.verify_sm_services(
                ["svc"], {"svc"}, max_retries=1, delay_seconds=0)

    def test_update_sysinv_config_error(self):
        with patch.object(self.m, "update_config_file", side_effect=Exception("fail")):
            with self.assertRaises(Exception):
                self.m.update_sysinv_config("pass")

    def test_update_fm_config_error(self):
        with patch.object(self.m, "update_config_file", side_effect=Exception("fail")):
            with self.assertRaises(Exception):
                self.m.update_fm_config("pass")

    def test_update_barbican_config_error(self):
        with patch.object(self.m, "update_config_file", side_effect=Exception("fail")):
            with self.assertRaises(Exception):
                self.m.update_barbican_config("pass")

    def test_update_usm_config_error(self):
        with patch.object(self.m, "update_config_file", side_effect=Exception("fail")):
            with self.assertRaises(Exception):
                self.m.update_usm_config("pass")

    def test_update_mtce_config_error(self):
        with patch.object(self.m, "update_config_file", side_effect=Exception("fail")):
            with self.assertRaises(Exception):
                self.m.update_mtce_config("pass")

    def test_main_no_file(self):
        with patch.object(sys, "argv", ["prog", "/nonexistent"]):
            with self.assertRaises(SystemExit):
                self.m.main()

    def test_main_bad_json(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            with patch.object(sys, "argv", ["prog", path]):
                with self.assertRaises(SystemExit):
                    self.m.main()
        finally:
            os.unlink(path)


class TestDLMore(BaseModuleTestCase):
    """More download_images coverage."""

    role_path = "common/push-docker-images/files"
    filename = "download_images.py"
    mod_name = "dli_cl"

    def setUp(self):
        os.environ.setdefault("REGISTRIES", "{}")
        super().setUp()
        self.m = self.module
        self.m.get_local_registry_auth = lambda: {"username": "u", "password": "p"}

    def _mock_docker(self, inspect=True):
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = inspect
        self.m.docker.APIClient = lambda: mock_client
        return mock_client

    def test_download_and_push_cached_in_crictl(self):
        self.m.crictl_image_list = ["registry.local:9001/k8s.gcr.io/img:v1"]
        self._mock_docker()
        self.assertTrue(self.m.download_and_push_an_image("k8s.gcr.io/img:v1")[1])

    def test_download_and_push_on_registry_not_in_backup(self):
        self.m.crictl_image_list = []
        self.m.backed_up_crictl_cache_images = ["other:v1"]
        self._mock_docker()
        self.assertTrue(self.m.download_and_push_an_image("k8s.gcr.io/img:v1")[1])
        self.m.backed_up_crictl_cache_images = None

    def test_download_and_push_on_registry_in_backup(self):
        self.m.crictl_image_list = []
        self.m.backed_up_crictl_cache_images = ["k8s.gcr.io/img:v1"]
        self._mock_docker()
        self.m.subprocess = MagicMock()
        self.assertTrue(self.m.download_and_push_an_image("k8s.gcr.io/img:v1")[1])
        self.m.backed_up_crictl_cache_images = None

    def test_download_and_push_prestage_found(self):
        self._mock_docker()
        self.assertEqual(self.m.download_and_push_an_image_for_prestage(("img:v1", "target:v1", None)), (None, True))

    def test_get_image_list_with_auth_url_prefix(self):
        self.m.registries = {"k8s.gcr.io": {"url": "mirror.io/k8s", "username": "u", "password": "p"}}
        result = self.m.get_image_list_with_auth_info(["mirror.io/k8s/img:v1"])
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0][2])


class TestCPAMore(BaseModuleTestCase):
    """More check_patches_to_apply coverage."""

    role_path = "enroll-subcloud/patch-before-enroll/files"
    filename = "check_patches_to_apply.py"
    mod_name = "cpa_cl"

    def test_extract_release_id(self):
        checker = self.m.PatchChecker([], "24.09", "24.09")
        self.assertTrue(callable(checker._extract_release_id))

    def test_get_patch_file_mapping_lazy(self):
        checker = self.m.PatchChecker([], "24.09", "24.09")
        checker.patch_file_id_dict = {"a": "b"}
        self.assertEqual(checker._get_patch_file_mapping(), {"a": "b"})

    def test_filter_diff_version(self):
        releases = [{"release_id": "stx-1", "component": "stx", "prepatched_iso": False, "state": "deployed"}]
        checker = self.m.PatchChecker(releases, "24.09", "25.03")
        self.assertEqual(len(checker.filter_system_controller_patches("stx")), 1)

    def test_filter_excludes_unavailable_same_version(self):
        releases = [{"release_id": "stx-1", "component": "stx", "prepatched_iso": False, "state": "unavailable"}]
        checker = self.m.PatchChecker(releases, "24.09", "24.09")
        self.assertEqual(len(checker.filter_system_controller_patches("stx")), 1)


class TestKSVMore(BaseModuleTestCase):
    """More kube_supported_versions coverage."""

    role_path = "backup/prepare-env/files"
    filename = "kube_supported_versions.py"
    mod_name = "ksv_cl"

    def test_cgts_client_class(self):
        _ = _password_client(self.module, "CgtsClient").sysinv

    def test_get_kubernetes_version_empty(self):
        c = MagicMock()
        c.sysinv.kube_version.list.return_value = []
        self.assertEqual(self.module.get_kubernetes_version(c), [])


class TestClearMgmtMore(BaseModuleTestCase):
    """More clear-mgmt-ipsec-flag coverage."""

    role_path = "common/files"
    filename = "clear-mgmt-ipsec-flag.py"
    mod_name = "cmif_cl"

    def test_main_no_restore(self):
        with patch.object(sys, "argv", ["prog"]):
            with patch.object(self.module, "clear_mgmt_ipsec") as mc:
                self.module.main()
                mc.assert_called_once_with(False)

    def test_main_restore(self):
        with patch.object(sys, "argv", ["prog", "-r"]):
            with patch.object(self.module, "clear_mgmt_ipsec") as mc:
                self.module.main()
                mc.assert_called_once_with(True)


class TestMigrateKeystoneMore(Psycopg2MockTestCase, BaseModuleTestCase):
    """More migrate_keystone_ids coverage."""

    role_path = "rehome-enroll-common/update-keystone-data/files"
    filename = "migrate_keystone_ids.py"
    mod_name = "mki_cl"

    def setUp(self):
        BaseModuleTestCase.setUp(self)
        self.m = self.module

    def test_update_keystone_user_id_same(self):
        mock_conn, mock_cur = self.create_mock_connection(fetchone_data={"user_id": "same-uid"})
        with self.patch_psycopg2_connect(mock_conn):
            self.m.update_keystone_user_id("admin", "same-uid")

    def test_update_keystone_project_id_same(self):
        mock_conn, mock_cur = self.create_mock_connection(fetchone_data={"id": "same-pid"})
        with self.patch_psycopg2_connect(mock_conn):
            self.m.update_keystone_project_id("services", "same-pid")

    def test_update_barbican_project_external_id(self):
        mock_conn, _ = self.create_mock_connection()
        with self.patch_psycopg2_connect(mock_conn):
            self.m.update_barbican_project_external_id("old", "new")


class TestUSCUpdateMgmt(BaseModuleTestCase):
    """Cover update_management_network lines 763-823."""

    role_path = "rehome-enroll-common/persist-configuration/files"
    filename = "update_system_config.py"
    mod_name = "usc_mgmt"

    def _configure_mgmt_defaults(self):
        defaults = default_bootstrap_config()
        defaults["SYSTEM_MODE"] = "system_mode_simplex"
        defaults["MANAGEMENT_GATEWAY_ADDRESS"] = MGMT_FLOAT
        configure_mock_conf(self.module, defaults)

    def _make_mgmt_client(self):
        c = MagicMock()
        net = MagicMock()
        net.name = self.m.sysinv_constants.NETWORK_TYPE_MGMT
        net.uuid = "nu"
        net.pool_uuid = "pu"
        net.primary_pool_family = "ipv4"
        c.sysinv.network.list.return_value = [net]
        c.sysinv.network_addrpool.list.return_value = []
        pool = MagicMock(network="10.0.0.0", prefix="24", floating_address="10.0.0.1",
                         gateway_address="10.0.0.1", controller0_address=None, controller1_address=None)
        pool.ranges = [("10.0.0.1", "10.0.0.254")]
        c.sysinv.address_pool.get.return_value = pool
        return c

    def test_update_management_network_duplex(self):
        self._configure_mgmt_defaults()
        c = self._make_mgmt_client()
        with patch.object(self.m, "precheck_update_management_network", return_value=True):
            with patch.object(self.m, "wait_for_file"):
                self.m.update_management_network(c, "S")
        c.sysinv.address_pool.update.assert_called_once()

    def test_update_management_network_fail(self):
        self._configure_mgmt_defaults()
        c = self._make_mgmt_client()
        c.sysinv.address_pool.update.side_effect = Exception("fail")
        with patch.object(self.m, "precheck_update_management_network", return_value=True):
            with self.assertRaises(SystemExit):
                self.m.update_management_network(c, "S")


if __name__ == "__main__":
    unittest.main()
