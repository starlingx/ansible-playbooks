#!/usr/bin/env python3

# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Update service users' passwords in keystone and keyring
#

import os
import sys
import subprocess
import time
import json

from cgtsclient import client as cgts_client
from datetime import datetime
import keyring
from keystoneauth1 import exceptions as keystone_exceptions
from keystoneclient.v3 import client as keystone_client
from keystoneclient.auth.identity import v3
from keystoneclient import session
from sysinv.common.utils import generate_random_password


MAX_RETRIES_MANIFEST_APPLIED = 30
INTERVAL_WAIT_MANIFEST_APPLIED = 10


def print_with_timestamp(*args, **kwargs):
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{current_time}]", *args, **kwargs)


class OpenStackClient:
    """Client to interact with OpenStack Keystone."""

    def __init__(self, verify_certs) -> None:
        self.conf = {}
        self._session = None
        self._keystone = None
        self.verify_certs = verify_certs

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
        return session.Session(auth=auth, verify=self.verify_certs)

    @property
    def keystone(self):
        """Return the keystone client."""
        if not self._keystone:
            if not self._session:
                self._session = self._get_new_keystone_session(self.conf)
            self._keystone = keystone_client.Client(
                session=self._session,
                region_name=self.conf["region_name"],
            )
        return self._keystone

    def check_password(self, username, password):
        """Check the password, return True if the password is in use."""
        custom_conf = self.conf.copy()
        custom_conf.update({
            "username": username,
            "password": password,
            "project_name": "services",
        })
        try:
            sess = self._get_new_keystone_session(custom_conf)
            sess.get_auth_headers()
            return True
        except keystone_exceptions.http.Unauthorized:
            # Expected as new user password should not be authorized if not
            # updated in the Keystone.
            return False
        except Exception as e:
            print_with_timestamp("Check keystone password failed for "
                                 f"{username}: {e}")
            sys.exit(1)

    def update_user_password(self, username, new_password):
        """Update the password of a Keystone user."""
        updated = False
        ks_user = self.get_keystone_user_by_name(username)
        if not new_password:
            print_with_timestamp(f"Empty password for {username}, creating new one.")
            new_password = generate_random_password()
        if not ks_user:
            print_with_timestamp(f"User not found: {username}, attempting to create.")
            try:
                self.create_keystone_user(username, new_password)
                store_password_in_keyring(username, new_password)
                updated = True
                return updated
            except Exception as error:
                print_with_timestamp(f"Failed to update password for {username}: "
                                     f"{str(error)}")
                sys.exit(1)

        if not self.check_password(username, new_password):
            try:
                self.update_keystone_password(ks_user, new_password)
                store_password_in_keyring(username, new_password)
                updated = True
            except Exception as error:
                print_with_timestamp(f"Failed to update password for {username}: "
                                     f"{str(error)}")
                sys.exit(1)
        else:
            print_with_timestamp(f"No update needed: password for {username} is "
                                 "already up to date.")

        return updated

    def create_keystone_user(self, username, password):
        """Create a new keystone user."""
        user = self.keystone.users.create(
            name=username,
            password=password,
            default_project=self.conf["project_name"],
            )
        print_with_timestamp(f"Keystone user created: {username}")

        # Assigning roles to the new user
        service_project = self.keystone.projects.find(name="services")
        admin_project = self.keystone.projects.find(name="admin")
        admin_role = self.keystone.roles.find(name="admin")
        self.keystone.roles.grant(role=admin_role, user=user, project=service_project)
        print_with_timestamp(f"Admin role added for {username} in 'service' projects.")

        # Assign "dcmanager" to be admin role in admin project.
        if username == "dcmanager":
            self.keystone.roles.grant(role=admin_role, user=user, project=admin_project)
            print_with_timestamp(f"Admin role added for {username} in 'admin' projects.")

    def get_keystone_user_by_name(self, username):
        """Retrieve a keystone user by username."""
        users = self.keystone.users.list(name=username)
        if not users:
            print_with_timestamp(f"No user found with username: {username}")
            return None
        if len(users) > 1:
            print_with_timestamp(f"Multiple users found with username: {username}, "
                                 "please ensure usernames are unique.")
        return users[0]

    def update_keystone_password(self, user, password):
        """Update the password of a keystone user."""
        self.keystone.users.update(user, password=password)
        # Wait 10s for application of puppet runtime manifest
        time.sleep(10)
        print_with_timestamp(f"Keystone password updated for user: {user.name}")


# CgtsClient class to handle API interactions
class CgtsClient(object):
    SYSINV_API_VERSION = 1

    def __init__(self, verify_certs):
        self.conf = {}
        self._sysinv = None
        self.insecure = False if verify_certs else True

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
                os_endpoint_type='admin',
                insecure=self.insecure)
        return self._sysinv

    def wait_until_config_updated(self, old_config, username):
        retries = 0
        while retries < MAX_RETRIES_MANIFEST_APPLIED:
            if self.get_host_config_applied("controller-0") != old_config:
                return
            time.sleep(INTERVAL_WAIT_MANIFEST_APPLIED)
            retries = retries + 1
        print_with_timestamp(f"Time out waiting for host config update for {username}")
        sys.exit(1)

    def get_host_config_applied(self, host_name):
        hostlist = self.sysinv.ihost.list()
        for h in hostlist:
            if h.hostname == host_name:
                return h.config_applied
        else:
            print_with_timestamp('host not found: %s' % host_name)
            sys.exit(1)


def set_keyring_path(sw_ver):
    """Set the keyring path."""
    os.environ['XDG_DATA_HOME'] = f"/opt/platform/.keyring/{sw_ver}"
    print_with_timestamp("Keyring path set.")


def store_password_in_keyring(username, password):
    """Store the password in the keyring."""
    keyring.set_password(username, "services", password)
    print_with_timestamp(f"Keyring password stored securely for {username}.")


def main():
    """Main function to execute based on command-line input."""
    if len(sys.argv) < 3:
        print_with_timestamp("Usage: update_keystone_passwords.py <sw_ver> <json_file> [optional: verify_cert False]")
        sys.exit(1)

    sw_ver = sys.argv[1]
    json_file = sys.argv[2]
    if not os.path.isfile(json_file):
        print_with_timestamp(f"Error: JSON file '{json_file}' does not exist.")
        sys.exit(1)

    with open(json_file, 'r') as file:
        user_data = json.load(file)

    verify_certs = True
    if len(sys.argv) > 3:
        verify_value = sys.argv[3].lower()
        if verify_value == 'false':
            print_with_timestamp("Cert checks will be disabled.")
            verify_certs = False

    osclient = OpenStackClient(verify_certs)
    cgts_client = CgtsClient(verify_certs)
    set_keyring_path(sw_ver)
    for user in user_data:
        config_applied = cgts_client.get_host_config_applied("controller-0")
        updated = osclient.update_user_password(user["username"], user["password"])
        # The dc users password update will not trigger a manifest to apply
        if updated and user["username"] not in ("dcmanager", "dcagent"):
            cgts_client.wait_until_config_updated(
                config_applied,
                user["username"],
            )


if __name__ == '__main__':
    main()
