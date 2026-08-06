#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

"""Unit tests for parse_dual_stack module."""

import sys
import unittest
from io import StringIO


class ParseDualStackTestBase(unittest.TestCase):
    """Base class that loads parse_dual_stack once per class."""

    mod = None

    def setUp(self):
        """Import parse_dual_stack module (cached at class level)."""
        if self.__class__.mod is None:
            import parse_dual_stack as mod
            self.__class__.mod = mod


class TestIsCidr(ParseDualStackTestBase):
    """Tests for is_valid_cidr function."""

    def test_valid_ipv4_cidr(self):
        self.assertTrue(self.mod.is_valid_cidr("192.168.1.0/24"))

    def test_valid_ipv6_cidr(self):
        self.assertTrue(self.mod.is_valid_cidr("fd00::/64"))

    def test_invalid_cidr_no_prefix(self):
        self.assertFalse(self.mod.is_valid_cidr("192.168.1.0"))

    def test_invalid_cidr_empty_prefix(self):
        self.assertFalse(self.mod.is_valid_cidr("192.168.1.0/"))

    def test_invalid_cidr_garbage(self):
        self.assertFalse(self.mod.is_valid_cidr("not_a_cidr"))

    def test_valid_cidr_slash_32(self):
        """Test /32 CIDR."""
        self.assertTrue(self.mod.is_valid_cidr("10.0.0.1/32"))

    def test_valid_cidr_slash_0(self):
        """Test /0 CIDR."""
        self.assertTrue(self.mod.is_valid_cidr("0.0.0.0/0"))


class TestIsValidIpv4(ParseDualStackTestBase):
    """Tests for is_valid_ipv4 function."""

    def test_valid_ipv4(self):
        self.assertTrue(self.mod.is_valid_ipv4("192.168.1.1"))

    def test_invalid_ipv4(self):
        self.assertFalse(self.mod.is_valid_ipv4("999.999.999.999"))

    def test_ipv6_as_ipv4(self):
        self.assertFalse(self.mod.is_valid_ipv4("fd00::1"))

    def test_empty_string(self):
        self.assertFalse(self.mod.is_valid_ipv4(""))

    def test_loopback(self):
        self.assertTrue(self.mod.is_valid_ipv4("127.0.0.1"))


class TestIsValidIpv6(ParseDualStackTestBase):
    """Tests for is_valid_ipv6 function."""

    def test_valid_ipv6(self):
        self.assertTrue(self.mod.is_valid_ipv6("fd00::1"))

    def test_invalid_ipv6(self):
        self.assertFalse(self.mod.is_valid_ipv6("not_ipv6"))

    def test_ipv4_as_ipv6(self):
        self.assertFalse(self.mod.is_valid_ipv6("192.168.1.1"))

    def test_full_ipv6(self):
        self.assertTrue(
            self.mod.is_valid_ipv6(
                "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
            )
        )

    def test_loopback_ipv6(self):
        self.assertTrue(self.mod.is_valid_ipv6("::1"))


class TestIsValidIpv6Cidr(ParseDualStackTestBase):
    """Tests for is_valid_ipv6_cidr function."""

    def test_valid_ipv6_cidr(self):
        self.assertTrue(self.mod.is_valid_ipv6_cidr("fd00::/64"))

    def test_invalid_ipv6_cidr(self):
        self.assertFalse(self.mod.is_valid_ipv6_cidr("garbage/64"))


class TestGetFamily(ParseDualStackTestBase):
    """Tests for get_family_of_address and get_family_of_cidr."""

    def test_family_ipv4_address(self):
        self.assertEqual(
            self.mod.get_family_of_address("10.0.0.1"), "ipv4"
        )

    def test_family_ipv6_address(self):
        self.assertEqual(
            self.mod.get_family_of_address("fd00::1"), "ipv6"
        )

    def test_family_invalid_address(self):
        with self.assertRaises(ValueError):
            self.mod.get_family_of_address("invalid")

    def test_family_ipv4_cidr(self):
        self.assertEqual(
            self.mod.get_family_of_cidr("192.168.0.0/24"), "ipv4"
        )

    def test_family_ipv6_cidr(self):
        self.assertEqual(
            self.mod.get_family_of_cidr("fd00::/64"), "ipv6"
        )

    def test_family_invalid_cidr(self):
        with self.assertRaises(ValueError):
            self.mod.get_family_of_cidr("invalid")


class TestValidate(ParseDualStackTestBase):
    """Tests for validate function."""

    def _validate_capture(self, value):
        """Run validate and capture stdout.

        :param value: input to validate
        :returns: stdout output string
        """
        captured = StringIO()
        sys.stdout = captured
        self.mod.validate(value)
        sys.stdout = sys.__stdout__
        return captured.getvalue()

    def test_single_ipv4_cidr(self):
        output = self._validate_capture("192.168.1.0/24")
        self.assertIn("primary=192.168.1.0/24", output)
        self.assertIn("secondary=False", output)

    def test_dual_stack_cidr(self):
        """Test dual-stack CIDR validation."""
        output = self._validate_capture("192.168.1.0/24,fd00::/64")
        self.assertIn("primary=192.168.1.0/24", output)
        self.assertIn("secondary=fd00::/64", output)

    def test_single_ipv4_address(self):
        output = self._validate_capture("192.168.1.1")
        self.assertIn("primary=192.168.1.1", output)
        self.assertIn("secondary=False", output)

    def test_dual_stack_addresses(self):
        """Test dual-stack address validation."""
        output = self._validate_capture("192.168.1.1,fd00::1")
        self.assertIn("primary=192.168.1.1", output)
        self.assertIn("secondary=fd00::1", output)

    def test_same_family_raises(self):
        """Test same IP family dual-stack raises ValueError."""
        with self.assertRaises(ValueError):
            self.mod.validate("192.168.1.0/24,10.0.0.0/8")

    def test_more_than_two_raises(self):
        with self.assertRaises(ValueError):
            self.mod.validate("10.0.0.1,fd00::1,10.0.0.2")

    def test_mixed_cidr_address_raises(self):
        with self.assertRaises(ValueError):
            self.mod.validate("192.168.1.0/24,fd00::1")


class TestValidateDualStackAddressVsSubnet(unittest.TestCase):
    """Tests for validate_dual_stack_address_vs_subnet module."""

    mod = None

    def setUp(self):
        """Import module."""
        if self.__class__.mod is None:
            import validate_dual_stack_address_vs_subnet as mod
            self.__class__.mod = mod

    def test_matching_single_stack(self):
        """Test matching single-stack address and subnet."""
        self.mod.validate("192.168.1.1", "192.168.1.0/24")

    def test_matching_dual_stack(self):
        """Test matching dual-stack address and subnet."""
        self.mod.validate(
            "192.168.1.1,fd00::1", "192.168.1.0/24,fd00::/64"
        )

    def test_mismatched_count_raises(self):
        with self.assertRaises(ValueError):
            self.mod.validate("192.168.1.1", "192.168.1.0/24,fd00::/64")

    def test_mismatched_family_raises(self):
        with self.assertRaises(ValueError):
            self.mod.validate("fd00::1", "192.168.1.0/24")

    def test_get_ip_version_of_network(self):
        self.assertEqual(
            self.mod.get_ip_version_of_network("192.168.0.0/24"), 4
        )
        self.assertEqual(
            self.mod.get_ip_version_of_network("fd00::/64"), 6
        )

    def test_get_ip_version_of_address(self):
        self.assertEqual(
            self.mod.get_ip_version_of_address("10.0.0.1"), 4
        )
        self.assertEqual(self.mod.get_ip_version_of_address("::1"), 6)


if __name__ == "__main__":
    unittest.main()
