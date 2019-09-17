#!/usr/bin/python

#
# Copyright (c) 2019 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import sys

from fm_api import constants as fm_constants
from fm_api import fm_api
from sysinv.common import constants as sysinv_constants


def update_alarm(alarm_state, alarm_id, reason_text=None):
    """ Update backup-in-progress alarm"""
    fmApi = fm_api.FaultAPIs()
    entity_instance_id = "%s=%s" % (fm_constants.FM_ENTITY_TYPE_HOST,
                                    sysinv_constants.CONTROLLER_HOSTNAME)

    if alarm_state == fm_constants.FM_ALARM_STATE_SET:
        fault = fm_api.Fault(
            alarm_id=alarm_id,
            alarm_state=alarm_state,
            entity_type_id=fm_constants.FM_ENTITY_TYPE_HOST,
            entity_instance_id=entity_instance_id,
            severity=fm_constants.FM_ALARM_SEVERITY_MINOR,
            reason_text=("System Backup in progress."),
            # operational
            alarm_type=fm_constants.FM_ALARM_TYPE_7,
            # congestion
            probable_cause=fm_constants.ALARM_PROBABLE_CAUSE_8,
            proposed_repair_action=("No action required."),
            service_affecting=False)

        fmApi.set_fault(fault)
    else:
        fmApi.clear_fault(alarm_id, entity_instance_id)


def handle_invalid_input():
    raise Exception("Invalid input!\nUsage: <--set|--clear> <--alarm-name>")


if __name__ == '__main__':

    argc = len(sys.argv)
    if argc != 3:
        handle_invalid_input()

    if sys.argv[1] == "--set":
        alarm_state = fm_constants.FM_ALARM_STATE_SET
    elif sys.argv[1] == "--clear":
        alarm_state = fm_constants.FM_ALARM_STATE_CLEAR
    else:
        handle_invalid_input()

    if sys.argv[2] == "--backup":
        alarm_id = fm_constants.FM_ALARM_ID_BACKUP_IN_PROGRESS
        reason_text = "System Backup in progress."
    else:
        handle_invalid_input()

    update_alarm(alarm_state, alarm_id, reason_text)
