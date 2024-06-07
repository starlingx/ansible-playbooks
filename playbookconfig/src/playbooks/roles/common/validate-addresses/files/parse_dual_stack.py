#!/usr/bin/python

#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
#

"""
Validate comma separated dual-stack subnets or addresses
and parse them into primary and secondary category.
"""

import sys

from sysinv.common.utils import is_valid_cidr
from sysinv.common.utils import is_valid_ipv4
from sysinv.common.utils import is_valid_ipv6
from sysinv.common.utils import is_valid_ipv6_cidr

IPv4 = 'ipv4'
IPv6 = 'ipv6'


def get_family_of_address(address):
    if is_valid_ipv4(address):
        return IPv4
    elif is_valid_ipv6(address):
        return IPv6
    else:
        raise ValueError(f"Invalid IP address: {address}")


def get_family_of_cidr(network):
    if is_valid_ipv6_cidr(network):
        return IPv6
    elif is_valid_cidr(network):
        return IPv4
    else:
        raise ValueError(f"Invalid IP network: {network}")


def validate(network_param_value):
    ip_family = []
    cidr_address = []
    CIDR = 0
    ADDRESS = 1

    network_values = network_param_value.split(',')

    if len(network_values) > 2:
        raise ValueError("More than two IPs not supported")

    for network_value in network_values:
        if "/" in network_value:
            cidr_address.append(CIDR)
            ip_family.append(get_family_of_cidr(network_value))
        else:
            cidr_address.append(ADDRESS)
            ip_family.append(get_family_of_address(network_value))

    if len(network_values) == 2 and ip_family[0] == ip_family[1]:
        raise ValueError("Dual-stack of same IP family not supported")

    if len(network_values) == 2 and cidr_address[0] != cidr_address[1]:
        raise ValueError("Value should be both either Subnet or Address")

    primary = network_values[0]
    print(f"primary={primary}")

    if len(network_values) == 2:
        print(f"secondary={network_values[1]}")
    else:
        print("secondary=False")


if __name__ == '__main__':
    network_param_key = sys.argv[1]
    network_param_value = sys.argv[2]
    try:
        validate(network_param_value)
    except ValueError as e:
        print(f"An error occurred during parsing {network_param_key}:"
              f"{network_param_value} : {str(e)}")
        raise e
