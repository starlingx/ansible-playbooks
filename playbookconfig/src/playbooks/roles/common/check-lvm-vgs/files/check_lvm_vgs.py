#!/usr/bin/python
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Compare LVM CSI volume groups registered in the sysinv database
# against the volume groups actually present on the Linux host.
#
# For each VG that exists in the DB (with lvm_function=lvm-csi in
# its capabilities) but is missing from the host, emit a WARNING
# indicating it will be recreated during host unlock.
#
# This script is intended to run on AIO-SX systems after the
# postgres database has been restored, so the sysinv DB reflects
# the backup state while the Linux VGs reflect the current disk
# state.
#

import json
import subprocess
import sys

LVM_CFG = "devices { filter=[\"a|.*|\"] global_filter=[\"a|.*|\"] }"


def log_info(msg):
    print("INFO: %s" % msg, file=sys.stderr)


def log_warn(msg):
    print("WARNING: %s" % msg, file=sys.stderr)


def log_error(msg):
    print("ERROR: %s" % msg, file=sys.stderr)


def get_db_lvm_csi_vgs():
    """Query sysinv DB for volume groups with lvm_function=lvm-csi
    on controller-0.

    Returns a list of dicts with vg_name and lvm_type.
    """
    query = (
        "SELECT lvg.lvm_vg_name, lvg.capabilities "
        "FROM i_lvg lvg "
        "JOIN i_host h ON lvg.forihostid = h.id "
        "WHERE h.hostname = 'controller-0' "
        "AND lvg.capabilities LIKE '%%lvm-csi%%'"
    )

    result = subprocess.run(
        ['sudo', '-u', 'postgres',
         'psql', '-t', '-A', '-F', '|', '-d', 'sysinv', '-c', query],
        capture_output=True, text=True,
        timeout=10
    )

    if result.returncode != 0:
        log_error("Failed to query sysinv DB: %s" % result.stderr.strip())
        return []

    vgs = []
    for line in result.stdout.strip().splitlines():
        if not line:
            continue
        parts = line.split('|', 1)
        if len(parts) != 2:
            continue
        vg_name = parts[0].strip()
        caps_raw = parts[1].strip()
        try:
            caps = json.loads(caps_raw)
        except (json.JSONDecodeError, ValueError):
            caps = {}

        if caps.get('lvm_function') != 'lvm-csi':
            continue

        vgs.append({
            'vg_name': vg_name,
            'lvm_type': caps.get('lvm_type', 'unknown'),
        })

    return vgs


def get_linux_vgs():
    """Get volume group names present on the Linux host via vgs command.

    Returns a set of VG names.
    """
    result = subprocess.run(
        ['vgs', '--config', LVM_CFG,
         '-o', 'vg_name', '--noheadings', '--nosuffix'],
        capture_output=True, text=True,
        timeout=10
    )

    if result.returncode != 0:
        log_error("Failed to run vgs: %s" % result.stderr.strip())
        return set()

    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def main():
    db_vgs = get_db_lvm_csi_vgs()
    linux_vgs = get_linux_vgs()

    log_info("LVM CSI VGs in backup DB (controller-0): %s"
             % [v['vg_name'] for v in db_vgs])
    log_info("VGs on Linux host: %s" % sorted(linux_vgs))

    missing_vgs = []
    matched_vgs = []
    warnings = []

    for vg in db_vgs:
        if vg['vg_name'] not in linux_vgs:
            missing_vgs.append({
                'vg_name': vg['vg_name'],
                'lvm_type': vg['lvm_type'],
                'host': 'controller-0',
            })
            warning_msg = (
                "VG '%s' (%s) is registered in the backup database "
                "but was not found on the host. It was likely removed "
                "manually and will be recreated on host unlock."
                % (vg['vg_name'], vg['lvm_type'])
            )
            warnings.append(warning_msg)
            log_warn(warning_msg)
        else:
            matched_vgs.append(vg['vg_name'])

    if not missing_vgs:
        log_info("All LVM CSI volume groups from backup DB "
                 "are present on the host.")

    print(json.dumps({
        'missing_vgs': missing_vgs,
        'matched_vgs': matched_vgs,
        'warnings': warnings,
    }))


if __name__ == '__main__':
    main()
