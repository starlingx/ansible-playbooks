#!/usr/bin/env python3

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Remove replicationFactor from LVM backends in a System manifest.

This script scans a multi-document YAML file and removes the
replicationFactor field from any storage backend with:

    type: lvm

Each modification is reported to stderr.

Usage:
    remove_lvm_replication_factor.py input.yaml > output.yaml

Notes:
    - Only documents with kind: System are modified.
    - Only storage.backends entries with type=lvm are examined.
    - Quoting style in the output may differ, which is harmless.
"""

import sys
import yaml


def remove_lvm_replication_factor(doc):
    if not isinstance(doc, dict) or doc.get("kind") != "System":
        return doc

    name = doc.get("metadata", {}).get("name", "<unknown>")
    spec = doc.get("spec", {})
    storage = spec.get("storage", {})
    backends = storage.get("backends", [])

    if not isinstance(backends, list):
        return doc

    changes = 0

    for backend in backends:
        if not isinstance(backend, dict):
            continue

        if backend.get("type") != "lvm":
            continue

        if "replicationFactor" in backend:
            del backend["replicationFactor"]
            changes += 1

    if changes:
        print(
            f"Removed replicationFactor from {changes} lvm backend(s) in System '{name}'",
            file=sys.stderr
        )

    return doc


def main():
    input_file = sys.argv[1]

    with open(input_file, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f.read()))

    cleaned = [remove_lvm_replication_factor(d) for d in docs if d is not None]

    yaml.safe_dump_all(
        cleaned,
        sys.stdout,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        explicit_start=True,
        allow_unicode=True
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: remove_lvm_replication_factor.py input.yaml > output.yaml", file=sys.stderr)
        sys.exit(1)
    main()
