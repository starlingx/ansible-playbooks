#!/usr/bin/env python3

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
convert_storage_to_worker.py

Converts storage nodes to regular worker nodes:
- personality: storage  ->  worker
- subfunctions: [storage] -> [worker]

Usage:
    ./convert_storage_to_worker.py storage-only.yaml > worker-from-storage.yaml
"""

import sys
import yaml


def convert_doc(doc):
    if not isinstance(doc, dict):
        return doc

    kind = doc.get("kind")
    spec = doc.get("spec", {})

    # 1. Convert HostProfile: storage -> worker
    if kind == "HostProfile" and spec.get("personality") == "storage":
        print(f"Converting profile {doc['metadata']['name']}: storage -> worker", file=sys.stderr)
        spec["personality"] = "worker"

        if "subfunctions" in spec and spec["subfunctions"] == ["storage"]:
            spec["subfunctions"] = ["worker"]

    return doc


def main(input_file):
    with open(input_file, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))

    converted_docs = []
    for doc in docs:
        if doc is None:
            continue
        converted = convert_doc(doc)
        converted_docs.append(converted)

    yaml.safe_dump_all(
        converted_docs,
        sys.stdout,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        explicit_start=True,   # preserves --- between documents
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./convert_storage_to_worker.py input.yaml > output.yaml", file=sys.stderr)
        sys.exit(1)

    main(sys.argv[1])
