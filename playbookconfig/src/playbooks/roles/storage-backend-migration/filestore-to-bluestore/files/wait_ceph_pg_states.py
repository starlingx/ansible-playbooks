#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Waits for all PGs to leave incomplete, inactive, or peering states.
#
# After OSDs go down, some PGs may enter these transient states.
# This script polls until no PGs remain in any of those states.
#
# The stall timer resets whenever the bad PG count decreases.
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

BAD_STATES = ("incomplete", "inactive", "peering")


def get_bad_pg_count(cluster):
    """Return the number of PGs in bad states, or None on failure."""
    ret, buf, _ = cluster.mon_command(
        json.dumps({"prefix": "pg stat", "format": "json"}), b""
    )
    if ret != 0:
        return None
    states = json.loads(buf)["pg_summary"]["num_pg_by_state"]
    return sum(
        s["num"] for s in states if any(b in s["name"] for b in BAD_STATES)
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stall-timeout", type=int, required=True)
    parser.add_argument("--poll-interval", type=int, required=True)
    args = parser.parse_args()

    last_bad = -1
    stall_elapsed = 0

    log.info("Waiting for PGs to leave incomplete|inactive|peering states...")

    with rados.Rados(conffile=rados.Rados.DEFAULT_CONF_FILES) as cluster:
        while True:
            bad_pgs = get_bad_pg_count(cluster)

            if bad_pgs is None:
                stall_elapsed += args.poll_interval
            else:
                log.info(
                    "PGs in bad states: %d (stall: %d/%ds)",
                    bad_pgs, stall_elapsed, args.stall_timeout,
                )

                if bad_pgs == 0:
                    log.info(
                        "No PGs in incomplete|inactive|peering states."
                    )
                    return 0

                if bad_pgs < last_bad and last_bad >= 0:
                    stall_elapsed = 0
                else:
                    stall_elapsed += args.poll_interval

                last_bad = bad_pgs

            if stall_elapsed >= args.stall_timeout:
                log.error(
                    "No progress for %ds. PGs in bad states: %s",
                    args.stall_timeout, bad_pgs,
                )
                return 1

            time.sleep(args.poll_interval)


if __name__ == "__main__":
    sys.exit(main())
