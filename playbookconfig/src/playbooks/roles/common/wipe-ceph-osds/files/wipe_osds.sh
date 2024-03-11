#!/bin/bash
#
# Copyright (c) 2020, 2023-2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

# WORKAROUND: For script module become user issue.
#             It doesn't detected correctly the BECOME-SUCCESS
#             message of become. It happens for tasks quick to produce
#             output. The python scripts seem not to be affected by
#             this due to overhead of loading the interpreter.
#
#             Upstream reports of this:
#             - https://github.com/ansible/ansible/issues/70092
if [ -z "${NO_WORKAROUND}" ]; then
    sleep 2
fi

CEPH_REGULAR_OSD_GUID="4FBD7E29-9D25-41B8-AFD0-062C0CEFF05D"
CEPH_REGULAR_JOURNAL_GUID="45B0969E-9B03-4F30-B4C6-B4B80CEFF106"
CEPH_MPATH_OSD_GUID="4FBD7E29-8AE0-4982-BF9D-5A8D867AF560"
CEPH_MPATH_JOURNAL_GUID="45B0969E-8AE0-4982-BF9D-5A8D867AF560"

# This script is not supposed to fail, print extended logs from ansible if it does.
set -x

unlock_dev() {
    local __lock_fd="${lock_fd}"

    if [ -z "${__lock_fd}" ]; then
        return
    fi

    flock -u "${__lock_fd}"
    exec {__lock_fd}>&-

    lock_fd=
    trap "" EXIT
}

lock_dev() {
    local __dev="${1}"

    declare -g lock_fd=

    trap "unlock_dev" EXIT
    exec {lock_fd}>"${__dev}"
    flock -x "${lock_fd}"
}

__wipe_if_ceph_disk() {
    __dev="$1"
    __osd_guid="$2"
    __journal_guid="$3"
    __is_multipath="$4"

    ceph_disk="false"

    for part in $(sfdisk -q -l "${__dev}" | \
        awk '$1 == "Device" {i=1; next}; i {print $1}'); do

        part_no="$(echo "${part}" | sed -n -e 's@^.*[^0-9]\([0-9]\+\)$@\1@p')"
        guid=$(sfdisk --part-type "$__dev" "$part_no")
        if [ "${guid}" = "$__osd_guid" ]; then
            echo "Found Ceph OSD partition #${part_no} ${part}, erasing!"
            dd if=/dev/zero of="${part}" bs=512 count=34 2>/dev/null
            seek_end=$(($(blockdev --getsz "${part}") - 34))
            dd if=/dev/zero of="${part}" \
                bs=512 count=34 seek="${seek_end}" 2>/dev/null
            parted -s "${__dev}" rm "${part_no}"
            ceph_disk="true"
            # without "set -e" need to check if
            # the partitions were removed correctly
            if parted "${__dev}" p | grep "ceph data"; then
                echo "Ceph data partition could not be deleted! \
                        Wipe osd disk manually and try again."
                exit 1
            fi
        elif [ "${guid}" = "$__journal_guid" ]; then
            echo "Found Ceph journal partition #${part_no} ${part}, erasing!"
            dd if=/dev/zero of="${part}" bs=1M count=100 2>/dev/null
            seek_end=$(($(blockdev --getsz "${part}") / (1024 * 2) - 100 ))
            dd if=/dev/zero of="${part}" \
                bs=1M count=100 seek=${seek_end} 2>/dev/null
            parted -s "${__dev}" rm "${part_no}"
            ceph_disk="true"
            # without "set -e" need to check if
            # the partitions were removed correctly
            if parted "${__dev}" p | grep "ceph journal"; then
                echo "Ceph journal partition could not be deleted! \
                        Wipe osd disk manually and try again."
                exit 1
            fi
        fi
    done

    # Wipe the entire disk, including GPT signatures
    if [ "${ceph_disk}" = "true" ]; then
        echo "Wiping Ceph disk ${__dev} signatures."
        if [ "${__is_multipath}" = 1 ]; then
            # when a partition are removed in
            # multipath systems needs to update partitions
            # uuid list to avoid errors when
            # the ceph-disk prepare run
            kpartx "${__dev}"
        fi
        wipefs -a "${__dev}"
    fi
}

wipe_if_ceph_disk() {
    local __dev="$1"

    # Based on past experience observing race conditions with udev and updates
    # to partition data/metadata we will continue to use flock in accordance
    # with: https://systemd.io/BLOCK_DEVICE_LOCKING/
    lock_dev "${__dev}"

    __wipe_if_ceph_disk "${@}"

    unlock_dev
}

# Only non multipath
for f in /dev/disk/by-path/*; do

    # list of partitions in the loop may no longer be valid as
    # we are wiping disks.
    if [ ! -e "${f}" ]; then
        continue
    fi

    dev=$(readlink -f "$f")
    if ! lsblk --nodeps --pairs "$dev" | grep -q 'TYPE="disk"' ; then
        continue
    fi

    #Skip if this is a valid multipath device
    if multipath -c "$dev" ; then
        continue
    fi

    set -e

    wipe_if_ceph_disk \
        "$dev" \
        $CEPH_REGULAR_OSD_GUID \
        $CEPH_REGULAR_JOURNAL_GUID \
        0

    set +e
done

# Only multipath
for f in /dev/disk/by-id/wwn-*; do

    # list of partitions in the loop may no longer be valid as
    # we are wiping disks.
    if [ ! -e "${f}" ]; then
        continue
    fi

    dm_path=$(readlink -f "$f")


    if ! lsblk --nodeps --pairs "$dm_path" | grep -q 'TYPE="mpath"' ; then
        continue
    fi

    dev=$(find -L /dev/mapper -samefile "$dm_path")

    # The 'set -e' has caused issues with this script when dealing
    # with multipath configurations. This is because the 'parted -s' 
    # command may not return a 0 when multipath partitions are removed
    wipe_if_ceph_disk "$dev" $CEPH_MPATH_OSD_GUID $CEPH_MPATH_JOURNAL_GUID 1

done
