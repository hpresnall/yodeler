# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import unittest
import os.path
import tempfile

import config.site as site
import role.roles as role


class TestSite(unittest.TestCase):
    _base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def test_load_none_site_path(self):
        with self.assertRaises(ValueError):
            site.load(None)

    def test_load_empty_site_path(self):
        with self.assertRaises(ValueError):
            site.load("")

    def test_load_config_str(self):
        with self.assertRaises(ValueError):
            site.validate("")

    def test_load_config_none(self):
        with self.assertRaises(ValueError):
            site.validate(None)

    def test_load_config_no_name(self):
        with self.assertRaises(ValueError):
            site.validate({})

    def test_load_config_nonstr_name(self):
        with self.assertRaises(KeyError):
            site.validate({"site_name": 0})

    def test_load_config_empty_name(self):
        with self.assertRaises(KeyError):
            site.validate({"site_name": ""})

    def test_load_test_site(self):
        site_cfg = site.load(os.path.join(self._base_path, "sites", "test"))

        self.assertEqual(site_cfg["site_name"], "test")
        self.assertIsNotNone(site_cfg["hosts"])

        roles = site_cfg["roles_to_hostnames"]
        self.assertIsNotNone(roles)
        self.assertEqual(12, len(roles))
        self.assertIn("router", roles)
        self.assertIn("dns", roles)
        self.assertIn("dhcp", roles)
        self.assertIn("ntp", roles)
        self.assertIn("xwindows", roles)
        self.assertIn("build", roles)
        self.assertIn("storage", roles)
        self.assertIn("metrics", roles)
        self.assertIn("test", roles)
        self.assertEqual(["router"], roles["router"])

        host_cfgs = site_cfg["hosts"]
        self.assertEqual(5, len(host_cfgs))
        self.assertIn("server", host_cfgs.keys())
        self.assertIn("client", host_cfgs.keys())
        self.assertIn("vmhost", host_cfgs.keys())
        self.assertIn("dns", host_cfgs.keys())
        self.assertIn("router", host_cfgs.keys())

    def test_write_host_config(self):
        with tempfile.TemporaryDirectory() as config_dir:
            site_cfg = site.load(os.path.join(self._base_path, "sites", "test"))

            site.write_host_scripts(site_cfg, config_dir)

            for host_cfg in site_cfg["hosts"].values():
                hostname = host_cfg["hostname"]

                host_dir = os.path.join(config_dir, site_cfg["site_name"], hostname)

                self.assertTrue(os.path.isdir(host_dir))

                required_files = ["yodel.sh", "setup.sh", "hosts", "interfaces",
                                  "resolv.conf.head", "chrony.conf", "packages"]
                required_dirs = []

                if hostname == "router":
                    required_files.append("dhcpcd.conf")
                    self.assertIn("firewall", host_cfg["aliases"])
                    self.assertNotIn("test", host_cfg["aliases"])
                    # alphabetical ordering of hosts => router before server so router is test1
                    self.assertIn("test1", host_cfg["aliases"])

                if hostname == "server":
                    required_files.remove("resolv.conf.head")  # completely dynamic config => no resolv.conf
                    self.assertNotIn("test", host_cfg["aliases"])
                    self.assertIn("test2", host_cfg["aliases"])

                if hostname == "client":
                    self.assertIn("laptop", host_cfg["aliases"])
                    required_files.remove("resolv.conf.head")

                if host_cfg["local_firewall"]:
                    required_dirs.append("awall")

                if host_cfg["is_vm"]:
                    required_files.extend(["start_vm.sh", "delete_vm.sh", hostname + ".xml"])
                else:
                    required_files.append("answerfile")

                for path in required_files:
                    self.assertTrue(
                        os.path.isfile(os.path.join(host_dir, path)),
                        f"{host_dir}/{path} not created for {hostname}")

                for path in required_dirs:
                    self.assertTrue(
                        os.path.isdir(os.path.join(host_dir, path)),
                        f"{path} directory not created for {hostname}")
