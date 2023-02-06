#!/usr/bin/python
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import parted
import pyudev
import re
import sys

from sysinv.common import constants as sysinv_constants


def get_rootfs_node():
    """Cloned from sysinv"""
    cmdline_file = '/proc/cmdline'
    device = None

    with open(cmdline_file, 'r') as f:
        for line in f:
            for param in line.split():
                params = param.split("=", 1)
                if params[0] == "root":
                    if "UUID=" in params[1]:
                        key, uuid = params[1].split("=")
                        symlink = "/dev/disk/by-uuid/%s" % uuid
                        device = os.path.basename(os.readlink(symlink))
                    else:
                        device = os.path.basename(params[1])
                elif params[0] == "ostree_boot":
                    if "LABEL=" in params[1]:
                        key, label = params[1].split("=")
                        symlink = "/dev/disk/by-label/%s" % label
                        device = os.path.basename(os.readlink(symlink))

    if device is not None:
        if sysinv_constants.DEVICE_NAME_NVME in device:
            re_line = re.compile(r'^(nvme[0-9]*n[0-9]*)')
        elif sysinv_constants.DEVICE_NAME_DM in device:
            return get_mpath_from_dm(os.path.join("/dev", device))
        else:
            re_line = re.compile(r'^(\D*)')
        match = re_line.search(device)
        if match:
            return os.path.join("/dev", match.group(1))

    return


def get_mpath_from_dm(dm_device):
    """Get mpath node from /dev/dm-N"""
    mpath_device = None

    context = pyudev.Context()

    pydev_device = pyudev.Devices.from_device_file(context, dm_device)

    if sysinv_constants.DEVICE_NAME_MPATH in pydev_device.get("DM_NAME", ""):
        re_line = re.compile(r'^(\D*)')
        match = re_line.search(pydev_device.get("DM_NAME"))
        if match:
            mpath_device = os.path.join("/dev/mapper", match.group(1))

    return mpath_device


def parse_fdisk(device_node):
    dev_info = parted.getDevice(device_node)
    size_bytes = dev_info.length * dev_info.sectorSize

    # Convert bytes to GiB (1 GiB = 1024*1024*1024 bytes)
    int_size = int(size_bytes)
    size_gib = int_size / 1073741824

    return int(size_gib)


def get_root_disk_size():
    """Get size of the root disk """
    context = pyudev.Context()
    rootfs_node = get_rootfs_node()
    print(rootfs_node)
    size_gib = 0

    # Determine if we are using the new Device API, or the older
    # (deprecated in debian) API:
    use_new_api = hasattr(pyudev.Device, 'properties')

    for device in context.list_devices(DEVTYPE='disk'):
        # /dev/nvmeXn1 259 are for NVME devices
        # For debian/centos compatibility:
        if use_new_api:
            major = device.properties['MAJOR']
        else:
            # Deprecated in python3 version:
            major = device['MAJOR']
        if (major == '8' or major == '3' or major == '253' or
                major == '259'):
            if sysinv_constants.DEVICE_NAME_MPATH in device.get("DM_NAME", ""):
                devname = os.path.join("/dev/mapper", device.get("DM_NAME"))
            else:
                if use_new_api:
                    devname = device.properties['DEVNAME']
                else:
                    devname = device['DEVNAME']
            if devname == rootfs_node:
                try:
                    size_gib = parse_fdisk(devname)
                except Exception:
                    break
                break
    return size_gib


if __name__ == '__main__':

    if len(sys.argv) < 2:
        raise Exception("Invalid input!")

    rds = get_root_disk_size()
    print(rds)
    if rds < int(sys.argv[1]):
        raise Exception("Failed validation!")
