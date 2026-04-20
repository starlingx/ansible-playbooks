#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Integration tests for project structure and configs."""

import os
import unittest

import yaml


PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


def _read(path):
    """Read file content relative to PROJECT_ROOT."""
    with open(os.path.join(PROJECT_ROOT, path)) as f:
        return f.read()


class TestProjectStructure(unittest.TestCase):
    """Validate project file structure."""

    EXPECTED_FILES = [
        "tox.ini", ".zuul.yaml", "LICENSE", "README.rst",
        "requirements-bullseye.txt", "requirements-trixie.txt",
        "test-requirements-bullseye.txt", "test-requirements-trixie.txt",
    ]
    EXPECTED_DIRS = [
        "playbookconfig",
        os.path.join("playbookconfig", "src", "playbooks"),
        os.path.join("playbookconfig", "src", "playbooks", "roles"),
    ]

    def test_expected_files_exist(self):
        """Test all expected project files exist."""
        for fname in self.EXPECTED_FILES:
            path = os.path.join(PROJECT_ROOT, fname)
            self.assertTrue(os.path.isfile(path), f"Missing: {fname}")

    def test_expected_dirs_exist(self):
        """Test all expected directories exist."""
        for dname in self.EXPECTED_DIRS:
            path = os.path.join(PROJECT_ROOT, dname)
            self.assertTrue(os.path.isdir(path), f"Missing: {dname}")


class TestYamlLintConfig(unittest.TestCase):
    """Validate yamllint configuration."""

    @classmethod
    def setUpClass(cls):
        """Load yamllint config once."""
        with open(os.path.join(PROJECT_ROOT, ".yamllint")) as f:
            cls.config = yaml.safe_load(f)

    def test_yamllint_config_valid(self):
        """Test .yamllint has rules."""
        self.assertIn("rules", self.config)

    def test_yamllint_line_length(self):
        """Test yamllint line-length rule."""
        self.assertIn("line-length", self.config["rules"])


class TestAnsibleLintConfig(unittest.TestCase):
    """Validate ansible-lint configuration."""

    @classmethod
    def setUpClass(cls):
        """Load ansible-lint config once."""
        with open(os.path.join(PROJECT_ROOT, ".ansible-lint")) as f:
            cls.config = yaml.safe_load(f)

    def test_ansible_lint_config_valid(self):
        """Test .ansible-lint has skip_list."""
        self.assertIn("skip_list", self.config)

    def test_ansible_lint_uses_default_rules(self):
        """Test ansible-lint uses default rules."""
        self.assertTrue(self.config.get("use_default_rules"))


class TestZuulConfig(unittest.TestCase):
    """Validate .zuul.yaml configuration."""

    @classmethod
    def setUpClass(cls):
        """Load zuul config once."""
        cls.content = _read(".zuul.yaml")

    EXPECTED_CONTENT = [
        "- project:", "check:", "gate:",
        "ansible-playbooks-tox-coverage",
        "ansible-playbooks-tox-bandit",
        "ansible-playbooks-tox-coverage-trixie",
        "ansible-playbooks-tox-bandit-trixie",
        "ansible-playbooks-tox-linters-trixie",
        "ansible-playbooks-tox-pep8-trixie",
    ]

    def test_zuul_yaml_not_empty(self):
        """Test .zuul.yaml is not empty."""
        self.assertGreater(len(self.content), 0)

    def test_zuul_has_expected_content(self):
        """Test .zuul.yaml contains all expected sections."""
        for expected in self.EXPECTED_CONTENT:
            self.assertIn(expected, self.content)


class TestToxConfig(unittest.TestCase):
    """Validate tox.ini configuration."""

    @classmethod
    def setUpClass(cls):
        """Load tox.ini once."""
        cls.content = _read("tox.ini")

    EXPECTED_ENVS = [
        "[testenv:linters]", "[testenv:pep8]",
        "[testenv:bandit]", "[testenv:coverage]",
        "[testenv:coverage-trixie]", "[testenv:bandit-trixie]",
        "[testenv:linters-trixie]", "[testenv:pep8-trixie]",
    ]

    def test_tox_ini_has_all_environments(self):
        """Test tox.ini has all expected environments."""
        for env in self.EXPECTED_ENVS:
            self.assertIn(env, self.content)


class TestPythonSourceFiles(unittest.TestCase):
    """Validate Python source files are syntactically correct."""

    @classmethod
    def setUpClass(cls):
        """Collect all Python source files."""
        cls.py_files = []
        roles_dir = os.path.join(
            PROJECT_ROOT, "playbookconfig", "src", "playbooks", "roles"
        )
        for root, dirs, files in os.walk(roles_dir):
            if ".tox" in root:
                continue
            for f in files:
                if f.endswith(".py") and not f.startswith("test_"):
                    cls.py_files.append(os.path.join(root, f))

    def test_python_files_exist(self):
        """Test that Python source files exist."""
        self.assertGreater(len(self.py_files), 0)

    def test_python_files_syntax(self):
        """Test Python files have valid syntax."""
        import py_compile
        for py_file in self.py_files:
            try:
                py_compile.compile(py_file, doraise=True)
            except py_compile.PyCompileError:
                self.fail(f"Syntax error in {py_file}")


class TestShellScripts(unittest.TestCase):
    """Validate shell scripts exist and have shebangs."""

    def test_shell_scripts_have_shebang(self):
        """Test shell scripts start with shebang."""
        roles_dir = os.path.join(
            PROJECT_ROOT, "playbookconfig", "src", "playbooks", "roles"
        )
        for root, dirs, files in os.walk(roles_dir):
            for f in files:
                if f.endswith(".sh"):
                    path = os.path.join(root, f)
                    with open(path) as fh:
                        first_line = fh.readline()
                    self.assertTrue(
                        first_line.startswith("#!"),
                        f"Missing shebang in {path}",
                    )


class TestPlaybookYamlFiles(unittest.TestCase):
    """Validate playbook YAML files are parseable."""

    def test_top_level_playbooks_valid_yaml(self):
        """Test top-level playbook YAML files are valid."""
        playbooks_dir = os.path.join(
            PROJECT_ROOT, "playbookconfig", "src", "playbooks"
        )
        for f in os.listdir(playbooks_dir):
            if not f.endswith((".yml", ".yaml")):
                continue
            path = os.path.join(playbooks_dir, f)
            with open(path) as fh:
                content = fh.read()
            if "!encrypted" in content or "{{" in content:
                continue
            try:
                yaml.safe_load(content)
            except yaml.YAMLError:
                self.fail(f"Invalid YAML: {path}")


if __name__ == "__main__":
    unittest.main()
