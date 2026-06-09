#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Restore factory rook-ceph K8s state after etcd restore.
# This script patches secrets, configmap, deployment, and
# recreates the MON service with the factory's ClusterIP.
#

import json
import subprocess
import sys

NAMESPACE = "rook-ceph"
TEMP_DIR = "/tmp/factory_rook_ceph_restore"


def kubectl(*args, input_data=None):
    cmd = ["kubectl"] + list(args)
    r = subprocess.run(cmd, input=input_data, capture_output=True, text=True)
    return r


def restore_secrets():
    data = json.load(open(f"{TEMP_DIR}/secrets.json"))
    failures = []
    for s in data["items"]:
        name = s["metadata"]["name"]
        patch = json.dumps({"data": s["data"]})
        r = kubectl("patch", "secret", "-n", NAMESPACE,
                    name, "--type", "merge", "-p", patch)
        if r.returncode != 0:
            failures.append(name)
    if failures:
        print(f"Failed to patch secrets: {', '.join(failures)}")
        return False
    print(f"Restored {len(data['items'])} secrets")
    return True


def restore_configmap():
    cm = json.load(open(f"{TEMP_DIR}/configmap.json"))
    patch = json.dumps({"data": cm["data"]})
    r = kubectl("patch", "configmap", "-n", NAMESPACE,
                "rook-ceph-mon-endpoints", "--type", "merge", "-p", patch)
    if r.returncode != 0:
        print(f"FAILED: {r.stderr}", file=sys.stderr)
        return False
    print("Restored rook-ceph-mon-endpoints configmap")
    return True


def restore_deployment():
    d = json.load(open(f"{TEMP_DIR}/mon_deploy.json"))
    name = d["metadata"]["name"]
    args = d["spec"]["template"]["spec"]["containers"][0]["args"]
    patch = json.dumps({"spec": {"template": {"spec": {
        "containers": [{"name": "mon", "args": args}]}}}})
    r = kubectl("patch", "deploy", "-n", NAMESPACE,
                name, "--type", "strategic", "-p", patch)
    if r.returncode != 0:
        print(f"FAILED: {r.stderr}", file=sys.stderr)
        return False
    print(f"Restored {name} deployment")
    return True


def restore_service():
    svc = json.load(open(f"{TEMP_DIR}/mon_svc.json"))
    cluster_ip = svc["spec"]["clusterIP"]
    name = svc["metadata"]["name"]
    # Delete existing service (ClusterIP is immutable)
    kubectl("delete", "svc", "-n", NAMESPACE, name)

    # Recreate with factory ClusterIP
    new_svc = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": NAMESPACE,
            "labels": svc["metadata"].get("labels", {})
        },
        "spec": {
            "clusterIP": cluster_ip,
            "ports": svc["spec"]["ports"],
            "selector": svc["spec"]["selector"],
            "type": "ClusterIP"
        }
    }
    r = kubectl("apply", "-f", "-", input_data=json.dumps(new_svc))
    if r.returncode != 0:
        print(f"FAILED: {r.stderr}", file=sys.stderr)
        return False
    print(f"Restored {name} service with ClusterIP {cluster_ip}")
    return True


def restore_cephcluster():
    cr = json.load(open(f"{TEMP_DIR}/cephcluster.json"))
    patch = json.dumps({"spec": {"storage": cr["spec"]["storage"]}})
    r = kubectl("patch", "cephcluster", "-n", NAMESPACE,
                "rook-ceph", "--type", "merge", "-p", patch)
    if r.returncode != 0:
        print(f"FAILED: {r.stderr}", file=sys.stderr)
        return False
    print("Restored CephCluster CR spec.storage")
    return True


def main():
    steps = [
        ("secrets", restore_secrets),
        ("configmap", restore_configmap),
        ("deployment", restore_deployment),
        ("service", restore_service),
        ("cephcluster", restore_cephcluster),
    ]
    for name, func in steps:
        if not func():
            print(f"Failed to restore {name}", file=sys.stderr)
            sys.exit(1)
    print("All rook-ceph state restored successfully")


if __name__ == "__main__":
    main()
