#!/usr/bin/python
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
import psycopg2

from psycopg2.extras import RealDictCursor


def get_hostnames_list():
    hostnames_list = []
    conn = psycopg2.connect("dbname='sysinv' user='postgres'")
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("select hostname from i_host;")
            rows = cur.fetchall()
            if rows is None or len(rows) == 0:
                return hostnames_list

            hostnames_list = [record['hostname'] for record in rows]

    return hostnames_list


if __name__ == '__main__':
    hostnames_list = get_hostnames_list()
    print(hostnames_list)
