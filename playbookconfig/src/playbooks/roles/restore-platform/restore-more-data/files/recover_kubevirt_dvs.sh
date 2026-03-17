#!/bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# Temporary file for manipulation
DV_RECOVER_YAML="/tmp/dv-recover.yaml"

# Get all namespaces to search for DVs
DVS_NAMESPACE_LIST=$(kubectl get namespaces -o name | sed 's/^namespace\///')

# Iterate among all namespaces
for NAMESPACE in ${DVS_NAMESPACE_LIST}; do
    echo "Checking DataVolumes in namespace '${NAMESPACE}'"

    # Get all DVs
    DVS_NAME_LIST=$(kubectl -n "${NAMESPACE}" get datavolume -o name 2>/dev/null)
    if [ -z "${DVS_NAME_LIST}" ]; then
        echo "  No DVs found on namespace '${NAMESPACE}'"
        continue
    fi

    for DV in ${DVS_NAME_LIST}; do
        echo "  Processing ${DV}..."

        # Export DataVolume manifest
        kubectl -n "${NAMESPACE}" get "${DV}" -o yaml > ${DV_RECOVER_YAML}

        # Remove bind information
        python3 roles/restore-platform/restore-more-data/files/clean_kubevirt_dv.py "${DV_RECOVER_YAML}"

        # Delete the DataVolume
        kubectl -n "${NAMESPACE}" delete "${DV}" --wait=false
        kubectl -n "${NAMESPACE}" patch "${DV}" -p '{"metadata":{"finalizers":null}}' --type=merge 2>/dev/null

        # Check if it has been deleted
        for RETRY in {1..15}; do
            if ! kubectl -n "${NAMESPACE}" get "${PVC}" 1>/dev/null 2>&1; then
                if ! kubectl -n "${NAMESPACE}" get "${PV}" 1>/dev/null 2>&1; then
                    break
                fi
            fi
            sleep 1
        done
        if [ $RETRY -eq 15 ]; then
            echo "  Could not delete ${PVC}"
        fi

        # Recreate the clean DataVolume with retries to handle CDI Webhook instability
        MAX_RETRIES=12

        echo "  Applying ${DV_RECOVER_YAML}..."

        for RETRY_COUNT in $(seq 1 $MAX_RETRIES); do
            kubectl apply -f "${DV_RECOVER_YAML}" && break
            echo "  Warning: CDI Webhook connection refused. Retrying in 10s ($RETRY_COUNT/$MAX_RETRIES)..."
            if [ "$RETRY_COUNT" -eq "$MAX_RETRIES" ]; then
                echo "  Error: Failed to recreate ${DV} after $MAX_RETRIES attempts. CDI API might be down."
                exit 1
            fi
            sleep 10
        done

        echo "  ${DV} recreated successfully. CDI will start provisioning."

        rm -f "${DV_RECOVER_YAML}"
    done
done
