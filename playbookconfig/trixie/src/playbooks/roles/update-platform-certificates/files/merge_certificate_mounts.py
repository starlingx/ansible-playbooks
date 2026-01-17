#!/usr/bin/python
#
# Copyright (c) 2022-2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import psycopg2
from psycopg2.extras import RealDictCursor
import yaml
import sys

# sql to fetch the user_overrides from DB for oidc-auth-apps
sql_overrides = ("SELECT helm_overrides.name, user_overrides"
                 " FROM helm_overrides"
                 " LEFT OUTER JOIN kube_app"
                 " ON helm_overrides.app_id = kube_app.id"
                 " WHERE kube_app.name = 'oidc-auth-apps'"
                 " AND helm_overrides.name = 'dex'")


def get_overrides(conn):
    """Fetch helm overrides from DB"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql_overrides)
        return cur.fetchall()


def get_chart_user_override(overrides, chart):
    """Get a specific set of user overrides from the db value"""
    chart_overrides = None
    for chart_overrides in overrides:
        if 'name' in chart_overrides and chart_overrides['name'] == chart:
            break
    else:
        chart_overrides = None

    if chart_overrides and chart_overrides.get('user_overrides', None):
        return yaml.safe_load(chart_overrides['user_overrides'])
    else:
        return None


def update_or_create_item(overrides, key, new_item):
    """Look for existing tls https mounts and updates then"""
    existing_https_tls = False
    for index, item in enumerate(overrides[key]):
        if 'https-tls' == item['name']:
            overrides[key][index] = new_item
            existing_https_tls = True

    if not existing_https_tls:
        overrides[key].append(new_item)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        raise Exception("Invalid Input!")

    conn = psycopg2.connect("dbname=sysinv user=postgres")
    overrides = get_overrides(conn)
    current_dex_overrides = get_chart_user_override(overrides, 'dex')

    new_override_str = sys.argv[1]
    new_overrides = yaml.safe_load(new_override_str)

    overrides = dict()
    overrides['volumeMounts'] = current_dex_overrides.get('volumeMounts', [])
    overrides['volumes'] = current_dex_overrides.get('volumes', [])

    new_https_tls_volume = new_overrides['volumes'][0]
    new_https_tls_volume_mount = new_overrides['volumeMounts'][0]

    update_or_create_item(overrides, 'volumes', new_https_tls_volume)
    update_or_create_item(overrides, 'volumeMounts', new_https_tls_volume_mount)

    print(yaml.safe_dump(overrides))
