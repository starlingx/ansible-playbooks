#!/usr/bin/python
#
# Copyright (c) 2019 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import shutil
import subprocess
import sys


def recover_ceph_data():
    ceph_osds = '/var/lib/ceph/osd/'
    mon_store = '/tmp/mon-store'

    if os.path.exists(mon_store):
        print("Removing {}.".format(mon_store))
        shutil.rmtree(mon_store)

    os.mkdir(mon_store, 0o751)

    for osd in os.listdir(ceph_osds):
        osd = ceph_osds + osd
        print("Scanning {}.".format(osd))

        # Fix possible lost objects
        subprocess.run(["ceph-objectstore-tool", "--data-path",
                        osd, "--op", "fix-lost"], stderr=subprocess.STDOUT)

        output = subprocess.check_output(["ceph-objectstore-tool", "--data-path",
                                          osd, "--op", "update-mon-db",
                                          "--mon-store-path",
                                          mon_store], stderr=subprocess.STDOUT)
        print("Scan osd {} output: {}".format(osd, output))

    print("Rebuilding monitor data.")
    output = subprocess.check_output(["ceph-monstore-tool", mon_store, "rebuild"],
                                     stderr=subprocess.STDOUT)
    print("Rebuild monitor data output: {}".format(output))


if __name__ == '__main__':
    try:
        recover_ceph_data()
    except subprocess.CalledProcessError as e:
        print("Error: Running command \"{}\" exited with {}. Output: {}".format(e.cmd, e.returncode, e.output))
        sys.exit(e.returncode)
