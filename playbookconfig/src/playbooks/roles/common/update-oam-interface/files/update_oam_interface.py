#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Update OAM interface on controller-0 to ensure OAM interface stored
# in database if a reboot required operation during enrollment.
#

import os
import subprocess
import sys
from datetime import datetime
from typing import Optional, Dict, Any, List
from cgtsclient import client as cgts_client
from sysinv.common import constants as sysinv_constants


def print_with_timestamp(*args, **kwargs):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{current_time}]", *args, **kwargs)
    sys.stdout.flush()


class CgtsClient(object):
    SYSINV_API_VERSION = 1

    def __init__(self):
        self.conf = {}
        self._sysinv = None

        source_command = "source /etc/platform/openrc && env"

        with open(os.devnull, "w") as fnull:
            proc = subprocess.Popen(
                ["bash", "-c", source_command],
                stdout=subprocess.PIPE,
                stderr=fnull,
                universal_newlines=True,
            )

        for line in proc.stdout:
            key, _, value = line.partition("=")
            if key == "OS_USERNAME":
                self.conf["admin_user"] = value.strip()
            elif key == "OS_PASSWORD":
                self.conf["admin_pwd"] = value.strip()
            elif key == "OS_PROJECT_NAME":
                self.conf["admin_tenant"] = value.strip()
            elif key == "OS_AUTH_URL":
                self.conf["auth_url"] = value.strip()
            elif key == "OS_REGION_NAME":
                self.conf["region_name"] = value.strip()
            elif key == "OS_USER_DOMAIN_NAME":
                self.conf["user_domain"] = value.strip()
            elif key == "OS_PROJECT_DOMAIN_NAME":
                self.conf["project_domain"] = value.strip()

        proc.communicate()

    @property
    def sysinv(self):
        if not self._sysinv:
            self._sysinv = cgts_client.get_client(
                self.SYSINV_API_VERSION,
                os_username=self.conf["admin_user"],
                os_password=self.conf["admin_pwd"],
                os_auth_url=self.conf["auth_url"],
                os_project_name=self.conf["admin_tenant"],
                os_project_domain_name=self.conf["project_domain"],
                os_user_domain_name=self.conf["user_domain"],
                os_region_name=self.conf["region_name"],
                os_service_type="platform",
                os_endpoint_type="admin",
            )
        return self._sysinv


def find_oam_network(client: CgtsClient) -> Any:
    """Find the OAM network.

    Returns:
        OAM network object

    Raises:
        ValueError: If OAM network not found
    """
    oam_network = next(
        (
            n
            for n in client.sysinv.network.list()
            if n.type == sysinv_constants.NETWORK_TYPE_OAM
        ),
        None,
    )
    if not oam_network:
        raise ValueError("OAM network not found")
    return oam_network


def find_port(client: CgtsClient, ihost_uuid: str, bootstrap_interface: str) -> Any:
    """Find the port by interface name.

    Returns:
        Port object

    Raises:
        ValueError: If port not found
    """
    ports = client.sysinv.port.list(ihost_uuid)

    # First try to find the interface with the bootstrap name and get its port
    interfaces = client.sysinv.iinterface.list(ihost_uuid)
    bootstrap_iface = next(
        (i for i in interfaces if i.ifname == bootstrap_interface), None
    )

    if bootstrap_iface:
        # Interface exists, find the port assigned to it
        port = next(
            (p for p in ports if p.interface_uuid == bootstrap_iface.uuid), None
        )
        if port:
            return port

    # Fallback: try to find port by name matching bootstrap_interface
    port = next((p for p in ports if p.name == bootstrap_interface), None)
    if not port:
        raise ValueError(f"Port for {bootstrap_interface} not found")

    return port


def find_existing_oam_interface(
    client: CgtsClient, interfaces: List[Any], oam_network_uuid: str
) -> Optional[Any]:
    """Find existing OAM interface.

    Returns:
        OAM interface object if found, None otherwise
    """
    for iface in interfaces:
        if_networks = client.sysinv.interface_network.list_by_interface(iface.uuid)
        for if_net in if_networks:
            if if_net.network_uuid == oam_network_uuid:
                return iface
    return None


def interface_update_required(
    oam_if: Any,
    bootstrap_vlan: Optional[str],
    bootstrap_interface: str,
    interfaces: List[Any],
    port: Any,
) -> bool:
    """Check if OAM interface needs update following Go reconciliation logic.

    Returns:
        True if update needed, False otherwise
    """
    print_with_timestamp(
        f"Checking interface update for {oam_if.ifname}: "
        f"bootstrap_vlan={bootstrap_vlan}, "
        f"iftype={oam_if.iftype}, uses={getattr(oam_if, 'uses', [])}, "
        f"ports={getattr(oam_if, 'ports', [])}"
    )

    if oam_if.iftype == sysinv_constants.INTERFACE_TYPE_VLAN:
        # Condition 1: iftype is VLAN
        vlan_id = getattr(oam_if, "vlan_id", None)
        if bootstrap_vlan and vlan_id != int(bootstrap_vlan):
            print_with_timestamp(
                "  -> Update required: vlan_id mismatch "
                f"(expected {bootstrap_vlan}, got {vlan_id})"
            )
            return True
        uses = getattr(oam_if, "uses", [])
        # Find the interface that owns the bootstrap port
        bootstrap_iface = next(
            (i for i in interfaces if i.uuid == port.interface_uuid), None
        )
        bootstrap_iface_name = bootstrap_iface.ifname if bootstrap_iface else None
        if bootstrap_iface_name not in uses:
            print_with_timestamp(
                "  -> Update required: bootstrap interface "
                f"'{bootstrap_iface_name}' not in uses {uses}"
            )
            return True
    else:
        # Condition 2: iftype is not VLAN
        if bootstrap_vlan:
            print_with_timestamp(
                "  -> Update required: bootstrap_vlan offered but "
                f"iftype is {oam_if.iftype}"
            )
            return True
        uses = getattr(oam_if, "uses", [])
        port_uuids = getattr(oam_if, "ports", [])
        # Find the interface that owns the bootstrap port
        bootstrap_iface = next(
            (i for i in interfaces if i.uuid == port.interface_uuid), None
        )
        if bootstrap_iface and bootstrap_iface.uuid != oam_if.uuid:
            # Port is owned by another interface, check if it's in uses
            if bootstrap_iface.ifname not in uses:
                print_with_timestamp(
                    "  -> Update required: bootstrap interface "
                    f"'{bootstrap_iface.ifname}' not in uses {uses}"
                )
                return True
        elif not bootstrap_iface:
            # Port is not owned by any interface, check if it's directly in ports
            if port.uuid not in port_uuids:
                print_with_timestamp(
                    f"  -> Update required: port {port.uuid} not in ports {port_uuids}"
                )
                return True
        # else: port is owned by oam_if itself, which is correct

    print_with_timestamp("  -> No update required")
    return False


def build_interface_values(
    ihost_uuid: str,
    bootstrap_vlan: Optional[str],
    oam_if: Optional[Any],
    port: Any,
    interfaces: List[Any],
    bootstrap_interface: str,
) -> Dict[str, Any]:
    """Build interface configuration values.

    Args:
        ihost_uuid: Host UUID
        bootstrap_vlan: VLAN ID if using VLAN interface
        oam_if: Existing OAM interface
        port: Existing Port
        interfaces: List of interface
        bootstrap_interface: Bootstrap interface name

    Returns:
        Dictionary of interface configuration values
    """

    # if names can be corrected based on the values in deployment
    # configuration in the end of the enrollment
    ifname = "oam0"

    values = {
        "ihost_uuid": ihost_uuid,
        "ifname": ifname,
        "ifclass": sysinv_constants.INTERFACE_CLASS_PLATFORM,
    }

    if bootstrap_vlan:
        values.update(
            {
                "iftype": sysinv_constants.INTERFACE_TYPE_VLAN,
                "vlan_id": int(bootstrap_vlan),
            }
        )
    else:
        values.update(
            {
                "iftype": sysinv_constants.INTERFACE_TYPE_ETHERNET,
            }
        )

    if oam_if:
        values.update(
            {
                "imtu": oam_if.imtu,
                "ptp_role": oam_if.ptp_role,
            }
        )

    # Use ports for ethernet, uses for VLAN
    if bootstrap_vlan:
        # Find the interface that owns the bootstrap port
        bootstrap_iface = next(
            (i for i in interfaces if i.uuid == port.interface_uuid), None
        )
        if bootstrap_iface:
            values["uses"] = [bootstrap_iface.ifname]
        else:
            values["uses"] = [bootstrap_interface]
    else:
        values["ports"] = [port.name]

    return values


def remove_interface_network_assignment(
    client: CgtsClient, oam_if: Any, oam_network_uuid: str
) -> None:
    """Remove OAM network association from interface."""
    if_networks = client.sysinv.interface_network.list_by_interface(oam_if.uuid)
    for if_net in if_networks:
        if if_net.network_uuid == oam_network_uuid:
            print_with_timestamp(
                f"Removing OAM network from interface: {oam_if.ifname}"
            )
            client.sysinv.interface_network.remove(if_net.uuid)
            break


def delete_interface(client: CgtsClient, oam_if: Any) -> bool:
    """Delete interface that needs to be recreated.

    Returns:
        True if interface was deleted, False if it should be updated
    """
    if oam_if.iftype in [
        sysinv_constants.INTERFACE_TYPE_VLAN,
        sysinv_constants.INTERFACE_TYPE_AE,
    ]:
        print_with_timestamp(f"Deleting stale interface: {oam_if.ifname}")
        client.sysinv.iinterface.delete(oam_if.uuid)
        return True
    return False


def configure_interface(
    client: CgtsClient,
    oam_if: Optional[Any],
    deleted: bool,
    ihost_uuid: str,
    bootstrap_vlan: Optional[str],
    bootstrap_interface: str,
    port: Any,
    interfaces: List[Any],
    oam_network_uuid: str,
) -> None:
    """Create or update interface."""
    values = build_interface_values(
        ihost_uuid,
        bootstrap_vlan,
        oam_if,
        port,
        interfaces,
        bootstrap_interface,
    )

    if deleted or not oam_if:
        # Create new interface
        new_if = client.sysinv.iinterface.create(**values)
        print_with_timestamp(f"OAM interface created: {new_if.ifname}")
        interface_uuid = new_if.uuid
    else:
        # Clear the old OAM interface class to none first (releases the name)
        print_with_timestamp(f"Clearing class for old OAM interface: {oam_if.ifname}")
        patch = [{"op": "replace", "path": "/ifclass", "value": "none"}]
        client.sysinv.iinterface.update(oam_if.uuid, patch)

        # Modify the interface that owns the port
        bootstrap_iface = next(
            (i for i in interfaces if i.uuid == port.interface_uuid), None
        )
        if not bootstrap_iface:
            raise ValueError(f"Cannot find interface for port {port.name}")

        print_with_timestamp(f"Modifying interface {bootstrap_iface.ifname} to oam0")
        patch = [
            {"op": "replace", "path": "/ifname", "value": values["ifname"]},
            {"op": "replace", "path": "/ifclass", "value": values["ifclass"]},
            {"op": "replace", "path": "/imtu", "value": values["imtu"]},
            {"op": "replace", "path": "/ptp_role", "value": values["ptp_role"]},
        ]
        updated_if = client.sysinv.iinterface.update(bootstrap_iface.uuid, patch)
        print_with_timestamp(f"OAM interface updated: {updated_if.ifname}")
        interface_uuid = updated_if.uuid

    client.sysinv.interface_network.assign(
        interface_uuid=interface_uuid, network_uuid=oam_network_uuid
    )
    print_with_timestamp("OAM network assigned to interface")


def update_oam_interface(
    bootstrap_interface: str,
    bootstrap_vlan: Optional[str] = None,
    client: Optional[CgtsClient] = None,
) -> None:
    """Update OAM interface following Go reconciliation workflow.

    Raises:
        ValueError: If OAM network or port not found
    """
    if client is None:
        client = CgtsClient()

    oam_network = find_oam_network(client)
    ihost = client.sysinv.ihost.get("controller-0")
    interfaces = client.sysinv.iinterface.list("controller-0")
    port = find_port(client, ihost.uuid, bootstrap_interface)
    oam_if = find_existing_oam_interface(client, interfaces, oam_network.uuid)

    if oam_if and not interface_update_required(
        oam_if, bootstrap_vlan, bootstrap_interface, interfaces, port
    ):
        print_with_timestamp(
            f"OAM interface already configured correctly: {oam_if.ifname}"
        )
        return

    deleted = False
    if oam_if:
        # Phase 1: Remove stale interface-network assignment
        remove_interface_network_assignment(client, oam_if, oam_network.uuid)
        # Phase 2: Delete stale interfaces that need recreation (VLAN/Bond only)
        deleted = delete_interface(client, oam_if)

    # Phase 3: Create or Update interface and network assignment
    configure_interface(
        client,
        oam_if,
        deleted,
        ihost.uuid,
        bootstrap_vlan,
        bootstrap_interface,
        port,
        interfaces,
        oam_network.uuid,
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_with_timestamp(
            "Usage: update_oam_interface.py <bootstrap_interface> [bootstrap_vlan]"
        )
        sys.exit(1)

    bootstrap_interface = sys.argv[1]
    bootstrap_vlan = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        update_oam_interface(bootstrap_interface, bootstrap_vlan)
    except ValueError as e:
        print_with_timestamp(str(e))
        sys.exit(1)
