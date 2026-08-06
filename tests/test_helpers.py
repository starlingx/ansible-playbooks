#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Shared test helper functions.

Provides reusable module loading, mock configuration,
and mock client creation used across test files.
"""

import importlib.util
import os
import sys
from unittest.mock import MagicMock

ROLES = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "playbookconfig",
    "src",
    "playbooks",
    "roles",
)


def load_module(role_path, filename, mod_name=None):
    """Load a module by file path with a unique name.

    :param role_path: relative path under roles dir
    :param filename: Python filename to load
    :param mod_name: unique module name for sys.modules
    :returns: loaded module object
    """
    full_path = os.path.join(ROLES, role_path, filename)
    name = mod_name or filename.replace(".py", "").replace("-", "_")
    if name in sys.modules:
        del sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, full_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def configure_mock_conf(module, defaults, overrides=None):
    """Configure a module's CONF mock with test values.

    :param module: the loaded module to configure
    :param defaults: dict of default config values
    :param overrides: optional dict to override defaults
    :returns: None
    """
    if overrides:
        defaults.update(overrides)
    module.CONF.get = lambda section, key: defaults.get(key, "undef")
    module.CONF.getboolean = lambda section, key: defaults.get(
        key, "False"
    ).lower() in ("true", "1", "yes")
    module.CONF.items = lambda s=None, section=None: []
    module.CONF.has_section = lambda section: False


def create_mock_sysinv_client():
    """Create a mock sysinv client with common defaults.

    :returns: MagicMock configured as sysinv client
    """
    mock_client = MagicMock()
    mock_pool = MagicMock()
    mock_pool.uuid = "pool-uuid"
    mock_client.sysinv.address_pool.create.return_value = mock_pool
    mock_client.sysinv.address_pool.list.return_value = []
    mock_client.sysinv.network.list.return_value = []
    mock_client.sysinv.network_addrpool.list.return_value = []
    mock_client.sysinv.ihost.get.return_value = MagicMock(uuid="h-uuid")
    mock_client.sysinv.route.list_by_host.return_value = []
    mock_client.sysinv.address.list_by_host.return_value = []
    mock_client.sysinv.isystem.list.return_value = [
        MagicMock(uuid="sys-uuid", system_type="All-in-one")
    ]
    mock_client.sysinv.idns.list.return_value = [
        MagicMock(uuid="dns-uuid")
    ]
    mock_client.sysinv.service_parameter.list.return_value = []
    return mock_client


def create_mock_network(name, uuid="n-uuid"):
    """Create a mock network object.

    :param name: network name
    :param uuid: network UUID
    :returns: MagicMock configured as network
    """
    network = MagicMock()
    network.name = name
    network.uuid = uuid
    network.pool_uuid = "p-uuid"
    return network


def add_role_dirs(dirs):
    """Add role directories to sys.path.

    :param dirs: list of relative paths under ROLES
    """
    for d in dirs:
        dir_path = os.path.join(ROLES, d)
        if dir_path not in sys.path:
            sys.path.insert(0, dir_path)


def setup_pplr_mocks(pplr_mod):
    """Configure pplr module mocks for testing.

    :param pplr_mod: push_pull_local_registry module
    """
    from unittest.mock import MagicMock
    pplr_mod.get_local_registry_auth = lambda: {
        "username": "u", "password": "p"
    }
    pplr_mod.docker = MagicMock()
    pplr_mod.subprocess = MagicMock()
    pplr_mod.time = MagicMock()
    pplr_mod.docker.errors.APIError = type("APIError", (Exception,), {})


def setup_dli_mocks(dli_mod):
    """Configure download_images module mocks for testing.

    :param dli_mod: download_images module
    """
    from unittest.mock import MagicMock
    dli_mod.get_local_registry_auth = lambda: {
        "username": "u", "password": "p"
    }
    dli_mod.docker = MagicMock()
    dli_mod.subprocess = MagicMock()
    dli_mod.time = MagicMock()
    dli_mod.crictl_image_list = []
    dli_mod.backed_up_crictl_cache_images = None
