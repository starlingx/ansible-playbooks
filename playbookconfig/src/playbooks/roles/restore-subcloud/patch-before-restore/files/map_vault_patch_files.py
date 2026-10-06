#!/usr/bin/env python3
#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Map a set of software release ids to their patch files in the system
# controller software vault (/opt/dc-vault/software/<version>/).
#
# The patch-before-restore role reads the backup's deployed patch release ids
# (see get_backup_patches.py) and must locate the matching .patch files on the
# system controller so they can be uploaded to the subcloud and deployed. A
# .patch file embeds its release id in metadata.tar -> metadata.xml -> <id>,
# which is the same extraction used by the enrollment patch tooling.
#
# Given a vault directory and a comma-separated list of required release ids,
# emit JSON:
#   {
#     "patch_files": [<basename>, ...],   # files for the required release ids,
#                                         # in the SAME order as --release-ids
#     "missing": [<release_id>, ...]      # required ids with no vault file
#   }
#
# A non-empty "missing" list means the vault is incomplete; the caller is
# expected to fail with an actionable message.

from argparse import ArgumentParser
import glob
import json
import os
import tarfile

import defusedxml.ElementTree as ET


def extract_release_id(patch_file):
    """Return the release id embedded in a .patch file, or None."""
    try:
        with tarfile.open(patch_file, "r") as tar:
            metadata_tar = tar.extractfile("metadata.tar")
            if metadata_tar is None:
                return None
            with tarfile.open(fileobj=metadata_tar, mode="r") as meta_tar:
                metadata_xml = meta_tar.extractfile("metadata.xml")
                if metadata_xml is None:
                    return None
                root = ET.parse(metadata_xml).getroot()
                node = root.find("id")
                return node.text if node is not None else None
    except (tarfile.TarError, OSError, ET.ParseError):
        return None


def build_vault_mapping(vault_dir):
    """Map release id -> patch file basename for every .patch in the vault."""
    mapping = {}
    for patch_file in glob.glob(os.path.join(vault_dir, "*.patch")):
        release_id = extract_release_id(patch_file)
        if release_id:
            mapping[release_id] = os.path.basename(patch_file)
    return mapping


def resolve(vault_dir, release_ids):
    """Resolve required release ids to vault patch files, preserving order."""
    mapping = build_vault_mapping(vault_dir)
    patch_files = []
    missing = []
    for release_id in release_ids:
        filename = mapping.get(release_id)
        if filename is None:
            missing.append(release_id)
        else:
            patch_files.append(filename)
    return {"patch_files": patch_files, "missing": missing}


def main(argv=None):
    parser = ArgumentParser(
        description="Resolve release ids to patch files in the software vault."
    )
    parser.add_argument(
        "vault_dir", help="Vault dir, e.g. /opt/dc-vault/software/XX.YY"
    )
    parser.add_argument(
        "--release-ids",
        default="",
        help="Comma-separated release ids to resolve, in apply order",
    )
    args = parser.parse_args(argv)
    release_ids = [r for r in args.release_ids.split(",") if r]
    return resolve(args.vault_dir, release_ids)


if __name__ == "__main__":
    print(json.dumps(main()))
