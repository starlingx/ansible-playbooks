#!/bin/bash
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

delete_k8s_resource() {
    local NAMESPACE=$1
    local RESOURCE=$2

    # If no namespace is provided, set NAMESPACE_FLAG to empty string
    if [ -z "${NAMESPACE}" ]; then
        NAMESPACE_FLAG=""
    else
        NAMESPACE_FLAG="-n ${NAMESPACE}"
    fi

    kubectl ${NAMESPACE_FLAG} delete "${RESOURCE}" --wait=false
    kubectl ${NAMESPACE_FLAG} patch "${RESOURCE}" \
            -p '{"metadata":{"finalizers":null}}' --type=merge

    # Check if it has been deleted
    for RETRY in {1..15}; do
        if ! kubectl ${NAMESPACE_FLAG} get "${RESOURCE}" > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    if [ $RETRY -eq 15 ]; then
        echo "  Could not delete ${RESOURCE}"
    fi
}

# Get all volume snapshot contents
VOLUME_SNAPSHOT_CONTENTS_LIST=$(kubectl get volumesnapshotcontents -o name)

if [ -z "$VOLUME_SNAPSHOT_CONTENTS_LIST" ]; then
    echo "No volume snapshot found"
fi

# Iterate among all volume snapshot contents
for VOLUME_SNAPSHOT_CONTENT in ${VOLUME_SNAPSHOT_CONTENTS_LIST}; do
    echo "Checking '${VOLUME_SNAPSHOT_CONTENT}'"

    VOLUME_SNAPSHOT_CONTENT_DRIVER=$(kubectl get "${VOLUME_SNAPSHOT_CONTENT}" \
            -o jsonpath='{.spec.driver}')

    if ! echo "$VOLUME_SNAPSHOT_CONTENT_DRIVER" | \
            grep -Pq "rbd.csi.ceph.com|cephfs.csi.ceph.com|ceph.com/rbd|ceph.com/cephfs"; then
        echo "  Skipping ${VOLUME_SNAPSHOT_CONTENT}: not provisioned by ceph-csi"
        continue
    fi

    VOLUME_SNAPSHOT_NAME=$(kubectl get "${VOLUME_SNAPSHOT_CONTENT}" \
            -o jsonpath='{.spec.volumeSnapshotRef.name}')
    VOLUME_SNAPSHOT_NAMESPACE=$(kubectl get "${VOLUME_SNAPSHOT_CONTENT}" \
            -o jsonpath='{.spec.volumeSnapshotRef.namespace}')
    VOLUME_SNAPSHOT="volumesnapshot.snapshot.storage.k8s.io/${VOLUME_SNAPSHOT_NAME}"

    # Delete the VolumeSnapshot
    delete_k8s_resource "${VOLUME_SNAPSHOT_NAMESPACE}" "${VOLUME_SNAPSHOT}"

    # Delete the VolumeSnapshotContent
    if kubectl get "${VOLUME_SNAPSHOT_CONTENT}" > /dev/null 2>&1; then
        delete_k8s_resource "" "${VOLUME_SNAPSHOT_CONTENT}"
    fi
done
