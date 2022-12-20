#!/bin/sh
#
# Copyright (c) 2020, 2023 Wind River Systems, Inc.
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
sleep 2

part_type_guid_str="Partition GUID code"
CEPH_REGULAR_OSD_GUID="4FBD7E29-9D25-41B8-AFD0-062C0CEFF05D"
CEPH_REGULAR_JOURNAL_GUID="45B0969E-9B03-4F30-B4C6-B4B80CEFF106"
CEPH_MPATH_OSD_GUID="4FBD7E29-8AE0-4982-BF9D-5A8D867AF560"
CEPH_MPATH_JOURNAL_GUID="45B0969E-8AE0-4982-BF9D-5A8D867AF560"

# This script is not supposed to fail, print extended logs from ansible if it does.
set -x

function wipe_if_ceph_disk {
    local dev=$1
    local osd_guid=$2
    local journal_guid=$3

    part_no=1
    ceph_disk="false"
    for part in $(lsblk -rip ${dev} -o TYPE,NAME | \
        awk '$1 == "part" {print $2}'); do
        # UDEV triggers a partition rescan when a device node opened in write mode is closed.
        # To avoid this, we have to acquire a shared lock on the device while sgdisk works
        # with the device. For more details see:
        # https://git.devuan.org/devuan-packages/elogind/commit/4196a3ead3cfb823670d225eefcb3e60e34c7d95?view=parallel&w=1
        sgdisk_part_info=$(flock ${dev} sgdisk -i ${part_no} ${dev} || true)
        guid=$(echo "${sgdisk_part_info}" | \
            grep "$part_type_guid_str" | awk '{print $4;}')
        if [ "${guid}" == "$osd_guid" ]; then
            echo "Found Ceph OSD partition #${part_no} ${part}, erasing!"
            dd if=/dev/zero of=${part} bs=512 count=34 2>/dev/null
            seek_end=$((`blockdev --getsz ${part}` - 34))
            dd if=/dev/zero of=${part} \
                bs=512 count=34 seek=${seek_end} 2>/dev/null
            parted -s ${dev} rm ${part_no}
            ceph_disk="true"
        elif [ "${guid}" == "$journal_guid" ]; then
            echo "Found Ceph journal partition #${part_no} ${part}, erasing!"
            dd if=/dev/zero of=${part} bs=1M count=100 2>/dev/null
            seek_end=$((`blockdev --getsz ${part}` / (1024 * 2) - 100 ))
            dd if=/dev/zero of=${part} \
                bs=1M count=100 seek=${seek_end} 2>/dev/null
            parted -s ${dev} rm ${part_no}
            ceph_disk="true"
        fi

        part_no=$((part_no + 1))
    done

    # Wipe the entire disk, including GPT signatures
    if [ "${ceph_disk}" == "true" ]; then
        echo "Wiping Ceph disk ${dev} signatures."
        wipefs -a ${dev}
    fi

}

# Only non multipath
for f in /dev/disk/by-path/*; do

    # list of partitions in the loop may no longer be valid as
    # we are wiping disks.
    if [ ! -e "${f}" ]; then
        continue
    fi

    dev=$(readlink -f $f)
    lsblk --nodeps --pairs $dev | grep -q 'TYPE="disk"'
    if [ $? -ne 0 ] ; then
        continue
    fi

    #Skip if this is a valid multipath device
    multipath -c $dev
    if [ $? -eq 0 ] ; then
        continue
    fi

    set -e

    wipe_if_ceph_disk $dev $CEPH_REGULAR_OSD_GUID $CEPH_REGULAR_JOURNAL_GUID

    set +e
done

# Only multipath
for f in /dev/disk/by-id/wwn-*; do

    # list of partitions in the loop may no longer be valid as
    # we are wiping disks.
    if [ ! -e "${f}" ]; then
        continue
    fi

    dm_path=$(readlink -f $f)

    lsblk --nodeps --pairs $dm_path | grep -q 'TYPE="mpath"'
    if [ $? -ne 0 ] ; then
        continue
    fi

    dev=$(find -L /dev/mapper -samefile $dm_path)

    set -e

    wipe_if_ceph_disk $dev $CEPH_MPATH_OSD_GUID $CEPH_MPATH_JOURNAL_GUID

    set +e
done

