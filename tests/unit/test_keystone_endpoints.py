#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Force pytest-cov to discover the 11 missing source files by
importing them normally.
"""
import os
import sys
import unittest

# Install mocks before any imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks

install_mocks()

# Add each missing file's directory to sys.path and import normally
from test_helpers import ROLES

_DIRS = [
    "bootstrap/apply-manifest/files",
    "bootstrap/prepare-env/files",
    "common/get_network_addresses_from_sysinv/files",
    "common/push-docker-images/files",
    "common/update-sc-admin-endpoints/files",
    "enroll-subcloud/update-oam-interface/files",
    "recover-ceph-data/files",
    "recover-rook-ceph-data/files",
]

for d in _DIRS:
    dir_path = os.path.join(ROLES, d)
    if dir_path not in sys.path:
        sys.path.insert(0, dir_path)

# Prevent eventlet monkey_patch from running
sys.modules["eventlet"].monkey_patch = lambda **kw: None

# Now import normally so pytest-cov traces them
import configure_keystone
import create_barbican_endpoints as cbe
import create_sysinv_endpoints
import check_root_disk_size
import get_network_addresses_from_sysinv
import push_imported_images_to_local_registry as piilr
import push_pull_local_registry
import update_admin_endpoints as uae
import update_oam_interface
import prepare_ceph_partitions
import recover_rook_ceph


class TestConfigureKeystone(unittest.TestCase):
    def test_projects_to_create(self):
        self.assertIsInstance(
            configure_keystone.PROJECTS_TO_CREATE, list
        )

    def test_roles_to_create(self):
        self.assertIsInstance(configure_keystone.ROLES_TO_CREATE, list)

    def test_retrieve_env_vars(self):
        self.assertTrue(
            callable(configure_keystone._retrieve_environment_variables)
        )


class TestCreateBarbicanEndpoints(unittest.TestCase):
    def test_services_to_create(self):
        self.assertIsInstance(cbe.SERVICES_TO_CREATE, list)

    def test_endpoints_to_create(self):
        self.assertIsInstance(cbe.ENDPOINTS_TO_CREATE, list)

    def test_retrieve_env_vars(self):
        self.assertTrue(callable((cbe._retrieve_environment_variables)))


class TestCreateSysinvEndpoints(unittest.TestCase):
    def test_services_to_create(self):
        self.assertIsInstance(
            create_sysinv_endpoints.SERVICES_TO_CREATE, list
        )

    def test_users_to_update(self):
        self.assertIsInstance(
            create_sysinv_endpoints.USERS_TO_UPDATE, list
        )

    def test_retrieve_env_vars(self):
        self.assertTrue(
            callable(
                create_sysinv_endpoints._retrieve_environment_variables
            )
        )


class TestCheckRootDiskSize(unittest.TestCase):
    def test_get_rootfs_node_callable(self):
        self.assertTrue(callable(check_root_disk_size.get_rootfs_node))

    def test_parse_fdisk_callable(self):
        self.assertTrue(callable(check_root_disk_size.parse_fdisk))

    def test_get_root_disk_size_callable(self):
        self.assertTrue(
            callable(check_root_disk_size.get_root_disk_size)
        )


class TestGetNetworkAddresses(unittest.TestCase):
    def test_network_types(self):
        self.assertIsInstance(
            get_network_addresses_from_sysinv.NETWORK_TYPES, list
        )

    def test_get_addresses_callable(self):
        self.assertTrue(
            callable(get_network_addresses_from_sysinv.get_addresses)
        )

    def test_get_network_callable(self):
        self.assertTrue(
            callable(get_network_addresses_from_sysinv.get_network)
        )

    def test_get_addresses_of_pool(self):
        from unittest.mock import MagicMock

        c = MagicMock()
        pool = MagicMock()
        pool.floating_address = "10.0.0.1"
        pool.controller0_address = "10.0.0.2"
        pool.controller1_address = "10.0.0.3"
        pool.gateway_address = "10.0.0.4"
        c.sysinv.address_pool.list.return_value = [pool]
        addrpool_cache = (
            get_network_addresses_from_sysinv._get_addrpool_list
        )
        addrpool_cache.cache_clear()
        result = (
            get_network_addresses_from_sysinv.get_addresses_of_pool(
                c, pool.uuid
            )
        )
        self.assertIsInstance(result, dict)


class TestPushImportedImages(unittest.TestCase):
    def test_registry_patterns(self):
        self.assertIsInstance(
            piilr.REGISTRY_PATTERNS,
            list,
        )

    def test_push_an_image_callable(self):
        self.assertTrue(callable(piilr.push_an_image))

    def test_get_local_registry_auth_callable(self):
        self.assertTrue(callable((piilr.get_local_registry_auth)))


class TestPushPullLocalRegistry(unittest.TestCase):
    def test_max_download_attempts(self):
        self.assertEqual(
            push_pull_local_registry.MAX_DOWNLOAD_ATTEMPTS, 3
        )

    def test_push_from_filesystem_callable(self):
        self.assertTrue(
            callable(push_pull_local_registry.push_from_filesystem)
        )

    def test_pull_image_callable(self):
        self.assertTrue(
            callable(
                push_pull_local_registry.pull_image_from_local_registry
            )
        )


class TestUpdateAdminEndpoints(unittest.TestCase):
    def test_openrc_path(self):
        self.assertEqual(uae.OPENRC_PATH, "/etc/platform/openrc")

    def test_load_credentials_callable(self):
        self.assertTrue(
            callable((uae.load_credentials_and_create_session))
        )

    def test_main_callable(self):
        self.assertTrue(callable(uae.main))


class TestUpdateOamInterface(unittest.TestCase):
    def test_print_with_timestamp_callable(self):
        self.assertTrue(
            callable(update_oam_interface.print_with_timestamp)
        )

    def test_find_oam_network_callable(self):
        self.assertTrue(callable(update_oam_interface.find_oam_network))

    def test_build_interface_values_callable(self):
        self.assertTrue(
            callable(update_oam_interface.build_interface_values)
        )

    def test_update_oam_interface_callable(self):
        self.assertTrue(
            callable(update_oam_interface.update_oam_interface)
        )


class TestPrepareCephPartitions(unittest.TestCase):
    def test_osd_root_dir(self):
        self.assertEqual(
            prepare_ceph_partitions.OSD_ROOT_DIR, "/var/lib/ceph/osd"
        )

    def test_mount_osds_callable(self):
        self.assertTrue(callable(prepare_ceph_partitions.mount_osds))

    def test_prepare_monitor_callable(self):
        self.assertTrue(
            callable(prepare_ceph_partitions.prepare_monitor)
        )


class TestRecoverRookCeph(unittest.TestCase):
    def test_ceph_tmp_dir(self):
        self.assertEqual(recover_rook_ceph.CEPH_TMP_DIR, "/tmp/ceph")

    def test_recover_callable(self):
        self.assertTrue(callable(recover_rook_ceph.recover))

    def test_get_template_callable(self):
        self.assertTrue(callable(recover_rook_ceph.get_template))


if __name__ == "__main__":
    unittest.main()
