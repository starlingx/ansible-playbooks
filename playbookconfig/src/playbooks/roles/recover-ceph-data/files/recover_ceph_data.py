#!/usr/bin/python
#
# Copyright (c) 2019 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import shutil
import subprocess


def recover_ceph_data():
    ceph_osds = '/var/lib/ceph/osd/'
    mon_store = '/tmp/mon-store'

    if os.path.exists(mon_store):
        print("Removing {}.".format(mon_store))
        shutil.rmtree(mon_store)

    os.mkdir(mon_store, 0o751)

    with open(os.devnull, "w") as fnull:
        for osd in os.listdir(ceph_osds):
            osd = ceph_osds + osd
            print("Scanning {}.".format(osd))
            subprocess.check_output(["ceph-objectstore-tool", "--data-path",
                                     osd, "--op", "update-mon-db",
                                     "--mon-store-path",
                                     mon_store], stderr=fnull)
        print("Rebuilding monitor data.")
        subprocess.check_output(["ceph-monstore-tool", mon_store, "rebuild"],
                                stderr=fnull)


if __name__ == '__main__':
    recover_ceph_data()
