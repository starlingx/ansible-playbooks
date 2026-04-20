#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Base test classes for StarlingX ansible-playbooks tests.

Provides shared setUp patterns, module loading, mock configuration,
temp file management, and stdout capture using OOP/DRY principles.
"""

import os
import sys
import tempfile
import unittest
from io import StringIO  # noqa: H306
from unittest.mock import MagicMock  # noqa: H301
from unittest.mock import patch  # noqa: H301

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
from mock_deps import install_mocks
from test_helpers import load_module
from test_helpers import configure_mock_conf
from test_helpers import create_mock_sysinv_client
from test_helpers import add_role_dirs
from constants import default_bootstrap_config
from constants import OS_ENV_LINES

install_mocks()


class BaseModuleTestCase(unittest.TestCase):
    """Base class for tests that load StarlingX modules.

    Subclasses set role_path, filename, and mod_name
    as class attributes, then access self.module in tests.
    """

    role_path = None
    filename = None
    mod_name = None

    def setUp(self):
        """Load the module under test."""
        if self.role_path and self.filename:
            self.module = load_module(
                self.role_path, self.filename, self.mod_name
            )
            self.m = self.module

    def configure_conf(self, **overrides):
        """Configure module CONF with defaults + overrides."""
        defaults = default_bootstrap_config()
        configure_mock_conf(self.module, defaults, overrides)

    def create_client(self):
        """Create a mock sysinv client."""
        return create_mock_sysinv_client()


class SimpleModuleTestCase(unittest.TestCase):
    """Base for tests that import a single module by name.

    Subclasses set `module_name` class attribute.
    Module is imported once and cached at class level.
    """

    module_name = None
    mod = None

    def setUp(self):
        """Import module (cached at class level)."""
        if self.__class__.mod is None and self.module_name:
            import importlib
            self.__class__.mod = importlib.import_module(
                self.module_name
            )


class DirectImportTestCase(unittest.TestCase):
    """Base for tests that import modules directly from role dirs.

    Subclasses set role_dirs as list of relative paths under ROLES.
    """

    role_dirs = []

    @classmethod
    def setUpClass(cls):
        """Add role directories to sys.path."""
        sys.modules.setdefault("eventlet", MagicMock())
        sys.modules["eventlet"].monkey_patch = lambda **kw: None
        add_role_dirs(cls.role_dirs)


class TempFileTestCase(unittest.TestCase):
    """Base with temp file creation and cleanup helpers."""

    def write_temp(self, content, suffix=".yaml"):
        """Write content to a temp file, return path."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=suffix, delete=False
        ) as f:
            f.write(content)
            return f.name

    def capture_stdout(self, func, *args, **kwargs):
        """Capture stdout from a function call."""
        captured = StringIO()
        sys.stdout = captured
        try:
            result = func(*args, **kwargs)
        finally:
            sys.stdout = sys.__stdout__
        return result, captured.getvalue()

    def capture_both(self, func, *args, **kwargs):
        """Capture stdout and stderr from a function call."""
        out = StringIO()
        err = StringIO()
        sys.stdout = out
        sys.stderr = err
        try:
            result = func(*args, **kwargs)
        finally:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
        return result, out.getvalue(), err.getvalue()


class YamlModuleTestCase(TempFileTestCase):
    """Base for testing YAML-processing modules."""

    def write_yaml_temp(self, data):
        """Write data as YAML to temp file."""
        import yaml
        content = yaml.dump(data, default_flow_style=False)
        return self.write_temp(content)

    def load_yaml_file(self, path):
        """Load YAML from file."""
        import yaml
        with open(path) as f:
            return yaml.safe_load(f)

    def load_yaml_all(self, text):
        """Load all YAML documents from text."""
        import yaml
        return [d for d in yaml.safe_load_all(text) if d]


class Psycopg2MockTestCase(unittest.TestCase):
    """Base for tests that need psycopg2 mock connection setup."""

    def create_mock_connection(self, fetchall_data=None,
                               fetchone_data=None):
        """Create a mock psycopg2 connection with cursor.

        :param fetchall_data: data for cursor.fetchall()
        :param fetchone_data: data for cursor.fetchone()
        :returns: tuple (mock_conn, mock_cur)
        """
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        if fetchall_data is not None:
            mock_cur.fetchall.return_value = fetchall_data
        if fetchone_data is not None:
            mock_cur.fetchone.return_value = fetchone_data
        mock_conn.__enter__ = lambda s: s
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
        mock_conn.cursor.return_value.__exit__ = MagicMock(
            return_value=False
        )
        return mock_conn, mock_cur

    def patch_psycopg2_connect(self, mock_conn):
        """Return a patch context for psycopg2.connect."""
        return patch.object(
            sys.modules["psycopg2"], "connect",
            return_value=mock_conn
        )


class OpenStackClientTestCase(BaseModuleTestCase):
    """Base for tests that exercise OpenStack/Cgts client patterns."""

    def create_env_with_token(self, **extra):
        """Return env dict with OS_TOKEN auth."""
        env = {
            "OS_AUTH_URL": "http://x",
            "OS_TOKEN": "tok",
            "SYSTEM_URL": "http://sys",
        }
        env.update(extra)
        return env

    def create_mock_popen_proc(self, env_lines=None):
        """Create a mock Popen process returning env lines."""
        proc = MagicMock()
        proc.stdout = iter(env_lines or OS_ENV_LINES)
        proc.communicate = MagicMock()
        return proc


class DockerImageTestCase(unittest.TestCase):
    """Base for tests that exercise docker image push/pull patterns."""

    def setUp(self):
        """Set up common docker mock infrastructure."""
        self._setup_docker_mocks()

    def _setup_docker_mocks(self):
        """Override in subclass to set up module-specific mocks."""

    def create_mock_docker_client(self, inspect_result=True,
                                  pull_result=None):
        """Create a mock docker API client."""
        mock_client = MagicMock()
        mock_client.inspect_distribution.return_value = inspect_result
        if pull_result is not None:
            mock_client.pull.return_value = pull_result
        else:
            mock_client.pull.return_value = iter([b'{"status":"ok"}'])
        mock_client.images.return_value = True
        return mock_client
