#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Waits for all PGs to reach active+clean state after a recovery.
#
# The stall timer resets whenever the active+clean count increases.
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


def get_pg_stats(cluster):
    """Return (num_pgs, active_clean_count), or None on failure."""
    ret, buf, _ = cluster.mon_command(
        json.dumps({"prefix": "pg stat", "format": "json"}), b""
    )
    if ret != 0:
        return None
    summary = json.loads(buf)["pg_summary"]
    num_pgs = summary["num_pgs"]
    active_clean = next(
        (s["num"] for s in summary["num_pg_by_state"]
         if s["name"] == "active+clean"),
        0,
    )
    return num_pgs, active_clean


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stall-timeout", type=int, required=True)
    parser.add_argument("--poll-interval", type=int, required=True)
    args = parser.parse_args()

    last_clean = -1
    stall_elapsed = 0

    with rados.Rados(conffile=rados.Rados.DEFAULT_CONF_FILES) as cluster:
        while True:
            result = get_pg_stats(cluster)

            if result is None:
                time.sleep(args.poll_interval)
                continue

            num_pgs, active_clean = result

            log.info(
                "PGs active+clean: %d/%d (stall: %d/%ds)",
                active_clean, num_pgs, stall_elapsed, args.stall_timeout,
            )

            if active_clean == num_pgs:
                log.info("All PGs are active+clean.")
                return 0

            if active_clean > last_clean and last_clean >= 0:
                stall_elapsed = 0
            else:
                stall_elapsed += args.poll_interval

            last_clean = active_clean

            if stall_elapsed >= args.stall_timeout:
                log.error(
                    "No recovery progress for %ds. "
                    "PGs active+clean: %d/%d",
                    args.stall_timeout, active_clean, num_pgs,
                )
                return 1

            time.sleep(args.poll_interval)


if __name__ == "__main__":
    sys.exit(main())
