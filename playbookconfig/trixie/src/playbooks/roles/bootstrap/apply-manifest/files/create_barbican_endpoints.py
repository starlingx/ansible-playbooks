#!/usr/bin/python
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Create barbicans's user, grant it admin role and set up its services and endpoints.

It's necessary to perform the Barbican endpoint creation outside the
openstack_config_endpoints.py script because the registry secrets need to be created
before updating the sysinv database..
"""

import os
import sys
from subprocess import Popen, PIPE

from keystoneauth1 import loading, session
from keystoneclient.v3 import client
from sysinv.common import openstack_config_endpoints

BARBICAN_USER_TO_CREATE = [
    {
        "name": "barbican",
        "password": "",
        "email": "barbican@localhost",
    }
]

SERVICES_TO_CREATE = [
    {
        "name": "barbican",
        "description": "BarbicanService",
        "type": "key-manager",
    }
]

ENDPOINTS_TO_CREATE = [
    {
        "service": "barbican",
        "region": "RegionOne",
        "endpoints": {
            "admin": "http://127.0.0.1:9311",
            "internal": "http://127.0.0.1:9311",
            "public": "http://127.0.0.1:9311",
        },
    }
]


def _retrieve_environment_variables(username, password):
    with open(os.devnull, "w") as fnull:
        process = Popen(
            ["bash", "-c", "source /etc/platform/openrc --no_credentials && env"],
            stdout=PIPE,
            stderr=fnull,
            universal_newlines=True,
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

    process.communicate()

    return env_vars


def _generate_auth(env_vars):
    loader = loading.get_plugin_loader("password")

    return loader.load_from_options(
        auth_url=env_vars["auth_url"],
        username=env_vars["username"],
        password=env_vars["password"],
        project_name=env_vars["project_name"],
        user_domain_name=env_vars["user_domain_name"],
        project_domain_name=env_vars["project_domain_name"],
    )


def _create_keystone_client(env_vars):
    return client.Client(session=session.Session(auth=_generate_auth(env_vars)))


if __name__ == "__main__":
    username = sys.argv[1]
    password = sys.argv[2]
    BARBICAN_USER_TO_CREATE[0]["password"] = sys.argv[3]
    admin_username = sys.argv[4]

    env_vars = _retrieve_environment_variables(username, password)
    ENDPOINTS_TO_CREATE[0]["region"] = env_vars["region_name"]

    keystone = _create_keystone_client(env_vars)

    openstack_config_endpoints.create_users(keystone, BARBICAN_USER_TO_CREATE)
    openstack_config_endpoints.grant_admin_role(
        keystone, BARBICAN_USER_TO_CREATE, "services"
    )
    openstack_config_endpoints.create_services(keystone, SERVICES_TO_CREATE)
    openstack_config_endpoints.create_endpoints(keystone, ENDPOINTS_TO_CREATE)
