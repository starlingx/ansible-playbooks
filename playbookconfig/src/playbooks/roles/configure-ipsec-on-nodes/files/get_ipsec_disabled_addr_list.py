#!/usr/bin/python
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
import json
import os
import psycopg2

from psycopg2.extras import RealDictCursor

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
    pxeboot_addr_dict = {}
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
            pxeboot_addr_dict[list[0]] = list[2]

    conn = psycopg2.connect("dbname='sysinv' user='postgres'")
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("select mgmt_mac,capabilities from i_host")
            rows = cur.fetchall()
            if rows is None:
                return ip_addr_list

            for record in rows:
                mgmt_mac = record['mgmt_mac']
                capabilities = json.loads(record['capabilities'])

                if 'mgmt_ipsec' not in capabilities or \
                    capabilities['mgmt_ipsec'] != 'enabled':
                    ip_addr_list.append(pxeboot_addr_dict[mgmt_mac])

    return ip_addr_list


if __name__ == '__main__':
    ip_addr_list = get_pxeboot_addrs_list()
    print(ip_addr_list)
