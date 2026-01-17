#!/usr/bin/env python3

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
remove_osds.py

Removes the OSD configuration from storage HostProfiles.

Usage:
    ./remove_osds.py input.yaml > no-osd.yaml
"""

import sys
import yaml


def remove_osds_from_profile(doc):
    if not isinstance(doc, dict) or doc.get("kind") != "HostProfile":
        return doc

    name = doc.get("metadata", {}).get("name", "<unknown>")
    spec = doc.get("spec", {})

    if "storage" not in spec:
        return doc

    storage = spec["storage"]

    if "osds" in storage:
        old_count = len(storage["osds"])
        del storage["osds"]
        print(f"Removed {old_count} OSD(s) from profile {name}", file=sys.stderr)

    # Optional: clean up empty storage section (makes the YAML cleaner)
    if not storage:  # empty dict after removing osds
        del spec["storage"]
        print(f"Removed empty storage: section from profile {name}", file=sys.stderr)

    return doc


def main(input_file):
    with open(input_file, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))

    cleaned_docs = []
    for doc in docs:
        if doc is None:
            continue
        cleaned = remove_osds_from_profile(doc)
        cleaned_docs.append(cleaned)

    yaml.safe_dump_all(
        cleaned_docs,
        sys.stdout,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        explicit_start=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./remove_osds.py storage-only.yaml > worker-no-ceph.yaml", file=sys.stderr)
        sys.exit(1)

    main(sys.argv[1])
