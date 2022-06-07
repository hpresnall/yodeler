# pylint: disable=missing-module-docstring
import unittest

import os.path
import copy

import util.file

import config.yaml as yaml


class TestCfgBase(unittest.TestCase):
    """Base class for testing Yodler configuration functions."""
    _base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    @classmethod
    def setUpClass(cls):
        cls._minimal = util.file.load_yaml(
            os.path.join(cls._base_path, "yaml/minimal.yaml"))

    def setUp(self):
        self._cfg_dict = copy.deepcopy(self._minimal)

    def tearDown(self):
        self._cfg_dict = None

    def build_cfg(self):
        """Build the current configuration. This should not error."""
        return yaml.config_from_dict(self._cfg_dict)

    def build_error(self):
        """Build the current configuration, assuming it will error."""
        with self.assertRaises(KeyError):
            self.build_cfg()
