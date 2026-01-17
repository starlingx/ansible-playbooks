#!/usr/bin/python
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
import os

platform_conf_file = '/etc/platform/platform.conf'


def get_software_version():
    value = None

    if not os.path.exists(platform_conf_file):
        return value

    with open(platform_conf_file) as fp:
        lines = fp.readlines()
        for line in lines:
            if line.find('sw_version') != -1:
                value = line.split('=')[1]
                value = value.replace('\n', '')

    return value


def get_pxeboot_addrs_list():
    ip_addr_list = []
    version = None
    dnsmasq_hosts_file = None

    conf_dir = '/opt/platform/config/'
    version = get_software_version()
    if version is None:
        return ip_addr_list

    dnsmasq_hosts_file = conf_dir + version + '/dnsmasq.hosts'
    if not os.path.exists(dnsmasq_hosts_file):
        return ip_addr_list

    with open(dnsmasq_hosts_file) as file:
        for line in file:
            if line.find('pxecontroller') != -1:
                continue

            list = line.split(",")
            ip_addr_list.append(list[2])

    return ip_addr_list


if __name__ == '__main__':

    ip_addr_list = get_pxeboot_addrs_list()
    print(ip_addr_list)
