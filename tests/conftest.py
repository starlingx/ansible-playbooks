#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Shared test fixtures for ansible-playbooks test suite."""

import os
import sys
import tempfile

import pytest


@pytest.fixture
def project_root():
    """Return the project root directory.

    :returns: absolute path to the project root
    :rtype: str
    """
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def tmp_dir():
    """Provide a temporary directory for test artifacts.

    :returns: path to a temporary directory
    :rtype: str
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def tmp_yaml_file(tmp_dir):
    """Create a temporary YAML file.

    :param tmp_dir: path to temporary directory
    :returns: function that writes content to a YAML file
    :rtype: callable
    """

    def _create(content, name="test.yaml"):
        filepath = os.path.join(tmp_dir, name)
        with open(filepath, "w") as file_handle:
            file_handle.write(content)
        return filepath

    return _create


@pytest.fixture
def tmp_ini_file(tmp_dir):
    """Create a temporary INI config file.

    :param tmp_dir: path to temporary directory
    :returns: function that writes content to an INI file
    :rtype: callable
    """

    def _create(content, name="test.ini"):
        filepath = os.path.join(tmp_dir, name)
        with open(filepath, "w") as file_handle:
            file_handle.write(content)
        return filepath

    return _create


@pytest.fixture(autouse=True)
def add_src_to_path(project_root):
    """Add source directories to sys.path for imports.

    :param project_root: absolute path to project root
    :returns: None (yields for teardown)
    """
    roles_base = os.path.join(
        project_root, "playbookconfig", "src", "playbooks", "roles"
    )
    added_paths = []
    for root, dirs, files in os.walk(roles_base):
        if any(f.endswith(".py") for f in files):
            if root not in sys.path:
                sys.path.insert(0, root)
                added_paths.append(root)
    yield
    for path in added_paths:
        if path in sys.path:
            sys.path.remove(path)
