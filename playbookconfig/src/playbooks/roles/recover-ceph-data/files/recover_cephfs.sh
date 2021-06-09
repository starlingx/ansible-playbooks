#!/bin/sh
#
# Copyright (c) 2021 Wind River Systems, Inc.
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

FS_NAME=kube-cephfs
DATA_POOL_NAME=kube-cephfs-data
METADATA_POOL_NAME=kube-cephfs-metadata

# This script is not supposed to fail, print extended logs from ansible
set -x

# This should be called when ceph process recovery has been disabled, but ceph
# mon/osds are operational

# Ensure that the Ceph MDS is stopped
/etc/init.d/ceph stop mds

# Check if the filesystem for the system RWX provisioner is present
ceph fs ls | grep ${FS_NAME}
if [ $? -ne 0 ]; then
    # Attempt to create the pool if not present, this should be present
    ceph fs new ${FS_NAME} ${METADATA_POOL_NAME} ${DATA_POOL_NAME}
    if [ $? -eq 22 ]; then
        # We need to rebuild the fs since we have hit:
        #   Error EINVAL: pool 'kube-cephfs-metadata' already contains some
        #   objects. Use an empty pool instead.
        ceph fs new ${FS_NAME} ${METADATA_POOL_NAME} ${DATA_POOL_NAME} --force
        ceph fs reset ${FS_NAME} --yes-i-really-mean-it
    fi
fi

# Start the Ceph MDS
/etc/init.d/ceph start mds
