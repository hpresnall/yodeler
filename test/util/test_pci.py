# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import unittest

import util.pci


class TestPCI(unittest.TestCase):
    def test_valid(self):
        bus, slot, function = util.pci.split("1A:2B.C", "test")
        self.assertEqual(0x1A, bus)
        self.assertEqual(0x2B, slot)
        self.assertEqual(0xC, function)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            util.pci.split("foo", "test")
    
    def test_none(self):
        with self.assertRaises(ValueError):
            util.pci.split(None, "test")  # type: ignore

    def test_empty(self):
        with self.assertRaises(ValueError):
            util.pci.split("", "test")  # type: ignore