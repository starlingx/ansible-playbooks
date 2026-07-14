#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Outputs a JSON array of PVCs filtered by storage class (cephfs/general)
# with a match flag based on a regex pattern.
# Usage: get_pvcs_json.py <regex>

import json
import re
import subprocess
import sys


def run_kubectl_json(*args):
    """Run kubectl with -o json and return parsed JSON, or None on failure."""
    result = subprocess.run(
        ["kubectl"] + list(args) + ["-o", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    return json.loads(result.stdout)


def get_pv_reclaim_policies():
    """Build a map of PV name -> persistentVolumeReclaimPolicy."""
    data = run_kubectl_json("get", "pv")
    if not data:
        return {}
    return {
        item["metadata"]["name"]: item["spec"].get(
            "persistentVolumeReclaimPolicy", "Delete"
        )
        for item in data.get("items", [])
    }


def get_pvcs(regex):
    """Get all PVCs filtered by cephfs/general storage class."""
    data = run_kubectl_json("get", "pvc", "-A")
    if not data:
        return []

    pv_policies = get_pv_reclaim_policies()
    pattern = re.compile(regex) if regex else re.compile(".*")
    results = []

    for item in data.get("items", []):
        spec = item.get("spec", {})
        metadata = item.get("metadata", {})

        sc = spec.get("storageClassName", "")
        if sc not in ("cephfs", "general"):
            continue

        namespace = metadata.get("namespace", "")
        name = metadata.get("name", "")
        vol_mode = spec.get("volumeMode", "Filesystem")
        size = spec.get("resources", {}).get("requests", {}).get("storage", "")
        access_modes = spec.get("accessModes", ["ReadWriteOnce"])
        pv_name = spec.get("volumeName", "")

        results.append({
            "namespace": namespace,
            "name": name,
            "type": "CephFS" if sc == "cephfs" else "RBD",
            "volume_mode": vol_mode,
            "requested_size": size,
            "access_modes": ",".join(access_modes),
            "reclaim_policy": pv_policies.get(pv_name, "Delete"),
            "match": bool(pattern.search(name)),
        })

    return results


def main():
    regex = sys.argv[1] if len(sys.argv) > 1 else ".*"
    pvcs = get_pvcs(regex)
    print(json.dumps(pvcs))


if __name__ == "__main__":
    main()
