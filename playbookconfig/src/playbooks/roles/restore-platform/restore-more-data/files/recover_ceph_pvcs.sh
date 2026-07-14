#!/bin/bash
#
# Copyright (c) 2023,2025-2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Temporary file for manipulation
PVC_RECOVER_YAML="/tmp/pvc-recover.yaml"
PV_RECOVER_YAML="/tmp/pv-recover.yaml"
RECLAIM_POLICY_MAP="/tmp/reclaim-policy-map.txt"

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

        # Store PV name
        PV_NAME=$(kubectl -n "${NAMESPACE}" get "${PVC}" -o jsonpath='{.spec.volumeName}')
        PV="persistentvolume/${PV_NAME}"

        # Store PV details
        kubectl get "${PV}" -o yaml > ${PV_RECOVER_YAML}

        # Store PVC details
        kubectl -n "${NAMESPACE}" get "${PVC}" -o yaml > ${PVC_RECOVER_YAML}

        # Check if PVC/PV was provisioned by ceph-csi (check both PVC and PV)
        if ! grep -E "rbd.csi.ceph.com|cephfs.csi.ceph.com|ceph.com/rbd|ceph.com/cephfs" \
                ${PVC_RECOVER_YAML} ${PV_RECOVER_YAML} 1>/dev/null 2>&1; then
            echo "  Skipping ${PVC}: not provisioned by ceph-csi"
            continue
        fi

        # Save original reclaim policy for later restoration
        ORIGINAL_RECLAIM_POLICY=$(kubectl get "${PV}" -o jsonpath='{.spec.persistentVolumeReclaimPolicy}')
        PVC_SHORT_NAME=$(echo "${PVC}" | sed 's|^persistentvolumeclaim/||')

        # Remove bind information
        sed -i -e '/volumeName:/d' -e '/pv.kubernetes.io\/bind-completed:/d' \
            -e '/pv.kubernetes.io\/bound-by-controller:/d' "${PVC_RECOVER_YAML}"

        # Replace ReadOnlyMany with ReadWriteOnce so CSI can provision dynamically.
        # RBD (storageClass general) do not support ReadWriteMany, change to
        # ReadWriteOnce to ensure the PVCs is provisioned as expected
        sed -i 's/ReadOnlyMany/ReadWriteOnce/g' "${PVC_RECOVER_YAML}"

        # Delete the PVC
        kubectl -n "${NAMESPACE}" delete "${PVC}" --wait=false
        kubectl -n "${NAMESPACE}" patch "${PVC}" \
                -p '{"metadata":{"finalizers":null}}' --type=merge

        # Delete the PV
        kubectl delete "${PV}" --wait=false
        kubectl patch "${PV}" \
                -p '{"metadata":{"finalizers":null}}' --type=merge

        # Check if it has been deleted
        for RETRY in {1..15}; do
            if ! kubectl -n "${NAMESPACE}" get "${PVC}" 1>/dev/null 2>&1; then
                if ! kubectl get "${PV}" 1>/dev/null 2>&1; then
                    break
                fi
            fi
            sleep 1
        done
        if [ $RETRY -eq 15 ]; then
            echo "  Could not delete ${PVC}"
        fi

        # If the PVC is from a volume snapshot, it should only be deleted, not recreated.
        if grep -iE "snapshot.storage.k8s.io" ${PVC_RECOVER_YAML} 1>/dev/null 2>&1; then
            echo "  Discarding ${PVC}: VolumeSnapshot"
            rm -f "${PVC_RECOVER_YAML}"
            continue
        fi

        # If the PVC is from a DataVolume, it should only be deleted, not recreated.
        if grep -iE "cdi.kubevirt.io|DataVolume" ${PVC_RECOVER_YAML} 1>/dev/null 2>&1; then
            echo "  Discarding ${PVC}: CDI/DataVolume"
            rm -f "${PVC_RECOVER_YAML}"
            continue
        fi

        # Recreate the PVC
        kubectl apply -f "${PVC_RECOVER_YAML}"
        echo "${NAMESPACE} ${PVC_SHORT_NAME} ${ORIGINAL_RECLAIM_POLICY}" >> "${RECLAIM_POLICY_MAP}"
        rm -f "${PVC_RECOVER_YAML}"
    done
done

# Restore original reclaimPolicy on new PVs
echo "Restoring original reclaimPolicy on recreated PVs..."
while read -r NS PVC_NAME POLICY; do
    [ -z "${NS}" ] && continue

    # Get the StorageClass binding mode to decide if we should wait
    SC_NAME=$(kubectl -n "${NS}" get pvc "${PVC_NAME}" -o jsonpath='{.spec.storageClassName}' 2>/dev/null)
    BIND_MODE=$(kubectl get sc "${SC_NAME}" -o jsonpath='{.volumeBindingMode}' 2>/dev/null)

    if [ "${BIND_MODE}" = "WaitForFirstConsumer" ]; then
        echo "  Skipping ${NS}/${PVC_NAME}: StorageClass ${SC_NAME} uses WaitForFirstConsumer"
        continue
    fi

    # Wait for PVC to be Bound (up to 150s)
    for i in {1..30}; do
        PHASE=$(kubectl -n "${NS}" get pvc "${PVC_NAME}" -o jsonpath='{.status.phase}' 2>/dev/null)
        [ "${PHASE}" = "Bound" ] && break
        echo "  Waiting 5 seconds to check bound again for PVC ${PVC_NAME}"
        sleep 5
    done

    if [ "${PHASE}" != "Bound" ]; then
        echo "  WARNING: PVC ${NS}/${PVC_NAME} not Bound after timeout, skipping reclaimPolicy restore"
        continue
    fi

    NEW_PV=$(kubectl -n "${NS}" get pvc "${PVC_NAME}" -o jsonpath='{.spec.volumeName}')
    if [ -n "${NEW_PV}" ]; then
        kubectl patch pv "${NEW_PV}" -p "{\"spec\":{\"persistentVolumeReclaimPolicy\":\"${POLICY}\"}}"
        echo "  ${NEW_PV} -> reclaimPolicy=${POLICY}"
    fi
done < "${RECLAIM_POLICY_MAP}"

rm -f "${RECLAIM_POLICY_MAP}"
