#!/usr/bin/env python3

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
Fix empty Ceph Rook backend network values in a System manifest.

This script scans a multi-document YAML file and updates any storage
backend with:

    type: ceph-rook
    network: ''   (empty string)

and replaces the network value with:

    network: cluster-host

Each modification is reported to stderr.

Usage:
    fix_rook_backend_network.py input.yaml > output.yaml

Notes:
    - Only documents with kind: System are modified.
    - Only storage.backends entries with type=ceph-rook are examined.
    - Quoting style in the output may differ, which is harmless.
"""

import sys
import yaml

NEW_NETWORK = "cluster-host"


def fix_system_rook_network(doc):
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

        if backend.get("type") != "ceph-rook":
            continue

        network = backend.get("network", None)

        if network == "" or network is None:
            backend["network"] = NEW_NETWORK
            changes += 1

    if changes:
        print(
            f"Updated network for {changes} ceph-rook backend(s) in System '{name}'",
            file=sys.stderr
        )

    return doc


def main():
    input_file = sys.argv[1]

    with open(input_file, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f.read()))

    cleaned = [fix_system_rook_network(d) for d in docs if d is not None]

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
        print("Usage: fix_rook_backend_network.py input.yaml > output.yaml", file=sys.stderr)
        sys.exit(1)
    main()
