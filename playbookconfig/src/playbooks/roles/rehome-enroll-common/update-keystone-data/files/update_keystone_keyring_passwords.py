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

import keyring
from keystoneauth1.exceptions.http import Unauthorized
from keystoneclient.v3 import client as keystone_client
from keystoneclient.auth.identity import v3
from keystoneclient import session


class OpenStackClient:
    """Client to interact with OpenStack Keystone."""

    def __init__(self) -> None:
        self.conf = {}
        self._session = None
        self._keystone = None

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
            print(f"Configuration key missing: {e}")
            sys.exit(1)
        return session.Session(auth=auth)

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
        except Unauthorized:
            # Expected as new user password should not be authorized
            return False
        except Exception as e:
            print(f"check keystone password failed for {username}: {e}")
            sys.exit(1)

    def update_user_password(self, username, new_password):
        """Update the password of a keystone user."""
        ks_user = self.get_keystone_user_by_name(username)
        if not ks_user:
            print(f"User not found: {username}, attempting to create.")
            try:
                self.create_keystone_user(username, new_password)
                store_password_in_keyring(username, new_password)
            except Exception as error:
                print(f"Failed to update password for {username}: {str(error)}")

        if not self.check_password(username, new_password):
            try:
                print(f"Start updating keystone password for user: {username}")
                self.update_keystone_password(ks_user, new_password)
                store_password_in_keyring(username, new_password)
            except Exception as error:
                print(f"Failed to update password for {username}: {str(error)}")
        else:
            print(f"No update needed: password for {username} is already up to date.")

    def create_keystone_user(self, username, password):
        """Create a new keystone user."""
        user = self.keystone.users.create(
            name=username,
            password=password,
            default_project=self.conf["project_name"],
            )
        print(f"Keystone user created: {username}")

        # Assigning roles to the new user
        service_project = self.keystone.projects.find(name="services")
        admin_project = self.keystone.projects.find(name="admin")
        admin_role = self.keystone.roles.find(name="admin")
        self.keystone.roles.grant(role=admin_role, user=user, project=service_project)
        print(f"Admin role added for {username} in 'service' projects.")

        # Assign "dcmanager" to be admin role in admin project.
        if username == "dcmanager":
            self.keystone.roles.grant(role=admin_role, user=user, project=admin_project)
            print(f"Admin role added for {username} in 'admin' projects.")

    def get_keystone_user_by_name(self, username):
        """Retrieve a keystone user by username."""
        users = self.keystone.users.list(name=username)
        if not users:
            print(f"No user found with username: {username}")
            return None
        if len(users) > 1:
            print(f"Multiple users found with username: {username}, "
                  "please ensure usernames are unique.")
        return users[0]

    def update_keystone_password(self, user, password):
        """Update the password of a keystone user."""
        self.keystone.users.update(user, password=password)
        # Wait 10s for application of puppet runtime manifest
        time.sleep(10)
        print(f"Keystone password updated for user: {user.name}")


def set_keyring_path(sw_ver):
    """Set the keyring path."""
    os.environ['XDG_DATA_HOME'] = f"/opt/platform/.keyring/{sw_ver}"
    print("Keyring path set.")


def store_password_in_keyring(username, password):
    """Store the password in the keyring."""
    keyring.set_password(username, "services", password)
    print(f"Keyring password stored securely for {username}.")


def main():
    """Main function to execute based on command-line input."""
    if len(sys.argv) < 3:
        print("Usage: update_keystone_passwords.py <sw_ver> <json_file>")
        sys.exit(1)

    sw_ver = sys.argv[1]
    json_file = sys.argv[2]
    if not os.path.isfile(json_file):
        print(f"Error: JSON file '{json_file}' does not exist.")
        sys.exit(1)

    with open(json_file, 'r') as file:
        user_data = json.load(file)

    client = OpenStackClient()
    set_keyring_path(sw_ver)
    for user in user_data:
        client.update_user_password(user['username'], user['password'])


if __name__ == '__main__':
    main()
