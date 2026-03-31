#!/usr/bin/python
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Extract and check backup data for factory restore without reinstall
# compatibility.
#
# Usage: check_backup_factory_data.py <action> <postgres_data_file>
#
# Actions:
#   cpu - Extract backup CPU topology (cpus,sockets,cores,threads)
#   pci - Extract backup PCI vendor:device ID pairs
#   fs  - Compare backup filesystem sizes against factory live DB;
#         exits non-zero if any factory LV is smaller than backup
#

import subprocess
import sys

action = sys.argv[1]
data_file = sys.argv[2]


def read_lines(path):
    with open(path) as f:
        return f.readlines()


if action == 'cpu':
    # Count CPU topology from i_icpu table
    # Columns: created_at(0), updated_at(1), deleted_at(2), id(3), uuid(4),
    #          cpu(5), core(6), thread(7), cpu_family(8), cpu_model(9),
    #          allocated_function(10), capabilities(11), forihostid(12), forinodeid(13)
    rows = [r for r in read_lines(data_file) if 'INSERT INTO public.i_icpu VALUES' in r]
    cpus = len(rows)  # total logical CPUs
    nodes = set()  # unique NUMA nodes (sockets)
    cores = set()  # unique (node, core) pairs (physical cores)
    max_t = 0  # max threads
    for r in rows:
        parts = r.split('(', 1)[1].rstrip(');').split(', ')
        nodes.add(parts[-1])
        cores.add((parts[-1], parts[6]))
        max_t = max(max_t, int(parts[7]))
    # Output: total_cpus, sockets, physical_cores, threads_per_core
    print('%d,%d,%d,%d' % (cpus, len(nodes), len(cores), max_t + 1))

elif action == 'pci':
    devices = set()
    for line in read_lines(data_file):
        if 'INSERT INTO public.pci_devices VALUES' in line:
            parts = line.split('(', 1)[1].rstrip(');').split(', ')
            devices.add(parts[9].strip("'") + ':' + parts[10].strip("'"))
    for d in sorted(devices):
        print(d)

elif action == 'fs':
    backup = {}
    for line in read_lines(data_file):
        if 'INSERT INTO public.controller_fs VALUES' in line:
            p = line.split('(', 1)[1].rstrip(');').split(', ')
            backup[p[7].strip("'")] = int(p[8])
        elif 'INSERT INTO public.host_fs VALUES' in line:
            p = line.split('(', 1)[1].rstrip(');').split(', ')
            backup[p[5].strip("'")] = int(p[6])
    r = subprocess.run(
        ['sudo', '-u', 'postgres', 'psql', '-t', '-A', '-F', ',', '-c',
         "SELECT name, size FROM controller_fs UNION ALL SELECT name, size FROM host_fs",
         'sysinv'], capture_output=True, text=True)
    if r.returncode != 0:
        print('ERROR: psql query failed: %s' % r.stderr.strip())
        sys.exit(2)
    oversized_backup_fs = []
    for line in r.stdout.strip().split('\n'):
        if ',' in line:
            n, s = line.split(',', 1)
            if n in backup and int(s) < backup[n]:
                oversized_backup_fs.append('%s: factory=%sG backup=%dG' % (n, s, backup[n]))
    if oversized_backup_fs:
        print('|'.join(oversized_backup_fs))
        sys.exit(1)
    print('OK')
