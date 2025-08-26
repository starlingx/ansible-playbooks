#!/bin/bash
#
# Copyright (c) 2023,2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Temporary file for manipulation
PVC_RECOVER_YAML="/tmp/pvc-recover.yaml"

# Get all namespaces to search for PVCs
PVCS_NAMESPACE_LIST=$(kubectl get namespaces -o name | sed 's/^namespace\///')

# Iterate among all namespaces
for NAMESPACE in ${PVCS_NAMESPACE_LIST}; do
    echo "Checking namespace '${NAMESPACE}'"

    # Get all PVCs
    PVCS_NAME_LIST=$(kubectl -n "${NAMESPACE}" get pvc -o name)
    if [ -z "${PVCS_NAME_LIST}" ]; then
        echo "  No PVCs found on namespace '${NAMESPACE}'"
        continue
    fi

    # Delete all PVCs in NAMESPACE
    for PVC in ${PVCS_NAME_LIST}; do

        # Store PVC details
        kubectl -n "${NAMESPACE}" get "${PVC}" -o yaml > ${PVC_RECOVER_YAML}
        if ! grep -E "rbd.csi.ceph.com|cephfs.csi.ceph.com|ceph.com/rbd|ceph.com/cephfs" \
                ${PVC_RECOVER_YAML} 1>/dev/null 2>&1; then
            echo "  Skipping ${PVC}: not provisioned by ceph-csi"
            continue
        fi

        # Remove bind information
        sed -i -e '/volumeName:/d' -e '/pv.kubernetes.io\/bind-completed:/d' \
            -e '/pv.kubernetes.io\/bound-by-controller:/d' "${PVC_RECOVER_YAML}"

        # Delete the PVC
        kubectl -n "${NAMESPACE}" delete "${PVC}" --wait=false
        kubectl -n "${NAMESPACE}" patch "${PVC}" \
                -p '{"metadata":{"finalizers":null}}' --type=merge

        # Check if it has been deleted
        for RETRY in {1..15}; do
            if ! kubectl -n "${NAMESPACE}" get "${PVC}" 1>/dev/null 2>&1; then
                break
            fi
            sleep 1
        done
        if [ $RETRY -eq 15 ]; then
            echo "  Could not delete ${PVC}"
        fi

        # If the PVC is from a volume snapshot, it should only be deleted, not recreated.
        if grep -E "snapshot.storage.k8s.io" ${PVC_RECOVER_YAML} 1>/dev/null 2>&1; then
            echo "  Discarding ${PVC}: VolumeSnapshot"
            rm -f "${PVC_RECOVER_YAML}"
            continue
        fi

        # Recreate the PVC
        kubectl apply -f "${PVC_RECOVER_YAML}"
        rm -f "${PVC_RECOVER_YAML}"
    done
done
