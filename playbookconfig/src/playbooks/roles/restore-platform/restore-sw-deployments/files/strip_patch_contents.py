#!/usr/bin/env python3
#
# Copyright (c) 2024 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from argparse import ArgumentParser
import defusedxml.ElementTree as ET


def strip_patch_contents(patch_xml_path):
    """Remove contents from an a patch.

    During restore, available patches will have contents from when they were deployed.
    These need to be removed to keep the metadata valid.
    """

    xtree = ET.parse(patch_xml_path)
    xroot = xtree.getroot()
    xnode = xroot.find("./contents")
    xroot.remove(xnode)
    xtree.write(patch_xml_path)


def main(argv=None):
    parser = ArgumentParser()
    parser.add_argument("patch_xml_path")
    args = parser.parse_args(argv)
    strip_patch_contents(args.patch_xml_path)


if __name__ == "__main__":
    main()
