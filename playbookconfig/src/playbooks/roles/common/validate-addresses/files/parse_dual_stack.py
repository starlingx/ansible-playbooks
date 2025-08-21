#!/usr/bin/python

#
# Copyright (c) 2024-2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
#

"""
Validate comma separated dual-stack subnets or addresses
and parse them into primary and secondary category.
"""

import sys

import netaddr

IPv4 = 'ipv4'
IPv6 = 'ipv6'

# NOTE: importing from sysinv.common.utils takes too long, need to move this to a
# common lighter utils file to avoid duplicating code here


def is_valid_cidr(address):
    """Check if the provided ipv4 or ipv6 address is a valid CIDR address."""
    try:
        # Validate the correct CIDR Address
        netaddr.IPNetwork(address)
    except netaddr.core.AddrFormatError:
        return False
    except UnboundLocalError:
        # NOTE(MotoKen): work around bug in netaddr 0.7.5 (see detail in
        # https://github.com/drkjam/netaddr/issues/2)
        return False

    # Prior validation partially verify /xx part
    # Verify it here
    ip_segment = address.split('/')

    if (len(ip_segment) <= 1 or ip_segment[1] == ''):
        return False

    return True


def is_valid_ipv4(address):
    """Verify that address represents a valid IPv4 address."""
    try:
        return netaddr.valid_ipv4(address)
    except Exception:
        return False


def is_valid_ipv6(address):
    try:
        return netaddr.valid_ipv6(address)
    except Exception:
        return False


def is_valid_ipv6_cidr(address):
    try:
        str(netaddr.IPNetwork(address, version=6).cidr)
        return True
    except Exception:
        return False


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
