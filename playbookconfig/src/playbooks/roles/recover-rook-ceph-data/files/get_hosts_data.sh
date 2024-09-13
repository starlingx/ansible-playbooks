#!/bin/sh
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

ONLY_OSD=""
OSD_N_MON=""
HOSTS_WITH_OSD=()

source /etc/platform/openrc;

HOSTS=$(system host-list --format value --column hostname | tr '\n' ' ')
IFS=', ' read -r -a HOSTS_ARRAY <<< "$HOSTS"

for host in "${HOSTS_ARRAY[@]}"; do
    HAS_MON=false
    HAS_OSD=false

    if system host-stor-list $host | grep osd | grep configured &>/dev/null; then
        echo "osd found on $host"
        HOSTS_WITH_OSD+=($host)
        HAS_OSD=true
    fi

    if system host-label-list $host | grep ceph-mon-placement &>/dev/null; then
        echo "mon found on $host"
        HAS_MON=true
    fi

    if [[ $HAS_MON == true && $HAS_OSD == true && $OSD_N_MON == "" ]]; then
        OSD_N_MON=$host
    elif [[ $HAS_OSD == true && $ONLY_OSD == "" ]]; then
        ONLY_OSD=$host
    fi
done

if [[ $OSD_N_MON ]]; then
    TARGET=$OSD_N_MON
    if [ ${#HOSTS_ARRAY[@]} == 1 ]; then
        STRUCT="ONE_HOST"
    else
        STRUCT="OSD_N_MON"
    fi
elif [[ $ONLY_OSD ]]; then
    TARGET=$ONLY_OSD
    STRUCT="ONLY_OSD"
else
    exit 1
fi

echo "{\"structure\": \"$STRUCT\", \"target_hostname\": \"$TARGET\", \"hosts_with_osd\": \"${HOSTS_WITH_OSD[@]}\"}"
exit 0
