#!/usr/bin/python

#
# Copyright (c) 2023-2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
#

import sys
import yaml

from sysinv.common.utils import is_valid_dns_hostname
from sysinv.common.utils import is_valid_ipv4
from sysinv.common.utils import is_valid_ipv6


def check_duplicate_host_records(user_host_data):
    host_record_list = []
    for host, value in user_host_data.items():
        value_set = set(x.strip() for x in value.split(','))
        if value_set not in host_record_list:
            host_record_list.append(value_set)
        else:
            msg = "User dns host-records has duplicate: %s" % (value)
            raise ValueError(msg)


def parse_user_dns_host_records(user_host_data):

    for host, values in user_host_data.items():
        values_list = [value.strip() for value in values.split(',')]
        ipv4, ipv6, domain_names = None, None, []

        for value in values_list:
            if not value.isdigit():
                if is_valid_ipv4(value):
                    ipv4 = value
                elif is_valid_ipv6(value):
                    ipv6 = value
                elif is_valid_dns_hostname(value if '.' in value else value + '.dummy'):
                    # If hostname does not contain Top-Level Domain (TLD),
                    # append 'dummy' as TLD for the input of is_valid_dns_hostname()
                    domain_names.append(value)
                else:
                    raise ValueError("Invalid DNS domain name: %s" % (value))

        if not domain_names or not (ipv4 or ipv6):
            msg = "User dns host-records has invalid format: {%s: %s}" % (host, values)
            raise ValueError(msg)
        if ipv4:
            ipv4_entry = " ".join([ipv4] + [str(domain_name) for domain_name in domain_names])
            print(ipv4_entry)
        if ipv6:
            ipv6_entry = " ".join([ipv6] + [str(domain_name) for domain_name in domain_names])
            print(ipv6_entry)


if __name__ == '__main__':

    user_host_data_yaml = sys.argv[1]
    user_host_data = yaml.safe_load(user_host_data_yaml)
    try:
        check_duplicate_host_records(user_host_data)
        parse_user_dns_host_records(user_host_data)
    except ValueError as e:
        print(f"An error occurred during parsing user dns host-records: {str(e)}")
        raise e
