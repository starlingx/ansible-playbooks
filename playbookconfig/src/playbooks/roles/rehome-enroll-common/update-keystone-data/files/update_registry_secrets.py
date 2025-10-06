#!/usr/bin/env python3

# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Make a RPC call to sysinv to update credentials for the local docker
# registry stored in secrets in each namespace
#

from six.moves import configparser
from sysinv.conductor import rpcapiproxy as conductor_rpcapi
from oslo_config import cfg
from oslo_context import context as mycontext

CONF = cfg.CONF
SYSINV_CONFIG_FILE = '/etc/sysinv/sysinv.conf'


def get_conductor_rpc_bind_ip():
    ini_str = '[DEFAULT]\n' + open(SYSINV_CONFIG_FILE, 'r').read()
    config_applied = configparser.RawConfigParser()
    config_applied.read_string(ini_str)

    conductor_bind_ip = None
    if config_applied.has_option('DEFAULT', 'rpc_zeromq_conductor_bind_ip'):
        conductor_bind_ip = \
            config_applied.get('DEFAULT', 'rpc_zeromq_conductor_bind_ip')
    return conductor_bind_ip


def run_local_registry_secrets_audit_rpc():
    CONF.rpc_zeromq_conductor_bind_ip = get_conductor_rpc_bind_ip()
    context = mycontext.get_admin_context()
    rpcapi = conductor_rpcapi.ConductorAPI(topic=conductor_rpcapi.MANAGER_TOPIC)
    rpcapi.run_local_registry_secrets_audit(context)


def main():
    run_local_registry_secrets_audit_rpc()


if __name__ == '__main__':
    main()
