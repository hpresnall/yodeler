# pylint: disable=missing-module-docstring
import unittest

import logging

import os.path
import copy

import util.file as file

import config.site as site
import config.host as host


class TestCfgBase(unittest.TestCase):
    """Base class for testing Yodler configuration functions."""
    _base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def __init__(self, methodName: str) -> None:
        super().__init__(methodName)

        self._site_yaml: dict
        self._host_yaml: dict

        self._site_cfg: dict
        self._host_cfg: dict

    @classmethod
    def setUpClass(cls):
        logging.basicConfig(level="ERROR")

        cls._site_yaml = file.load_yaml(os.path.join(cls._base_path, "sites", "minimal.yaml"))

    def setUp(self):
        # minimal yaml has all; split up into site and host parts

        # note site.validate works in place; no need for separate _cfg and _yaml
        self._site_yaml = copy.deepcopy(self._site_yaml)
        self._host_yaml = copy.deepcopy(self._site_yaml)

        del self._site_yaml["interfaces"]
        del self._site_yaml["hostname"]
        del self._host_yaml["vswitches"]
        del self._host_yaml["public_ssh_key"]

    def tearDown(self):
        self._site_yaml = {}
        self._host_yaml = {}
        self._site_cfg = {}
        self._host_cfg = {}

    def build_cfg(self):
        """Build the current configuration. No exceptions will indicate a successful test."""

        self._site_cfg = site.validate(self._site_yaml)
        self._host_cfg = host.validate(self._site_cfg, self._host_yaml)

        return self._host_cfg

    def build_error(self):
        """Build the current configuration, assuming it will error."""
        with self.assertRaises((KeyError, ValueError)):
            self.build_cfg()
