# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import unittest
import os.path
import tempfile

import config.site as site
import util.file as config

class TestSetup(unittest.TestCase):
    _base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_load_site(self):
        site_cfg = site.load_site(
            os.path.join(self._base_path, "sites", "test"))

        self.assertEqual(site_cfg["site"], "test")
        self.assertIsNotNone(site_cfg["hosts"])

        roles = site_cfg["roles_to_hostnames"]
        self.assertIsNotNone(roles)
        self.assertEqual(2, len(roles))
        self.assertIn("router", roles)
        self.assertIn("dns", roles)
        self.assertEqual("router.test.site.example", roles["router"])

        host_cfgs = site_cfg["hosts"]
        self.assertEqual(4, len(host_cfgs))
        self.assertIn("server", host_cfgs.keys())
        self.assertIn("vmhost", host_cfgs.keys())
        self.assertIn("dns", host_cfgs.keys())
        self.assertIn("router", host_cfgs.keys())

    def test_write_host_config(self):
        with tempfile.TemporaryDirectory() as config_dir:
            site_cfg = site.load_site(os.path.join(
                self._base_path, "sites", "test"))

            site.write_host_configs(site_cfg, config_dir)

            for host_cfg in site_cfg["hosts"].values():
                hostname = host_cfg["hostname"]

                host_dir = os.path.join(config_dir, hostname)
                self.assertTrue(os.path.isdir(host_dir))

                required_files = ["setup.sh", "common.sh", "hosts", "interfaces",
                                  "resolv.conf", "dhcpcd.conf", "chrony.conf", "packages"]
                required_dirs = []

                if host_cfg["local_firewall"]:
                    required_dirs.append("awall")

                if host_cfg["is_vm"]:
                    required_files.extend(
                        ["create_vm.sh", "delete_vm.sh", hostname + ".xml"])
                else:
                    required_files.extend(["create_physical.sh", "answerfile"])

                for path in required_files:
                    self.assertTrue(
                        os.path.isfile(os.path.join(host_dir, path)),
                        f"{path} not created for {hostname}")

                for path in required_dirs:
                    self.assertTrue(
                        os.path.isdir(os.path.join(host_dir, path)),
                        f"{path} directory not created for {hostname}")
