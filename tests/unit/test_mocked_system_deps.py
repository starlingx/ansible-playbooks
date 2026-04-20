#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Tests for modules requiring fm_api, psycopg2, and other system deps."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks
from constants import CONTROLLER_HOSTNAME
from test_helpers import ROLES

install_mocks()
from base_test import (
    BaseModuleTestCase, Psycopg2MockTestCase,
)


class TestFmAlarmSetClear(unittest.TestCase):
    """Tests for push-docker-images fm_alarm_set_clear."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "common/push-docker-images/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        if "fm_alarm_set_clear" in sys.modules:
            del sys.modules["fm_alarm_set_clear"]
        import fm_alarm_set_clear as mod
        self.mod = mod

    def test_alarm_set(self):
        self.mod.alarm_push_to_local_registry_handle("set", "900.401", "test")

    def test_alarm_clear(self):
        self.mod.alarm_push_to_local_registry_handle("clear", "900.401", "test")

    def test_handle_invalid_input(self):
        with self.assertRaises(Exception):
            self.mod.handle_invalid_input()


class TestBackupFmAlarm(BaseModuleTestCase):
    """Tests for backup fm_alarm."""

    role_path = "backup/backup-system/files"
    filename = "fm_alarm.py"
    mod_name = "backup_fm_alarm"

    def test_update_alarm_set(self):
        self.module.update_alarm("set", "250.001", "Backup in progress")

    def test_update_alarm_clear(self):
        self.module.update_alarm("clear", "250.001")

    def test_handle_invalid_input(self):
        with self.assertRaises(Exception):
            self.module.handle_invalid_input()


class TestMigrationFmAlarm(unittest.TestCase):
    """Tests for storage-backend-migration fm_alarm."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "storage-backend-migration/common/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "migration_fm_alarm", os.path.join(mod_path, "fm_alarm.py")
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.mod = mod

    def test_update_alarm_set(self):
        self.mod.update_alarm(
            "uuid-123", "set", "in_progress",
            {"severity": "minor", "reason_text": "test",
             "probable_cause": "8", "proposed_repair_action": "none"},
        )

    def test_update_alarm_clear(self):
        self.mod.update_alarm("uuid-123", "clear", "in_progress")

    def test_parse_args_set(self):
        with patch("sys.argv", ["prog", "--entity-uuid", "u1", "--set", "in_progress"]):
            args = self.mod.parse_args()
        self.assertEqual(args.set, "in_progress")

    def test_parse_args_clear(self):
        with patch("sys.argv", ["prog", "--entity-uuid", "u1", "--clear", "error"]):
            args = self.mod.parse_args()
        self.assertEqual(args.clear, "error")


class TestClearMgmtIpsecFlag(Psycopg2MockTestCase):
    """Tests for clear-mgmt-ipsec-flag."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "common/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "clear_mgmt_ipsec_flag",
            os.path.join(mod_path, "clear-mgmt-ipsec-flag.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.mod = mod

    def test_clear_mgmt_ipsec_normal(self):
        mock_conn, mock_cur = self.create_mock_connection(
            fetchall_data=[{"uuid": "u1", "hostname": "worker-0",
                           "capabilities": '{"mgmt_ipsec_flag": "enabled"}'}]
        )
        with self.patch_psycopg2_connect(mock_conn):
            self.mod.clear_mgmt_ipsec(False)

    def test_clear_mgmt_ipsec_restore_mode(self):
        mock_conn, mock_cur = self.create_mock_connection(
            fetchall_data=[{"uuid": "u1", "hostname": CONTROLLER_HOSTNAME,
                           "capabilities": "{}"}]
        )
        with self.patch_psycopg2_connect(mock_conn):
            self.mod.clear_mgmt_ipsec(True)


class TestGetAllHostnames(Psycopg2MockTestCase):
    """Tests for configure-ipsec get_all_hostnames."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "configure-ipsec/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        if "get_all_hostnames" in sys.modules:
            del sys.modules["get_all_hostnames"]
        import get_all_hostnames as mod
        self.mod = mod

    def test_get_hostnames_list(self):
        mock_conn, _ = self.create_mock_connection(
            fetchall_data=[{"hostname": CONTROLLER_HOSTNAME}, {"hostname": "worker-0"}]
        )
        with self.patch_psycopg2_connect(mock_conn):
            result = self.mod.get_hostnames_list()
        self.assertEqual(result, [CONTROLLER_HOSTNAME, "worker-0"])

    def test_get_hostnames_empty(self):
        mock_conn, _ = self.create_mock_connection(fetchall_data=[])
        with self.patch_psycopg2_connect(mock_conn):
            result = self.mod.get_hostnames_list()
        self.assertEqual(result, [])


class TestGetAllMgmtAddrs(Psycopg2MockTestCase):
    """Tests for configure-ipsec get_all_mgmt_addrs."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "configure-ipsec/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        if "get_all_mgmt_addrs" in sys.modules:
            del sys.modules["get_all_mgmt_addrs"]
        import get_all_mgmt_addrs as mod
        self.mod = mod

    def test_get_mgmt_addrs_ipv4(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [
            [{"network": "192.168.1.0"}],
            [{"address": "192.168.1.1"}, {"address": "10.0.0.1"}],
        ]
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        with self.patch_psycopg2_connect(mock_conn):
            result = self.mod.get_hostnames_list()
        self.assertIn("192.168.1.1", result)

    def test_get_mgmt_addrs_empty_pools(self):
        mock_conn, _ = self.create_mock_connection(fetchall_data=[])
        with self.patch_psycopg2_connect(mock_conn):
            result = self.mod.get_hostnames_list()
        self.assertEqual(result, [])


class TestGetIpsecDisabledAddrList(unittest.TestCase):
    """Tests for configure-ipsec get_ipsec_disabled_addr_list."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "configure-ipsec/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        if "get_ipsec_disabled_addr_list" in sys.modules:
            del sys.modules["get_ipsec_disabled_addr_list"]
        import get_ipsec_disabled_addr_list as mod
        self.mod = mod

    @patch("get_ipsec_disabled_addr_list.get_software_version", return_value=None)
    def test_no_version(self, _mock):
        self.assertEqual(self.mod.get_pxeboot_addrs_list(), [])

    @patch("get_ipsec_disabled_addr_list.os.path.exists", return_value=False)
    def test_get_software_version_no_file(self, _mock):
        self.assertIsNone(self.mod.get_software_version())


class TestMergeCertificateMounts(unittest.TestCase):
    """Tests for merge_certificate_mounts (psycopg2)."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "update-platform-certificates/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        if "merge_certificate_mounts" in sys.modules:
            del sys.modules["merge_certificate_mounts"]
        import merge_certificate_mounts as mod
        self.mod = mod

    def test_get_chart_user_override_found(self):
        overrides = [{"name": "dex", "user_overrides": "volumeMounts: []\nvolumes: []"}]
        self.assertIsNotNone(self.mod.get_chart_user_override(overrides, "dex"))

    def test_get_chart_user_override_not_found(self):
        self.assertIsNone(self.mod.get_chart_user_override([], "dex"))

    def test_get_chart_user_override_no_overrides(self):
        overrides = [{"name": "dex", "user_overrides": None}]
        self.assertIsNone(self.mod.get_chart_user_override(overrides, "dex"))

    def test_update_or_create_item_new(self):
        overrides = {"volumes": []}
        self.mod.update_or_create_item(overrides, "volumes", {"name": "https-tls", "secret": "tls-secret"})
        self.assertEqual(len(overrides["volumes"]), 1)

    def test_update_or_create_item_existing(self):
        overrides = {"volumes": [{"name": "https-tls", "secret": "old"}]}
        self.mod.update_or_create_item(overrides, "volumes", {"name": "https-tls", "secret": "new"})
        self.assertEqual(overrides["volumes"][0]["secret"], "new")


class TestMigrateKeystoneIds(Psycopg2MockTestCase):
    """Tests for migrate_keystone_ids (psycopg2)."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "rehome-enroll-common/update-keystone-data/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        if "migrate_keystone_ids" in sys.modules:
            del sys.modules["migrate_keystone_ids"]
        import migrate_keystone_ids as mod
        self.mod = mod

    def test_get_keystone_local_user_id_found(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"user_id": "uid-123"}
        self.assertEqual(self.mod.get_keystone_local_user_id("admin", mock_cur), "uid-123")

    def test_get_keystone_local_user_id_not_found(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        self.assertIsNone(self.mod.get_keystone_local_user_id("missing", mock_cur))

    def test_get_keystone_project_id_found(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {"id": "pid-123"}
        self.assertEqual(self.mod.get_keystone_project_id("services", mock_cur), "pid-123")

    def test_get_keystone_project_id_not_found(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = None
        self.assertIsNone(self.mod.get_keystone_project_id("missing", mock_cur))

    def test_get_keystone_local_user_record(self):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = {
            "id": "uid", "extra": "{}", "enabled": True,
            "created_at": "2024-01-01", "domain_id": "default",
        }
        result = self.mod.get_keystone_local_user_record("admin", mock_cur)
        self.assertEqual(result["id"], "uid")

    def test_clean_keystone_non_local_user(self):
        mock_cur = MagicMock()
        self.mod.clean_keystone_non_local_user("uid-123", mock_cur)
        self.assertEqual(mock_cur.execute.call_count, 3)


class TestParseUserDnsHostRecord(unittest.TestCase):
    """Tests for parse_user_dns_host_record."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "bootstrap/validate-config/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        if "parse_user_dns_host_record" in sys.modules:
            del sys.modules["parse_user_dns_host_record"]
        import parse_user_dns_host_record as mod
        self.mod = mod

    def test_check_duplicate_no_duplicates(self):
        data = {"host1": "192.168.1.1, myhost.example.com", "host2": "10.0.0.1, other.example.com"}
        self.mod.check_duplicate_host_records(data)

    def test_check_duplicate_raises(self):
        data = {"host1": "192.168.1.1, myhost.example.com", "host2": "192.168.1.1, myhost.example.com"}
        with self.assertRaises(ValueError):
            self.mod.check_duplicate_host_records(data)

    def test_parse_valid_record(self):
        from io import StringIO
        data = {"host1": "192.168.1.1, myhost.example.com"}
        captured = StringIO()
        sys.stdout = captured
        self.mod.parse_user_dns_host_records(data)
        sys.stdout = sys.__stdout__
        self.assertIn("192.168.1.1", captured.getvalue())

    def test_parse_invalid_no_ip(self):
        with self.assertRaises(ValueError):
            self.mod.parse_user_dns_host_records({"host1": "myhost.example.com"})


class TestKubeSupportedVersions(unittest.TestCase):
    """Tests for kube_supported_versions."""

    def setUp(self):
        mod_path = os.path.join(ROLES, "backup/prepare-env/files")
        if mod_path not in sys.path:
            sys.path.insert(0, mod_path)
        if "kube_supported_versions" in sys.modules:
            del sys.modules["kube_supported_versions"]
        import kube_supported_versions as mod
        self.mod = mod

    def test_parse_version(self):
        self.assertEqual(self.mod.parse_version("v1.24.4"), "1.24.4")
        self.assertEqual(self.mod.parse_version("1.24.4"), "1.24.4")

    def test_handle_invalid_input(self):
        with self.assertRaises(Exception):
            self.mod.handle_invalid_input()


if __name__ == "__main__":
    unittest.main()
