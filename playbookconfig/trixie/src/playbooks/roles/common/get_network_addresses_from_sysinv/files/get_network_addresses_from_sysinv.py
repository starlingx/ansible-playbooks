#!/usr/bin/python

#
# Copyright (c) 2024-2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# OpenStack Keystone and Sysinv interactions
#
# Retrieve addresses (floating_address, controller0_address,
# controller1_address, gateway_address) as individual lines
# of key=value of given network type and given network stack
# (primary/secondary).

import argparse
from functools import lru_cache
import json
import os
import subprocess

from cgtsclient import client as cgts_client
from sysinv.common import constants as sysinv_constants

NETWORK_TYPES = [
    sysinv_constants.NETWORK_TYPE_PXEBOOT,
    sysinv_constants.NETWORK_TYPE_MGMT,
    sysinv_constants.NETWORK_TYPE_OAM,
    sysinv_constants.NETWORK_TYPE_CLUSTER_HOST,
    sysinv_constants.NETWORK_TYPE_CLUSTER_POD,
    sysinv_constants.NETWORK_TYPE_CLUSTER_SERVICE,
    sysinv_constants.NETWORK_TYPE_ADMIN,
    sysinv_constants.NETWORK_TYPE_MULTICAST,
    sysinv_constants.NETWORK_TYPE_SYSTEM_CONTROLLER,
    sysinv_constants.NETWORK_TYPE_SYSTEM_CONTROLLER_OAM,
]

NETWORK_STACK_PRIMARY = "primary"
NETWORK_STACK_SECONDARY = "secondary"
NETWORK_STACKS = [NETWORK_STACK_PRIMARY, NETWORK_STACK_SECONDARY]


class CgtsClient(object):
    SYSINV_API_VERSION = 1

    def __init__(self):
        self.conf = {}
        self._sysinv = None

        self.auth_token = os.getenv("OS_AUTH_TOKEN")
        self.system_url = os.getenv("SYSTEM_URL")

        if not (self.auth_token and self.system_url):
            source_command = "source /etc/platform/openrc && env"

            with open(os.devnull, "w") as fnull:
                proc = subprocess.Popen(
                    ["bash", "-c", source_command],
                    stdout=subprocess.PIPE,
                    stderr=fnull,
                    universal_newlines=True,
                )

            for line in proc.stdout:
                key, _, value = line.partition("=")
                if key == "OS_USERNAME":
                    self.conf["admin_user"] = value.strip()
                elif key == "OS_PASSWORD":
                    self.conf["admin_pwd"] = value.strip()
                elif key == "OS_PROJECT_NAME":
                    self.conf["admin_tenant"] = value.strip()
                elif key == "OS_AUTH_URL":
                    self.conf["auth_url"] = value.strip()
                elif key == "OS_REGION_NAME":
                    self.conf["region_name"] = value.strip()
                elif key == "OS_USER_DOMAIN_NAME":
                    self.conf["user_domain"] = value.strip()
                elif key == "OS_PROJECT_DOMAIN_NAME":
                    self.conf["project_domain"] = value.strip()

            proc.communicate()

    @property
    def sysinv(self):
        if not self._sysinv:
            if self.auth_token and self.system_url:
                self._sysinv = cgts_client.get_client(
                    str(self.SYSINV_API_VERSION),
                    os_auth_token=self.auth_token,
                    system_url=self.system_url,
                )
            else:
                self._sysinv = cgts_client.get_client(
                    self.SYSINV_API_VERSION,
                    os_username=self.conf["admin_user"],
                    os_password=self.conf["admin_pwd"],
                    os_auth_url=self.conf["auth_url"],
                    os_project_name=self.conf["admin_tenant"],
                    os_project_domain_name=self.conf["project_domain"],
                    os_user_domain_name=self.conf["user_domain"],
                    os_region_name=self.conf["region_name"],
                    os_service_type="platform",
                    os_endpoint_type="internal",
                )
        return self._sysinv


@lru_cache(maxsize=None)
def _get_network_list(client):
    return client.sysinv.network.list()


@lru_cache(maxsize=None)
def _get_addrpool_list(client):
    return client.sysinv.address_pool.list()


@lru_cache(maxsize=None)
def _get_network_addrpool_list(client):
    return client.sysinv.network_addrpool.list()


def _addrpool_list_to_dict(addrpool_list):
    return {addrpool.uuid: addrpool for addrpool in addrpool_list}


def get_network(client, network_type):
    networks = _get_network_list(client)
    for network in networks:
        if network.type == network_type:
            return network
    return None


def get_addresses_of_pool(client, pool_uuid):
    values = {
        "floating_address": None,
        "controller0_address": None,
        "controller1_address": None,
        "gateway_address": None,
    }

    network_addrpools = _get_addrpool_list(client)
    addrpools_dict = _addrpool_list_to_dict(network_addrpools)
    address_pool = addrpools_dict.get(pool_uuid)
    if address_pool:
        values["floating_address"] = address_pool.floating_address
        values["controller0_address"] = address_pool.controller0_address
        values["controller1_address"] = address_pool.controller1_address
        values["gateway_address"] = address_pool.gateway_address
    return values


def get_secondary_pool_uuid(client, network_uuid, primary_pool_uuid):
    network_addrpools = _get_network_addrpool_list(client)
    for network_addrpool in network_addrpools:
        if (
            network_addrpool.network_uuid == network_uuid and
                network_addrpool.address_pool_uuid != primary_pool_uuid
        ):
            return network_addrpool.address_pool_uuid
    return None


def get_addresses(client, network_type, network_stack):
    network_uuid = None
    primary_pool_uuid = None
    secondary_pool_uuid = None
    values = {
        "floating_address": None,
        "controller0_address": None,
        "controller1_address": None,
        "gateway_address": None,
    }

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
        secondary_pool_uuid = get_secondary_pool_uuid(
            client, network_uuid, primary_pool_uuid
        )
        if secondary_pool_uuid:
            values = get_addresses_of_pool(client, secondary_pool_uuid)

    return values


def main():
    help_text = f"""
        Processes network requests from a JSON string.
        The JSON can be a single object or an array of objects.

        Valid values:
        - network-type: {NETWORK_TYPES}
        - network-stack: {NETWORK_STACKS}
    """
    parser = argparse.ArgumentParser(
        description="Get network addresses from sysinv",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=help_text,
    )

    parser.add_argument(
        "json_input",
        help=(
            "A JSON string of a list of dicts with "
            "'network_type' and 'network_stack' keys"
        ),
    )

    args = parser.parse_args()

    try:
        results = {}
        data = json.loads(args.json_input)
        if isinstance(data, dict):
            data = [data]
        client = CgtsClient()
        for params in data:
            network_type = params.get("network_type")
            network_stack = params.get("network_stack")
            try:
                addresses = get_addresses(client, network_type, network_stack)
                key = f"{network_type}_{network_stack}"
                key = key.replace("-", "_")
                results[key] = addresses
            except Exception as e:
                raise Exception(f"Error processing {params}: {e}")
        print(json.dumps(results))
    except json.JSONDecodeError:
        raise ValueError(f"Error: Invalid JSON provided: {args.json_input}")


if __name__ == "__main__":
    main()
