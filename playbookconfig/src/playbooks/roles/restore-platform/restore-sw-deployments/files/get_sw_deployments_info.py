#!/usr/bin/env python3
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from argparse import ArgumentParser
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import defusedxml.ElementTree as ET

TAR_CMD = ["tar", "--use-compress-program=pigz"]


@lru_cache(maxsize=None)
def read_file(backup_data, path):
    """Read a single file from the backup tar"""

    return subprocess.check_output(
        TAR_CMD + ["-Oxf", backup_data, path],
        text=True,
        stderr=subprocess.DEVNULL,
    )


def get_sw_version(patch_metadata):
    """Read the SW version from a patch"""

    xroot = ET.XML(patch_metadata)
    xnode = xroot.find("./sw_version")
    return tuple(map(int, xnode.text.split(".")))


def get_root_commit(patch_metadata):
    """Read the first commit from a deployed patch metadata string"""

    xroot = ET.XML(patch_metadata)
    xnode = xroot.find("./contents/ostree/commit1/commit")
    return xnode.text if xnode is not None else None


def get_base_commit(patch_metadata):
    """Read the base commit from a deployed patch metadata string"""

    xroot = ET.XML(patch_metadata)
    xnode = xroot.find("./contents/ostree/base/commit")
    return xnode.text if xnode is not None else None


def get_reboot_required_patch(patch_metadata):
    """Determine if this patch is RR"""

    xroot = ET.XML(patch_metadata)
    xnode = xroot.find("./reboot_required")
    return xnode.text == "Y" if xnode is not None else False


@lru_cache(maxsize=None)
def get_metadata(backup_data):
    """Get the paths to all the metadata files and group them by type

    Group by type, sorted by recentness.  Latest patch will be last index.
    """

    metadata = {}
    p = subprocess.run(
        TAR_CMD + ["--wildcards", "-tf", backup_data, "opt/software/metadata/*.xml"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    entries = p.stdout.splitlines() if p.returncode == 0 else []
    for v in entries:
        metadata.setdefault(Path(v).parent.name, []).append(v)
    for k, v in metadata.items():
        metadata[k] = sorted(v, key=lambda x: get_sw_version(read_file(backup_data, x)))
    return metadata


def get_target_commit(backup_data, metadata):
    """Get the base OSTree commit of the ISO/earliest commit"""

    if not metadata:
        target_commit = None
    elif len(metadata.get("deployed", [])) == 1:
        target_commit = get_root_commit(read_file(backup_data, metadata["deployed"][0]))
    elif len(metadata.get("deployed", [])) > 1:
        target_commit = get_base_commit(read_file(backup_data, metadata["deployed"][1]))
    else:
        raise EnvironmentError("Unable to determine root/base commit")
    return target_commit


@lru_cache(maxsize=None)
def check_if_backup_patched(backup_data):
    """Return if this backup has patching data"""

    rc = subprocess.call(
        TAR_CMD + ["-tf", backup_data, "opt/software/.controller.state"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return rc == 0


def get_target_release_id(metadata):
    """Get which release we will upgrade too"""

    if len(metadata["deployed"]) <= 1:
        return None

    patch_path = metadata["deployed"][-1]
    return Path(patch_path).name.replace("-metadata.xml", "")


def get_target_reboot_required(backup_data, metadata):
    """Get if we are RR for our target upgrade"""

    return any(
        get_reboot_required_patch(read_file(backup_data, v))
        for v in metadata["deployed"][1:]
    )


def get_tar_transforms(metadata):
    """Convert deployed release to available releases"""

    transforms = []
    for v in metadata.get("deployed", [])[1:]:
        transforms.append(f"s|{v}|{v.replace('deployed', 'available')}|")
    return transforms


def collect_sw_deployments_info(backup_data):
    """Collect software deployments info from backup so it can be printed as a JSON"""

    result = {}
    metadata = get_metadata(backup_data)

    if metadata.get("committed"):
        raise NotImplementedError("Committed patches not supported yet")

    result["backup_patched"] = check_if_backup_patched(backup_data)
    result["target_commit"] = get_target_commit(backup_data, metadata)

    if result["backup_patched"]:
        result["target_release_id"] = get_target_release_id(metadata)
        result["target_reboot_required"] = get_target_reboot_required(backup_data, metadata)
        result["tar_transforms"] = get_tar_transforms(metadata)

    result["metadata"] = metadata
    return result


def main(argv=None):
    parser = ArgumentParser()
    parser.add_argument("backup_data")
    args = parser.parse_args(argv)
    result = collect_sw_deployments_info(args.backup_data)
    return result


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
