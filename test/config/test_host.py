# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import os.path

import copy

import test.config.base as base

import config.site as site
import config.host as host

import config.vlan


class TestHost(base.TestCfgBase):
    def test_load_none_host_path(self):
        with self.assertRaises(ValueError):
            host.load(site.validate(self._site_yaml), None)

    def test_load_empty_host_path(self):
        with self.assertRaises(ValueError):
            host.load(site.validate(self._site_yaml), "")

    def test_load_config_str(self):
        with self.assertRaises(ValueError):
            host.validate(site.validate(self._site_yaml), "")

    def test_load_config_none(self):
        with self.assertRaises(ValueError):
            host.validate(site.validate(self._site_yaml), None)

    def test_load_config_no_hostname(self):
        with self.assertRaises(KeyError):
            host.validate(site.validate(self._site_yaml), {"value": 0})

    def test_load_config_nonstr_hostname(self):
        with self.assertRaises(KeyError):
            host.validate(site.validate(self._site_yaml), {"hostname": 0})

    def test_load_config_empty_hostname(self):
        with self.assertRaises(KeyError):
            host.validate(site.validate(self._site_yaml), {"hostname": ""})

    def test_validate_none_site(self):
        with self.assertRaises(ValueError):
            host.validate(None, self._host_yaml)

    def test_validate_non_dict_site(self):
        with self.assertRaises(ValueError):
            host.validate("invalid", self._host_yaml)

    def test_validate_empty_site(self):
        with self.assertRaises(ValueError):
            host.validate({}, self._host_yaml)

    def test_validate_empty_host(self):
        with self.assertRaises(ValueError):
            host.validate(site.validate(self._site_yaml), {})

    def test_validate_duplicate_host(self):
        duplicate = copy.deepcopy(self._host_yaml)

        self.build_cfg()

        with self.assertRaises(ValueError):
            host.validate(self._site_cfg, duplicate)

    def test_minimal(self):
        cfg = self.build_cfg()

        # has common role
        self.assertEqual(1, len(cfg["roles"]))
        self.assertEqual("common", cfg["roles"][0].name)

        # has all default config
        for key in site.DEFAULT_CONFIG:
            self.assertIsNotNone(cfg[key])
            self.assertEqual(site.DEFAULT_CONFIG[key], cfg[key])
        for key in host.DEFAULT_CONFIG:
            self.assertIsNotNone(cfg[key])
            self.assertEqual(host.DEFAULT_CONFIG[key], cfg[key])

        # has all default packages
        packages = cfg["packages"]
        self.assertIsNotNone(packages)
        self.assertEqual(10, len(packages))
        # common packages + metrics enabled by default
        self.assertEqual(0, len({"e2fsprogs", "acpi", "doas", "openssh", "chrony",
                         "awall", "dhcpcd", "ifupdown-ng", "iproute2", "prometheus-node-exporter"} - packages))

        vswitch = cfg["vswitches"]["public"]

        self.assertIsNotNone(vswitch["vlans_by_name"])
        self.assertIsNotNone(vswitch["vlans_by_id"])
        self.assertEqual(len(vswitch["vlans_by_name"]), len(vswitch["vlans_by_id"]))

        # single vlan
        # default not specified; should default to only vlan
        self.assertEqual("pub_test", vswitch["default_vlan"]["name"])
        self.assertTrue(vswitch["vlans_by_id"][10]["default"])

        # single interface, no domain specified
        self.assertIsNotNone(cfg["primary_domain"])

        # has all default vlan config
        vlan = vswitch["vlans_by_id"][10]
        for key in config.vlan.DEFAULT_VLAN_CONFIG:
            self.assertIsNotNone(vlan[key])
            self.assertEqual(config.vlan.DEFAULT_VLAN_CONFIG[key], vlan[key])

        # has interface config
        iface = cfg["interfaces"][0]
        self.assertEqual(10, iface["vlan"]["id"])
        self.assertEqual("PUBLIC", iface["firewall_zone"])
        self.assertEqual("eth0", iface["name"])

        self.assertEqual("192.168.1.1", str(iface["ipv4_address"]))
        self.assertEqual("192.168.1.1", str(iface["ipv4_gateway"]))
        self.assertEqual("24", str(iface["ipv4_prefixlen"]))

        self.assertTrue(iface["accept_ra"])
        self.assertFalse(iface["ipv6_tempaddr"])

    def test_site_and_host(self):
        site_cfg = site.load(os.path.join(self._base_path, "sites", "test"))

        self.assertIsNotNone(site_cfg["hosts"])

        host = site_cfg["hosts"]["server"]
        self.assertIsNotNone(host)

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
        del self._site_yaml["public_ssh_key"]
        self.build_error()

    def test_invalid_role(self):
        self._host_yaml["roles"] = ["invalid"]
        self.build_error()

    def test_invalid_role_class(self):
        self._host_yaml["roles"] = ["role"]
        self.build_error()

    def test_invalid_external_dns(self):
        self._host_yaml["external_dns"] = ["invalid"]
        self.build_error()

    def test_package_conflict(self):
        self._host_yaml["packages"] = {"explicit_add", "add"}
        self._host_yaml["remove_packages"] = {"explicit_add", "remove"}
        cfg = self.build_cfg()

        self.assertIn("explicit_add", cfg["packages"])
        self.assertIn("add", cfg["packages"])

        self.assertNotIn("explicit_add", cfg["remove_packages"])
        self.assertIn("remove", cfg["remove_packages"])

    def test_duplicate_vlans(self):
        self._host_yaml["interfaces"].append(copy.deepcopy(self._host_yaml["interfaces"][0]))
        cfg = self.build_cfg()

        with self.assertRaises(ValueError):
            cfg["roles"][0].validate()

    def test_duplicate_routable_vlans_on_switch(self):
        vlan = copy.deepcopy(self._site_yaml["vswitches"][0]["vlans"][0])
        vlan["name"] = "test"
        vlan["id"] = 123
        self._site_yaml["vswitches"][0]["vlans"].append(vlan)

        iface = copy.deepcopy(self._host_yaml["interfaces"][0])
        iface["vlan"] = "test"
        self._host_yaml["interfaces"].append(iface)

        cfg = self.build_cfg()

        with self.assertRaises(ValueError):
            cfg["roles"][0].validate()