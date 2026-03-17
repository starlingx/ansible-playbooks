#!/usr/bin/python
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import yaml
import sys


def clean_dv(filepath):
    try:
        with open(filepath, 'r') as f:
            dv = yaml.safe_load(f)
    except Exception as e:
        print(f'Error reading {filepath}: {e}')
        sys.exit(1)

    # Clean metadata
    if 'metadata' in dv:
        for key in ['uid', 'resourceVersion', 'creationTimestamp', 'generation', 'selfLink', 'managedFields', 'ownerReferences', 'finalizers']:
            dv['metadata'].pop(key, None)

        # Remove annotations
        annotations = dv['metadata'].get('annotations', {})
        if annotations:
            dv['metadata'].pop('annotations', None)

    if 'spec' in dv and 'pvc' in dv['spec']:
        dv['spec']['pvc'].pop('volumeName', None)

    dv.pop('status', None)

    try:
        with open(filepath, 'w') as f:
            yaml.dump(dv, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        print(f'Error saving {filepath}: {e}')
        sys.exit(1)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python clean_dv.py <filepath>')
        sys.exit(1)
    clean_dv(sys.argv[1])
