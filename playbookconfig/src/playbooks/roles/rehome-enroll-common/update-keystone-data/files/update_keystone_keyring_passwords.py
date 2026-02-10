#!/usr/bin/env python3

# Copyright (c) 2024-2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Update service users' passwords in keystone and keyring
#

import argparse
import configparser
import json
import logging
import os
import subprocess
import sys
import time
from typing import List

import keyring
from keystoneauth1 import session
from keystoneauth1 import exceptions as ks_exceptions
from keystoneauth1.identity import v3
from keystoneclient.v3 import client as keystone_client
from oslo_config import cfg
from oslo_context import context as mycontext
from sysinv.common.utils import generate_random_password
from sysinv.conductor import rpcapiproxy as conductor_rpcapi

LOG = logging.getLogger(__name__)
CONF = cfg.CONF

SYSINV_USERNAME = "sysinv"
ADMIN_USERNAME = "admin"
BARBICAN_USERNAME = "barbican"
FM_USERNAME = "fm"
VIM_USERNAME = "vim"
USM_USERNAME = "usm"
MTCE_USERNAME = "mtce"

SERVICES_TO_RESTART_SM = {
    SYSINV_USERNAME: ["sysinv-inv", "sysinv-conductor", "cert-alarm", "cert-mon"],
    BARBICAN_USERNAME: [
        "barbican-api",
        "barbican-worker",
        "barbican-keystone-listener",
    ],
    FM_USERNAME: ["fm-mgr"],
    VIM_USERNAME: ["vim", "vim-api"],
}
SERVICES_TO_RESTART_SYSTEMD = {
    USM_USERNAME: ["software-agent.service", "software-controller-daemon.service"],
    FM_USERNAME: ["fm-api.service"],
}

SERVICES_TO_RESTART_FUNCTION = {
    MTCE_USERNAME: lambda: restart_mtce_service(),
}

KEYSTONE_CONFIG_PATH = "/etc/keystone/keystone.conf"
SYSINV_CONFIG_PATH = "/etc/sysinv/sysinv.conf"
SYSINV_API_PASTE_CONFIG_PATH = "/etc/sysinv/api-paste.ini"
CERTMON_CONFIG_PATH = "/etc/sysinv/cert-mon.conf"
CERTALARM_CONFIG_PATH = "/etc/sysinv/cert-alarm.conf"
FM_CONFIG_PATH = "/etc/fm/fm.conf"
BARBICAN_CONFIG_PATH = "/etc/barbican/barbican.conf"
USM_CONFIG_PATH = "/etc/software/software.conf"
MTCE_CONFIG_PATH = "/etc/mtc.ini"


class OpenStackClient:
    """Client to interact with OpenStack Keystone with caching."""

    def __init__(self, verify_certs):
        self.conf = {}
        self._session = None
        self._keystone = None
        self.verify_certs = verify_certs
        self._cache = {
            "users": None,
            "projects": None,
            "roles": None,
            "endpoints": None,
            "services": None,
        }

        self._load_openrc_config()

    def _load_openrc_config(self):
        """Load credentials and configurations from /etc/platform/openrc."""
        LOG.info("Loading configuration from /etc/platform/openrc")
        source_command = "source /etc/platform/openrc && env"
        try:
            with open(os.devnull, "w") as fnull:
                proc = subprocess.Popen(
                    ["bash", "-c", source_command],
                    stdout=subprocess.PIPE,
                    stderr=fnull,
                    universal_newlines=True,
                )
            for line in proc.stdout:
                key, _, value = line.partition("=")
                if key.startswith("OS_"):
                    self.conf[key[3:].lower()] = value.strip()
            proc.communicate()
            LOG.info("Configuration loaded successfully.")
        except Exception as e:
            LOG.error(f"Failed to load openrc config: {e}")
            raise

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
            return session.Session(auth=auth, verify=self.verify_certs)
        except KeyError as e:
            LOG.error(f"Configuration key missing from openrc: {e}")
            raise

    def check_if_keystone_is_active(self):
        """Check if the Keystone service is active by issuing a service list call."""
        for i in range(1, 31):
            try:
                # We don't care about the response here, just that we can connect
                # successfully to keystone
                self.keystone.services.list()
                LOG.info("Keystone service is active")
                return True
            except ks_exceptions.http.Unauthorized:
                # If it was unauthorized, we get a new session/token and try again
                # in the next loop
                LOG.warning("Keystone unauthorized, refreshing session and retrying.")
                self._keystone = None
                self._session = None
                self._load_openrc_config()
                time.sleep(2)
            except Exception as e:
                LOG.error(f"Attempt {i}, Keystone is not up yet, retrying. Error: {e}")
                time.sleep(2)
        return False

    @property
    def keystone(self):
        """Return the keystone client, creating it if it doesn't exist."""
        if not self._keystone:
            if not self._session:
                self._session = self._get_new_keystone_session(self.conf)
            self._keystone = keystone_client.Client(
                session=self._session,
                region_name=self.conf["region_name"],
                interface="internal",
            )
        return self._keystone

    @property
    def users(self):
        if self._cache["users"] is None:
            LOG.info("Caching all Keystone users...")
            self._cache["users"] = {
                user.name: user for user in self.keystone.users.list()
            }
        return self._cache["users"]

    @property
    def projects(self):
        if self._cache["projects"] is None:
            LOG.info("Caching all Keystone projects...")
            self._cache["projects"] = {
                project.name: project for project in self.keystone.projects.list()
            }
        return self._cache["projects"]

    @property
    def roles(self):
        if self._cache["roles"] is None:
            LOG.info("Caching all Keystone roles...")
            self._cache["roles"] = {
                role.name: role for role in self.keystone.roles.list()
            }
        return self._cache["roles"]

    def update_user_password(self, username, new_password):
        """Update the password for a user, handling creation if needed."""
        user = self.users.get(username)

        if not new_password:
            LOG.warning(f"Empty password for {username}, generating a new one.")
            new_password = generate_random_password()

        if user:
            try:
                LOG.info(f"Updating {username} password")
                self.keystone.users.update(user, password=new_password)
            except Exception as error:
                LOG.error(f"Failed to update password for {username}: {error}")
                raise
        else:
            LOG.info(f"User not found: {username}, attempting to create.")
            try:
                new_user = self.create_keystone_user(username, new_password)
                self.grant_keystone_roles(new_user)
            except Exception as error:
                LOG.error(f"Failed to create user {username}: {error}")
                raise
        try:
            service_name = "CGCS" if username == ADMIN_USERNAME else "services"
            store_password_in_keyring(username, new_password, service_name=service_name)
        except Exception as error:
            LOG.error(f"Failed to store password in keyring for {username}: {error}")
            raise

    def create_keystone_user(self, username, password):
        """Creates a new user entity in Keystone."""
        LOG.info(f"Creating Keystone user: {username}")
        user = self.keystone.users.create(
            name=username,
            password=password,
            default_project=self.projects.get("services"),
        )
        LOG.info(f"Keystone user '{username}' created successfully with ID {user.id}.")
        return user

    def grant_keystone_roles(self, user):
        """Grants the default admin roles to a given user."""
        username = user.name
        LOG.info(f"Granting default roles to user: {username}")

        service_project = self.projects.get("services")
        admin_role = self.roles.get("admin")

        # Grant admin role in the 'services' project for all users
        self.keystone.roles.grant(role=admin_role, user=user, project=service_project)
        LOG.info(f"Admin role granted to '{username}' in 'services' project.")

        # Grant admin role in the 'admin' project for the 'dcmanager' user
        if username == "dcmanager":
            admin_project = self.projects.get("admin")
            self.keystone.roles.grant(role=admin_role, user=user, project=admin_project)
            LOG.info(f"Admin role granted to '{username}' in 'admin' project.")

    def disable_users_lockout(self, user_data):
        """Disable lockout for a list of users."""
        users_with_lockout_disabled = []
        for user_info in user_data:
            username = user_info.get("username")
            user = self.users.get(username)
            if user and not user.options.get("ignore_lockout_failure_attempts"):
                self.keystone.users.update(
                    user.id, options={"ignore_lockout_failure_attempts": True}
                )
                users_with_lockout_disabled.append(username)
        return users_with_lockout_disabled

    def enable_users_lockout(self, usernames):
        """Re-enable lockout for a list of usernames."""
        for username in usernames:
            user = self.users.get(username)
            if user:
                LOG.info(f"Re-enabling lockout for user {username}.")
                self.keystone.users.update(
                    user.id, options={"ignore_lockout_failure_attempts": False}
                )


def store_password_in_keyring(username, password, service_name="services"):
    """Store the password in the keyring."""
    keyring.set_password(username, service_name, password)
    LOG.info(f"Keyring password stored securely for {username}.")


def get_conductor_rpc_bind_ip():
    ini_str = "[DEFAULT]\n" + open(SYSINV_CONFIG_PATH, "r").read()
    config_applied = configparser.RawConfigParser()
    config_applied.read_string(ini_str)

    conductor_bind_ip = None
    if config_applied.has_option("DEFAULT", "rpc_zeromq_conductor_bind_ip"):
        conductor_bind_ip = config_applied.get(
            "DEFAULT", "rpc_zeromq_conductor_bind_ip"
        )
    return conductor_bind_ip


def run_local_registry_secrets_audit_rpc():
    CONF.rpc_zeromq_conductor_bind_ip = get_conductor_rpc_bind_ip()
    context = mycontext.get_admin_context()
    rpcapi = conductor_rpcapi.ConductorAPI(topic=conductor_rpcapi.MANAGER_TOPIC)
    rpcapi.run_local_registry_secrets_audit(context)


def restart_services_sm(service_list: List[str]):
    """
    Restarts a given list of services using the 'sm-restart-safe' command.

    Args:
        service_list: A list of strings, where each string is a service name.
    """
    LOG.info(f"Preparing to restart services: {', '.join(service_list)}")
    for service in service_list:
        LOG.info(f"Issuing restart command for service: {service}")
        try:
            subprocess.run(
                ["sm-restart-safe", "service", service],
                capture_output=True,
                text=True,
            )
            LOG.info(f"Successfully commanded '{service}' to restart.")
        except subprocess.CalledProcessError as e:
            LOG.error(
                f"Failed to restart service '{service}'. Stderr: {e.stderr.strip()}"
            )
            raise


def restart_services_systemd(service_list: List[str]):
    """
    Restarts a given list of services using systemctl.

    Args:
        service_list: A list of strings, where each string is a systemd service name.
    """
    LOG.info(f"Preparing to restart systemd services: {', '.join(service_list)}")
    for service in service_list:
        LOG.info(f"Issuing restart command for systemd service: {service}")
        try:
            subprocess.run(
                ["systemctl", "restart", service],
                capture_output=True,
                text=True,
            )
            LOG.info(f"Successfully restarted systemd service '{service}'.")
        except subprocess.CalledProcessError as e:
            LOG.error(
                f"Failed to restart systemd service '{service}'. Stderr: {e.stderr.strip()}"
            )
            raise


def restart_mtce_service():
    """Restart the mtce service using its specific command."""
    LOG.info("Issuing restart command for mtce service")
    try:
        subprocess.run(
            ["pkill", "-HUP", "mtcAgent"],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["pkill", "-HUP", "hbsAgent"],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["pmon-restart", "hbsClient"],
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["pmon-restart", "mtcClient"],
            capture_output=True,
            text=True,
        )
        LOG.info("Successfully commanded mtce to restart.")
    except subprocess.CalledProcessError as e:
        LOG.error(f"Failed to restart mtce service. Stderr: {e.stderr.strip()}")
        raise


def verify_sm_services(
    service_list: List[str], max_retries: int = 30, delay_seconds: int = 4
):
    """
    Verifies a list of services are 'enabled-active' with a retry mechanism.

    Args:
        service_list: A list of strings, where each string is a service name.
        max_retries: The maximum number of times to check a service's status.
        delay_seconds: The number of seconds to wait between retries.
    """
    LOG.info(f"Preparing to verify services: {', '.join(service_list)}")
    for service in service_list:
        LOG.info(f"Verifying status of service: '{service}'...")
        for attempt in range(1, max_retries + 1):
            try:
                result = subprocess.run(
                    ["sm-query", "service", service],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                if "enabled-active" in result.stdout:
                    LOG.info(f"Service '{service}' is confirmed enabled-active.")
                    break
            except subprocess.CalledProcessError as e:
                LOG.warning(
                    f"Verification command failed for '{service}' on attempt {attempt}/{max_retries}. Error: {e.stderr.strip()}"
                )

            if attempt < max_retries:
                LOG.info(
                    f"Attempt {attempt}/{max_retries}: '{service}' not active yet. Retrying in {delay_seconds}s..."
                )
                time.sleep(delay_seconds)
        else:
            error_msg = f"Service '{service}' did not become active after {max_retries} attempts."
            LOG.error(error_msg)
            raise TimeoutError(error_msg)


def update_config_file(config_filepath: str, values_to_update: list):
    """Update a config file with the desired information using configparser.

    :param config_filepath: Path of the config file.
    :param values_to_update: List of dicts with the following format:
        values_to_update = [
            {'section': '<section-name1>', 'key': '<key1>', 'value': 'value1'},
            {'section': '<section-name2>', 'key': '<key2>', 'value': 'value2'},
        ]
    """
    config = configparser.ConfigParser()

    # Preserve the case of keys/options
    config.optionxform = str

    # Read the existing configuration file.
    # configparser will handle an empty or non-existent file gracefully.
    config.read(config_filepath)

    # Iterate through the list of changes to apply
    for item in values_to_update:
        section = item["section"]
        key = item["key"]
        value = str(item["value"])  # configparser requires values to be strings

        # If the section doesn't exist, create it
        if not config.has_section(section):
            config.add_section(section)

        # Set the key-value pair in the specified section
        config.set(section, key, value)

    # Write the changes back to the file
    with open(config_filepath, "w") as configfile:
        config.write(configfile)


def update_sysinv_config(new_password):
    """Update the sysinv config files with the new password."""
    default_values_to_update = [
        {"section": "keystone_authtoken", "key": "password", "value": new_password}
    ]
    api_paste_values_to_update = [
        {"section": "filter:authtoken", "key": "password", "value": new_password}
    ]
    LOG.info("Updating sysinv configuration files with new password.")
    try:
        update_config_file(SYSINV_CONFIG_PATH, default_values_to_update)
        update_config_file(SYSINV_API_PASTE_CONFIG_PATH, api_paste_values_to_update)
        update_config_file(CERTMON_CONFIG_PATH, default_values_to_update)
        update_config_file(CERTALARM_CONFIG_PATH, default_values_to_update)
    except Exception as e:
        LOG.error(f"Failed to update sysinv config files: {e}")
        raise


def update_fm_config(new_password):
    """Update the fm.conf file with the new password."""
    default_values_to_update = [
        {"section": "keystone_authtoken", "key": "password", "value": new_password}
    ]
    LOG.info("Updating fm configuration file with new password.")
    try:
        update_config_file(FM_CONFIG_PATH, default_values_to_update)
    except Exception as e:
        LOG.error(f"Failed to update fm config file: {e}")
        raise


def update_barbican_config(new_password):
    """Update the barbican.conf file with the new password."""
    default_values_to_update = [
        {"section": "keystone_authtoken", "key": "password", "value": new_password}
    ]
    LOG.info("Updating barbican configuration file with new password.")
    try:
        update_config_file(BARBICAN_CONFIG_PATH, default_values_to_update)
    except Exception as e:
        LOG.error(f"Failed to update barbican config file: {e}")
        raise


def update_usm_config(new_password):
    """Update the software.conf file with the new password."""
    default_values_to_update = [
        {"section": "keystone_authtoken", "key": "password", "value": new_password}
    ]
    LOG.info("Updating usm configuration file with new password.")
    try:
        update_config_file(USM_CONFIG_PATH, default_values_to_update)
    except Exception as e:
        LOG.error(f"Failed to update usm config file: {e}")
        raise


def update_mtce_config(new_password):
    """Update the mtc.ini file with the new password."""
    default_values_to_update = [
        {"section": "agent", "key": "keystone_auth_pw", "value": new_password}
    ]
    LOG.info("Updating mtce configuration file with new password.")
    try:
        update_config_file(MTCE_CONFIG_PATH, default_values_to_update)
    except Exception as e:
        LOG.error(f"Failed to update mtce config file: {e}")
        raise


def update_password_on_config(username, new_password):
    """Update the appropriate configuration file based on the username."""
    # VIM doesn't have the password in the config files, it dynamically
    # fetches it from keyring
    if username == SYSINV_USERNAME:
        update_sysinv_config(new_password)
    elif username == FM_USERNAME:
        update_fm_config(new_password)
    elif username == BARBICAN_USERNAME:
        update_barbican_config(new_password)
    elif username == USM_USERNAME:
        update_usm_config(new_password)
    elif username == MTCE_USERNAME:
        update_mtce_config(new_password)
    elif username == VIM_USERNAME:
        LOG.info("No configuration file update needed for 'vim'.")
    else:
        LOG.warning(f"No configuration update function defined for user: {username}")


def main():
    """Main function to parse arguments and execute password updates."""
    parser = argparse.ArgumentParser(
        description="Update service users' passwords in Keystone and keyring."
    )
    parser.add_argument(
        "json_file",
        help="Path to the JSON file containing user data ([{'username': 'u', 'password': 'p'}]).",
    )
    parser.add_argument(
        "--no-verify", action="store_true", help="Disable SSL certificate verification."
    )

    args = parser.parse_args()

    log_level = logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if not os.path.isfile(args.json_file):
        LOG.error(f"JSON file does not exist: '{args.json_file}'")
        sys.exit(1)

    try:
        with open(args.json_file, "r") as file:
            user_data = json.load(file)
    except (json.JSONDecodeError, IOError) as e:
        LOG.error(f"Error reading or parsing JSON file '{args.json_file}': {e}")
        sys.exit(1)

    verify_certs = not args.no_verify
    if not verify_certs:
        LOG.warning("SSL certificate verification is disabled.")

    try:
        osclient = OpenStackClient(verify_certs)
        users_with_lockout_disabled = osclient.disable_users_lockout(user_data)
        for user in user_data:
            username = user.get("username")
            password = user.get("password")

            LOG.info(f"### Processing user: {username} ###")
            osclient.update_user_password(username, password)

            update_password_on_config(username, password)

            if username == SYSINV_USERNAME:
                run_local_registry_secrets_audit_rpc()

            if username in SERVICES_TO_RESTART_SM:
                restart_services_sm(SERVICES_TO_RESTART_SM[username])
            if username in SERVICES_TO_RESTART_SYSTEMD:
                restart_services_systemd(SERVICES_TO_RESTART_SYSTEMD[username])
            if username in SERVICES_TO_RESTART_FUNCTION:
                SERVICES_TO_RESTART_FUNCTION[username]()

            LOG.info(f"### Finished processing user: {username} ###")

            if username == ADMIN_USERNAME:
                osclient.check_if_keystone_is_active()

        # We only need to wait for sysinv to be active as it will be necessary for
        # other steps of the playbook. Other services we can check at the end if
        # they're enabled/active
        verify_sm_services(SERVICES_TO_RESTART_SM[SYSINV_USERNAME])
        osclient.enable_users_lockout(users_with_lockout_disabled)

        LOG.info("Script completed successfully.")

    except Exception as e:
        LOG.exception(f"An unrecoverable error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
