# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import os.path

import test.yodeler.base as base

import yodeler.config as config
import yodeler.vlan


class TestConfig(base.TestCfgBase):
    def test_empty_string(self):
        with self.assertRaises(KeyError):
            config.config_from_string("")

    def test_minimal(self):
        cfg = self.build_cfg()

        # has common role
        self.assertEqual(1, len(cfg["roles"]))
        self.assertEqual("common", cfg["roles"][0].name)

        # has all default config
        for key in config.DEFAULT_CONFIG:
            self.assertIsNotNone(cfg[key])
            self.assertEqual(config.DEFAULT_CONFIG[key], cfg[key])

        # has all default packages
        packages = cfg["packages"]
        for package in config.DEFAULT_PACKAGES:
            self.assertIn(package, packages)

        # default metrics; default is_vm
        self.assertIn("prometheus-node-exporter", packages)
        self.assertIn("libusb", cfg["remove_packages"])

        vswitch = cfg["vswitches"]["public"]

        self.assertIsNotNone(vswitch["vlans_by_name"])
        self.assertIsNotNone(vswitch["vlans_by_id"])
        self.assertEqual(len(vswitch["vlans_by_name"]),
                         len(vswitch["vlans_by_id"]))

        # single vlan
        # default not specified; should default to only vlan
        self.assertEqual("test", vswitch["default_vlan"]["name"])
        self.assertTrue(vswitch["vlans_by_id"][10]["default"])

        # single interface, no domain specified
        self.assertIsNotNone(cfg["primary_domain"])

        # uplinks added from all vswitches
        self.assertIsNotNone(cfg["uplinks"])
        self.assertEqual(1, len(cfg["uplinks"]))

        # has all default vlan config
        vlan = vswitch["vlans_by_id"][10]
        for key in yodeler.vlan.DEFAULT_VLAN_CONFIG:
            self.assertIsNotNone(vlan[key])
            self.assertEqual(yodeler.vlan.DEFAULT_VLAN_CONFIG[key], vlan[key])

        # has interface config
        iface = cfg["interfaces"][0]
        self.assertEqual(10, iface["vlan"]["id"])
        self.assertEqual("PUBLIC", iface["firewall_zone"])
        self.assertEqual("eth0", iface["name"])

        self.assertEqual("static", iface["ipv4_method"])
        self.assertEqual("192.168.1.1", str(iface["ipv4_gateway"]))
        self.assertEqual("255.255.255.0", str(iface["ipv4_netmask"]))

        self.assertEqual("auto", iface["ipv6_method"])
        self.assertEqual(1, iface["ipv6_dhcp"])
        self.assertEqual(64, iface["ipv6_prefixlen"])
        self.assertEqual(1, iface["accept_ra"])
        self.assertEqual(2, iface["privext"])

    def test_site_and_host(self):
        site = config.load_site_config(
            os.path.join(self._base_path, "sites/test"))
        host = config.load_host_config(site, "server")

        # host overwrites site
        self.assertEqual("server", host["motd"])

        # validate merging of packages with overlapping add / remove
        # sanity check package is still in the merged sets
        self.assertIn("both_need", host["packages"])
        self.assertNotIn("both_need", host["remove_packages"])
        self.assertNotIn("both_remove", host["packages"])
        self.assertIn("both_remove", host["remove_packages"])

        # conflicts on either side should not remove
        self.assertIn("site_needs", host["packages"])
        self.assertNotIn("site_needs", host["remove_packages"])

        self.assertIn("server_needs", host["packages"])
        self.assertNotIn("server_needs", host["remove_packages"])

    def test_missing_required(self):
        del self._cfg_dict["site"]
        self.build_error()

    def test_none_site_(self):
        with self.assertRaises(KeyError):
            config.load_host_config(None, "server")

    def test_empty_site(self):
        with self.assertRaises(KeyError):
            config.load_site_config(os.path.join(
                self._base_path, "sites/empty"))

    def test_empty_site_for_host(self):
        site = {}
        with self.assertRaises(KeyError):
            config.load_host_config(site, "server")

    def test_empty_host(self):
        site = config.load_site_config(
            os.path.join(self._base_path, "sites/test"))
        # keep empty host YAML out of working test site
        site["site_dir"] = "test/sites/empty"
        with self.assertRaises(KeyError):
            config.load_host_config(site, "empty")

    def test_invalid_role(self):
        self._cfg_dict["roles"] = ["invalid"]
        self.build_error()

    def test_invalid_role_class(self):
        self._cfg_dict["roles"] = ["role"]
        self.build_error()

    def test_invalid_external_dns(self):
        self._cfg_dict["external_dns"] = ["invalid"]
        self.build_error()

    def test_package_conflict(self):
        self._cfg_dict["packages"] = {"explicit_add", "add"}
        self._cfg_dict["remove_packages"] = {"explicit_add", "remove"}
        cfg = self.build_cfg()

        self.assertIn("explicit_add", cfg["packages"])
        self.assertIn("add", cfg["packages"])

        self.assertNotIn("explicit_add", cfg["remove_packages"])
        self.assertIn("remove", cfg["remove_packages"])

    def test_invalid_local_dns(self):
        self._cfg_dict["local_dns"] = ["invalid"]
        self.build_error()

    def test_no_local_firewall(self):
        self._cfg_dict["local_firewall"] = False
        cfg = self.build_cfg()

        # remove iptables when no firewall
        self.assertIn("iptables", cfg["remove_packages"])
        self.assertIn("ip6tables", cfg["remove_packages"])
