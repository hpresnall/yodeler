# pylint: disable=missing-module-docstring
import unittest

import logging

import os.path
import copy

import util.file

import config.site
import config.host


class TestCfgBase(unittest.TestCase):
    """Base class for testing Yodler configuration functions."""
    _base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(level="ERROR")

        cls._site_cfg = config.site.load(os.path.join(cls._base_path, "sites/minimal"))

    def setUp(self):
        self._site_cfg = copy.deepcopy(self._site_cfg)
        self._cfg_dict = {}

    def tearDown(self):
        self._site_cfg = None
        self._cfg_dict = None

    def build_cfg(self):
        """Build the current configuration. This should not error."""
        return config.host.load_from_dict(self._site_cfg, self._cfg_dict)

    def build_error(self):
        """Build the current configuration, assuming it will error."""
        with self.assertRaises(KeyError):
            self.build_cfg()
