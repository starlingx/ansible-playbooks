#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Finalizes all PVC target sizes:
# - Filesystem PVCs: applies file count data to decide upsize.
# - Block PVCs: resolves K8s quantity strings to bytes (passthrough).

import argparse
import json
import math

from kubernetes.utils.quantity import parse_quantity

GIB = 1024 * 1024 * 1024


def ceil_to_next_gib(size_bytes):
    return math.ceil(size_bytes / GIB) * GIB


def main():
    parser = argparse.ArgumentParser(
        description='Finalize PVC target sizes with file density decision.')
    parser.add_argument('initial_sizing', help='JSON array from compute_initial_sizes')
    parser.add_argument('--file-counts', required=True,
                        help='JSON dict of namespace/name -> file count')
    parser.add_argument('--block-pvcs', required=True,
                        help='JSON array of block PVCs with requested_size')
    parser.add_argument('--xfs-min-bytes', type=int, required=True,
                        help='XFS minimum filesystem size in bytes')
    args = parser.parse_args()

    pvcs = json.loads(args.initial_sizing)
    file_counts = json.loads(args.file_counts)
    block_pvcs = json.loads(args.block_pvcs)

    results = []

    # Filesystem PVCs: apply file density decision
    for pvc in pvcs:
        if not pvc.get('needs_file_count'):
            pvc['effective_bytes'] = max(pvc['target_bytes'], args.xfs_min_bytes)
            pvc['needs_upsize'] = False
            pvc['file_count'] = None
            pvc['files_per_gib'] = None
            results.append(pvc)
            continue

        key = f"{pvc['namespace']}/{pvc['name']}"
        file_count = int(file_counts.get(key, 0))
        used_gib = pvc['used_bytes'] / GIB
        files_per_gib = int(file_count / used_gib) if used_gib > 0 else 0
        upsize_percent = pvc['upsize_percent']
        file_density_per_gib = pvc['file_density_per_gib']

        if files_per_gib > file_density_per_gib:
            upsized = pvc['requested_bytes'] * (1 + upsize_percent / 100)
            target_bytes = ceil_to_next_gib(int(upsized))
            needs_upsize = True
        else:
            target_bytes = pvc['requested_bytes']
            needs_upsize = False

        pvc['target_bytes'] = target_bytes
        pvc['effective_bytes'] = max(target_bytes, args.xfs_min_bytes)
        pvc['needs_upsize'] = needs_upsize
        pvc['file_count'] = file_count
        pvc['files_per_gib'] = files_per_gib
        results.append(pvc)

    # Block PVCs: resolve quantity to bytes, passthrough
    for pvc in block_pvcs:
        requested_bytes = int(parse_quantity(pvc['requested_size']))
        results.append({
            'namespace': pvc['namespace'],
            'name': pvc['name'],
            'type': pvc['type'],
            'volume_mode': 'Block',
            'requested_bytes': requested_bytes,
            'used_bytes': 0,
            'usage_percent': 0,
            'target_bytes': requested_bytes,
            'effective_bytes': requested_bytes,
            'needs_upsize': False,
            'needs_file_count': False,
            'file_count': None,
            'files_per_gib': None,
        })

    print(json.dumps(results))


if __name__ == '__main__':
    main()
