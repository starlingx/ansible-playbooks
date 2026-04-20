#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Helper to inject mock system dependencies into sys.modules.

Call install_mocks() before importing any StarlingX module that
depends on packages not available in the test environment.
"""

import sys
import types
from unittest.mock import MagicMock


def _make_module(name, attrs=None):
    """Create a fake module with optional attributes.

    :param name: module name string
    :param attrs: dict of attribute names to values
    :returns: a new module object with given attributes
    :rtype: types.ModuleType
    """
    mod = types.ModuleType(name)
    if attrs:
        for key, value in attrs.items():
            setattr(mod, key, value)
    return mod


def install_mocks():
    """Inject all missing StarlingX dependencies as mocks.

    Populates sys.modules with MagicMock objects for
    packages not available in the test environment.
    Sets required constants on sysinv and fm_api mocks.

    :returns: None
    """
    # Only install if not already present
    if "cgtsclient" in sys.modules:
        return

    mock_names = [
        # sysinv
        "sysinv",
        "sysinv.common",
        "sysinv.common.constants",
        "sysinv.common.utils",
        "sysinv.common.openstack_config_endpoints",
        "sysinv.conductor",
        "sysinv.conductor.rpcapiproxy",
        # cgtsclient
        "cgtsclient",
        "cgtsclient.client",
        "cgtsclient.exc",
        # tsconfig
        "tsconfig",
        "tsconfig.tsconfig",
        # fm_api
        "fm_api",
        "fm_api.constants",
        "fm_api.fm_api",
        # keyring / keystone / barbican / oslo
        "keyring",
        "keystoneauth1",
        "keystoneauth1.identity",
        "keystoneauth1.identity.v3",
        "keystoneauth1.session",
        "keystoneauth1.exceptions",
        "keystoneauth1.exceptions.http",
        "keystoneclient",
        "keystoneclient.v3",
        "keystoneclient.v3.client",
        "keystoneclient.auth",
        "keystoneclient.auth.identity",
        "keystoneclient.auth.identity.v3",
        "keystoneclient.session",
        "keystoneclient.exceptions",
        "keystoneauth1.loading",
        "barbicanclient",
        "barbicanclient.client",
        "oslo_config",
        "oslo_config.cfg",
        "oslo_context",
        "oslo_context.context",
        # psycopg2
        "psycopg2",
        "psycopg2.extras",
        # docker / eventlet
        "docker",
        "docker.errors",
        "eventlet",
        "eventlet.greenpool",
        # boto3 / botocore
        "boto3",
        "botocore",
        "botocore.config",
        # pyudev / parted / six
        "pyudev",
        "parted",
        "six",
        "six.moves",
        "six.moves.configparser",
        # software_client
        "software_client",
        "software_client.auth",
    ]

    for name in mock_names:
        if name not in sys.modules:
            sys.modules[name] = MagicMock()

    # Set specific constants needed by source code
    fm_const = sys.modules["fm_api.constants"]
    fm_const.FM_ALARM_STATE_SET = "set"
    fm_const.FM_ALARM_STATE_CLEAR = "clear"
    fm_const.FM_ENTITY_TYPE_HOST = "host"
    fm_const.FM_ENTITY_TYPE_STORAGE_BACKEND = "storage-backend"
    fm_const.FM_ALARM_CRITICAL_STATUS = "critical"
    fm_const.FM_ALARM_TYPE_0 = "0"
    fm_const.FM_ALARM_TYPE_5 = "5"
    fm_const.FM_ALARM_TYPE_7 = "7"
    fm_const.ALARM_PROBABLE_CAUSE_UNKNOWN = "unknown"
    fm_const.ALARM_PROBABLE_CAUSE_8 = "8"
    fm_const.ALARM_PROBABLE_CAUSE_39 = "39"
    fm_const.ALARM_PROBABLE_CAUSE_75 = "75"
    fm_const.FM_ALARM_SEVERITY_MINOR = "minor"
    fm_const.FM_ALARM_SEVERITY_MAJOR = "major"
    fm_const.FM_ALARM_SEVERITY_WARNING = "warning"
    fm_const.FM_ALARM_ID_BACKUP_IN_PROGRESS = "250.001"
    fm_const.FM_ALARM_ID_SW_UPGRADE_AUTO_APPLY_FAILED = "900.401"
    fm_const.FM_ALARM_ID_STORAGE_CEPH = "800.001"

    sysinv_const = sys.modules["sysinv.common.constants"]
    for attr in [
        "NETWORK_TYPE_MGMT",
        "NETWORK_TYPE_OAM",
        "NETWORK_TYPE_ADMIN",
        "NETWORK_TYPE_PXEBOOT",
        "NETWORK_TYPE_MULTICAST",
        "NETWORK_TYPE_CLUSTER_HOST",
        "NETWORK_TYPE_CLUSTER_POD",
        "NETWORK_TYPE_CLUSTER_SERVICE",
        "NETWORK_TYPE_SYSTEM_CONTROLLER",
        "NETWORK_TYPE_SYSTEM_CONTROLLER_OAM",
        "SYSTEM_MODE_SIMPLEX",
        "SYSTEM_MODE_DUPLEX",
        "DISTRIBUTED_CLOUD_ROLE_SUBCLOUD",
        "CONTROLLER_HOSTNAME",
        "CONTROLLER",
        "ADMIN_LOCKED",
        "OPERATIONAL_DISABLED",
        "AVAILABILITY_OFFLINE",
        "PROVISIONING",
        "INV_STATE_INITIAL_INVENTORIED",
        "DEVICE_NAME_NVME",
        "DEVICE_NAME_DM",
        "DEVICE_NAME_MPATH",
        "INTERFACE_TYPE_VLAN",
        "INTERFACE_TYPE_ETHERNET",
        "INTERFACE_TYPE_AE",
        "INTERFACE_CLASS_PLATFORM",
        "MGMT_IPSEC_FLAG",
    ]:
        setattr(sysinv_const, attr, attr.lower())

    # Service parameter constants
    for attr in [
        "SERVICE_TYPE_DOCKER",
        "SERVICE_TYPE_KUBERNETES",
        "SERVICE_TYPE_PLATFORM",
        "SERVICE_TYPE_DNS",
        "SERVICE_PARAM_NAME_DOCKER_HTTP_PROXY",
        "SERVICE_PARAM_NAME_DOCKER_HTTPS_PROXY",
        "SERVICE_PARAM_NAME_DOCKER_NO_PROXY",
        "SERVICE_PARAM_NAME_DOCKER_URL",
        "SERVICE_PARAM_NAME_DOCKER_AUTH_SECRET",
        "SERVICE_PARAM_NAME_DOCKER_TYPE",
        "SERVICE_PARAM_NAME_DOCKER_SECURE_REGISTRY",
        "SERVICE_PARAM_NAME_DOCKER_ADDITIONAL_OVERRIDES",
        "SERVICE_PARAM_SECTION_DOCKER_PROXY",
        "SERVICE_PARAM_SECTION_DOCKER_K8S_REGISTRY",
        "SERVICE_PARAM_SECTION_DOCKER_GCR_REGISTRY",
        "SERVICE_PARAM_SECTION_DOCKER_QUAY_REGISTRY",
        "SERVICE_PARAM_SECTION_DOCKER_DOCKER_REGISTRY",
        "SERVICE_PARAM_SECTION_DOCKER_ELASTIC_REGISTRY",
        "SERVICE_PARAM_SECTION_DOCKER_GHCR_REGISTRY",
        "SERVICE_PARAM_SECTION_DOCKER_REGISTRYK8S_REGISTRY",
        "SERVICE_PARAM_SECTION_DOCKER_ICR_REGISTRY",
        "SERVICE_PARAM_SECTION_KUBERNETES_APISERVER",
        "SERVICE_PARAM_SECTION_KUBERNETES_APISERVER_VOLUMES",
        "SERVICE_PARAM_SECTION_KUBERNETES_CONTROLLER_MANAGER",
        "SERVICE_PARAM_SECTION_KUBERNETES_CONTROLLER_MANAGER_VOLUMES",
        "SERVICE_PARAM_SECTION_KUBERNETES_SCHEDULER",
        "SERVICE_PARAM_SECTION_KUBERNETES_SCHEDULER_VOLUMES",
        "SERVICE_PARAM_SECTION_KUBERNETES_KUBELET",
        "SERVICE_PARAM_SECTION_KUBERNETES_CONFIG",
        "SERVICE_PARAM_SECTION_PLATFORM_CONFIG",
        "SERVICE_PARAM_SECTION_PLATFORM_DRBD",
        "SERVICE_PARAM_SECTION_DNS_HOST_RECORD",
        "SERVICE_PARAM_SECTION_DNS_LOCAL",
        "SERVICE_PARAM_NAME_PLAT_CONFIG_VIRTUAL",
        "SERVICE_PARAM_NAME_DRBD_HMAC",
        "SERVICE_PARAM_NAME_DRBD_SECRET",
        "SERVICE_PARAM_NAME_DRBD_SECURE",
        "SERVICE_PARAM_NAME_KUBERNETES_POD_MAX_PIDS",
        "SERVICE_PARAM_KUBERNETES_POD_MAX_PIDS_DEFAULT",
        "SERVICE_PARAM_NAME_OIDC_ISSUER_URL",
        "SERVICE_PARAM_NAME_OIDC_CLIENT_ID",
        "SERVICE_PARAM_NAME_OIDC_USERNAME_CLAIM",
        "SERVICE_PARAM_NAME_OIDC_GROUPS_CLAIM",
        "SERVICE_PARAM_NAME_PLATFORM_TLS_MIN_VERSION",
        "SERVICE_PARAM_NAME_PLATFORM_TLS_CIPHER_SUITE",
        "SERVICE_PARAM_PLATFORM_TLS_MIN_VERSION_DEFAULT",
        "SERVICE_PARAM_PLATFORM_TLS_CIPHER_SUITE_DEFAULT",
    ]:
        setattr(sysinv_const, attr, attr.lower())

    sysinv_utils = sys.modules["sysinv.common.utils"]
    sysinv_utils.generate_random_password = lambda: "random_password"
    sysinv_utils.is_valid_dns_hostname = lambda h: True
    sysinv_utils.is_valid_ipv4 = lambda a: "." in a and all(
        p.isdigit() for p in a.split(".")
    )
    sysinv_utils.is_valid_ipv6 = lambda a: ":" in a

    # six.moves.configparser -> configparser
    import configparser

    sys.modules["six.moves.configparser"] = configparser

    # psycopg2 extras
    psycopg2_extras = sys.modules["psycopg2.extras"]
    psycopg2_extras.RealDictCursor = "RealDictCursor"

    # tsconfig
    tsc = sys.modules["tsconfig.tsconfig"]
    tsc.system_type = "All-in-one"
    tsc.system_mode = "simplex"
    tsc.PLATFORM_CONF_PATH = "/tmp"
    tsc.MGMT_NETWORK_RECONFIGURATION_ONGOING = "/tmp/.mgmt_reconfig"

    # docker.errors
    docker_errors = sys.modules["docker.errors"]
    docker_errors.APIError = type("APIError", (Exception,), {})
    docker_errors.NotFound = type("NotFound", (Exception,), {})

    # oslo_config.cfg
    oslo_cfg = sys.modules["oslo_config.cfg"]
    oslo_cfg.CONF = MagicMock()

    # conductor rpcapi
    rpcapi = sys.modules["sysinv.conductor.rpcapiproxy"]
    rpcapi.MANAGER_TOPIC = "sysinv.conductor_manager"
    rpcapi.ConductorAPI = MagicMock
