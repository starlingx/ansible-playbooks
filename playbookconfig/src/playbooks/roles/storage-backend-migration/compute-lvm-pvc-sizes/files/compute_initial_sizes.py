#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Computes initial target PVC sizes based on actual Ceph usage.
# Marks PVCs that exceed the usage threshold as needing file count.

import argparse
import json

from kubernetes.utils.quantity import parse_quantity

GIB = 1024 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser(
        description='Compute initial target PVC sizes based on Ceph usage.')
    parser.add_argument('pvcs', help='JSON array of PVCs with used_bytes')
    parser.add_argument('--usage-threshold-regular-volume-percent', type=int, required=True,
                        help='Usage threshold %% for volumes larger than --small-vol-gib')
    parser.add_argument('--usage-threshold-small-volume-percent', type=int, required=True,
                        help='Usage threshold %% for volumes at or below --small-vol-gib')
    parser.add_argument('--small-vol-gib', type=int, required=True,
                        help='Max size (GiB) to be considered a small volume')
    parser.add_argument('--upsize-percent', type=int, required=True,
                        help='Percentage to upsize when high density detected')
    parser.add_argument('--file-density-per-gib', type=int, required=True,
                        help='File density threshold (files per GiB)')
    args = parser.parse_args()

    pvcs = json.loads(args.pvcs)

    results = []
    for pvc in pvcs:
        requested_bytes = int(parse_quantity(pvc['requested_size']))
        used_bytes = int(pvc['used_bytes'])
        requested_gib = requested_bytes / GIB

        threshold = (args.usage_threshold_small_volume_percent
                     if requested_gib <= args.small_vol_gib
                     else args.usage_threshold_regular_volume_percent)
        usage_percent = (used_bytes / requested_bytes * 100) if requested_bytes > 0 else 0
        needs_file_count = usage_percent >= threshold

        usage_rounded = round(usage_percent, 2)
        if usage_rounded > usage_percent:
            usage_display = f"<{usage_rounded}%"
        elif usage_rounded < usage_percent:
            usage_display = f">{usage_rounded}%"
        else:
            usage_display = f"{usage_rounded}%"

        results.append({
            'namespace': pvc['namespace'],
            'name': pvc['name'],
            'type': pvc['type'],
            'volume_mode': 'Filesystem',
            'requested_bytes': requested_bytes,
            'used_bytes': used_bytes,
            'usage_percent': usage_percent,
            'usage_display': usage_display,
            'threshold': threshold,
            'target_bytes': requested_bytes,
            'needs_file_count': needs_file_count,
            'file_density_per_gib': args.file_density_per_gib,
            'upsize_percent': args.upsize_percent,
        })

    print(json.dumps(results))


if __name__ == '__main__':
    main()
