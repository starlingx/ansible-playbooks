#!/usr/bin/env python3

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
strip_to_storage_only.py
Keeps ONLY:
  - HostProfile with personality: storage
  - Host resources that reference that storage profile
Everything else (Namespace, controllers, computes, secrets, etc.) is removed.
"""

import sys
import yaml


def is_storage_profile(doc):
    """Return True if this document is a storage HostProfile"""
    if not isinstance(doc, dict):
        return False
    if doc.get("kind") != "HostProfile":
        return False
    spec = doc.get("spec") or {}
    return spec.get("personality") == "storage"


def main(input_file):
    with open(input_file, "r", encoding="utf-8") as f:
        all_docs = list(yaml.safe_load_all(f))

    # Step 1: collect names of all storage profiles
    storage_profiles = {
        doc["metadata"]["name"]
        for doc in all_docs
        if doc and is_storage_profile(doc)
    }

    # Step 2: keep only the objects we really want
    kept = []
    for doc in all_docs:
        if not doc:  # skip empty/None docs
            continue

        # Keep storage HostProfile(s)
        if is_storage_profile(doc):
            kept.append(doc)
            continue

        # Keep Hosts that use a storage profile
        if doc.get("kind") == "Host":
            profile_ref = doc.get("spec", {}).get("profile")
            if profile_ref in storage_profiles:
                kept.append(doc)

    # Output exactly like the original (with --- separators)
    yaml.safe_dump_all(
        kept,
        sys.stdout,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        explicit_start=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <input-dm.yaml> > storage-only.yaml", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
