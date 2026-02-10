#!/usr/bin/python
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Configure keystone by adding the services project, _member_ role, updating
the admin user to the correct e-mail address, creating the identity service and
creating the initial (RegionOne) endpoints for keystone.
"""

import os
from subprocess import PIPE
from subprocess import Popen
import sys

from sysinv.common import openstack_config_endpoints

from keystoneauth1 import loading
from keystoneauth1 import session
from keystoneclient.v3 import client


PROJECTS_TO_CREATE = [
    {
        "name": "services",
        "domain": "default",
        "description": "",
        "parent": "default"
    }
]

ROLES_TO_CREATE = [
    {
        "name": "_member_",
        "domain": None
    },
    {
        "name": "operator",
        "domain": None
    },
    {
        "name": "configurator",
        "domain": None
    },
]

USERS_TO_UPDATE = [{"name": "admin", "email": "admin@localhost"}]

SERVICES_TO_CREATE = [
    {
        "name": "keystone",
        "description": "KeystoneService",
        "type": "identity",
    }
]

ENDPOINTS_TO_CREATE = [
    {
        "service": "keystone",
        "endpoints": {
            "admin": "http://127.0.0.1:5000",
            "internal": "http://127.0.0.1:5000",
            "public": "http://127.0.0.1:5000",
        },
    }
]


def _retrieve_environment_variables(username, password):
    with open(os.devnull, "w") as fnull:
        process = Popen(
            ["bash", "-c", "source /etc/platform/openrc --no_credentials && env"],
            stdout=PIPE, stderr=fnull, universal_newlines=True
        )

    env_vars = {}
    env_vars["username"] = username
    env_vars["password"] = password
    env_vars["user_domain_name"] = "Default"
    env_vars["project_domain_name"] = "Default"

    for line in process.stdout:
        key, _, value = line.partition("=")
        if key == "OS_AUTH_URL":
            env_vars["auth_url"] = value.strip()
        elif key == "OS_REGION_NAME":
            env_vars["region_name"] = value.strip()
        elif key == "OS_PROJECT_NAME":
            env_vars["project_name"] = value.strip()
        elif key == "OS_USER_DOMAIN_NAME":
            env_vars["user_domain_name"] = value.strip()
        elif key == "OS_PROJECT_DOMAIN_NAME":
            env_vars["project_domain_name"] = value.strip()

    process.communicate()

    return env_vars


def _generate_auth(env_vars):
    loader = loading.get_plugin_loader("password")

    return loader.load_from_options(
        auth_url=env_vars["auth_url"], username=env_vars["username"],
        password=env_vars["password"], project_name=env_vars["project_name"],
        user_domain_name=env_vars["user_domain_name"],
        project_domain_name=env_vars["project_domain_name"]
    )


def _create_keystone_client(env_vars):
    return client.Client(session=session.Session(auth=_generate_auth(env_vars)))


if __name__ == "__main__":
    username = sys.argv[1]
    password = sys.argv[2]

    env_vars = _retrieve_environment_variables(username, password)
    keystone = _create_keystone_client(env_vars)
    # This value is overridden based on distributed_cloud_role
    # if distributed_cloud_role is subcloud or none region_name will
    # be UUID value else in case of systemcontroller it will be
    # default 'RegionOne'
    ENDPOINTS_TO_CREATE[0]["region"] = env_vars["region_name"]

    openstack_config_endpoints.create_projects(keystone, PROJECTS_TO_CREATE)
    openstack_config_endpoints.create_roles(keystone, ROLES_TO_CREATE)
    openstack_config_endpoints.update_users(keystone, USERS_TO_UPDATE)
    openstack_config_endpoints.create_services(keystone, SERVICES_TO_CREATE)
    openstack_config_endpoints.create_endpoints(keystone, ENDPOINTS_TO_CREATE)
