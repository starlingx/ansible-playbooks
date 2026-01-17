#!/usr/bin/env python3
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Description:
#   This script updates OpenStack admin endpoints to reflect a subcloud's
#   network reconfiguration
#

import argparse
import ipaddress
import logging
import os
import subprocess
import sys

from keystoneauth1.identity import v3
from keystoneauth1 import session
from keystoneclient.v3 import client as keystone_client
from keystoneclient import exceptions as ks_exceptions

OPENRC_PATH = "/etc/platform/openrc"

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def load_credentials_and_create_session() -> session.Session:
    """
    Creates a Keystone session by first checking for token-based auth environment
    variables. If they are not present, it falls back to sourcing an openrc
    file for password-based authentication.
    """
    auth_url = os.getenv("OS_AUTH_URL")
    auth_token = os.getenv("OS_TOKEN")

    if auth_token and auth_url:
        logging.info("Using token-based authentication from environment variables")
        auth = v3.Token(
            auth_url=auth_url,
            token=auth_token,
            project_name=os.getenv("OS_PROJECT_NAME", "admin"),
            project_domain_name=os.getenv("OS_PROJECT_DOMAIN_NAME", "Default"),
        )
        return session.Session(auth=auth)

    logging.info(
        "Token not found in environment. "
        f"Falling back to sourcing '{OPENRC_PATH}' for password credentials"
    )
    source_command = f"source {OPENRC_PATH} && env"
    try:
        with open(os.devnull, "w") as fnull:
            proc = subprocess.Popen(
                ["bash", "-c", source_command],
                stdout=subprocess.PIPE,
                stderr=fnull,
                universal_newlines=True,
            )

        creds = {}
        for line in proc.stdout:
            if "=" in line:
                key, _, value = line.partition("=")
                value = value.strip()
                if key == "OS_USERNAME":
                    creds["username"] = value
                elif key == "OS_PASSWORD":
                    creds["password"] = value
                elif key == "OS_PROJECT_NAME":
                    creds["project_name"] = value
                elif key == "OS_AUTH_URL":
                    creds["auth_url"] = value
                elif key == "OS_REGION_NAME":
                    creds["region_name"] = value
                elif key == "OS_USER_DOMAIN_NAME":
                    creds["user_domain_name"] = value
                elif key == "OS_PROJECT_DOMAIN_NAME":
                    creds["project_domain_name"] = value
        proc.communicate()

    except subprocess.SubprocessError as e:
        logging.critical(f"Failed to execute source command: {e}")
        sys.exit(1)

    auth = v3.Password(
        auth_url=creds.get("auth_url"),
        username=creds.get("username"),
        password=creds.get("password"),
        project_name=creds.get("project_name"),
        user_domain_name=creds.get("user_domain_name", "Default"),
        project_domain_name=creds.get("project_domain_name", "Default"),
    )
    return session.Session(auth=auth)


def main():
    parser = argparse.ArgumentParser(
        description="Update OpenStack admin endpoints for a subcloud.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "region_name",
        help="The region_name of the subcloud.",
    )
    parser.add_argument(
        "sc_floating_address",
        help="The floating IP address of the subcloud.",
    )
    parser.add_argument(
        "--mode",
        choices=["enroll"],
        help="Optional mode. If set to 'enroll', certain services are skipped",
    )
    args = parser.parse_args()

    try:
        region_name = args.region_name
        ip = ipaddress.ip_address(args.sc_floating_address.strip("[]"))
        parsed_sc_floating_address = (
            f"[{ip}]" if isinstance(ip, ipaddress.IPv6Address) else str(ip)
        )
    except ValueError:
        logging.critical(f"Invalid IP address provided: {args.sc_floating_address}")
        sys.exit(1)

    logging.info(f"Parsed floating address as: {parsed_sc_floating_address}")

    keystone_session = load_credentials_and_create_session()
    keystone = keystone_client.Client(session=keystone_session, interface="internal")

    service_list = [
        {"port": "5001", "service": "keystone"},
        {"port": "6386/v1", "service": "sysinv"},
        {"port": "5492", "service": "patching"},
        {"port": "4546", "service": "vim"},
        {"port": "18003", "service": "fm"},
        {"port": "9312", "service": "barbican"},
        {"port": "5498", "service": "usm"},
    ]

    if args.mode != "enroll":
        logging.info("Mode is not 'enroll', adding dcdbsync and dcagent services")
        service_list.extend(
            [
                {"port": "8220/v1.0", "service": "dcdbsync"},
                {"port": "8326", "service": "dcagent"},
            ]
        )

    try:
        logging.info("Fetching data from Keystone...")
        existing_services = keystone.services.list()
        all_endpoints = keystone.endpoints.list(interface="admin")
    except ks_exceptions.ClientException as e:
        logging.critical(f"Failed to fetch Keystone data. Error: {e}")
        sys.exit(1)

    logging.info(f"Found {len(all_endpoints)} admin endpoints.")

    services_dict = {service.name: service.id for service in existing_services}

    for item in service_list:
        service_name = item["service"]
        port = item["port"]
        desired_url = f"https://{parsed_sc_floating_address}:{port}"

        admin_endpoint = next(
            (
                ep
                for ep in all_endpoints
                if ep.service_id == services_dict.get(service_name) and
                ep.region == region_name
            ),
            None,
        )

        if not admin_endpoint:
            logging.warning(
                f"No admin endpoint found for service '{service_name}', skipping"
            )
            continue

        if admin_endpoint.url == desired_url:
            logging.info(
                f"Endpoint for '{service_name}' is already correct, no change needed"
            )
            continue
        logging.info(
            f"Updating endpoint for '{service_name}': OLD='{admin_endpoint.url}', NEW='{desired_url}'"
        )
        try:
            keystone.endpoints.update(
                endpoint=admin_endpoint,
                url=desired_url,
                enabled=True,
            )
            logging.info(f"Successfully updated endpoint for '{service_name}'")
        except ks_exceptions.ClientException as e:
            logging.error(f"Failed to update endpoint for '{service_name}'. Error: {e}")


if __name__ == "__main__":
    main()
