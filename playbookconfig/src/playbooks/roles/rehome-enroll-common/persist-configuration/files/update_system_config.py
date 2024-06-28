#!/usr/bin/env python3

# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Update Sysinv configurations during subcloud rehoming/enrollment
#

import configparser
import os
import subprocess
import sys


from cgtsclient import client as cgts_client
from sysinv.common import constants as sysinv_constants


# Configuration parser setup
# By default, configparse transforms all loaded parameters to lowercase.
# This is a problem for Kubernetes kubelet configurations because they are
# written with Camel Case notation. With the optionxform attribute it is
# possible to disable the transformation to lowercase.
CONF = configparser.ConfigParser(interpolation=None)
CONF.optionxform = str


RECONFIGURE_NETWORK = False
RECONFIGURE_SERVICE = False


# CgtsClient class to handle API interactions
class CgtsClient(object):
    SYSINV_API_VERSION = 1

    def __init__(self):
        self.conf = {}
        self._sysinv = None

        # Loading credentials and configurations from environment variables
        # typically set in OpenStack
        source_command = 'source /etc/platform/openrc && env'

        with open(os.devnull, "w") as fnull:
            proc = subprocess.Popen(
                ['bash', '-c', source_command],
                stdout=subprocess.PIPE, stderr=fnull,
                universal_newlines=True)

        # Strip the configurations starts with 'OS_' and change the value to lower
        for line in proc.stdout:
            key, _, value = line.partition("=")
            if key.startswith('OS_'):
                self.conf[key[3:].lower()] = value.strip()

        proc.communicate()

    @property
    def sysinv(self):
        if not self._sysinv:
            self._sysinv = cgts_client.get_client(
                self.SYSINV_API_VERSION,
                os_username=self.conf['username'],
                os_password=self.conf['password'],
                os_auth_url=self.conf['auth_url'],
                os_project_name=self.conf['project_name'],
                os_project_domain_name=self.conf['project_domain_name'],
                os_user_domain_name=self.conf['user_domain_name'],
                os_region_name=self.conf['region_name'],
                os_service_type='platform',
                os_endpoint_type='admin')
        return self._sysinv


def dict_to_patch(values, install_action=False):
    # install default action
    if install_action:
        values.update({'action': 'install'})
    patch = []
    for key, value in values.items():
        path = '/' + key
        patch.append({'op': 'replace', 'path': path, 'value': value})
    return patch


def update_docker_proxy_config(client, section_name):
    http_proxy = CONF.get(section_name, 'DOCKER_HTTP_PROXY')
    https_proxy = CONF.get(section_name, 'DOCKER_HTTPS_PROXY')
    no_proxy = CONF.get(section_name, 'DOCKER_NO_PROXY')

    # Get rid of the faulty docker proxy entries that might have
    # been created in the previous failed run.
    parameters = client.sysinv.service_parameter.list()
    for parameter in parameters:
        if (parameter.name == sysinv_constants.SERVICE_PARAM_NAME_DOCKER_HTTP_PROXY or
                parameter.name == sysinv_constants.SERVICE_PARAM_NAME_DOCKER_HTTPS_PROXY or
                parameter.name == sysinv_constants.SERVICE_PARAM_NAME_DOCKER_NO_PROXY):
            client.sysinv.service_parameter.delete(parameter.uuid)

    if http_proxy != 'undef' or https_proxy != 'undef':
        parameters = {}
        if http_proxy != 'undef':
            parameters[
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_HTTP_PROXY] = http_proxy
        if https_proxy != 'undef':
            parameters[
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_HTTPS_PROXY] = https_proxy

        parameters[sysinv_constants.SERVICE_PARAM_NAME_DOCKER_NO_PROXY] = no_proxy
        values = {
            'service': sysinv_constants.SERVICE_TYPE_DOCKER,
            'section': sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_PROXY,
            'personality': None,
            'resource': None,
            'parameters': parameters
        }

        print("Populating/Updating docker proxy config...")
        client.sysinv.service_parameter.create(**values)
        print("Docker proxy config completed.")


def update_docker_registry_config(client, section_name):
    """Handle Docker registry configurations."""
    use_default_registries = CONF.getboolean(
        section_name, 'USE_DEFAULT_REGISTRIES')
    # Get rid of any faulty docker registry entries that might have been
    # created in the previous failed run.
    parameters = client.sysinv.service_parameter.list()
    for parameter in parameters:
        if (parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_K8S_REGISTRY or
                parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_GCR_REGISTRY or
                parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_QUAY_REGISTRY or
                parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_DOCKER_REGISTRY or
                parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_ELASTIC_REGISTRY or
                parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_GHCR_REGISTRY or
                parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_REGISTRYK8S_REGISTRY or
                parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_ICR_REGISTRY):
            client.sysinv.service_parameter.delete(parameter.uuid)

    if not use_default_registries:
        parameters = {}

        registries_map = {
            sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_K8S_REGISTRY: 'K8S',
            sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_GCR_REGISTRY: 'GCR',
            sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_QUAY_REGISTRY: 'QUAY',
            sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_DOCKER_REGISTRY: 'DOCKER',
            sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_ELASTIC_REGISTRY: 'ELASTIC',
            sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_GHCR_REGISTRY: 'GHCR',
            sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_REGISTRYK8S_REGISTRY: 'REGISTRYK8S',
            sysinv_constants.SERVICE_PARAM_SECTION_DOCKER_ICR_REGISTRY: 'ICR'
        }

        registries = {}
        for registry, value in registries_map.items():
            registries[registry] = {
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_URL: CONF.get(
                    section_name, value + '_REGISTRY'),
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_AUTH_SECRET: CONF.get(
                    section_name, value + '_REGISTRY_SECRET'),
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_TYPE: CONF.get(
                    section_name, value + '_REGISTRY_TYPE'),
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_SECURE_REGISTRY: CONF.getboolean(
                    section_name, value + '_REGISTRY_SECURE'),
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_ADDITIONAL_OVERRIDES: CONF.get(
                    section_name, value + '_REGISTRY_ADDITIONAL_OVERRIDES'),
            }

        for registry, values in registries.items():

            parameters[registry] = {
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_URL:
                    values[sysinv_constants.SERVICE_PARAM_NAME_DOCKER_URL]
            }

            if values[sysinv_constants.SERVICE_PARAM_NAME_DOCKER_AUTH_SECRET] != 'none':

                # we need the split because we want the Barbican UUID, not the secret href
                parameters[registry][sysinv_constants.SERVICE_PARAM_NAME_DOCKER_AUTH_SECRET] = \
                    values[sysinv_constants.SERVICE_PARAM_NAME_DOCKER_AUTH_SECRET].split('/')[-1]
                parameters[registry][sysinv_constants.SERVICE_PARAM_NAME_DOCKER_TYPE] = \
                    values[sysinv_constants.SERVICE_PARAM_NAME_DOCKER_TYPE]

            if not values[sysinv_constants.SERVICE_PARAM_NAME_DOCKER_SECURE_REGISTRY]:
                parameters[registry][sysinv_constants.SERVICE_PARAM_NAME_DOCKER_SECURE_REGISTRY] = "False"

            if values[sysinv_constants.SERVICE_PARAM_NAME_DOCKER_ADDITIONAL_OVERRIDES] != 'undef':

                parameters[registry][sysinv_constants.SERVICE_PARAM_NAME_DOCKER_ADDITIONAL_OVERRIDES] = \
                    values[sysinv_constants.SERVICE_PARAM_NAME_DOCKER_ADDITIONAL_OVERRIDES]

        print("Populating/Updating docker registry config...")
        for registry in parameters:
            values = {
                'service': sysinv_constants.SERVICE_TYPE_DOCKER,
                'section': registry,
                'personality': None,
                'resource': None,
                'parameters': parameters[registry]
            }
            client.sysinv.service_parameter.create(**values)
        print("Docker registry config completed.")


def populate_user_dns_host_records(client):
    # Remove any previous user DNS entry that have been created in the
    # previous run.
    parameters = client.sysinv.service_parameter.list()
    for parameter in parameters:
        if parameter.section == sysinv_constants.SERVICE_PARAM_SECTION_DNS_HOST_RECORD:
            client.sysinv.service_parameter.delete(parameter.uuid)

    parameters = {}
    for user_dns_host_name, host_record in CONF.items(section="USER_DNS_HOST_RECORDS"):
        parameters[user_dns_host_name] = host_record
    if parameters:
        values = {
            'service': sysinv_constants.SERVICE_TYPE_DNS,
            'section':
                sysinv_constants.SERVICE_PARAM_SECTION_DNS_HOST_RECORD,
            'personality': None,
            'resource': None,
            'parameters': parameters
        }

        print("Populating/Updating user dns host-records...")
        client.sysinv.service_parameter.create(**values)

        print("Populating/Updating user dns host-records completed.")


def populate_docker_config(client, section_name):
    """
    Update Docker and Kubernetes configuration parameters.
    Handles proxy settings and Docker registry configurations.
    """
    try:
        update_docker_proxy_config(client, section_name)
        update_docker_registry_config(client, section_name)
    except Exception as e:
        print(f"Failed to update Docker/Kube config: {e}")
        raise


def populate_dns_config(client, section_name):
    print("Populating/Updating DNS config...")
    nameservers = CONF.get(section_name, 'NAMESERVERS')

    dns_list = client.sysinv.idns.list()
    dns_record = dns_list[0]
    values = {
        'nameservers': nameservers.rstrip(','),
        'action': 'apply'
    }
    patch = dict_to_patch(values)
    client.sysinv.idns.update(dns_record.uuid, patch)
    print("DNS config completed.")


def populate_service_parameter_config(client, section_name):
    populate_docker_config(client, section_name)
    if CONF.has_section("USER_DNS_HOST_RECORDS"):
        populate_user_dns_host_records(client)
    else:
        print("Skipping Populating/Updating user dns host-records...")


def edit_dc_role_to_subcloud(client):
    """Changes Distributed Cloud Role to 'subcloud'
    """
    isystem_list = client.sysinv.isystem.list()
    isystem = isystem_list[0]
    current_dc_role = isystem.distributed_cloud_role
    patch = [
        {
            'op': 'replace',
            'path': '/distributed_cloud_role',
            'value': sysinv_constants.DISTRIBUTED_CLOUD_ROLE_SUBCLOUD
        }
    ]
    isystem = client.sysinv.isystem.update(isystem.uuid, patch)
    updated_dc_role = isystem.distributed_cloud_role
    print(f"Distributed Cloud Role updated: "
          f"'{current_dc_role}' -> '{updated_dc_role}'")


# Main function to execute based on command-line input
def main():
    if len(sys.argv) < 2:
        print("Usage: update_system_config.py <config_file>")
        sys.exit(1)

    config_file = sys.argv[1]
    if not os.path.isfile(config_file):
        print(f"Error: Config file '{config_file}' does not exist.")
        sys.exit(1)

    CONF.read(config_file)
    if 'OPERATION' not in CONF or 'MODE' not in CONF['OPERATION']:
        print("The 'MODE' option is missing in the 'OPERATION' section of the "
              "configuration file.")
        sys.exit(1)

    operation = CONF.get('OPERATION', 'MODE')
    section_name = operation.upper() + '_CONFIG'
    client = CgtsClient()
    populate_dns_config(client, section_name)
    populate_service_parameter_config(client, section_name)
    edit_dc_role_to_subcloud(client)


if __name__ == '__main__':
    main()
