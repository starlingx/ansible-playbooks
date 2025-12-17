#!/usr/bin/env python3

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
add_kube_labels.py

Adds the worker labels to HostProfile spec:

  kube-cpu-mgr-policy: static
  kube-topology-mgr-policy: restricted
  openvswitch: enabled
  sriov: enabled

Usage:
    ./add_kube_labels.py input.yaml > output-with-labels.yaml
"""

import sys
import yaml

# The exact labels we want to inject
KUBE_LABELS = {
    "kube-cpu-mgr-policy": "static",
    "kube-topology-mgr-policy": "restricted",
    "openvswitch": "enabled",
    "sriov": "enabled"
}


def add_labels_to_profile(doc):
    if not isinstance(doc, dict) or doc.get("kind") != "HostProfile":
        return doc

    name = doc.get("metadata", {}).get("name", "<unknown>")
    spec = doc.get("spec", {})

    # Ensure spec.labels exists
    if "labels" not in spec:
        spec["labels"] = {}
        print(f"Added new spec.labels section to profile: {name}", file=sys.stderr)
    else:
        print(f"Updating spec.labels in profile: {name}", file=sys.stderr)

    # Merge our labels (overwrite if already present)
    old_count = len(spec["labels"])
    spec["labels"].update(KUBE_LABELS)
    new_count = len(spec["labels"])

    added = new_count - old_count
    if added > 0:
        print(f"  -> Added {added} new label(s)", file=sys.stderr)
    else:
        print("  -> All labels already present", file=sys.stderr)

    return doc


def main(input_file):
    with open(input_file, "r", encoding="utf-8") as f:
        docs = list(yaml.safe_load_all(f))

    updated_docs = []
    for doc in docs:
        if doc is None:
            continue
        updated_docs.append(add_labels_to_profile(doc))

    yaml.safe_dump_all(
        updated_docs,
        sys.stdout,
        sort_keys=False,
        default_flow_style=False,
        indent=2,
        explicit_start=True,
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./add_kube_labels.py input.yaml > output.yaml", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
