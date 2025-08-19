#!/usr/bin/python3
#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Calculate patches to transfer and apply for subcloud enrollment
#

import os
import sys
import json
import subprocess
import argparse
import time
import secrets
import glob
import tarfile
from defusedxml import ElementTree as ET
from typing import Dict, List, Tuple, Any
from packaging.version import parse as parse_version
from software_client import client as sclient  # pylint: disable=import-error


def get_os_env() -> Dict[str, str]:
    """Get OpenStack environment variables."""
    source_command = "source /etc/platform/openrc && env"
    with subprocess.Popen(
        ["bash", "-c", source_command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    ) as proc:
        conf = {}
        for line in proc.stdout:
            line = line.strip()
            if "=" in line and line.startswith("OS_"):
                key, _, value = line.partition("=")
                conf[key[3:].lower()] = value.strip()

        proc.communicate()
    return conf


def get_releases(software_version: str) -> List[Dict[str, Any]]:
    """Get releases from software client."""
    conf = get_os_env()

    client = sclient.get_client(
        api_version="1",
        auth_mode="keystone",
        os_username=conf.get("username"),
        os_password=conf.get("password"),
        os_auth_url=conf.get("auth_url"),
        os_project_name=conf.get("project_name"),
        os_user_domain_name=conf.get("user_domain_name"),
        os_project_domain_name=conf.get("project_domain_name"),
        os_region_name=conf.get("region_name"),
        # TODO(yuxing): the software client expects both api_version and
        # system_api_version. Clean one of them if no longer requested.
        system_api_version="1",
    )

    # As a request in the central cloud, use exponential backoff to avoid
    # overwhelming the API
    for attempt in range(4):
        try:
            _, releases = client.http_client.json_request(
                "GET", f"/v1/release?release={software_version}"
            )
            return releases
        except Exception as exc:  # pylint: disable=broad-except
            if attempt == 3:
                raise exc
            backoff = (5**attempt) + secrets.SystemRandom().uniform(0, 1)
            time.sleep(backoff)
    return []


def compare_versions(version1: str, version2: str) -> int:
    """Compare versions, padding third part to 3 digits."""
    def normalize_version(version):
        parts = version.split(".")
        if len(parts) >= 3:
            parts[2] = parts[2].ljust(3, "0")  # Pad to 3 digits
        return ".".join(parts)

    ver1 = parse_version(normalize_version(version1))
    ver2 = parse_version(normalize_version(version2))
    if ver1 > ver2:
        return 1
    elif ver1 < ver2:
        return -1
    return 0


class PatchChecker:
    """Check patches to apply for subcloud enrollment."""

    def __init__(
        self,
        releases: List[Dict[str, Any]],
        sc_software_version: str,
        cc_software_version: str,
    ) -> None:
        self.releases = releases
        self.sc_software_version = sc_software_version
        self.cc_software_version = cc_software_version
        self.vault_path = f"/opt/dc-vault/software/{sc_software_version}"
        self.patch_files_to_apply = []
        self.release_ids_to_apply = []
        self.reboot_required = False
        self.patch_file_id_dict = None

    def _extract_release_id(self, patch_file: str) -> str:
        """Extract release ID from patch file metadata."""
        try:
            with tarfile.open(patch_file, "r") as tar:
                metadata_tar = tar.extractfile("metadata.tar")
                if not metadata_tar:
                    return None

                with tarfile.open(fileobj=metadata_tar, mode="r") as meta_tar:
                    metadata_xml = meta_tar.extractfile("metadata.xml")
                    if not metadata_xml:
                        return None

                    root = ET.parse(metadata_xml).getroot()
                    release_id = root.find("id")
                    return release_id.text if release_id is not None else None
        except (ET.ParseError, tarfile.TarError, OSError):
            return None

    def _build_patch_file_mapping(self) -> Dict[str, str]:
        """Build mapping of release IDs to patch file names."""
        patch_files = glob.glob(os.path.join(self.vault_path, "*.patch"))
        mapping = {}

        for patch_file in patch_files:
            try:
                release_id = self._extract_release_id(patch_file)
                if release_id:
                    mapping[release_id] = os.path.basename(patch_file)
            except (tarfile.TarError, OSError, ET.ParseError):
                continue

        return mapping

    def _get_patch_file_mapping(self) -> Dict[str, str]:
        """Lazy load patch file mapping."""
        if self.patch_file_id_dict is None:
            self.patch_file_id_dict = self._build_patch_file_mapping()
        return self.patch_file_id_dict

    def determine_subcloud_patch_level(
        self, subcloud_releases: List[str] = None
    ) -> Tuple[str, str]:
        """Determine the highest patch level and component from subcloud releases."""

        parsed_releases = []
        for rel in subcloud_releases:
            parts = rel.split("-")
            if len(parts) >= 2:
                component = parts[0]
                version = parts[1]
                parsed_releases.append((version, component))

        # Sort by version and get the highest
        parsed_releases.sort(key=lambda x: parse_version(x[0]))
        highest_version, component = parsed_releases[-1]
        return highest_version, component

    def filter_system_controller_patches(
        self, subcloud_component: str = None
    ) -> List[Dict[str, Any]]:
        """Filter system controller patches based on subcloud component."""
        if self.sc_software_version == self.cc_software_version:
            return [
                r
                for r in self.releases
                if (
                    r.get("state") in ["deployed", "committed", "unavailable"] and
                    r.get("component") == subcloud_component and
                    not r.get("prepatched_iso", False)
                )
            ]
        else:
            return [
                r
                for r in self.releases
                if r.get("component") == subcloud_component and
                not r.get("prepatched_iso", False)
            ]

    def find_patches_to_apply(
        self, subcloud_releases: List[str] = None
    ) -> Dict[str, str]:
        """Find patches to apply based on subcloud releases."""
        subcloud_patch_level, subcloud_component = self.determine_subcloud_patch_level(
            subcloud_releases
        )
        filtered_releases = self.filter_system_controller_patches(subcloud_component)

        if not filtered_releases:
            return {"release_ids_to_apply": []}

        # Find the highest release software version
        highest_release = max(filtered_releases, key=lambda x: parse_version(x.get("sw_version", "0")))
        target_release_id = highest_release.get("release_id")
        target_sw_version = highest_release.get("sw_version")

        if (
            compare_versions(
                highest_release.get("sw_version", "0"), subcloud_patch_level
            ) <= 0
        ):
            return {"release_ids_to_apply": []}

        success, error, found = self.check_patch_chain(
            target_release_id, subcloud_patch_level
        )

        if not success:
            return {"error": error}

        if not found:
            return {"error": "Insufficient patches uploaded to enable patching."}

        return {
            "patch_files_to_apply": list(reversed(self.patch_files_to_apply)),
            "release_ids_to_apply": list(reversed(self.release_ids_to_apply)),
            "target_release_id": target_release_id,
            "target_sw_version": target_sw_version,
            "reboot_required": self.reboot_required,
        }

    def check_patch_chain(
        self, release_id: str, base_level: str
    ) -> Tuple[bool, str, bool]:
        """Check patch chain for dependencies."""
        release = next(
            (r for r in self.releases if r.get("release_id") == release_id), None
        )
        # Depended patches not uploaded
        if not release:
            return (
                False,
                f"Release {release_id} not found. Upload it before retry.",
                False,
            )

        # Check if patch file exists using metadata mapping
        patch_mapping = self._get_patch_file_mapping()
        if release_id not in patch_mapping:
            return (
                False,
                f"Patch file for {release_id} not uploaded, please upload it before enroll again.",
                False,
            )

        patch_file = patch_mapping[release_id]
        self.patch_files_to_apply.append(patch_file)
        self.release_ids_to_apply.append(release_id)
        if release.get("reboot_required", False):
            self.reboot_required = True

        requires = release.get("requires", [])
        if not requires:
            return (True, "", True)

        for req in requires:
            found = False
            # Looking for further dependencies if dependencies exist and higher
            # than the base level
            if compare_versions(req.split("-")[-1], base_level) > 0:
                success, error, found = self.check_patch_chain(req, base_level)
                if not success:
                    return False, error, found
            elif compare_versions(req.split("-")[-1], base_level) == 0:
                found = True

        return True, "", found


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check patches to apply for subcloud enrollment"
    )
    parser.add_argument(
        "--sc-software-version", required=True, help="Subcloud software version"
    )
    parser.add_argument(
        "--cc-software-version", required=True, help="Central cloud software version"
    )
    parser.add_argument(
        "--subcloud-releases",
        help="Comma-separated list of subcloud releases with components",
    )
    args = parser.parse_args()

    try:
        releases = get_releases(args.sc_software_version)
        checker = PatchChecker(
            releases, args.sc_software_version, args.cc_software_version
        )
        subcloud_releases = (
            args.subcloud_releases.split(",") if args.subcloud_releases else None
        )
        result = checker.find_patches_to_apply(subcloud_releases)

        if "error" in result:
            print(json.dumps({"failed": True, "msg": result["error"]}))
            sys.exit(1)
        else:
            print(json.dumps(result))

    except Exception as exc:  # pylint: disable=broad-except
        print(json.dumps({"failed": True, "msg": str(exc)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
