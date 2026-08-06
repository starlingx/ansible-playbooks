#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Tests for YAML-processing storage-backend-migration modules.

These modules (set_worker_cpu_memory, convert_storage_to_worker,
remove_osds, strip_to_storage_only, add_kube_labels) only depend
on yaml and argparse — no system mocks needed.
"""

import json
import os
import sys
import textwrap
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from base_test import TempFileTestCase, YamlModuleTestCase


class YamlModuleBase(YamlModuleTestCase):
    """Base for YAML-processing module tests with stdout capture."""

    module_name = None  # Override in subclass
    mod = None

    def setUp(self):
        """Import module under test (cached at class level)."""
        if self.__class__.mod is None:
            import importlib
            self.__class__.mod = importlib.import_module(
                self.module_name
            )

    def run_main_on_yaml(self, yaml_content):
        """Write YAML to temp, run main, return parsed output docs.

        :param yaml_content: YAML string
        :returns: list of parsed YAML documents from stdout
        """
        path = self.write_temp(yaml_content)
        try:
            _, output = self.capture_stdout(self.mod.main, path)
            return self.load_yaml_all(output)
        finally:
            os.unlink(path)


class TestSetWorkerCpuMemory(YamlModuleBase):
    """Tests for set_worker_cpu_memory module."""

    module_name = "set_worker_cpu_memory"

    def test_mib_to_pages(self):
        self.assertEqual(self.mod.mib_to_pages(7168), 7168 * 256)

    def test_build_memory_section_no_node1(self):
        mem = self.mod.build_memory_section(7168, False)
        self.assertEqual(len(mem), 1)
        self.assertEqual(mem[0]["node"], 0)

    def test_build_memory_section_with_node1(self):
        mem = self.mod.build_memory_section(7168, True)
        self.assertEqual(len(mem), 2)

    def test_build_processors_section(self):
        proc = self.mod.build_processors_section(2, False)
        self.assertEqual(proc[0]["functions"][0]["count"], 2)

    def test_build_processors_section_with_node1(self):
        proc = self.mod.build_processors_section(1, True)
        self.assertEqual(len(proc), 2)

    def test_update_profile_host_profile(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "worker"},
            "spec": {},
        }
        result = self.mod.update_profile(doc, 7168, 1, False)
        self.assertIn("memory", result["spec"])
        self.assertIn("processors", result["spec"])

    def test_update_profile_non_host_profile(self):
        doc = {"kind": "ConfigMap", "metadata": {"name": "x"}}
        result = self.mod.update_profile(doc, 7168, 1, False)
        self.assertEqual(result, doc)

    def test_main(self):
        yaml_content = textwrap.dedent("""\
            ---
            kind: HostProfile
            metadata:
              name: worker-profile
            spec:
              memory:
                - node: 0
                  functions:
                    - function: platform
                      pageCount: 100
                      pageSize: 4KB
        """)
        path = self.write_temp(yaml_content)
        try:
            with patch.object(
                sys, "argv", ["prog", "--node0-mib", "8192", path]
            ):
                _, output = self.capture_stdout(self.mod.main)
            docs = self.load_yaml_all(output)
            self.assertEqual(
                docs[0]["spec"]["memory"][0]["functions"][0]["pageCount"],
                8192 * 256,
            )
        finally:
            os.unlink(path)


class TestConvertStorageToWorker(YamlModuleBase):
    """Tests for convert_storage_to_worker module."""

    module_name = "convert_storage_to_worker"

    def test_convert_storage_profile(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "storage-0"},
            "spec": {
                "personality": "storage",
                "subfunctions": ["storage"],
            },
        }
        result = self.mod.convert_doc(doc)
        self.assertEqual(result["spec"]["personality"], "worker")
        self.assertEqual(result["spec"]["subfunctions"], ["worker"])

    def test_convert_non_storage(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "worker-0"},
            "spec": {"personality": "worker"},
        }
        result = self.mod.convert_doc(doc)
        self.assertEqual(result["spec"]["personality"], "worker")

    def test_convert_non_dict(self):
        self.assertEqual(self.mod.convert_doc("string"), "string")

    def test_main(self):
        yaml_content = textwrap.dedent("""\
            ---
            kind: HostProfile
            metadata:
              name: storage-0
            spec:
              personality: storage
              subfunctions:
                - storage
        """)
        docs = self.run_main_on_yaml(yaml_content)
        self.assertEqual(docs[0]["spec"]["personality"], "worker")


class TestRemoveOsds(YamlModuleBase):
    """Tests for remove_osds module."""

    module_name = "remove_osds"

    def test_remove_osds_from_profile(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "storage-0"},
            "spec": {"storage": {"osds": [{"id": 0}, {"id": 1}]}},
        }
        result = self.mod.remove_osds_from_profile(doc)
        self.assertNotIn("osds", result["spec"].get("storage", {}))

    def test_remove_osds_empty_storage(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "storage-0"},
            "spec": {"storage": {"osds": [{"id": 0}]}},
        }
        result = self.mod.remove_osds_from_profile(doc)
        self.assertNotIn("storage", result["spec"])

    def test_remove_osds_no_storage(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "worker"},
            "spec": {},
        }
        result = self.mod.remove_osds_from_profile(doc)
        self.assertNotIn("storage", result["spec"])

    def test_remove_osds_non_host_profile(self):
        doc = {"kind": "ConfigMap"}
        self.assertEqual(self.mod.remove_osds_from_profile(doc), doc)

    def test_main(self):
        yaml_content = textwrap.dedent("""\
            ---
            kind: HostProfile
            metadata:
              name: storage-0
            spec:
              storage:
                osds:
                  - id: 0
        """)
        docs = self.run_main_on_yaml(yaml_content)
        self.assertNotIn("storage", docs[0]["spec"])


class TestStripToStorageOnly(YamlModuleBase):
    """Tests for strip_to_storage_only module."""

    module_name = "strip_to_storage_only"

    def test_is_storage_profile_true(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "storage-0"},
            "spec": {"personality": "storage"},
        }
        self.assertTrue(self.mod.is_storage_profile(doc))

    def test_is_storage_profile_false_worker(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "worker"},
            "spec": {"personality": "worker"},
        }
        self.assertFalse(self.mod.is_storage_profile(doc))

    def test_is_storage_profile_false_non_dict(self):
        self.assertFalse(self.mod.is_storage_profile("string"))

    def test_is_storage_profile_false_non_host(self):
        self.assertFalse(
            self.mod.is_storage_profile({"kind": "ConfigMap"})
        )

    def test_main_filters(self):
        yaml_content = textwrap.dedent("""\
            ---
            kind: HostProfile
            metadata:
              name: storage-profile
            spec:
              personality: storage
            ---
            kind: Host
            metadata:
              name: storage-0
            spec:
              profile: storage-profile
            ---
            kind: HostProfile
            metadata:
              name: worker-profile
            spec:
              personality: worker
            ---
            kind: Host
            metadata:
              name: worker-0
            spec:
              profile: worker-profile
        """)
        docs = self.run_main_on_yaml(yaml_content)
        names = [d["metadata"]["name"] for d in docs]
        self.assertIn("storage-profile", names)
        self.assertIn("storage-0", names)
        self.assertNotIn("worker-profile", names)
        self.assertNotIn("worker-0", names)


class TestAddKubeLabels(YamlModuleBase):
    """Tests for add_kube_labels module."""

    module_name = "add_kube_labels"

    def test_add_labels_new(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "worker"},
            "spec": {},
        }
        result = self.mod.add_labels_to_profile(doc)
        self.assertIn("kube-cpu-mgr-policy", result["spec"]["labels"])

    def test_add_labels_existing(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "worker"},
            "spec": {"labels": {"existing": "label"}},
        }
        result = self.mod.add_labels_to_profile(doc)
        self.assertIn("existing", result["spec"]["labels"])
        self.assertIn("sriov", result["spec"]["labels"])

    def test_add_labels_non_host_profile(self):
        doc = {"kind": "ConfigMap"}
        self.assertEqual(self.mod.add_labels_to_profile(doc), doc)

    def test_add_labels_already_present(self):
        doc = {
            "kind": "HostProfile",
            "metadata": {"name": "worker"},
            "spec": {"labels": dict(self.mod.KUBE_LABELS)},
        }
        result = self.mod.add_labels_to_profile(doc)
        self.assertEqual(len(result["spec"]["labels"]), 4)

    def test_main(self):
        yaml_content = textwrap.dedent("""\
            ---
            kind: HostProfile
            metadata:
              name: worker
            spec: {}
        """)
        docs = self.run_main_on_yaml(yaml_content)
        self.assertIn("sriov", docs[0]["spec"]["labels"])


class TestGetOsdInfo(TempFileTestCase):
    """Tests for get_osd_info module."""

    def test_osd_info_output(self):
        from io import StringIO
        json_input = {
            "nodes": [
                {"id": 0, "type": "root", "name": "default",
                 "children": [1]},
                {"id": 1, "type": "host", "name": "host-0",
                 "children": [2]},
                {"id": 2, "type": "osd", "name": "osd.0",
                 "device_class": "hdd", "crush_weight": 0.5,
                 "reweight": 1.0},
            ]
        }
        mod_path = os.path.join(
            os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            )),
            "playbookconfig", "src", "playbooks", "roles",
            "storage-backend-migration", "get-infos", "files",
            "get_osd_info.py",
        )
        captured = StringIO()
        sys.stdout = captured
        sys.stdin = StringIO(json.dumps(json_input))
        exec(
            compile(open(mod_path).read(), mod_path, "exec"),
            {"__name__": "__test__"},
        )
        sys.stdout = sys.__stdout__
        sys.stdin = sys.__stdin__
        result = json.loads(captured.getvalue().strip())
        self.assertEqual(result["osd_id"], 2)
        self.assertEqual(result["osd_class"], "hdd")
        self.assertIn("root=default", result["osd_crush_location"])


class TestGetPxebootAddrList(unittest.TestCase):
    """Tests for get_pxeboot_addr_list module."""

    mod = None

    def setUp(self):
        if self.__class__.mod is None:
            import get_pxeboot_addr_list as mod
            self.__class__.mod = mod

    @patch("get_pxeboot_addr_list.os.path.exists", return_value=False)
    def test_get_software_version_no_file(self, _mock):
        self.assertIsNone(self.mod.get_software_version())

    @patch(
        "builtins.open",
        unittest.mock.mock_open(read_data="sw_version=24.09\n"),
    )
    @patch("get_pxeboot_addr_list.os.path.exists", return_value=True)
    def test_get_software_version_found(self, _mock):
        result = self.mod.get_software_version()
        self.assertEqual(result, "24.09")

    @patch(
        "get_pxeboot_addr_list.get_software_version", return_value=None
    )
    def test_get_pxeboot_addrs_no_version(self, _mock):
        self.assertEqual(self.mod.get_pxeboot_addrs_list(), [])

    @patch(
        "get_pxeboot_addr_list.os.path.exists",
        side_effect=lambda p: p
        != "/opt/platform/config/24.09/dnsmasq.hosts",
    )
    @patch(
        "get_pxeboot_addr_list.get_software_version",
        return_value="24.09",
    )
    def test_get_pxeboot_addrs_no_dnsmasq(self, _v, _e):
        self.assertEqual(self.mod.get_pxeboot_addrs_list(), [])

    @patch(
        "builtins.open",
        unittest.mock.mock_open(
            read_data="aa:bb:cc:dd:ee:ff,host1,192.168.1.1\n"
            "pxecontroller,ctrl,10.0.0.1\n"
            "11:22:33:44:55:66,host2,192.168.1.2\n"
        ),
    )
    @patch("get_pxeboot_addr_list.os.path.exists", return_value=True)
    @patch(
        "get_pxeboot_addr_list.get_software_version",
        return_value="24.09",
    )
    def test_get_pxeboot_addrs_success(self, _v, _e):
        result = self.mod.get_pxeboot_addrs_list()
        self.assertEqual(len(result), 2)
        self.assertTrue(result[0].startswith("192.168.1"))


class TestRecoverCephData(unittest.TestCase):
    """Tests for recover_ceph_data module."""

    mod = None

    def setUp(self):
        if self.__class__.mod is None:
            import recover_ceph_data as mod
            self.__class__.mod = mod

    @patch("recover_ceph_data.subprocess.check_output")
    @patch("recover_ceph_data.subprocess.run")
    @patch("recover_ceph_data.os.listdir", return_value=["ceph-0"])
    @patch("recover_ceph_data.os.mkdir")
    @patch("recover_ceph_data.shutil.rmtree")
    @patch("recover_ceph_data.os.path.exists", return_value=True)
    def test_recover_ceph_data(
        self, _exists, _rmtree, _mkdir, _listdir, _run, _check
    ):
        _check.return_value = b"output"
        self.mod.recover_ceph_data()
        self.assertTrue(_mkdir.called)


class TestGetRegistryAuth(unittest.TestCase):
    """Tests for get_registry_auth module (AWS ECR)."""

    mod = None

    def setUp(self):
        if self.__class__.mod is None:
            sys.modules.pop("get_registry_auth", None)
            sys.modules.setdefault("boto3", unittest.mock.MagicMock())
            sys.modules.setdefault(
                "botocore", unittest.mock.MagicMock()
            )
            sys.modules.setdefault(
                "botocore.config", unittest.mock.MagicMock()
            )
            import get_registry_auth as mod
            self.__class__.mod = mod

    def test_set_advanced_config_no_proxy(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("AWS_HTTP_PROXY", None)
            os.environ.pop("AWS_HTTPS_PROXY", None)
            result = self.mod.set_advanced_config_for_botocore_client()
            self.assertIsNone(result)

    def test_set_advanced_config_with_proxy(self):
        with patch.dict(
            os.environ,
            {
                "AWS_HTTP_PROXY": "http://proxy:3128",
                "AWS_HTTPS_PROXY": "http://proxy:3129",
            },
        ):
            result = self.mod.set_advanced_config_for_botocore_client()
            self.assertIsNotNone(result)


if __name__ == "__main__":
    unittest.main()
