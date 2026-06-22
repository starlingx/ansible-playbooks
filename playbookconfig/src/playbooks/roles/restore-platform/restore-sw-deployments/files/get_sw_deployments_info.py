#!/usr/bin/env python3
#
# Copyright (c) 2024-2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from argparse import ArgumentParser
from collections import defaultdict
from functools import lru_cache
import json
from pathlib import Path
import subprocess
import defusedxml.ElementTree as ET

TAR_CMD = ["tar", "--use-compress-program=pigz"]

MINIMUM_SW_VERSION = (24, 9)


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


def get_commit(patch_metadata):
    """Read the commit from a deployed metapackage metadata string"""

    xroot = ET.XML(patch_metadata)
    xnode = xroot.find("./contents/ostree/commit1/commit")
    return xnode.text if xnode is not None else None


def get_reboot_required_patch(patch_metadata):
    """Determine if this patch is RR"""

    xroot = ET.XML(patch_metadata)
    xnode = xroot.find("./reboot_required")
    return xnode.text == "Y" if xnode is not None else False


def get_metapackage_id(path):
    """Derive the metapackage ID from its metadata file path"""

    return Path(path).name.replace("-metadata.xml", "")


@lru_cache(maxsize=None)
def get_metadata(backup_data):
    """Get the paths to all the metapackage metadata files and group them by state.

    Looks in opt/software/releases/metadata/<state>/*.xml
    """

    metadata = {}
    p = subprocess.run(
        TAR_CMD + ["--wildcards", "-tf", backup_data,
                   "opt/software/releases/metadata/*/*.xml"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    entries = p.stdout.splitlines() if p.returncode == 0 else []
    for v in entries:
        state = Path(v).parent.name
        metadata.setdefault(state, []).append(v)
    for k, v in metadata.items():
        metadata[k] = sorted(v, key=lambda x: get_sw_version(read_file(backup_data, x)))
    return metadata


def get_deployed_groups(backup_data, metadata):
    """Group deployed metapackages by sw_version, sorted by version.

    Returns a list of dicts:
      [{"sw_version": (major, minor, ...), "metapackages": ["id1", "id2", ...],
        "paths": ["path1", "path2", ...]}, ...]
    """

    groups = defaultdict(lambda: {"metapackages": [], "paths": []})
    for path in metadata.get("deployed", []):
        content = read_file(backup_data, path)
        sw_version = get_sw_version(content)
        metapkg_id = get_metapackage_id(path)
        groups[sw_version]["metapackages"].append(metapkg_id)
        groups[sw_version]["paths"].append(path)

    result = []
    for sw_version in sorted(groups.keys()):
        result.append({
            "sw_version": sw_version,
            "metapackages": groups[sw_version]["metapackages"],
            "paths": groups[sw_version]["paths"],
        })
    return result


def get_target_commit(backup_data, deployed_groups):
    """Get the target OSTree commit from the ISO base group (first in sorted order).

    All metapackages in the base group should share the same commit.
    """

    if not deployed_groups:
        return None

    base_group = deployed_groups[0]
    commits = set()
    for path in base_group["paths"]:
        content = read_file(backup_data, path)
        commit = get_commit(content)
        if commit:
            commits.add(commit)

    if len(commits) > 1:
        raise EnvironmentError(
            "Base ISO metapackages have inconsistent commit IDs: {}".format(commits)
        )

    return commits.pop() if commits else None


@lru_cache(maxsize=None)
def check_if_backup_patched(backup_data):
    """Return if this backup has patching data"""

    rc = subprocess.call(
        TAR_CMD + ["-tf", backup_data, "opt/software/.controller.state"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return rc == 0


def get_deployments_to_restore(deployed_groups):
    """Get deployments to restore (everything after the base ISO group).

    Returns a list of dicts with sw_version string and metapackage IDs.
    """

    if len(deployed_groups) <= 1:
        return []

    result = []
    for group in deployed_groups[1:]:
        result.append({
            "sw_version": ".".join(map(str, group["sw_version"])),
            "metapackages": group["metapackages"],
            "paths": group["paths"],
        })
    return result


def get_target_reboot_required(backup_data, deployments_to_restore):
    """Check if any metapackage in the deployments to restore requires a reboot"""

    for deployment in deployments_to_restore:
        for path in deployment["paths"]:
            if get_reboot_required_patch(read_file(backup_data, path)):
                return True
    return False


def get_tar_transforms(deployments_to_restore):
    """Convert deployed metapackages to available for extraction"""

    transforms = []
    for deployment in deployments_to_restore:
        for path in deployment["paths"]:
            transforms.append(
                "s|{}|{}|".format(path, path.replace("deployed", "available"))
            )
    return transforms


def get_tar_excludes(backup_data, metadata):
    """Prevent unwanted items from being extracted during restore"""

    excludes = []
    for kind in ["committed", "unavailable"]:
        for v in metadata.get(kind, []):
            sw_version = get_sw_version(read_file(backup_data, v))
            if sw_version < MINIMUM_SW_VERSION:
                excludes.append(v)

    return excludes


def collect_sw_deployments_info(backup_data):
    """Collect software deployments info from backup so it can be printed as a JSON"""

    result = {}
    metadata = get_metadata(backup_data)
    deployed_groups = get_deployed_groups(backup_data, metadata)

    # Fail if committed data is found above minimum release
    for v in metadata.get("committed", []):
        sw_version = get_sw_version(read_file(backup_data, v))
        if sw_version >= MINIMUM_SW_VERSION:
            raise NotImplementedError("Committed patches not supported yet")

    result["backup_patched"] = check_if_backup_patched(backup_data)
    result["target_commit"] = get_target_commit(backup_data, deployed_groups)

    if result["backup_patched"]:
        deployments_to_restore = get_deployments_to_restore(deployed_groups)
        result["deployments_to_restore"] = deployments_to_restore
        result["target_reboot_required"] = get_target_reboot_required(
            backup_data, deployments_to_restore
        )
        result["tar_transforms"] = get_tar_transforms(deployments_to_restore)
        result["tar_excludes"] = get_tar_excludes(backup_data, metadata)

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
