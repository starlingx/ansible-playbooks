#!/bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
MODE=$1
LVM_CFG="--config 'devices { filter=[\"a|.*|\"] global_filter=[\"a|.*|\"] }'"

########################################################################
# Name      : log
# Purpose   : Print log message
# Parameters: \$1 log level
#             \$2 message
# Return    : Does not return
########################################################################
log() {
    local level="$1"
    local msg="$2"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $msg"
}

########################################################################
# Name      : wipe_lv
# Purpose   : Wipe all LVs from a VG without removing the VG or LV
#             structure
# Parameters: \$1 vg_name - Volume Group Name
# Return    : Does not return
########################################################################
wipe_lv() {
    local vg_name=${1}

    # Activate VG
    # LVM_CFG stablish a local configuration what avoid problems with the global_filter on lvm.conf
    eval vgchange $LVM_CFG -ay "$vg_name" >/dev/null 2>&1

    # Search for Logical Volumes on VG
    LVS=$(eval lvs $LVM_CFG "$vg_name" -o lv_path --noheadings 2>/dev/null | xargs)

    if [ -n "$LVS" ]; then
        for lv in $LVS; do
            # Skip if LV path contains the standard pool name
            if [[ "$lv" =~ lvmcsi-pool ]]; then
                continue
            fi
            # Activate LV
            eval lvchange $LVM_CFG -ay "$lv" 2>/dev/null

            # Wiping LV
            if ! wipefs -a "$lv" >/dev/null 2>&1; then
                log "ERROR" "Failed to wipe LV $lv"
            fi

            # Deactivate LV
            eval lvchange $LVM_CFG -an "$lv" >/dev/null 2>&1
        done
    fi

    # Deactivate VG
    eval vgchange $LVM_CFG -an "$vg_name" >/dev/null 2>&1

    log "INFO" "Successfully wiped LVs from ${vg_name} - ${LVS[*]}"
}

########################################################################
# Name      : wipe_disk
# Purpose   : Wipe the disk used to "store" th VG. To this, removes the VG,
#             removes the PV and wipes the disk.
# Parameters: \$1 vg_name - Volume Group Name
#             \$2 dev - Device path
# Return    : 1 if error, 0 for success
########################################################################
wipe_disk() {
    local vg_name=${1}
    local dev=${2}

    # Remove the VG with force option. This is necessary to avoid problems with
    # not empty VGs.
    if ! eval vgremove $LVM_CFG -fqy "$vg_name" >/dev/null 2>&1; then
        log "ERROR" "Failed to remove VG $vg_name"
        return 1
    fi

    # Remove the PV, avoiding orphans
    if ! eval pvremove $LVM_CFG -fqy "$dev" >/dev/null 2>&1; then
        log "ERROR" "Failed to remove PV $dev"
    fi

    # Wiping disk
    sgdisk --zap-all "${dev}"
    if ! wipefs -aqf "$dev" >/dev/null 2>&1; then
        log "ERROR" "Failed to wipe the disk $dev"
    fi

    log "INFO" "Successfully wiped disk ${dev} from ${vg_name}"
    return 0
}

########################################################################
# Validate if the script is running as root
if [ "$(id -u)" -ne 0 ]; then
    log "ERROR" "Must run as root"; exit 1
fi
########################################################################

log "INFO" "Starting LVM resources wipe process in ${MODE} mode"

ALL_DEVICES=$(lsblk -rnp -o NAME,TYPE | grep -iE '\b(disk|part)\b' | grep -v 'loop' | awk '{print $1}')

if [ -z "$ALL_DEVICES" ]; then
    log "ERROR" "No physical block devices found."
    exit 1
fi

for dev in $ALL_DEVICES; do
    vg_name=$(eval pvs $LVM_CFG "$dev" -o vg_name --noheadings --select 'vg_tags=lvm-csi' 2>&1 | xargs)

    # Skip in cases of error reading the device
    if [[ "$vg_name" =~ (Cannot|Failed|error|denied) ]]; then
        continue
    fi
    # Skip in cases of empty metadata
    if [ -z "$vg_name" ]; then
        continue
    fi

    # Skip cgts-vg
    if [ "$vg_name" = "cgts-vg" ]; then
        continue
    fi

    if [ "$MODE" = "bootstrap" ]; then
        wipe_disk "$vg_name" "$dev"
    else
        wipe_lv "$vg_name"
    fi

done
