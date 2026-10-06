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
# Name      : resolve_disk
# Purpose   : Resolve the whole disk backing a device. For a partition
#             it returns the parent disk; for a whole-disk device it
#             returns the device itself.
# Parameters: \$1 dev - Device path (partition or whole disk)
# Return    : Prints the whole-disk path on stdout
########################################################################
resolve_disk() {
    local dev=${1}
    local disk
    disk=$(lsblk -dnp -o PKNAME "$dev" 2>/dev/null | xargs)
    [ -z "$disk" ] && disk="$dev"
    echo "$disk"
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
# Purpose   : Fully wipe every disk backing a VG, removes the VG and all
#             its PVs and writes a fresh empty GPT over each whole disk.
#             The GPT is required so the sysinv agent reports a non-zero
#             available_mib. Handles VGs spanning more than one PV.
# Parameters: \$1 vg_name - Volume Group Name
# Return    : 1 if error, 0 for success
########################################################################
wipe_disk() {
    local vg_name=${1}

    # Discover all PVs assigned to the vg
    local pvs_list
    pvs_list=$(eval pvs $LVM_CFG -o pv_name --noheadings \
        --select "vg_name=$vg_name" 2>/dev/null | xargs)

    # Remove the VG (force, so a non-empty VG is handled).
    if ! eval vgremove $LVM_CFG -fqy "$vg_name" >/dev/null 2>&1; then
        log "ERROR" "Failed to remove VG $vg_name"
        return 1
    fi
    log "INFO" "Successfully removed VG ${vg_name}. Next: remove PVs."

    local rc=0
    local pv
    for pv in $pvs_list; do
        eval pvremove $LVM_CFG -fqy "$pv" >/dev/null 2>&1 \
            || log "WARNING" "Failed to remove PV $pv"

        # Always operate on the whole disk, even when the PV is a partition.
        local disk
        disk=$(resolve_disk "$pv")

        # Wipe each partition first, then the disk
        local parts
        parts=$(lsblk -rnp -o NAME,TYPE "$disk" 2>/dev/null | awk '$2 == "part" {print $1}')
        log "INFO" "Wiping partitions ${parts} and disk ${disk}"
        for part in $parts; do
            wipefs -f -a "$part" >/dev/null 2>&1 || log "WARNING" "wipefs failed on $part"
        done
        wipefs -f -a "$disk" >/dev/null 2>&1 || log "WARNING" "wipefs failed on $disk"

        # Zap any remaining GPT structures
        sgdisk --zap-all "$disk" >/dev/null 2>&1 || log "WARNING" "sgdisk failed on $disk"

        # Write a fresh empty GPT (retry once on transient failure)
        local gpt_ok=0
        local attempt
        for attempt in 1 2; do
            if parted -s "$disk" mklabel gpt >/dev/null 2>&1; then
                gpt_ok=1
                break
            fi
            log "WARNING" "Failed to create GPT label on disk $disk (attempt ${attempt}/2)"
            udevadm settle
        done
        if [ "$gpt_ok" -ne 1 ]; then
            log "ERROR" "Failed to create GPT label on disk $disk after 2 attempts"
            rc=1
            continue
        fi

        # Mark this disk as wiped so the main loop skips it on later PVs.
        WIPED_DISKS+="$disk "
        log "INFO" "Successfully wiped and GPT-formatted disk ${disk} from ${vg_name}"
    done
    udevadm settle

    return $rc
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

WIPED_DISKS=" "
OVERALL_RC=0

for dev in $ALL_DEVICES; do
    # Validate if the disk was already wiped
    disk=$(resolve_disk "$dev")
    if [[ "$WIPED_DISKS" == *" $disk "* ]]; then
        continue
    fi

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
        if ! wipe_disk "$vg_name"; then
            log "ERROR" "wipe_disk failed for VG $vg_name"
            OVERALL_RC=1
        fi
    else
        wipe_lv "$vg_name"
    fi

done

exit $OVERALL_RC
