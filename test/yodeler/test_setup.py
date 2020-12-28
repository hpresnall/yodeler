# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import unittest
import os.path
import tempfile

import yodeler.setup as setup


class TestSetup(unittest.TestCase):
    _base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_load_all_configs(self):
        host_cfgs = setup.load_all_configs(os.path.join(self._base_path, "sites"), "test")

        self.assertEqual(4, len(host_cfgs))
        self.assertIn("server", host_cfgs.keys())
        self.assertIn("vmhost", host_cfgs.keys())
        self.assertIn("dns", host_cfgs.keys())
        self.assertIn("router", host_cfgs.keys())

    def test_create_scripts_for_host(self):
        with tempfile.TemporaryDirectory() as config_dir:
            host_cfgs = setup.load_all_configs(os.path.join(self._base_path, "sites"), "test")

            for host_cfg in host_cfgs.values():
                hostname = host_cfg["hostname"]
                setup.create_scripts_for_host(host_cfg, config_dir)

                host_dir = os.path.join(config_dir, hostname)
                self.assertTrue(os.path.isdir(host_dir))

                required_files = ["setup.sh", "common.sh", "hosts", "interfaces", "dhclient.conf",
                                  "chrony.conf", "packages"]
                required_dirs = []

                if host_cfg["local_firewall"]:
                    required_dirs.append("awall")

                if host_cfg["is_vm"]:
                    required_files.extend(["create_vm.sh",
                                           "delete_vm.sh",
                                           hostname + ".xml",
                                           "resolv.conf"])
                # resolv.conf not in vmhost because initial interface is dhcp
                else:
                    required_files.extend(["bootstrap.sh",
                                           "install_alpine.sh",
                                           "answerfile",
                                           "setup.start",
                                           "finalize_network.sh",
                                           "interfaces.final",
                                           "resolv.conf.final"])
                    required_dirs.append("awall.final")

                for path in required_files:
                    self.assertTrue(
                        os.path.isfile(os.path.join(host_dir, path)),
                        f"{path} not created for {hostname}")

                for path in required_dirs:
                    self.assertTrue(
                        os.path.isdir(os.path.join(host_dir, path)),
                        f"{path} directory not created for {hostname}")
