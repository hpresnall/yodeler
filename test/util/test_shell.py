# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import unittest

import script.shell as shell


class TestShell(unittest.TestCase):
    def test_none_name(self):
        with self.assertRaises(ValueError):
            shell.ShellScript(None)  # type: ignore

    def test_empty_name(self):
        with self.assertRaises(ValueError):
            shell.ShellScript("")
