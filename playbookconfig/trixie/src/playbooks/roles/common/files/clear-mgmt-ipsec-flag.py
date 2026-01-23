#!/usr/bin/python
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# This script is to clear the "mgmt_ipsec" flag in capabilities of
# sysinv i_host table.

import json
import sys
import argparse

from psycopg2.extras import RealDictCursor
import psycopg2

from sysinv.common import constants


def main():
    restore_mode = False

    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--restore-mode", action="store_true",
                        help="Restore mode")
    args = parser.parse_args()

    if args.restore_mode:
        restore_mode = args.restore_mode

    clear_mgmt_ipsec(restore_mode)


def clear_mgmt_ipsec(restore_mode):
    """This function remove mgmt_ipsec in capabilities of sysinv i_host table.
    """

    conn = psycopg2.connect("dbname='sysinv' user='postgres'")
    with conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("select uuid,hostname,capabilities from i_host;")
            rows = cur.fetchall()
            for record in rows:
                if restore_mode and record['hostname'] == 'controller-0':
                    continue

                capabilities = json.loads(record['capabilities'])
                if capabilities.get(constants.MGMT_IPSEC_FLAG) is not None:
                    capabilities.pop(constants.MGMT_IPSEC_FLAG)

                    sqlcom = ("update i_host set "
                              f"capabilities='{json.dumps(capabilities)}' "
                              f"where uuid='{record['uuid']}'")
                    cur.execute(sqlcom)
        conn.commit()


if __name__ == "__main__":
    sys.exit(main())
