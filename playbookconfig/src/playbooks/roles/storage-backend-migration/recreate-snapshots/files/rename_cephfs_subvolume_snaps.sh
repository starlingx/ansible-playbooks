#!/bin/bash
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

VOLUME="kube-cephfs"
GROUP="csi"
MOUNT_POINT="/mnt/cephfs_temp_rename"

echo "Collecting cluster information for mounting..."
# Get admin key automatically
SECRET=$(ceph auth get-key client.admin)
# Get monitor IPs automatically (format ip1:port,ip2:port,ip3:port)
MONS=$(ceph mon dump 2>/dev/null | grep -oP 'v1:\K(\[[^\]]+\]:[0-9]+|[0-9.]+:[0-9]+)' | paste -sd "," -)

if [ -z "$SECRET" ] || [ -z "$MONS" ]; then
    echo "Error: Could not obtain Ceph credentials or monitor IPs."
    exit 1
fi

echo "Mounting CephFS at $MOUNT_POINT..."
mkdir -p "$MOUNT_POINT"
# Mount CephFS in kernel
mount -t ceph "$MONS:/" "$MOUNT_POINT" -o name=admin,secret="$SECRET"

if ! mountpoint -q "$MOUNT_POINT"; then
    echo "Error: Failed to mount CephFS."
    exit 1
fi

echo "Searching for subvolumes..."
SUBVOLUMES=$(ceph fs subvolume ls "$VOLUME" "$GROUP" --format json | grep -oP '"name":\s*"\K[^"]+')

if [ -z "$SUBVOLUMES" ]; then
    echo "No subvolumes found."
    echo "Unmounting CephFS..."
    umount "$MOUNT_POINT"
    rm -rf "$MOUNT_POINT"
    exit 0
fi

for SUBVOLUME in $SUBVOLUMES; do
    SNAP_DIR="$MOUNT_POINT/volumes/$GROUP/$SUBVOLUME/.snap"

    if [ -d "$SNAP_DIR" ]; then
        # Iterate over snapshots starting with cephfs-snap-
        for SNAP_PATH in "$SNAP_DIR"/cephfs-snap-*; do

            # Skip if glob doesn't find real files
            [ -e "$SNAP_PATH" ] || continue

            OLD_SNAP_NAME=$(basename "$SNAP_PATH")
            NEW_SNAP_NAME="${OLD_SNAP_NAME/cephfs-snap-/csi-snap-}"

            echo "  Renaming in subvolume $SUBVOLUME: $OLD_SNAP_NAME -> $NEW_SNAP_NAME"

            # Execute rename
            mv "$SNAP_DIR/$OLD_SNAP_NAME" "$SNAP_DIR/$NEW_SNAP_NAME"

            echo "  Done: $NEW_SNAP_NAME"
        done
    fi
done

echo "Unmounting CephFS..."
umount "$MOUNT_POINT"
rm -rf "$MOUNT_POINT"

echo "Process completed successfully!"
