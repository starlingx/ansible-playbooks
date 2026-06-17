#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Waits for a single OSD to be fully drained (0 PGs).
#
# After an OSD is stopped (status "down"), Ceph remaps its PGs
# to other OSDs. This script polls until the target OSD reports
# 0 PGs via "ceph osd df".
#
# The stall timer resets whenever the PG count decreases.
# If no progress is detected within the stall timeout, the script
# exits with an error.

import argparse
import json
import logging
import sys
import time

import rados

logging.basicConfig(
    format="%(asctime)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


def get_osd_pg_count(cluster, osd_id):
    """Return the PG count for the given OSD, or None on failure."""
    ret, buf, _ = cluster.mon_command(
        json.dumps({"prefix": "osd df", "format": "json"}), b""
    )
    if ret != 0:
        return None
    for node in json.loads(buf)["nodes"]:
        if node["id"] == osd_id:
            return node["pgs"]
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--osd-id", type=int, required=True)
    parser.add_argument("--stall-timeout", type=int, required=True)
    parser.add_argument("--poll-interval", type=int, required=True)
    args = parser.parse_args()

    last_pgs = -1
    stall_elapsed = 0

    log.info("Waiting for osd.%d to drain (0 PGs)...", args.osd_id)

    with rados.Rados(conffile=rados.Rados.DEFAULT_CONF_FILES) as cluster:
        while True:
            pgs = get_osd_pg_count(cluster, args.osd_id)

            if pgs is None:
                stall_elapsed += args.poll_interval
            else:
                log.info(
                    "osd.%d: %d PGs (stall: %d/%ds)",
                    args.osd_id, pgs, stall_elapsed, args.stall_timeout,
                )

                if pgs == 0:
                    log.info("osd.%d drained.", args.osd_id)
                    return 0

                if pgs < last_pgs and last_pgs >= 0:
                    stall_elapsed = 0
                else:
                    stall_elapsed += args.poll_interval

                last_pgs = pgs

            if stall_elapsed >= args.stall_timeout:
                log.error(
                    "No drain progress for %ds. PGs remaining: %s",
                    args.stall_timeout, pgs,
                )
                return 1

            time.sleep(args.poll_interval)


if __name__ == "__main__":
    sys.exit(main())
