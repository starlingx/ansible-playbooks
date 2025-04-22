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
import time

from barbicanclient import client as barbican_client
from cgtsclient import client as cgts_client
from datetime import datetime
from keystoneclient.auth.identity import v3
from keystoneclient import session
from netaddr import IPNetwork
from sysinv.common import constants as sysinv_constants
from tsconfig.tsconfig import MGMT_NETWORK_RECONFIGURATION_ONGOING


# Configuration parser setup
# By default, configparse transforms all loaded parameters to lowercase.
# This is a problem for Kubernetes kubelet configurations because they are
# written with Camel Case notation. With the optionxform attribute it is
# possible to disable the transformation to lowercase.
CONF = configparser.ConfigParser(interpolation=None)
CONF.optionxform = str


RECONFIGURE_NETWORK = False
RECONFIGURE_SERVICE = False


def print_with_timestamp(*args, **kwargs):
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{current_time}]", *args, **kwargs)


def wait_for_file(file_path, timeout=300, interval=5):
    start_time = time.time()
    while not os.path.exists(file_path):
        elapsed_time = time.time() - start_time
        if elapsed_time > timeout:
            raise ValueError(f"Timeout reached: {file_path} does not exist.")
        print_with_timestamp(f"Waiting for {file_path}...")
        time.sleep(interval)
    print_with_timestamp(f"File found: {file_path}")


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
                os_endpoint_type='internal')
        return self._sysinv


class OpenStackClient:
    """Client to interact with OpenStack Barbican."""

    def __init__(self) -> None:
        self.conf = {}
        self._session = None
        self._barbican = None

        # Loading credentials and configurations from environment variables
        # typically set in OpenStack
        source_command = 'source /etc/platform/openrc && env'

        with open(os.devnull, "w") as fnull:
            proc = subprocess.Popen(
                ['bash', '-c', source_command],
                stdout=subprocess.PIPE,
                stderr=fnull,
                universal_newlines=True,
            )

        # Strip the configurations starts with 'OS_' and change the value to lower
        for line in proc.stdout:
            key, _, value = line.partition("=")
            if key.startswith("OS_"):
                self.conf[key[3:].lower()] = value.strip()

        proc.communicate()

    def _get_new_keystone_session(self, conf):
        """Create a new keystone session."""
        try:
            auth = v3.Password(
                auth_url=conf["auth_url"],
                username=conf["username"],
                password=conf["password"],
                user_domain_name=conf["user_domain_name"],
                project_name=conf["project_name"],
                project_domain_name=conf["project_domain_name"],
            )
        except KeyError as e:
            print_with_timestamp(f"Configuration key missing: {e}")
            sys.exit(1)
        return session.Session(auth=auth)

    @property
    def barbican(self):
        """Return the barbican client."""
        if not self._barbican:
            if not self._session:
                self._session = self._get_new_keystone_session(self.conf)
            self._barbican = barbican_client.Client(
                session=self._session,
                interface='internal',
                )
        return self._barbican

    def list_secrets(self, secret_name):
        """List all secrets with the specified name."""
        secrets = []
        try:
            for secret in self.barbican.secrets.list(name=secret_name):
                secrets.append(secret)
        except Exception as e:
            print_with_timestamp(f"Failed to list secrets: {e}")
            sys.exit(1)
        return secrets

    def delete_secret(self, secret_id):
        """Delete a secret by ID."""
        try:
            self.barbican.secrets.delete(secret_id)
            print_with_timestamp(f"Secret {secret_id} deleted successfully.")
        except Exception as e:
            print_with_timestamp(f"Failed to delete secret {secret_id}: {e}")
            sys.exit(1)

    def create_secret(self, name, payload):
        """Create a new secret."""
        try:
            secret = self.barbican.secrets.create(
                name=name,
                payload=payload,
                payload_content_type='text/plain'
            )
            secret.store()
            print_with_timestamp(f"Secret {name} created successfully.")
            return secret
        except Exception as e:
            print_with_timestamp(f"Failed to create secret {name}: {e}")
            sys.exit(1)


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

        print_with_timestamp("Populating/Updating docker proxy config...")
        client.sysinv.service_parameter.create(**values)
        print_with_timestamp("Docker proxy config completed.")


def update_barbican_secrets(client, registry_name, username, password):
    """Update barbican secrets for a registry"""
    secret_name = f"{registry_name}-registry-secret"
    secrets = client.list_secrets(secret_name)
    for secret in secrets:
        client.delete_secret(secret.secret_ref)
    # Create a new secret
    secret_payload = f"username:{username} password:{password}"
    new_secret = client.create_secret(secret_name, secret_payload)
    print_with_timestamp(f"New secret created: {new_secret.secret_ref} for registry: {registry_name}")
    return new_secret.secret_ref


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
        openstack_client = OpenStackClient()
        for registry, value in registries_map.items():
            #  Update barbican secrets
            registry_secret = update_barbican_secrets(
                openstack_client,
                value.lower(),
                CONF.get(section_name, value + '_REGISTRY_USERNAME'),
                CONF.get(section_name, value + '_REGISTRY_PASSWORD')
            )
            # Update registry related service parameters
            registries[registry] = {
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_URL: CONF.get(
                    section_name, value + '_REGISTRY'),
                sysinv_constants.SERVICE_PARAM_NAME_DOCKER_AUTH_SECRET: registry_secret,
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

        print_with_timestamp("Populating/Updating docker registry config...")
        for registry in parameters:
            values = {
                'service': sysinv_constants.SERVICE_TYPE_DOCKER,
                'section': registry,
                'personality': None,
                'resource': None,
                'parameters': parameters[registry]
            }
            client.sysinv.service_parameter.create(**values)
        print_with_timestamp("Docker registry config completed.")


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

        print_with_timestamp("Populating/Updating user dns host-records...")
        client.sysinv.service_parameter.create(**values)

        print_with_timestamp("Populating/Updating user dns host-records completed.")


def populate_registry_dns_host_records(client, section_name):
    virtual_system = False
    registry_local = ''

    parameters = client.sysinv.service_parameter.list()

    for parameter in parameters:
        if parameter.name == sysinv_constants.SERVICE_PARAM_NAME_PLAT_CONFIG_VIRTUAL:
            virtual_system = True

    if virtual_system:
        registry_central_address = CONF.get(
            section_name, "SYSTEM_CONTROLLER_FLOATING_ADDRESS"
        )
        registry_local = CONF.get(
            section_name, "MANAGEMENT_FLOATING_ADDRESS"
        )
    else:
        registry_central_address = CONF.get(
            section_name, "SYSTEM_CONTROLLER_OAM_FLOATING_ADDRESS"
        )

    parameters = client.sysinv.service_parameter.list()
    for parameter in parameters:
        if parameter.name == 'registry.central':
            client.sysinv.service_parameter.delete(parameter.uuid)
        elif virtual_system and parameter.name == 'registry.local':
            client.sysinv.service_parameter.delete(parameter.uuid)

    values = {
        'service': sysinv_constants.SERVICE_TYPE_DNS,
        'section': sysinv_constants.SERVICE_PARAM_SECTION_DNS_HOST_RECORD,
        'personality': None,
        'resource': None,
        'parameters': {
            'registry.central': (
                f"registry.central,{registry_central_address}"
            )
        }
    }

    if registry_central_address and virtual_system:
        values['parameters']['registry.local'] = (
            f"registry.local,{registry_local}"
        )

    print_with_timestamp("Populating/Updating DNS host record for registry...")
    client.sysinv.service_parameter.create(**values)
    print_with_timestamp("DNS host record for registry completed.")


def populate_docker_config(client, section_name):
    """
    Update Docker and Kubernetes configuration parameters.
    Handles proxy settings and Docker registry configurations.
    """
    try:
        update_docker_proxy_config(client, section_name)
        update_docker_registry_config(client, section_name)
    except Exception as e:
        print_with_timestamp(f"Failed to update Docker/Kube config: {e}")
        raise


def populate_service_parameter_config(client, section_name):
    populate_docker_config(client, section_name)
    if CONF.has_section("USER_DNS_HOST_RECORDS"):
        populate_user_dns_host_records(client)
    else:
        print_with_timestamp("Skipping Populating/Updating user dns host-records...")
    populate_registry_dns_host_records(client, section_name)


def edit_dc_role_to_subcloud(client):
    """Changes Distributed Cloud Role to 'subcloud'
    """
    isystem_list = client.sysinv.isystem.list()
    isystem = isystem_list[0]
    current_dc_role = isystem.distributed_cloud_role
    capabilities = {'region_config': True,
                    'vswitch_type': 'none',
                    'shared_services': '[]',
                    'sdn_enabled': False,
                    'https_enabled': True}
    patch = [
        {
            'op': 'replace',
            'path': '/distributed_cloud_role',
            'value': sysinv_constants.DISTRIBUTED_CLOUD_ROLE_SUBCLOUD
        },
        {
            'op': 'replace',
            'path': '/capabilities',
            'value': capabilities
        }
    ]
    isystem = client.sysinv.isystem.update(isystem.uuid, patch)
    updated_dc_role = isystem.distributed_cloud_role
    print_with_timestamp(f"Distributed Cloud Role updated: "
                         f"'{current_dc_role}' -> '{updated_dc_role}'")


def get_secondary_pool_uuid(
        client, network_uuid, primary_pool_uuid, section_name):
    # Subcloud enrollment should be supported on N-1 load,
    # As dual-stack supported only on/after 24.09 software version,
    # newer api (network_addrpool) should not be called upon N-1 load.
    software_version = CONF.get(section_name, "SW_VERSION")
    if float(software_version) < 24.09:
        return None

    network_addrpools = client.sysinv.network_addrpool.list()
    for network_addrpool in network_addrpools:
        if (network_addrpool.network_uuid == network_uuid and
                network_addrpool.address_pool_uuid != primary_pool_uuid):
            return network_addrpool.address_pool_uuid
    return None


def delete_network_and_addrpool(client, network_name, section_name):
    network_uuid, primary_pool_uuid, secondary_pool_uuid = get_network_addrpools_uuid_of_network(
        client, network_name, section_name)
    # Delete secondary addrpool
    if secondary_pool_uuid:
        print_with_timestamp(f"Deleting secondary addrpool {secondary_pool_uuid}...")
        client.sysinv.address_pool.delete(secondary_pool_uuid)
    # Delete primary addrpool
    if primary_pool_uuid:
        print_with_timestamp(f"Deleting primary addrpool {primary_pool_uuid}...")
        client.sysinv.address_pool.delete(primary_pool_uuid)


def get_network_addrpools_uuid_of_network(
        client, network_name, section_name):
    networks = client.sysinv.network.list()
    network_uuid = None
    primary_pool_uuid = None
    secondary_pool_uuid = None
    for network in networks:
        if network.name == network_name:
            network_uuid = network.uuid
            primary_pool_uuid = network.pool_uuid
            break

    if network_uuid and primary_pool_uuid:
        # get secondary addrpool if supported and exists
        secondary_pool_uuid = get_secondary_pool_uuid(
            client, network_uuid, primary_pool_uuid, section_name)
    return network_uuid, primary_pool_uuid, secondary_pool_uuid


def create_system_controller_addr_network(client, section_name, network_type):

    if network_type == "sc_subnet":
        sc_values = {
            'name': 'system-controller-subnet',
            'network': CONF.get(section_name, "SYSTEM_CONTROLLER_SUBNET").split("/")[0],
            'prefix': CONF.get(section_name, "SYSTEM_CONTROLLER_SUBNET").split("/")[1],
            'floating_address': CONF.get(section_name, "SYSTEM_CONTROLLER_FLOATING_ADDRESS")
        }

        print_with_timestamp(f"Creating addrpool with name {sc_values['name']}...")
        sc_pool = client.sysinv.address_pool.create(**sc_values)

        sc_network_data = {
            'type': 'system-controller',
            'name': 'system-controller',
            'dynamic': False,
            'pool_uuid': sc_pool.uuid,
        }

        print_with_timestamp(f"Creating network with name {sc_network_data['name']}...")
        client.sysinv.network.create(**sc_network_data)

    elif network_type == "sc_oam":
        sc_oam_values = {
            'name': 'system-controller-oam-subnet',
            'network': CONF.get(section_name, "SYSTEM_CONTROLLER_OAM_SUBNET").split("/")[0],
            'prefix': CONF.get(section_name, "SYSTEM_CONTROLLER_OAM_SUBNET").split("/")[1],
            'floating_address': CONF.get(section_name, "SYSTEM_CONTROLLER_OAM_FLOATING_ADDRESS")
        }

        print_with_timestamp(f"Creating addrpool with name {sc_oam_values['name']}...")
        sc_oam_pool = client.sysinv.address_pool.create(**sc_oam_values)

        sc_oam_network_data = {
            'type': 'system-controller-oam',
            'name': 'system-controller-oam',
            'dynamic': False,
            'pool_uuid': sc_oam_pool.uuid,
        }

        print_with_timestamp(f"Creating network with name {sc_oam_network_data['name']}...")
        client.sysinv.network.create(**sc_oam_network_data)


def update_system_controller_subnets(client, section_name):

    pools = client.sysinv.address_pool.list()

    for addr in pools:

        addr_uuid = addr.uuid
        if addr.name == "system-controller-subnet":
            print_with_timestamp(f"Deleting address pool {addr_uuid}...")
            client.sysinv.address_pool.delete(addr_uuid)

    create_system_controller_addr_network(client, section_name, "sc_subnet")

    for addrpool in pools:

        pool_uuid = addrpool.uuid
        if addrpool.name == "system-controller-oam-subnet":
            print_with_timestamp(f"Deleting address pool {pool_uuid}...")
            client.sysinv.address_pool.delete(pool_uuid)

    create_system_controller_addr_network(client, section_name, "sc_oam")


def get_version_text(ip_network):
    return "ipv4" if ip_network.version == 4 else "ipv6"


def get_network(client, network_name):
    networks = client.sysinv.network.list()
    for network in networks:
        if network.name == network_name:
            return network
    raise ValueError(f'No {network_name} network found.')


def has_admin_network(section_name):
    admin_subnet = CONF.get(section_name, 'ADMIN_SUBNET')
    return admin_subnet != 'undef'


def has_admin_network_secondary(section_name):
    admin_subnet_secondary = CONF.get(section_name, 'ADMIN_SUBNET_SECONDARY')
    return admin_subnet_secondary != 'undef'


def has_oam_network_secondary(section_name):
    oam_subnet_secondary = CONF.get(section_name, 'EXTERNAL_OAM_SUBNET_SECONDARY')
    return oam_subnet_secondary != 'undef'


def update_admin_network(client, section_name):

    if not has_admin_network(section_name):
        return

    delete_network_and_addrpool(client, 'admin', section_name)

    admin_subnet = IPNetwork(CONF.get(section_name, "ADMIN_SUBNET"))
    admin_floating_address = CONF.get(section_name, "ADMIN_FLOATING_ADDRESS")
    admin_start_address = CONF.get(section_name, "ADMIN_START_ADDRESS")
    admin_end_address = CONF.get(section_name, "ADMIN_END_ADDRESS")
    subcloud_gateway = CONF.get(section_name, "ADMIN_GATEWAY_ADDRESS")

    values = {
        'name': f'admin-{get_version_text(admin_subnet)}',
        'network': str(admin_subnet.network),
        'prefix': admin_subnet.prefixlen,
        'ranges': [(admin_start_address, admin_end_address)],
        }

    if (subcloud_gateway != 'undef'):
        values.update({
            'gateway_address': subcloud_gateway,
        })

    if (admin_floating_address != 'undef'):
        values.update({
            'floating_address': admin_floating_address,
        })

    print_with_timestamp(f"Creating addrpool with name {values['name']}...")
    pool = client.sysinv.address_pool.create(**values)

    network_data = {
        'type': sysinv_constants.NETWORK_TYPE_ADMIN,
        'name': sysinv_constants.NETWORK_TYPE_ADMIN,
        'dynamic': False,
        'pool_uuid': pool.uuid,
    }

    print_with_timestamp(f"Creating network with name {network_data['name']}...")
    client.sysinv.network.create(**network_data)

    if has_admin_network_secondary(section_name):
        update_admin_network_secondary(client, section_name)

    assign_if_network(client,
                      CONF.get(section_name, "CONTROLLER_0_ADMIN_NETWORK_IF"),
                      "admin")


def update_admin_network_secondary(client, section_name):

    admin_subnet = IPNetwork(CONF.get(section_name, "ADMIN_SUBNET_SECONDARY"))
    admin_start_address = CONF.get(section_name, "ADMIN_START_ADDRESS_SECONDARY")
    admin_end_address = CONF.get(section_name, "ADMIN_END_ADDRESS_SECONDARY")
    subcloud_gateway = CONF.get(section_name, "ADMIN_GATEWAY_ADDRESS_SECONDARY")
    network_name = sysinv_constants.NETWORK_TYPE_ADMIN

    values = {
        'name': f'admin-{get_version_text(admin_subnet)}',
        'network': str(admin_subnet.network),
        'prefix': admin_subnet.prefixlen,
        'ranges': [(admin_start_address, admin_end_address)],
        }

    if (subcloud_gateway != 'undef'):
        values.update({
            'gateway_address': subcloud_gateway,
        })

    print_with_timestamp(f"Creating addrpool with name {values['name']}...")
    pool = client.sysinv.address_pool.create(**values)

    # add the pool to the network
    network_addrpool_data = {
        'network_uuid': get_network(client, network_name).uuid,
        'address_pool_uuid': pool.uuid,
    }

    print_with_timestamp(f"Creating network_addrpool with {network_addrpool_data}...")
    client.sysinv.network_addrpool.assign(**network_addrpool_data)


def precheck_update_management_network(client, section_name):
    # skip update management network if not simplex
    system_mode = CONF.get(section_name, 'SYSTEM_MODE')
    if system_mode != sysinv_constants.SYSTEM_MODE_SIMPLEX:
        print_with_timestamp(
            f"Ignore management network update in {system_mode}",
        )
        return False

    # skip update management network if admin network configured
    try:
        admin_network = get_network(client, sysinv_constants.NETWORK_TYPE_ADMIN)
        if admin_network:
            print_with_timestamp(
                f"Admin network: {admin_network.uuid} discovered, ignore management "
                "network update.",
            )
        return False
    except ValueError:
        # admin network is expected to be not configured if need to update
        # management network
        pass

    return True


# TODO(yuxing): improve the following method if dual stack reconfiguration on the
# management network is verified
def update_management_network(client, section_name):

    if not precheck_update_management_network(client, section_name):
        return

    management_subnet = IPNetwork(CONF.get(section_name, "MANAGEMENT_SUBNET"))
    ip_family = get_version_text(management_subnet)

    existing_network = get_network(client, sysinv_constants.NETWORK_TYPE_MGMT)
    primary_ip_family = existing_network.primary_pool_family
    if primary_ip_family.lower() != ip_family:
        print_with_timestamp(
            f"Primary IP family of management network: {primary_ip_family}, "
            f"can not be updated to {ip_family}."
        )
        sys.exit(1)

    subcloud_gateway = CONF.get(section_name, "MANAGEMENT_GATEWAY_ADDRESS")
    if subcloud_gateway == 'undef':
        print_with_timestamp(
            "Management gateway address required to update management network, "
            "please add it to the bootstrap values and try again."
        )
        sys.exit(1)

    pool_id = existing_network.pool_uuid

    values = {
        'network': str(management_subnet.network),
        'prefix': str(management_subnet.prefixlen),
        'ranges': [(
            CONF.get(section_name, "MANAGEMENT_START_ADDRESS"),
            CONF.get(section_name, "MANAGEMENT_END_ADDRESS"),
            )],
        'gateway_address': subcloud_gateway,
        'floating_address': CONF.get(section_name, "MANAGEMENT_FLOATING_ADDRESS"),
        'controller0_address': CONF.get(section_name, "MANAGEMENT_CONTROLLER0_ADDRESS"),
        'controller1_address': CONF.get(section_name, "MANAGEMENT_CONTROLLER1_ADDRESS"),
        }
    if is_equal_with_existing_pool(client, values, pool_id):
        print_with_timestamp(
            f"Management network addrpool {pool_id} is up-to-date.")
        return

    patch = []
    for (k, v) in values.items():
        patch.append({'op': 'replace', 'path': '/' + k, 'value': v})
    try:
        client.sysinv.address_pool.update(pool_id, patch)
        # Wait for flag to block the dnsmasq runtime manifest triggered by
        # system controller network update
        wait_for_file(MGMT_NETWORK_RECONFIGURATION_ONGOING)
        print_with_timestamp(
            f"Management network addrpool {pool_id} is updated.")
    except Exception as e:
        print_with_timestamp(f"Failed to update management network: {e}")
        sys.exit(1)

    return


def is_equal_with_existing_pool(client, pool_values, pool_uuid):
    address_pool = client.sysinv.address_pool.get(pool_uuid)
    return (
        pool_values['network'] == address_pool.network and
        pool_values['prefix'] == address_pool.prefix and
        pool_values['ranges'][0][0] == address_pool.ranges[0][0] and
        pool_values['ranges'][0][1] == address_pool.ranges[0][1] and
        (pool_values['floating_address'] == address_pool.floating_address
            if 'floating_address' in pool_values
            else address_pool.floating_address is None) and
        (pool_values['gateway_address'] == address_pool.gateway_address
            if 'gateway_address' in pool_values
            else address_pool.gateway_address is None) and
        (pool_values['controller0_address'] == address_pool.controller0_address
            if 'controller0_address' in pool_values
            else address_pool.controller0_address is None) and
        (pool_values['controller1_address'] == address_pool.controller1_address
            if 'controller1_address' in pool_values
            else address_pool.controller1_address is None)
    )


def update_oam_network_secondary(client, section_name):
    network_name = sysinv_constants.NETWORK_TYPE_OAM
    network_uuid, primary_pool_uuid, secondary_pool_uuid = (
        get_network_addrpools_uuid_of_network(client, network_name, section_name))
    if not has_oam_network_secondary(section_name):
        if secondary_pool_uuid:
            print_with_timestamp(
                f"Deleting oam secondary addrpool {secondary_pool_uuid}...")
            client.sysinv.address_pool.delete(secondary_pool_uuid)
        return

    oam_subnet = IPNetwork(CONF.get(section_name, "EXTERNAL_OAM_SUBNET_SECONDARY"))
    oam_start_address = CONF.get(section_name, "EXTERNAL_OAM_START_ADDRESS_SECONDARY")
    oam_end_address = CONF.get(section_name, "EXTERNAL_OAM_END_ADDRESS_SECONDARY")
    oam_gateway = CONF.get(section_name, "EXTERNAL_OAM_GATEWAY_ADDRESS_SECONDARY")
    floating_address = CONF.get(section_name, "EXTERNAL_OAM_FLOATING_ADDRESS_SECONDARY")

    # create the address pool
    values = {
        'name': f'oam-{get_version_text(oam_subnet)}',
        'network': str(oam_subnet.network),
        'prefix': oam_subnet.prefixlen,
        'ranges': [(oam_start_address, oam_end_address)],
        'floating_address': floating_address,
        'gateway_address': oam_gateway,
        }

    system_mode = CONF.get(section_name, 'SYSTEM_MODE')
    if system_mode != sysinv_constants.SYSTEM_MODE_SIMPLEX:
        values.update({
            'controller0_address': CONF.get(
                section_name, 'EXTERNAL_OAM_0_ADDRESS_SECONDARY'),
            'controller1_address': CONF.get(
                section_name, 'EXTERNAL_OAM_1_ADDRESS_SECONDARY'),
        })

    # In case secondary pool already exists, compare existing pool with given/expected
    # configuration
    # same: then nothing to do
    # different: update by doing delete old and create new
    if secondary_pool_uuid:
        if is_equal_with_existing_pool(client, values, secondary_pool_uuid):
            print_with_timestamp(
                f"OAM secondary addrpool {secondary_pool_uuid} is uptodate.")
            return
        else:
            print_with_timestamp(f"Deleting oam secondary addrpool {secondary_pool_uuid}...")
            client.sysinv.address_pool.delete(secondary_pool_uuid)

    print_with_timestamp(f"Creating addrpool with name {values['name']}...")
    pool = client.sysinv.address_pool.create(**values)

    # add the pool to the network
    network_addrpool_data = {
        'network_uuid': network_uuid,
        'address_pool_uuid': pool.uuid,
    }

    print_with_timestamp(f"Creating network_addrpool with {network_addrpool_data}...")
    client.sysinv.network_addrpool.assign(**network_addrpool_data)


def assign_if_network(client, host_interface_name, network_name):

    print_with_timestamp(f"Assigning network interface {host_interface_name} for {network_name}")

    if_uuid = ""
    net_uuid = ""

    networks = client.sysinv.network.list()
    host_interfaces = client.sysinv.iinterface.list('controller-0')
    for interface in host_interfaces:
        if interface.ifname == host_interface_name:
            if_uuid = interface.uuid

    for network in networks:
        if str(network.name).startswith(network_name):
            net_uuid = network.uuid

    values = {
        'interface_uuid': if_uuid,
        'network_uuid': net_uuid
    }

    client.sysinv.interface_network.assign(**values)


# Main function to execute based on command-line input
def main():
    if len(sys.argv) < 2:
        print_with_timestamp("Usage: update_system_config.py <config_file>")
        sys.exit(1)

    config_file = sys.argv[1]
    if not os.path.isfile(config_file):
        print_with_timestamp(f"Error: Config file '{config_file}' does not exist.")
        sys.exit(1)

    CONF.read(config_file)
    if 'OPERATION' not in CONF or 'MODE' not in CONF['OPERATION']:
        print_with_timestamp("The 'MODE' option is missing in the 'OPERATION' "
                             "section of the configuration file.")
        sys.exit(1)

    operation = CONF.get('OPERATION', 'MODE')
    section_name = operation.upper() + '_CONFIG'
    client = CgtsClient()
    # Primary OAM has been updated by cloud-init, secondary oam has been
    # procastinated until now.
    update_oam_network_secondary(client, section_name)
    update_management_network(client, section_name)
    populate_service_parameter_config(client, section_name)
    update_system_controller_subnets(client, section_name)
    update_admin_network(client, section_name)
    edit_dc_role_to_subcloud(client)


if __name__ == '__main__':
    main()
