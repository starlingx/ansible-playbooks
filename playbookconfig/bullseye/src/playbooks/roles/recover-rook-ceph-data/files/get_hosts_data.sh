#!/bin/sh
#
# Copyright (c) 2024-2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

OSD_ONLY_HOST=""
OSD_AND_MON_HOST=""
HOSTS_WITH_OSD=()

source /etc/platform/openrc;

# Creates an array with all hostnames
HOSTS=$(system host-list --format value --column hostname | tr '\n' ' ')
IFS=', ' read -r -a HOSTS_ARRAY <<< "$HOSTS"

# Iterates over the array
for host in "${HOSTS_ARRAY[@]}"; do
    HAS_MON=false
    HAS_OSD=false

    # Check if there is an OSD configured on host
    if system host-stor-list "$host" | grep -q 'osd.*configured'; then
        echo "osd found on $host"
        HOSTS_WITH_OSD+=("$host")
        HAS_OSD=true
    fi

    # Check if a monitor is configured on host
    if system host-label-list "$host" | grep -q ceph-mon-placement; then
        echo "mon found on $host"
        HAS_MON=true
    fi

    # Sets the "OSD_AND_MON_HOST" and "OSD_ONLY_HOST" to the hostname if empty
    if [[ -z "$OSD_AND_MON_HOST" && "$HAS_MON" == true && "$HAS_OSD" == true ]]; then
        OSD_AND_MON_HOST=$host
    elif [[ -z "$OSD_ONLY_HOST" && "$HAS_OSD" == true && "$HAS_MON" == false ]]; then
        OSD_ONLY_HOST=$host
    fi
done

# TODO: Prioritize controller-0 as the recovery target host.
# Sets the "RECOVERY_TARGET_HOST" and "RECOVERY_TYPE" according to what was found in the hosts
if [[ -n "$OSD_AND_MON_HOST" ]]; then
    RECOVERY_TARGET_HOST="$OSD_AND_MON_HOST"
    # Just one host means it's an AIO-SX
    if [[ ${#HOSTS_ARRAY[@]} -eq 1 ]]; then
        RECOVERY_TYPE="SINGLE_HOST"
    else
        RECOVERY_TYPE="OSD_AND_MON"
    fi
elif [[ -n "$OSD_ONLY_HOST" ]]; then
    RECOVERY_TARGET_HOST="$OSD_ONLY_HOST"
    RECOVERY_TYPE="OSD_ONLY"
else
    # This means that no OSD was found on any host
    exit 1
fi

# json to be read by the playbook
echo "{\"recovery_type\": \"$RECOVERY_TYPE\", \"recovery_target_host\": \"$RECOVERY_TARGET_HOST\", \"hosts_with_osd\": \"${HOSTS_WITH_OSD[@]}\"}"
exit 0
