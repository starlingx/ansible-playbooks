#!/usr/bin/python

#
# Copyright (c) 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
#

import sys
import yaml
from sysinv.common.utils import is_valid_ipv4
from sysinv.common.utils import is_valid_ipv6


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
                else:
                    domain_names.append(value)

        if not domain_names or not (ipv4 or ipv6):
            raise ValueError("""User dns host-records has either null ip address
                            or domain name for host: """ + host)
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
        parse_user_dns_host_records(user_host_data)
    except ValueError as e:
        print(f"An error occurred during parsing user dns host-records: {str(e)}")
        raise e
