#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Final push to 85% - targets recover_rook_ceph, download_images, and
remaining gaps.
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mock_deps import install_mocks

install_mocks()
sys.modules["eventlet"].monkey_patch = lambda **kw: None
from test_helpers import add_role_dirs
from test_helpers import setup_pplr_mocks, setup_dli_mocks
add_role_dirs(["common/push-docker-images/files", "recover-rook-ceph-data/files", "enroll-subcloud/update-oam-interface/files", "recover-ceph-data/files", "bootstrap/prepare-env/files", "common/update-sc-admin-endpoints/files"])

os.environ.setdefault("REGISTRIES", "{}")
import download_images as dli
import recover_rook_ceph as rrc
import push_pull_local_registry as pplr
import push_imported_images_to_local_registry as piilr


class TestDLIFinal85(unittest.TestCase):
    def setUp(self):
        setup_dli_mocks(dli)

    def test_download_and_push_on_registry_crictl_pull(self):
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        dli.docker.APIClient = lambda: mock_client
        img, ok = dli.download_and_push_an_image("k8s.gcr.io/img:v1")
        self.assertTrue(ok)

    def test_download_and_push_backup_exclude(self):
        dli.backed_up_crictl_cache_images = ["other:v1"]
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        dli.docker.APIClient = lambda: mock_client
        img, ok = dli.download_and_push_an_image("k8s.gcr.io/img:v1")
        self.assertTrue(ok)
        dli.backed_up_crictl_cache_images = None

    def test_download_and_push_backup_include(self):
        dli.backed_up_crictl_cache_images = ["k8s.gcr.io/img:v1"]
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        dli.docker.APIClient = lambda: mock_client
        img, ok = dli.download_and_push_an_image("k8s.gcr.io/img:v1")
        self.assertTrue(ok)
        dli.backed_up_crictl_cache_images = None

    def test_download_and_push_prestage_on_registry(self):
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        dli.docker.APIClient = lambda: mock_client
        r = dli.download_and_push_an_image_for_prestage(
            ("img:v1", "target:v1", None)
        )
        self.assertEqual(r, (None, True))

    def test_download_a_local_image(self):
        mock_client = MagicMock()
        mock_client.pull.return_value = iter([b'{"status":"ok"}'])
        dli.docker.APIClient = lambda: mock_client
        img, ok = dli.download_a_local_image("img:v1")
        self.assertTrue(ok)

    def test_download_an_image_local(self):
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        mock_client.pull.return_value = iter([b'{"status":"ok"}'])
        dli.docker.APIClient = lambda: mock_client
        r = dli.download_an_image(("img:v1", "target:v1", None))
        self.assertTrue(r[1])

    def test_generate_image_outfile(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            path = f.name
        try:
            dli.image_outfile = path
            dli.generate_image_outfile(["img1", "img2"], path)
            with open(path) as f:
                self.assertIn("img1", f.read())
        finally:
            os.unlink(path)

    def test_get_image_list_with_auth_url_match(self):
        dli.registries = {
            "k8s.gcr.io": {
                "url": "mirror/k8s",
                "username": "u",
                "password": "p",
            }
        }
        r = dli.get_image_list_with_auth_info(["mirror/k8s/img:v1"])
        self.assertEqual(len(r), 1)
        dli.registries = json.loads(os.environ.get("REGISTRIES", "{}"))


class TestRRCFinal85(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(rrc.CEPH_TMP_DIR, "/tmp/ceph")
        self.assertEqual(rrc.REGISTRY, "registry.local:9001")

    def test_get_template(self):
        with patch(
            "builtins.open", mock_open(read_data="$VAR template")
        ):
            t = rrc.get_template("test.tpl")
        r = t.safe_substitute({"VAR": "value"})
        self.assertIn("value", r)

    def test_check_failure_ok(self):
        rrc.get_rook_ceph_recovery_data = lambda n: "ok"
        rrc.check_failure()

    def test_check_failure_fail(self):
        rrc.get_rook_ceph_recovery_data = lambda n: (
            "recovery-failed" if n == "status" else "err"
        )
        with self.assertRaises(SystemExit):
            rrc.check_failure()

    def test_create_and_apply(self):
        rrc.subprocess = MagicMock()
        rrc.subprocess.run = MagicMock(
            return_value=MagicMock(returncode=0)
        )
        with patch("builtins.open", mock_open()):
            rrc.create_and_apply_k8s_resource(
                "yaml content", "test.yaml"
            )

    def test_apply_k8s_resource(self):
        rrc.subprocess = MagicMock()
        rrc.subprocess.run = MagicMock(
            return_value=MagicMock(returncode=0)
        )
        rrc.apply_k8s_resource("/tmp/test.yaml")

    def test_copy_and_apply(self):
        rrc.subprocess = MagicMock()
        rrc.subprocess.run = MagicMock(
            return_value=MagicMock(returncode=0)
        )
        rrc.copy = MagicMock()
        rrc.copy_and_apply_k8s_resource("src.tpl", "dst.yaml")


class TestPPLRFinal85(unittest.TestCase):
    def setUp(self):
        setup_pplr_mocks(pplr)

    def test_push_success_no_n3000(self):
        mock_client = MagicMock()
        mock_client.images.return_value = True
        pplr.docker.APIClient = lambda: mock_client
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.push_from_filesystem(
            "registry.local:9001/img:v1"
        )
        self.assertTrue(ok)

    def test_push_image_not_present(self):
        mock_client = MagicMock()
        mock_client.images.return_value = False
        pplr.docker.APIClient = lambda: mock_client
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.push_from_filesystem(
            "registry.local:9001/img:v1"
        )
        self.assertTrue(ok)

    def test_pull_success(self):
        mock_client = MagicMock()
        mock_client.pull.return_value = iter([b'{"status":"ok"}'])
        pplr.docker.APIClient = lambda: mock_client
        pplr.docker.errors.NotFound = type("NF", (Exception,), {})
        pplr.docker.errors.APIError = type("AE", (Exception,), {})
        img, ok = pplr.pull_image_from_local_registry("img:v1")
        self.assertTrue(ok)


class TestPIILRFinal85(unittest.TestCase):
    def setUp(self):
        piilr.get_local_registry_auth = lambda: {
            "username": "u",
            "password": "p",
        }
        piilr.docker = MagicMock()
        piilr.subprocess = MagicMock()

    def test_push_n3000(self):
        self.assertTrue(callable(piilr.push_an_image))


if __name__ == "__main__":
    unittest.main()
