#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Creates LVM PVCs by cloning existing PVC specs, replacing the storage class
# and converting unsupported access modes (RWX/ROX -> RWO).
#
# Args:
#   --storage-class SC  Target LVM storage class (required)
#
# Reads PVC list from stdin, one per line: "namespace from to [size]"
# The size field is optional.
#
# Environment variables:
#   KUBECONFIG - Path to kubeconfig
#
# State handling:
#
#   TO exists | FROM exists | Action
#   ----------|-------------|-------------------------------------------------
#   Yes       | -           | Skip (target PVC already exists)
#   No        | No          | Error: source PVC does not exist
#   No        | Yes         | Clone FROM, strip fields, create TO
#

import argparse
import json
import logging
import sys

from kubernetes import client
from kubernetes import config
from kubernetes.client.rest import ApiException

log = logging.getLogger(__name__)


def _read_pvc(v1, namespace, name):
    try:
        return v1.read_namespaced_persistent_volume_claim(name, namespace)
    except ApiException as exc:
        if exc.status == 404:
            return None
        raise


def _pvc_raw(v1, namespace, name):
    resp = v1.read_namespaced_persistent_volume_claim(
        name, namespace, _preload_content=False)
    return json.loads(resp.data)


def create_lvm_pvc(v1, namespace, from_, to, size, storage_class):
    # Skip if target PVC already exists
    if _read_pvc(v1, namespace, to) is not None:
        log.info("Skipping %s/%s: PVC already exists", namespace, to)
        return

    # Source PVC must exist
    if _read_pvc(v1, namespace, from_) is None:
        log.info("ERROR: Source PVC %s/%s does not exist", namespace, from_)
        sys.exit(1)

    # Clone the source PVC, strip server-managed fields, update name and storage
    # class, remove bind info, and convert RWX/ROX -> RWO (TopoLVM limitation)
    pvc = _pvc_raw(v1, namespace, from_)

    pvc["metadata"]["name"] = to
    pvc["spec"]["storageClassName"] = storage_class

    for key in ("uid", "creationTimestamp", "resourceVersion"):
        pvc["metadata"].pop(key, None)
    pvc["spec"].pop("volumeName", None)
    pvc["spec"].pop("dataSource", None)
    pvc["spec"].pop("dataSourceRef", None)
    pvc.pop("status", None)

    annotations = pvc.get("metadata", {}).get("annotations", {})
    annotations.pop("pv.kubernetes.io/bind-completed", None)
    annotations.pop("pv.kubernetes.io/bound-by-controller", None)
    annotations.pop("volume.kubernetes.io/storage-provisioner", None)
    annotations.pop("volume.beta.kubernetes.io/storage-provisioner", None)

    access_modes = pvc.get("spec", {}).get("accessModes", [])
    pvc["spec"]["accessModes"] = [
        "ReadWriteOnce" if m in ("ReadWriteMany", "ReadOnlyMany") else m
        for m in access_modes
    ]

    if size:
        pvc["spec"]["resources"]["requests"]["storage"] = size

    v1.create_namespaced_persistent_volume_claim(namespace, pvc)

    if size:
        log.info(
            "Created %s/%s (from: %s, storageClass: %s, size: %s)",
            namespace, to, from_, storage_class, size)
    else:
        log.info(
            "Created %s/%s (from: %s, storageClass: %s)",
            namespace, to, from_, storage_class)


def main():
    logging.basicConfig(
        stream=sys.stdout,
        level=logging.INFO,
        format="%(asctime)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--storage-class", dest="storage_class", default="")
    args = parser.parse_args()

    if not args.storage_class:
        log.info("ERROR: --storage-class is required.")
        sys.exit(1)

    config.load_kube_config()
    v1 = client.CoreV1Api()

    # Read PVC list from stdin: "namespace from to [size]" per line
    for line in sys.stdin:
        parts = line.split()
        if not parts:
            continue
        namespace = parts[0] if len(parts) > 0 else ""
        from_ = parts[1] if len(parts) > 1 else ""
        to = parts[2] if len(parts) > 2 else ""
        size = parts[3] if len(parts) > 3 else ""
        if not namespace or not from_ or not to:
            log.info(
                "ERROR: Invalid input: namespace='%s' from='%s' to='%s' "
                "(all 3 fields required)", namespace, from_, to)
            sys.exit(1)
        create_lvm_pvc(v1, namespace, from_, to, size, args.storage_class)


if __name__ == "__main__":
    main()
