#!/usr/bin/python
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# OpenStack Keystone and Sysinv interactions
#
# Retrieve addresses (floating_address, controller0_address,
# controller1_address, gateway_address) as individual lines
# of key=value of given network type and given network stack
# (primary/secondary).


import os
import subprocess
import re
import sys
from packaging import version

from cgtsclient import client as cgts_client


class CgtsClient(object):
    SYSINV_API_VERSION = 1

    def __init__(self):
        self.conf = {}
        self._sysinv = None

        source_command = 'source /etc/platform/openrc && env'

        with open(os.devnull, "w") as fnull:
            proc = subprocess.Popen(
                ['bash', '-c', source_command],
                stdout=subprocess.PIPE, stderr=fnull,
                universal_newlines=True)

        for line in proc.stdout:
            key, _, value = line.partition("=")
            if key == 'OS_USERNAME':
                self.conf['admin_user'] = value.strip()
            elif key == 'OS_PASSWORD':
                self.conf['admin_pwd'] = value.strip()
            elif key == 'OS_PROJECT_NAME':
                self.conf['admin_tenant'] = value.strip()
            elif key == 'OS_AUTH_URL':
                self.conf['auth_url'] = value.strip()
            elif key == 'OS_REGION_NAME':
                self.conf['region_name'] = value.strip()
            elif key == 'OS_USER_DOMAIN_NAME':
                self.conf['user_domain'] = value.strip()
            elif key == 'OS_PROJECT_DOMAIN_NAME':
                self.conf['project_domain'] = value.strip()

        proc.communicate()

    @property
    def sysinv(self):
        if not self._sysinv:
            self._sysinv = cgts_client.get_client(
                self.SYSINV_API_VERSION,
                os_username=self.conf['admin_user'],
                os_password=self.conf['admin_pwd'],
                os_auth_url=self.conf['auth_url'],
                os_project_name=self.conf['admin_tenant'],
                os_project_domain_name=self.conf['project_domain'],
                os_user_domain_name=self.conf['user_domain'],
                os_region_name=self.conf['region_name'],
                os_service_type='platform',
                os_endpoint_type='internal')
        return self._sysinv


def parse_version(version):
    # remove letters before the version number
    # i.e: "v1.24.4ab" will return "1.24.4ab"
    return re.sub(r'^[^\d]*', '', version)


def get_kubernetes_version(client):
    values = client.sysinv.kube_version.list()

    version_list = []
    for value in values:
        version_list.append(parse_version(value.version))

    return version_list


def handle_invalid_input():
    raise Exception("Invalid input!\nUsage: < all|latest|<version> >"
                    "\nall (default): get the list of all supported K8s version"
                    "\nlatest: get just the latest supported K8S version"
                    "\n<version>: the minimum version, get just the same or higher supported K8s version"
                    )


if __name__ == '__main__':
    argc = len(sys.argv)
    min_version = ""
    # default is to get all versions
    latest = False

    if argc == 2:
        if sys.argv[1] == "latest":
            latest = True
        elif sys.argv[1] == "all":
            latest = False
        else:
            min_version = sys.argv[1]
    elif argc > 2:
        print('Failed')
        handle_invalid_input()

    try:
        client = CgtsClient()
        kube_version = get_kubernetes_version(client)
        filtered_list = kube_version

        if latest and kube_version:
            filtered_list = [kube_version[-1]]
        elif min_version:
            min_ver = version.parse(min_version)
            filtered_list = [v for v in filtered_list
                             if version.parse(v) >= min_ver]

        for value in filtered_list:
            print(f'{value}')

    except Exception:
        print("Failed to get supported K8s version list")
        raise
