#!/usr/bin/python
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
import psycopg2

from psycopg2.extras import RealDictCursor


def get_hostnames_list():
    ip_addr_list = []
    conn = psycopg2.connect("dbname='sysinv' user='postgres'")
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("select network from address_pools where name='management';")
            ret = cur.fetchall()
            if ret is None:
                return ip_addr_list
            network = ret[0]['network'].rstrip('0')

            cur.execute("select address from addresses;")
            rows = cur.fetchall()
            if rows is None:
                return ip_addr_list

            ip_addr_list = [record['address']
                            for record in rows
                            if network in record['address']]

    return ip_addr_list


if __name__ == '__main__':
    ip_addr_list = get_hostnames_list()
    print(ip_addr_list)
