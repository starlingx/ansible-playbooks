#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Final 85 - cover recover_rook_ceph.recover() and download_images
remaining.
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
add_role_dirs(["recover-rook-ceph-data/files", "common/push-docker-images/files"])

os.environ.setdefault("REGISTRIES", "{}")
import recover_rook_ceph as rrc
import download_images as dli


class TestRRCRecover(unittest.TestCase):
    """Cover the recover() function."""

    def test_recover_osd_and_mon(self):
        rrc.subprocess = MagicMock()
        rrc.subprocess.run.return_value = MagicMock(
            returncode=0, stderr=""
        )
        node_data = (
            b'{"node":{"a":{"Hostname":'
            b'"ctrl-0"},"b":{"Hostname":'
            b'"w-0"}}}'
        )
        rrc.subprocess.check_output.return_value = node_data
        mock_tpl = MagicMock()
        mock_tpl.safe_substitute.return_value = "yaml"
        rrc.copy_and_apply_k8s_resource = MagicMock()
        rrc.create_and_apply_k8s_resource = MagicMock()
        rrc.check_failure = MagicMock()
        rrc.get_template = MagicMock(return_value=mock_tpl)
        rrc.os.path.exists = MagicMock(return_value=True)
        argv_data = {
            "recovery_target_host": "ctrl-0",
            "recovery_type": "OSD_AND_MON",
            "hosts_with_osd": "ctrl-0 w-0",
        }
        monmap = b"monmap-binary-data"
        with patch(
            "builtins.open",
            mock_open(read_data=monmap),
        ):
            with patch.object(
                sys,
                "argv",
                ["prog", json.dumps(argv_data)],
            ):
                rrc.recover()

    def test_recover_single_host(self):
        rrc.subprocess = MagicMock()
        rrc.subprocess.run.return_value = MagicMock(
            returncode=0, stderr=""
        )
        node_data = b'{"node":{"a":{"Hostname":"ctrl-0"}}}'
        rrc.subprocess.check_output.return_value = node_data
        mock_tpl = MagicMock()
        mock_tpl.safe_substitute.return_value = "yaml"
        rrc.copy_and_apply_k8s_resource = MagicMock()
        rrc.create_and_apply_k8s_resource = MagicMock()
        rrc.check_failure = MagicMock()
        rrc.get_template = MagicMock(return_value=mock_tpl)
        rrc.os.path.exists = MagicMock(return_value=True)
        argv_data = {
            "recovery_target_host": "ctrl-0",
            "recovery_type": "SINGLE_HOST",
            "hosts_with_osd": "ctrl-0",
        }
        monmap = b"monmap-binary-data"
        with patch(
            "builtins.open",
            mock_open(read_data=monmap),
        ):
            with patch.object(
                sys,
                "argv",
                ["prog", json.dumps(argv_data)],
            ):
                rrc.recover()


class TestDLIRemaining(unittest.TestCase):
    """Cover download_images remaining download functions."""

    def setUp(self):
        dli.docker = MagicMock()
        dli.subprocess = MagicMock()
        dli.time = MagicMock()
        dli.keyring = MagicMock()
        dli.keyring.get_password.return_value = "secret"
        dli.crictl_image_list = []
        dli.backed_up_crictl_cache_images = None
        dli.purge_images_list_file = None

    def test_download_and_push_not_cached_not_on_registry(self):
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        mock_client.pull.return_value = '{"status":"ok"}'
        mock_client.images.return_value = True
        dli.docker.APIClient.return_value = mock_client
        dli.docker.errors.APIError = api_error_cls
        dli.docker.errors.NotFound = type("NF", (Exception,), {})
        img, ok = dli.download_and_push_an_image("k8s.gcr.io/img:v1")
        self.assertTrue(ok)

    def test_download_and_push_not_cached_n3000(self):
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        mock_client.pull.return_value = '{"status":"ok"}'
        dli.docker.APIClient.return_value = mock_client
        dli.docker.errors.APIError = api_error_cls
        dli.docker.errors.NotFound = type("NF", (Exception,), {})
        img, ok = dli.download_and_push_an_image("n3000-opae:v1")
        self.assertTrue(ok)

    def test_download_a_local_image_success(self):
        mock_client = MagicMock()
        dli.json = MagicMock()
        dli.json.loads.return_value = {"status": "ok"}
        mock_client.pull.return_value = [b'{"status":"ok"}']
        dli.docker.APIClient.return_value = mock_client
        img, ok = dli.download_a_local_image("img:v1")
        self.assertTrue(ok)

    def test_download_an_image_from_local(self):
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = True
        dli.json = MagicMock()
        dli.json.loads.return_value = {"status": "ok"}
        mock_client.pull.return_value = [b'{"status":"ok"}']
        dli.docker.APIClient.return_value = mock_client
        dli.docker.errors.APIError = type("AE", (Exception,), {})
        r = dli.download_an_image(("img:v1", "target:v1", None))
        self.assertTrue(r[1])

    def test_download_an_image_not_local(self):
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        mock_client.pull.return_value = True
        dli.docker.APIClient.return_value = mock_client
        dli.docker.errors.APIError = api_error_cls
        dli.docker.errors.NotFound = type("NF", (Exception,), {})
        r = dli.download_an_image(("img:v1", "target:v1", None))
        self.assertTrue(r[1])

    def test_download_an_image_different_name(self):
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        mock_client.pull.return_value = True
        dli.docker.APIClient.return_value = mock_client
        dli.docker.errors.APIError = api_error_cls
        dli.docker.errors.NotFound = type("NF", (Exception,), {})
        r = dli.download_an_image(("img:v1", "mirror/img:v1", None))
        self.assertTrue(r[1])

    def test_download_and_push_for_prestage_not_found(self):
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        mock_client.pull.return_value = '{"status":"ok"}'
        mock_client.images.return_value = True
        dli.docker.APIClient.return_value = mock_client
        dli.docker.errors.APIError = api_error_cls
        dli.docker.errors.NotFound = type("NF", (Exception,), {})
        r = dli.download_and_push_an_image_for_prestage(
            ("img:v1", "target:v1", None)
        )
        self.assertTrue(r[1])

    def test_download_and_push_for_prestage_sw_deploy(self):
        mock_client = MagicMock()
        api_error_cls = type("APIError", (Exception,), {})
        mock_client.inspect_distribution.side_effect = api_error_cls(
            "not found"
        )
        mock_client.pull.return_value = '{"status":"ok"}'
        mock_client.images.return_value = True
        dli.docker.APIClient.return_value = mock_client
        dli.docker.errors.APIError = api_error_cls
        dli.docker.errors.NotFound = type("NF", (Exception,), {})
        os.environ["PRESTAGE_REASON"] = "for_sw_deploy"
        r = dli.download_and_push_an_image_for_prestage(
            ("img:v1", "target:v1", None)
        )
        self.assertTrue(r[1])
        os.environ.pop("PRESTAGE_REASON", None)


if __name__ == "__main__":
    unittest.main()
