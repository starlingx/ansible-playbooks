#!/usr/bin/python

#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
#

import sys
import netaddr


def get_ip_version_of_network(network):
    return netaddr.IPNetwork(network).version


def get_ip_version_of_address(address):
    return netaddr.IPAddress(address).version


def validate(address_value, subnet_value):
    subnets = subnet_value.split(',')
    addresses = address_value.split(',')
    if len(subnets) != len(addresses):
        raise ValueError("Not of same size (single or dual-stack)")
    for i, address in enumerate(addresses):
        if get_ip_version_of_address(address) != get_ip_version_of_network(subnets[i]):
            raise ValueError("IP family does not match on sequence")


if __name__ == '__main__':
    address_key = sys.argv[1]
    address_value = sys.argv[2]
    subnet_key = sys.argv[3]
    subnet_value = sys.argv[4]

    try:
        validate(address_value, subnet_value)
    except ValueError as e:
        print(f"An error occurred during validating {address_key}:{address_value} vs {subnet_key}:{subnet_value} : {str(e)}")
        raise e
