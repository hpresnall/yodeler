# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import unittest
import os.path
import copy

import yodeler.config as config
import util.file


class TestConfig(unittest.TestCase):
    _base_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    @classmethod
    def setUpClass(cls):
        cls._minimal = util.file.load_yaml(
            os.path.join(cls._base_path, "yaml/minimal.yaml"))

    def setUp(self):
        self._cfg_dict = copy.deepcopy(self._minimal)

    def tearDown(self):
        self._cfg_dict = None

    def test_empty_string(self):
        with self.assertRaises(KeyError):
            config.config_from_string("")

    def test_minimal(self):
        cfg = self.build_cfg()
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
        for key in config.DEFAULT_VLAN_CONFIG:
            self.assertIsNotNone(vlan[key])
            self.assertEqual(config.DEFAULT_VLAN_CONFIG[key], vlan[key])

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

    def test_no_vswitches(self):
        del self._cfg_dict["vswitches"]
        self.build_error()

    def test_no_vlans(self):
        del self._cfg_dict["vswitches"][0]["vlans"]
        self.build_error()

    def test_empty_vswitches(self):
        self._cfg_dict["vswitches"] = []
        self.build_error()

    def test_empty_vlans(self):
        self._cfg_dict["vswitches"][0]["vlans"] = []
        self.build_error()

    def test_no_vswitch_name(self):
        del self._cfg_dict["vswitches"][0]["name"]
        self.build_error()

    def test_no_vlan_name(self):
        del self._cfg_dict["vswitches"][0]["vlans"][0]["name"]
        self.build_error()

    def test_empty_vswitch_name(self):
        self._cfg_dict["vswitches"][0]["name"] = ""
        self.build_error()

    def test_empty_vlan_name(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["name"] = ""
        self.build_error()

    def test_none_vswitch_name(self):
        self._cfg_dict["vswitches"][0]["name"] = None
        self.build_error()

    def test_none_vlan_name(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["name"] = None
        self.build_error()

    def test_duplicate_vswitch_name(self):
        self._cfg_dict["vswitches"][0]["name"] = "private"
        self.build_error()

    def test_duplicate_vlan_name(self):
        vlan2 = {"name": "test", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64"}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        self.build_error()

    def test_duplicate_vlan_id(self):
        vlan2 = {"name": "test2", "id": 10, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64"}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        self.build_error()

    def test_no_vlan_id(self):
        del self._cfg_dict["vswitches"][0]["vlans"][0]["id"]
        del self._cfg_dict["interfaces"][0]["vlan"]
        cfg = self.build_cfg()

        # vswitch with no vlan id should have a None value
        self.assertIsNone(cfg["vswitches"]["public"]
                          ["vlans_by_name"]["test"]["id"])

    def test_none_vlan_id(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["id"] = None
        # interface must point to a valid vlan
        self._cfg_dict["interfaces"][0]["vlan"] = None
        cfg = self.build_cfg()

        # None value should carry over
        self.assertIsNone(cfg["vswitches"]["public"]
                          ["vlans_by_name"]["test"]["id"])
        self.assertIsNotNone(cfg["vswitches"]["public"]["vlans_by_id"][None])

    def test_default_vlan(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64", "default": True}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        cfg = self.build_cfg()

        # multiple vlans, one default
        # values exist and are set
        vswitch = cfg["vswitches"]["public"]
        self.assertEqual("test2", vswitch["default_vlan"]["name"])
        self.assertFalse(vswitch["vlans_by_id"][10]["default"])
        self.assertTrue(vswitch["vlans_by_id"][20]["default"])

    def test_multiple_default_vlans(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64", "default": True}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        self._cfg_dict["vswitches"][0]["vlans"][0]["default"] = True
        self.build_error()

    def test_multiple_vlans_no_default(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64"}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        cfg = self.build_cfg()

        # multiple vlans, no default
        # values exist and are set
        vswitch = cfg["vswitches"]["public"]
        self.assertIsNone(vswitch["default_vlan"])
        self.assertFalse(vswitch["vlans_by_id"][10]["default"])
        self.assertFalse(vswitch["vlans_by_id"][20]["default"])

    def test_multiple_vlans_no_default_no_iface_vlan(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64"}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        # interface must set a vlan if there is no default
        del self._cfg_dict["interfaces"][0]["vlan"]
        self.build_error()

    def test_unknown_access_vlans(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["access_vlans"] = [20]
        self.build_error()

    def test_non_array_access_vlans(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["access_vlans"] = 20
        self.build_error()

    def test_str_access_vlans(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["access_vlans"] = "20"
        self.build_error()

    def test_invalid_domain_vlan(self):
        # vlan domain not in top-level domain
        self._cfg_dict["domain"] = "example.com"
        self._cfg_dict["vswitches"][0]["vlans"][0]["domain"] = "test.foo.com"
        self.build_error()

    def test_default_primary_domain(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["domain"] = "foo.example.com"
        self._cfg_dict["interfaces"].append({"vswitch": "private",
                                             "ipv4_address": "192.168.2.1",
                                             "ipv6_address": "2001:db8:0:2::1"})

        cfg = self.build_cfg()

        # multiple ifaces, primary_domain should unset
        self.assertEqual("", cfg["primary_domain"])

    def test_no_primary_domain(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["domain"] = "foo.example.com"
        cfg = self.build_cfg()

        # single iface, primary_domain should be the vlan's
        self.assertEqual("foo.example.com", cfg["primary_domain"])

    def test_invalid_primary_domain(self):
        self._cfg_dict["domain"] = "example.com"
        self._cfg_dict["vswitches"][0]["vlans"][0]["domain"] = "foo.example.com"
        self._cfg_dict["primary_domain"] = "bar.example.com"
        self.build_error()

    def test_no_uplink(self):
        del self._cfg_dict["vswitches"][0]["uplink"]
        cfg = self.build_cfg()

        # key should exist and be None
        self.assertIsNone(cfg["vswitches"]["public"]["uplink"])
        self.assertEqual(0, len(cfg["uplinks"]))

    def test_multi_uplink(self):
        self._cfg_dict["vswitches"][0]["uplink"] = ["eth0", "eth1"]
        cfg = self.build_cfg()

        # key should exist
        self.assertEqual(2, len(cfg["vswitches"]["public"]["uplink"]))
        self.assertEqual(2, len(cfg["uplinks"]))

    def test_reused_uplink(self):
        self._cfg_dict["vswitches"][1]["uplink"] = "eth0"
        self.build_error()

    def test_reused_uplink_multi(self):
        self._cfg_dict["vswitches"][0]["uplink"] = "eth0"
        self._cfg_dict["vswitches"][1]["uplink"] = ["eth0", "eth1"]
        self.build_error()

    def test_invalid_vlan_ipv4_subnet(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["ipv4_subnet"] = "invalid"
        self.build_error()

    def test_invalid_vlan_ipv6_subnet(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["ipv6_subnet"] = "invalid"
        self.build_error()

    def test_none_vlan_ipv4_subnet(self):
        del self._cfg_dict["vswitches"][0]["vlans"][0]["ipv4_subnet"]
        self.build_error()

    def test_none_vlan_ipv6_subnet(self):
        del self._cfg_dict["vswitches"][0]["vlans"][0]["ipv6_subnet"]
        del self._cfg_dict["interfaces"][0]["ipv6_address"]
        cfg = self.build_cfg()

        # should be set to None
        self.assertIsNone(cfg["vswitches"]["public"]
                          ["vlans_by_id"][10]["ipv6_subnet"])

    def test_vlan_ipv4_min_dhcp(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["dhcp_min_address_ipv4"] = -10
        self.build_error()

    def test_vlan_ipv4_max_dhcp(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["dhcp_max_address_ipv4"] = 260
        self.build_error()

    def test_vlan_ipv4_misordered_dhcp(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["dhcp_min_address_ipv4"] = 250
        self._cfg_dict["vswitches"][0]["vlans"][0]["dhcp_max_address_ipv4"] = 2
        self.build_error()

    def test_vlan_ipv6_min_dhcp(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["dhcp_min_address_ipv6"] = -10
        self.build_error()

    def test_vlan_ipv6_max_dhcp(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["dhcp_max_address_ipv6"] = -10
        self.build_error()

    def test_vlan_ipv6_misordered_dhcp(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["dhcp_min_address_ipv6"] = 0xffff
        self._cfg_dict["vswitches"][0]["vlans"][0]["dhcp_max_address_ipv6"] = 2
        self.build_error()

    def test_vlan_ipv6_disabled(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["ipv6_disable"] = True
        cfg = self.build_cfg()

        self.assertIsNone(cfg["vswitches"]["public"]["vlans"][0]["ipv6_subnet"])
        self.assertEqual("manual", cfg["interfaces"][0]["ipv6_method"])

    def test_iface_ipv6_options(self):
        self._cfg_dict["interfaces"][0]["ipv6_dhcp"] = True
        self._cfg_dict["interfaces"][0]["accept_ra"] = False
        self._cfg_dict["interfaces"][0]["privext"] = 2

        cfg = self.build_cfg()

        self.assertEqual(1, cfg["interfaces"][0]["ipv6_dhcp"])
        self.assertEqual(0, cfg["interfaces"][0]["accept_ra"])
        self.assertEqual(2, cfg["interfaces"][0]["privext"])

    def test_invalid_ipv6_privext(self):
        self._cfg_dict["interfaces"][0]["privext"] = 3
        self.build_error()

    def test_no_local_firewall(self):
        self._cfg_dict["local_firewall"] = False
        cfg = self.build_cfg()

        # remove iptables when no firewall
        self.assertIn("iptables", cfg["remove_packages"])
        self.assertIn("ip6tables", cfg["remove_packages"])

    def test_no_interfaces(self):
        del self._cfg_dict["interfaces"]
        self.build_error()

    def test_empty_interfaces(self):
        self._cfg_dict["interfaces"] = []
        self.build_error()

    def test_no_interface_vswitch(self):
        del self._cfg_dict["interfaces"][0]["vswitch"]
        self.build_error()

    def test_empty_interface_vswitch(self):
        self._cfg_dict["interfaces"][0]["vswitch"] = ""
        self.build_error()

    def test_none_interface_vswitch(self):
        self._cfg_dict["interfaces"][0]["vswitch"] = None
        self.build_error()

    def test_interface_str_vlan(self):
        self._cfg_dict["interfaces"][0]["vlan"] = "test"
        cfg = self.build_cfg()

        # interface vlan as string should be valid
        self.assertIsNotNone(cfg["interfaces"][0]["vlan"])
        self.assertEqual("test", cfg["interfaces"][0]["vlan"]["name"])

    def test_none_interface_vlan_no_pvid_vswitch(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64", "default": True}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        self._cfg_dict["interfaces"][0]["vlan"] = None
        self._cfg_dict["interfaces"][0]["ipv4_address"] = "192.168.2.1"
        self._cfg_dict["interfaces"][0]["ipv6_address"] = "2001:db8:0:2::1"
        cfg = self.build_cfg()

        # no interface vlan; should still be set to valid vlan in config
        self.assertIsNotNone(cfg["interfaces"][0]["vlan"])
        # No PVID vlan defined in vswitch; should pick the default
        self.assertEqual("test2", cfg["interfaces"][0]["vlan"]["name"])

    def test_none_interface_vlan_pvid_vswitch(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64", "default": True}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        self._cfg_dict["vswitches"][0]["vlans"][0]["id"] = None
        del self._cfg_dict["interfaces"][0]["vlan"]
        cfg = self.build_cfg()

        # no interface vlan; should still be set to valid vlan in config
        self.assertIsNotNone(cfg["interfaces"][0]["vlan"])
        # PVID vlan defined in vswitch, should be the vlan with no id
        self.assertEqual("test", cfg["interfaces"][0]["vlan"]["name"])

    def test_none_interface_vlan_no_default(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64"}
        self._cfg_dict["vswitches"][0]["vlans"].append(vlan2)
        self._cfg_dict["interfaces"][0]["vlan"] = None
        self._cfg_dict["interfaces"][0]["ipv4_address"] = "192.168.2.1"
        self._cfg_dict["interfaces"][0]["ipv6_address"] = "2001:db8:0:2::1"

        self.build_error()
        # no PVID vlan defined in vswitch, no default vlan; should error

    def test_dhcp4_interface(self):
        self._cfg_dict["interfaces"][0]["ipv4_address"] = "dhcp"
        cfg = self.build_cfg()

        self.assertEqual("dhcp", cfg["interfaces"][0]["ipv4_address"])
        self.assertEqual("dhcp", cfg["interfaces"][0]["ipv4_method"])

    def test_invalid_interface_vswitch(self):
        self._cfg_dict["interfaces"][0]["vswitch"] = "unknown"
        self.build_error()

    def test_invalid_interface_vlan(self):
        self._cfg_dict["interfaces"][0]["vlan"] = 100
        self.build_error()

    def test_invalid_interface_ipv4_address(self):
        self._cfg_dict["interfaces"][0]["ipv4_address"] = "invalid"
        self.build_error()

    def test_invalid_interface_ipv6_address(self):
        self._cfg_dict["interfaces"][0]["ipv6_address"] = "invalid"
        self.build_error()

    def test_none_interface_ipv4_address(self):
        del self._cfg_dict["interfaces"][0]["ipv4_address"]
        self.build_error()

    def test_none_interface_ipv6_address(self):
        del self._cfg_dict["interfaces"][0]["ipv6_address"]
        cfg = self.build_cfg()

        # should be set to None
        self.assertIsNone(cfg["interfaces"][0]["ipv6_address"])

    def test_invalid_subnet_interface_ipv4_address(self):
        self._cfg_dict["interfaces"][0]["ipv4_address"] = "192.168.2.1"
        self.build_error()

    def test_invalid_subnet_interface_ipv6_address(self):
        self._cfg_dict["interfaces"][0]["ipv6_address"] = "2001:db8:0:2::1"
        self.build_error()

    def test_none_subnet_interface_ipv6_address(self):
        del self._cfg_dict["vswitches"][0]["vlans"][0]["ipv6_subnet"]
        self._cfg_dict["interfaces"][0]["ipv6_address"] = "2001:db8:0:2::1"
        self.build_error()

    def build_cfg(self):
        return config.config_from_dict(self._cfg_dict)

    def build_error(self):
        with self.assertRaises(KeyError):
            self.build_cfg()
