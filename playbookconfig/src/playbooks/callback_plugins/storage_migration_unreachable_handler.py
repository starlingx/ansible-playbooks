#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""
    Ansible callback plugin for storage-backend-migration playbooks.

    Tracks hosts that become unreachable during playbook execution and exposes
    them via the 'unreachable_hosts' play variable. This works around a Trixie
    ansible-core issue where any_errors_fatal=true does not reliably abort the
    play on host unreachable events.

    Enable in ansible.cfg:
        callbacks_enabled = storage_migration_unreachable_handler
"""

from ansible.plugins.callback import CallbackBase


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'notification'
    CALLBACK_NAME = 'storage_migration_unreachable_handler'
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super(CallbackModule, self).__init__()
        self._unreachable_hosts = []

    def v2_playbook_on_play_start(self, play):
        play.vars['unreachable_hosts'] = self._unreachable_hosts

    def v2_runner_on_unreachable(self, result):
        self._unreachable_hosts.append(result._host.get_name())
