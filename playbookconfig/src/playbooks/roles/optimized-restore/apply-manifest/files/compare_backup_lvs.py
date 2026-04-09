#!/usr/bin/python
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Compare backup DB filesystem sizes against the system's
# current logical volume sizes.
#
# Output JSON with lvs_to_update_after_db_restore
# for cases where current LV size > backup LV size,
# Backup LV > current LV is rejected at an earlier
# validation phase.
#
# Usage: compare_backup_lvs.py <postgres_staging_dir>

import json
import os
import subprocess
import sys

from cgtsclient import client as cgts_client


def log_info(msg):
    print("INFO: %s" % msg, file=sys.stderr)


def log_error(msg):
    print("ERROR: %s" % msg, file=sys.stderr)


def log_warn(msg):
    print("WARNING: %s" % msg, file=sys.stderr)


class CgtsClient(object):
    SYSINV_API_VERSION = 1

    OPENRC_KEY_MAP = {
        'OS_USERNAME': 'admin_user',
        'OS_PASSWORD': 'admin_pwd',
        'OS_PROJECT_NAME': 'admin_tenant',
        'OS_AUTH_URL': 'auth_url',
        'OS_REGION_NAME': 'region_name',
        'OS_USER_DOMAIN_NAME': 'user_domain',
        'OS_PROJECT_DOMAIN_NAME': 'project_domain',
    }

    def __init__(self):
        self.conf = {}
        self._sysinv = None

        result = subprocess.run(
            ['bash', '-c',
             'source /etc/platform/openrc && env'],
            capture_output=True, text=True)

        if result.returncode != 0:
            log_error("Failed to source openrc: %s"
                      % result.stderr.strip())
            sys.exit(1)

        for line in result.stdout.splitlines():
            key, _, value = line.partition("=")
            if key in self.OPENRC_KEY_MAP:
                self.conf[self.OPENRC_KEY_MAP[key]] = \
                    value.strip()

    @property
    def sysinv(self):
        if not self._sysinv:
            self._sysinv = cgts_client.get_client(
                self.SYSINV_API_VERSION,
                os_username=self.conf['admin_user'],
                os_password=self.conf['admin_pwd'],
                os_auth_url=self.conf['auth_url'],
                os_project_name=self.conf['admin_tenant'],
                os_project_domain_name=self.conf[
                    'project_domain'],
                os_user_domain_name=self.conf[
                    'user_domain'],
                os_region_name=self.conf['region_name'],
                os_service_type='platform',
                os_endpoint_type='internal')
        return self._sysinv


def get_backup_fs_sizes(postgres_dump_file):
    """Extract controller_fs and host_fs sizes from staged
    postgres dump file.

    :param postgres_dump_file: path to sysinv.postgreSql.data
    :returns: (ctrl_fs, host_fs) dicts of {name: size}
    """
    backup_ctrl_fs = {}
    backup_host_fs = {}
    with open(postgres_dump_file) as f:
        for line in f:
            if 'INSERT INTO public.controller_fs VALUES' \
                    in line:
                # controller_fs columns:
                # 0=created_at, 1=updated_at, 2=deleted_at,
                # 3=id, 4=uuid, 5=forisystemid, 6=state,
                # 7=name, 8=size, 9=logical_volume,
                # 10=replicated, 11=supported_functions
                cols = line.split('(', 1)[1] \
                    .rstrip(');\n').split(', ')
                backup_ctrl_fs[cols[7].strip("'")] = \
                    int(cols[8])
            elif 'INSERT INTO public.host_fs VALUES' \
                    in line:
                # host_fs columns:
                # 0=created_at, 1=updated_at, 2=deleted_at,
                # 3=id, 4=uuid, 5=name, 6=size,
                # 7=logical_volume, 8=forihostid, 9=state,
                # 10=supported_functions
                cols = line.split('(', 1)[1] \
                    .rstrip(');\n').split(', ')
                backup_host_fs[cols[5].strip("'")] = \
                    int(cols[6])

    if not backup_ctrl_fs or not backup_host_fs:
        log_error(
            "Missing filesystem entries in backup "
            "(controller_fs=%d, host_fs=%d)"
            % (len(backup_ctrl_fs), len(backup_host_fs)))
        sys.exit(1)
    return backup_ctrl_fs, backup_host_fs


def compare_fs(backup_fs, current_fs, db_table):
    """Compare backup vs current filesystem sizes.

    :param backup_fs: dict of {name: size} from backup DB dump
    :param current_fs: dict of {name: size} from sysinv API
    :param db_table: 'controller_fs' or 'host_fs'
    :returns: list of filesystems where current LV size > backup LV size
              (restored DB needs updating with current LV size)
    """
    update_db = []
    for fs_name, backup_size in backup_fs.items():
        if fs_name not in current_fs:
            log_warn("Skipping %s — filesystem not present in current system"
                     % fs_name)
            continue
        current_size = current_fs[fs_name]
        if backup_size > current_size:
            log_error(
                "%s backup size %dG > current size %dG. "
                "Should have been rejected at validation."
                % (fs_name, backup_size, current_size))
            sys.exit(1)
        elif backup_size < current_size:
            update_db.append({
                'fs_name': fs_name,
                'current_size': current_size,
                'db_table': db_table,
            })
    return update_db


def main():
    if len(sys.argv) != 2:
        print("Usage: %s <postgres_staging_dir>"
              % sys.argv[0], file=sys.stderr)
        sys.exit(1)

    postgres_dump_file = os.path.join(
        sys.argv[1], 'sysinv.postgreSql.data')

    if not os.path.isfile(postgres_dump_file):
        log_error("Dump file not found: %s"
                  % postgres_dump_file)
        sys.exit(1)

    backup_ctrl_fs, backup_host_fs = \
        get_backup_fs_sizes(postgres_dump_file)

    client = CgtsClient()

    current_ctrl_fs = {}
    for fs in client.sysinv.controller_fs.list():
        current_ctrl_fs[fs.name] = int(fs.size)

    try:
        host = client.sysinv.ihost.get('controller-0')
        host_uuid = host.uuid
    except cgts_client.exc.HTTPNotFound:
        log_error("controller-0 host not found")
        sys.exit(1)
    except Exception as e:
        log_error("Failed to get controller-0: %s" % e)
        sys.exit(1)

    current_host_fs = {}
    for fs in client.sysinv.host_fs.list(host_uuid):
        current_host_fs[fs.name] = int(fs.size)

    pending_db_updates = \
        compare_fs(backup_ctrl_fs, current_ctrl_fs,
                   'controller_fs') + \
        compare_fs(backup_host_fs, current_host_fs,
                   'host_fs')

    log_info("DB updates needed: %d" % len(pending_db_updates))
    for item in pending_db_updates:
        log_info("  %s.%s → %dG"
                 % (item['db_table'], item['fs_name'],
                    item['current_size']))

    print(json.dumps({
        'lvs_to_update_after_db_restore': pending_db_updates,
    }))


if __name__ == '__main__':
    main()
