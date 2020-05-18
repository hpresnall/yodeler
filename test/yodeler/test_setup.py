import unittest
import os.path
import tempfile

import yodeler.setup as setup


class TestSetup(unittest.TestCase):
    _base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_load_all_configs(self):
        host_cfgs = setup.load_all_configs(os.path.join(self._base_path, "sites"), "test")

        self.assertEqual(1, len(host_cfgs))
        self.assertIn("server", host_cfgs.keys())

    def test_create_scripts_for_host(self):
        with tempfile.TemporaryDirectory() as config_dir:
            host_cfgs = setup.load_all_configs(os.path.join(self._base_path, "sites"), "test")

            for host_cfg in host_cfgs.values():
                hostname = host_cfg["hostname"]
                setup.create_scripts_for_host(host_cfg, config_dir)

                host_dir = os.path.join(config_dir, hostname)
                self.assertTrue(os.path.isdir(host_dir))
                self.assertTrue(os.path.isdir(os.path.join(host_dir, "awall")))

                for path in ["setup.sh",
                             "common.sh",
                             "hosts",
                             "interfaces",
                             "dhclient.conf",
                             "chrony.conf",
                             "resolv.conf.head",
                             hostname + ".xml"]:
                    self.assertTrue(os.path.isfile(os.path.join(host_dir, path)), path + " not created")
