#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Read the software (patch) metadata captured in a subcloud platform backup
# and emit, as JSON, the non-base product releases that must be re-applied to
# restore the subcloud to its backed-up patch level.
#
# Subcloud backups intentionally exclude the ostree patch payload to keep the
# archive small; they include only the patch metadata under
# "opt/software/releases/metadata/". This script reads the PRODUCT metadata
# there directly from the backup tar, without extracting the whole archive.
#
# The product id is what USM reports in "software list" and what
# "software deploy start <id>" expects (USM then expands the product into its
# per-metapackage deployed releases). The per-metapackage metadata under
# "metadata/deployed/*.xml" uses a DIFFERENT id namespace ("<pkg>_<version>")
# that never matches "software list", so this script and the whole
# patch-before-restore path operate on the product id to stay consistent with
# common/usm-deploy-releases and the enroll path.
#
# The lowest sw_version product is the base ISO and is NOT returned, since the
# base is already present on a factory-installed subcloud. Only the products
# layered on top of the base are returned.
#
# Output JSON schema:
#   {
#     "backup_patched": <bool>,          # whether any non-base product exists
#     "reboot_required": <bool>,         # true if any returned product is RR
#     "release_ids": [<str>, ...],       # non-base product release ids,
#                                        # ordered oldest -> newest sw_version
#     "sw_versions": [<str>, ...],       # distinct non-base sw_versions,
#                                        # ordered oldest -> newest
#     "target_sw_version": <str|null>,   # highest non-base sw_version
#     "target_release_id": <str|null>,   # product release to pass to USM
#                                        # deploy start; USM resolves lower
#                                        # releases as dependencies
#     "patches": [                       # per-release detail
#        {"release_id": <str>, "sw_version": <str>, "reboot_required": <bool>},
#        ...
#     ]
#   }
#
# On empty/unpatched backups "backup_patched" is false and the lists are empty.

from argparse import ArgumentParser
from functools import lru_cache
import json
import subprocess

import defusedxml.ElementTree as ET

# The backup is compressed with pigz (same as the rest of the B&R tooling).
TAR_CMD = ["tar", "--use-compress-program=pigz"]

# Product metadata lives directly under this directory (one file per product
# release). The per-metapackage metadata lives in state subdirectories such as
# "deployed/" and is intentionally NOT read here (different id namespace).
METADATA_GLOB = "opt/software/releases/metadata/*.xml"


@lru_cache(maxsize=None)
def _read_member(backup_data, path):
    """Read a single member file out of the backup tar."""
    return subprocess.check_output(
        TAR_CMD + ["-Oxf", backup_data, path],
        text=True,
        stderr=subprocess.DEVNULL,
    )


def _list_product_metadata(backup_data):
    """List top-level product metadata member paths in the backup tar.

    The glob only matches files directly under metadata/, not the per-state
    subdirectories (deployed/, committed/, ...), which hold metapackage
    metadata in a different id namespace.
    """
    result = subprocess.run(
        TAR_CMD + ["--wildcards", "-tf", backup_data, METADATA_GLOB],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _version_tuple(sw_version):
    """Convert a dotted sw_version string into a sortable integer tuple."""
    return tuple(int(part) for part in sw_version.split("."))


def _parse_product(xml_text):
    """Extract product fields from product metadata XML.

    Returns (release_id, sw_version, reboot_required, metapackages) where
    metapackages is the list of component names the product installs. Returns
    (None, None, False, []) when the document is not a <product> (e.g. a stray
    non-product metadata file), so the caller can skip it.

    reboot_required here is only the product's own flag; a product's effective
    RR also depends on its metapackages (see _metapackages_reboot_required),
    because a test/patch product may omit the flag while a metapackage sets it.
    """
    root = ET.fromstring(xml_text)
    if root.tag != "product":
        return None, None, False, []
    release_id_node = root.find("./id")
    sw_version_node = root.find("./sw_version")
    reboot_node = root.find("./reboot_required")
    release_id = release_id_node.text if release_id_node is not None else None
    sw_version = sw_version_node.text if sw_version_node is not None else None
    reboot_required = (
        reboot_node is not None and (reboot_node.text or "").strip() == "Y"
    )
    metapackages = [
        pkg.text.strip()
        for pkg in root.findall("./metapackages/pkg")
        if pkg.text and pkg.text.strip()
    ]
    return release_id, sw_version, reboot_required, metapackages


def _metapackage_reboot_required(xml_text):
    """Return whether a metapackage metadata document is reboot-required."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return False
    reboot_node = root.find("./reboot_required")
    return reboot_node is not None and (reboot_node.text or "").strip() == "Y"


def _product_reboot_required(backup_data, product_reboot, sw_version, metapackages):
    """Determine a product's effective reboot_required.

    True if the product itself is flagged reboot-required, or if any of its
    metapackages (metadata under metadata/deployed/<pkg>_<sw_version>.xml) is.
    A test/patch product can omit <reboot_required> while a metapackage
    (e.g. infra) sets it, so the metapackages must be consulted.
    """
    if product_reboot:
        return True
    for pkg in metapackages:
        path = (
            "opt/software/releases/metadata/deployed/"
            "%s_%s-metadata.xml" % (pkg, sw_version)
        )
        try:
            if _metapackage_reboot_required(_read_member(backup_data, path)):
                return True
        except subprocess.CalledProcessError:
            # The metapackage metadata is not in the backup; treat as non-RR.
            continue
    return False


def collect_backup_patches(backup_data):
    """Build the patch selection info from a subcloud platform backup."""
    result = {
        "backup_patched": False,
        "reboot_required": False,
        "release_ids": [],
        "sw_versions": [],
        "target_sw_version": None,
        "target_release_id": None,
        "patches": [],
    }

    entries = []
    for path in _list_product_metadata(backup_data):
        release_id, sw_version, product_reboot, metapackages = _parse_product(
            _read_member(backup_data, path)
        )
        if release_id and sw_version:
            entries.append(
                {
                    "release_id": release_id,
                    "sw_version": sw_version,
                    "reboot_required": _product_reboot_required(
                        backup_data, product_reboot, sw_version, metapackages
                    ),
                }
            )

    if not entries:
        return result

    # The base ISO product is the lowest sw_version. Everything above it is a
    # layered patch that must be re-applied.
    all_versions = sorted({e["sw_version"] for e in entries}, key=_version_tuple)
    base_version = all_versions[0]
    patches = [e for e in entries if e["sw_version"] != base_version]
    # Sort deterministically by (sw_version, release_id) so the ordering does
    # not depend on the tar listing order. release_ids therefore has a stable
    # order and target_release_id below is deterministic.
    patches.sort(key=lambda e: (_version_tuple(e["sw_version"]), e["release_id"]))

    if not patches:
        return result

    result["backup_patched"] = True
    result["patches"] = patches
    result["release_ids"] = [e["release_id"] for e in patches]
    result["sw_versions"] = sorted(
        {e["sw_version"] for e in patches}, key=_version_tuple
    )
    result["target_sw_version"] = result["sw_versions"][-1]
    # The deploy target is the product release at the highest sw_version. USM
    # resolves and deploys the required lower releases as dependencies from this
    # single target (see common/usm-deploy-releases "deploy start"). Among
    # products that share the highest version, pick the last by the
    # deterministic sort.
    target_patches = [
        e for e in patches if e["sw_version"] == result["target_sw_version"]
    ]
    result["target_release_id"] = target_patches[-1]["release_id"]
    result["reboot_required"] = any(e["reboot_required"] for e in patches)
    return result


def main(argv=None):
    parser = ArgumentParser(
        description="Emit the non-base product patches from a subcloud backup."
    )
    parser.add_argument("backup_data", help="Path to the platform backup tar")
    args = parser.parse_args(argv)
    return collect_backup_patches(args.backup_data)


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
