#!/usr/bin/python

#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import argparse

from fm_api import constants as fm_constants
from fm_api import fm_api


def update_alarm(entity_uuid, alarm_state, type, alarm_args={}):
    """ Update migration alarm"""

    fm = fm_api.FaultAPIs()
    entity_instance_id = "%s_migration_%s=%s" % (fm_constants.FM_ENTITY_TYPE_STORAGE_BACKEND, type, entity_uuid)

    if alarm_state == fm_constants.FM_ALARM_STATE_SET:
        fault = fm_api.Fault(
            alarm_id=fm_constants.FM_ALARM_ID_STORAGE_CEPH,
            alarm_state=fm_constants.FM_ALARM_STATE_SET,
            entity_type_id=fm_constants.FM_ENTITY_TYPE_STORAGE_BACKEND,
            entity_instance_id=entity_instance_id,
            alarm_type=fm_constants.FM_ALARM_TYPE_5,
            service_affecting=True,
            **alarm_args,
        )
        fm.set_fault(fault)
    else:
        fm.clear_fault(fm_constants.FM_ALARM_ID_STORAGE_CEPH, entity_instance_id)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Update entity status"
    )

    parser.add_argument(
        "--entity-uuid",
        required=True,
        help="UUID of the storage-backend entity",
    )

    parser.add_argument(
        "--file-name",
        help="File name for repair action message",
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--set",
        choices=["in_progress", "error", "not_in_sync"],
        help="Set alarm type"
    )
    group.add_argument(
        "--clear",
        choices=["in_progress", "error", "not_in_sync"],
        help="Clear alarm"
    )

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_args()

    if args.clear:
        alarm_state = fm_constants.FM_ALARM_STATE_CLEAR
        type = args.clear
    else:
        alarm_state = fm_constants.FM_ALARM_STATE_SET
        type = args.set

    args_map = {
        "in_progress": dict(
            severity=fm_constants.FM_ALARM_SEVERITY_MINOR,
            reason_text="Rook Migration is in progress",
            probable_cause=fm_constants.ALARM_PROBABLE_CAUSE_8,
            proposed_repair_action="No action required.",
        ),
        "error": dict(
            severity=fm_constants.FM_ALARM_SEVERITY_MAJOR,
            reason_text="Error during Rook Migration",
            probable_cause=fm_constants.ALARM_PROBABLE_CAUSE_39,
            proposed_repair_action=f"Check {args.file_name or '<file-name>'}, fix and re-run migration.",
        ),
        "not_in_sync": dict(
            severity=fm_constants.FM_ALARM_SEVERITY_WARNING,
            reason_text="Hosts or system not in-sync or not reconciled after Rook migration",
            probable_cause=fm_constants.ALARM_PROBABLE_CAUSE_75,
            proposed_repair_action=f"Check the generated DM file in {args.file_name or '<file-name>'}, fix it and re-apply it."
        )
    }

    update_alarm(args.entity_uuid, alarm_state, type, args_map[type])
