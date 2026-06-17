#!/usr/bin/env python3

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
remove_incomplete_secrets.py

Removes any Secret objects that contain the string "Warning: Incomplete"
from a (multi-document) Kubernetes YAML file.

Usage:
    python3 remove_incomplete_secrets.py input.yaml > cleaned.yaml
"""

import yaml
import sys


def is_incomplete_secret(doc):
    """Return True if the document is a Secret with 'Warning: Incomplete' in it."""
    if not doc or doc.get('kind') != 'Secret':
        return False

    data = doc.get('data', {})
    string_data = doc.get('stringData', {})

    # Combine all values from data and stringData
    all_values = list(data.values()) + list(string_data.values())

    return any('Warning: Incomplete' in str(v) for v in all_values)


def main(input_file):
    with open(input_file, 'r') as f:
        docs = list(yaml.safe_load_all(f))

    kept_docs = []
    removed_count = 0

    for doc in docs:
        if doc is None:
            continue  # skip empty documents (--- separators)

        if is_incomplete_secret(doc):
            key = (
                doc.get('metadata', {}).get('namespace', '(no namespace)'),
                doc.get('metadata', {}).get('name', '(no name)')
            )
            print(f"Removing incomplete Secret {key[0]}/{key[1]}", file=sys.stderr)
            removed_count += 1
        else:
            kept_docs.append(doc)

    print(f"Removed {removed_count} incomplete secret(s).", file=sys.stderr)
    yaml.safe_dump_all(kept_docs, sys.stdout,
                       default_flow_style=False,
                       sort_keys=False,
                       explicit_start=True)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 remove_incomplete_secrets.py input.yaml > cleaned.yaml", file=sys.stderr)
        sys.exit(1)

    main(sys.argv[1])
