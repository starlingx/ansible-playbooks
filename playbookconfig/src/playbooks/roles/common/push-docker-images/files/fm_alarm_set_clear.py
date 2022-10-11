#!/usr/bin/python

#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
import argparse

from fm_api import constants as fm_constants
from fm_api import fm_api
from sysinv.common import constants as sysinv_constants


def alarm_push_to_local_registry_handle(alarm_state, alarm_id, reason_text):
    """handle local registry alarm"""
    fmApi = fm_api.FaultAPIsV2()
    entity_instance_id = "%s=%s" % (
        fm_constants.FM_ENTITY_TYPE_HOST,
        sysinv_constants.CONTROLLER_HOSTNAME,
    )

    data = {
        "alarm_id": alarm_id,
        "alarm_state": alarm_state,
        "severity": fm_constants.FM_ALARM_CRITICAL_STATUS,
        "alarm_type": fm_constants.FM_ALARM_TYPE_0,
        "probable_cause": fm_constants.ALARM_PROBABLE_CAUSE_UNKNOWN,
        "reason_text": reason_text,
        "entity_type_id": "",
        "entity_instance_id": entity_instance_id,
        "proposed_repair_action": "No action required.",
    }

    fault = fm_api.Fault(**data)

    if alarm_state == fm_constants.FM_ALARM_STATE_SET:
        fmApi.set_fault(fault)
    else:
        fmApi.clear_fault(alarm_id, entity_instance_id)


def handle_invalid_input():
    raise Exception("Invalid input!\nUsage: <--set|--clear> <--alarm-name>")


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Set or clear alarm")
    parser.add_argument("--set", dest="state", action="store_true", default=False)
    parser.add_argument("--clear", dest="state", action="store_false", default=False)
    args = parser.parse_args()

    alarm_state = fm_constants.FM_ALARM_STATE_SET
    if not args.state:
        alarm_state = fm_constants.FM_ALARM_STATE_CLEAR

    reason_text = "Fail to push imported images to local registry."
    alarm_push_to_local_registry_handle(
        alarm_state, fm_constants.FM_ALARM_ID_SW_UPGRADE_AUTO_APPLY_FAILED, reason_text
    )
