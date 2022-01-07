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
    # If we have existing metadata/data pools, use them
    ceph fs new ${FS_NAME} ${METADATA_POOL_NAME} ${DATA_POOL_NAME} --force
    # Reset the filesystem and journal
    ceph fs reset ${FS_NAME} --yes-i-really-mean-it
    cephfs-journal-tool --rank=${FS_NAME}:0 event recover_dentries summary
    cephfs-journal-tool --rank=${FS_NAME}:0 journal reset
fi

# Start the Ceph MDS
/etc/init.d/ceph start mds
