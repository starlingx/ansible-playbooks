#!/bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

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
        echo "  Deleting ${DV}..."

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

        echo "  ${DV} deleted. VirtualMachine will create it."
    done
done
