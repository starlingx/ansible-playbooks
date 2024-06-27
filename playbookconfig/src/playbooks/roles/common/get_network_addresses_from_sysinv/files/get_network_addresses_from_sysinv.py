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
import sys

from cgtsclient import client as cgts_client
from sysinv.common import constants as sysinv_constants

NETWORK_TYPES = [sysinv_constants.NETWORK_TYPE_PXEBOOT,
                 sysinv_constants.NETWORK_TYPE_MGMT,
                 sysinv_constants.NETWORK_TYPE_OAM,
                 sysinv_constants.NETWORK_TYPE_CLUSTER_HOST,
                 sysinv_constants.NETWORK_TYPE_CLUSTER_POD,
                 sysinv_constants.NETWORK_TYPE_CLUSTER_SERVICE,
                 sysinv_constants.NETWORK_TYPE_ADMIN,
                 sysinv_constants.NETWORK_TYPE_MULTICAST,
                 sysinv_constants.NETWORK_TYPE_SYSTEM_CONTROLLER,
                 sysinv_constants.NETWORK_TYPE_SYSTEM_CONTROLLER_OAM]

NETWORK_STACK_PRIMARY = "primary"
NETWORK_STACK_SECONDARY = "secondary"
NETWORK_STACKS = [NETWORK_STACK_PRIMARY, NETWORK_STACK_SECONDARY]


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


def get_network(client, network_type):
    networks = client.sysinv.network.list()
    for network in networks:
        if network.type == network_type:
            return network
    return None


def get_addresses_of_pool(client, pool_uuid):
    values = {'floating_address': None,
              'controller0_address': None,
              'controller1_address': None,
              'gateway_address': None}

    address_pool = client.sysinv.address_pool.get(pool_uuid)
    if address_pool:
        values['floating_address'] = address_pool.floating_address
        values['controller0_address'] = address_pool.controller0_address
        values['controller1_address'] = address_pool.controller1_address
        values['gateway_address'] = address_pool.gateway_address
    return values


def get_secondary_pool_uuid(client, network_uuid, primary_pool_uuid):
    network_addrpools = client.sysinv.network_addrpool.list()
    for network_addrpool in network_addrpools:
        if (network_addrpool.network_uuid == network_uuid and
                network_addrpool.address_pool_uuid != primary_pool_uuid):
            return network_addrpool.address_pool_uuid
    return None


def get_addresses(client, network_type, network_stack):
    network_uuid = None
    primary_pool_uuid = None
    secondary_pool_uuid = None
    values = {'floating_address': None,
              'controller0_address': None,
              'controller1_address': None,
              'gateway_address': None}

    network = get_network(client, network_type)
    if not network:
        return values

    network_uuid = network.uuid
    primary_pool_uuid = network.pool_uuid

    if not network_uuid or not primary_pool_uuid:
        return values

    if network_stack == NETWORK_STACK_PRIMARY:
        values = get_addresses_of_pool(client, primary_pool_uuid)
    elif network_stack == NETWORK_STACK_SECONDARY:
        secondary_pool_uuid = get_secondary_pool_uuid(client, network_uuid, primary_pool_uuid)
        if secondary_pool_uuid:
            values = get_addresses_of_pool(client, secondary_pool_uuid)
    else:
        pass

    return values


def handle_invalid_input():
    raise Exception(f"Invalid input!\nUsage: <network-type> <network-stack>"
                    f"\nnetwork-type: {NETWORK_TYPES}"
                    f"\nnetwork-stack: {NETWORK_STACKS}")


if __name__ == '__main__':
    argc = len(sys.argv)
    if argc != 3 or sys.argv[1] not in NETWORK_TYPES or sys.argv[2] not in NETWORK_STACKS:
        print("Failed")
        handle_invalid_input()

    network_type = sys.argv[1]
    network_stack = sys.argv[2]
    try:
        client = CgtsClient()
        addresses = get_addresses(client, network_type, network_stack)
        for key in addresses:
            print(f'{key}={addresses[key]}')
    except Exception:
        print("Failed to get {network_type}'s {network_stack} address")
        raise
