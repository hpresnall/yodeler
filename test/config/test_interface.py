# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring
import copy

import test.config.base as base

import config.interface as interface


class TestInterface(base.TestCfgBase):
    def test_iface_ipv6_options(self):
        self._host_yaml["interfaces"][0]["accept_ra"] = False
        self._host_yaml["interfaces"][0]["ipv6_tempaddr"] = 1

        cfg = self.build_cfg()

        self.assertFalse(cfg["interfaces"][0]["accept_ra"])
        self.assertTrue(cfg["interfaces"][0]["ipv6_tempaddr"])

    def test_no_interfaces(self):
        del self._host_yaml["interfaces"]
        self.build_error()

    def test_empty_interfaces(self):
        self._host_yaml["interfaces"] = []
        self.build_error()

    def test_string_interfaces(self):
        self._host_yaml["interfaces"] = "invalid"
        self.build_error()

    def test_num_interfaces(self):
        self._host_yaml["interfaces"] = 123
        self.build_error()

    def test_nonobject_interface(self):
        self._host_yaml["interfaces"] = ["invalid"]
        self.build_error()

    def test_no_interface_vswitch(self):
        del self._host_yaml["interfaces"][0]["vswitch"]
        self.build_error()

    def test_empty_interface_vswitch(self):
        self._host_yaml["interfaces"][0]["vswitch"] = ""
        self.build_error()

    def test_none_interface_vswitch(self):
        self._host_yaml["interfaces"][0]["vswitch"] = None
        self.build_error()

    def test_interface_str_vlan(self):
        self._host_yaml["interfaces"][0]["vlan"] = "pub_test"
        cfg = self.build_cfg()

        # interface vlan as string should be valid
        self.assertIsNotNone(cfg["interfaces"][0]["vlan"])
        self.assertEqual("pub_test", cfg["interfaces"][0]["vlan"]["name"])

    def test_none_interface_vlan_no_pvid_vswitch(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64", "default": True}
        self._site_yaml["vswitches"][0]["vlans"].append(vlan2)
        self._host_yaml["interfaces"][0]["vlan"] = None
        self._host_yaml["interfaces"][0]["ipv4_address"] = "192.168.2.1"
        self._host_yaml["interfaces"][0]["ipv6_address"] = "2001:db8:0:2::1"
        cfg = self.build_cfg()

        # no interface vlan; should still be set to valid vlan in config
        self.assertIsNotNone(cfg["interfaces"][0]["vlan"])
        # No PVID vlan defined in vswitch; should pick the default
        self.assertEqual("test2", cfg["interfaces"][0]["vlan"]["name"])

    def test_none_interface_vlan_pvid_vswitch(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64", "default": True}
        self._site_yaml["vswitches"][0]["vlans"].append(vlan2)
        self._site_yaml["vswitches"][0]["vlans"][0]["id"] = None
        del self._host_yaml["interfaces"][0]["vlan"]
        cfg = self.build_cfg()

        # no interface vlan; should still be set to valid vlan in config
        self.assertIsNotNone(cfg["interfaces"][0]["vlan"])
        # PVID vlan defined in vswitch, should be the vlan with no id
        self.assertEqual("pub_test", cfg["interfaces"][0]["vlan"]["name"])

    def test_none_interface_vlan_no_default(self):
        vlan2 = {"name": "test2", "id": 20, "ipv4_subnet": "192.168.2.0/24",
                 "ipv6_subnet": "2001:db8:0:2::/64"}
        self._site_yaml["vswitches"][0]["vlans"].append(vlan2)
        self._host_yaml["interfaces"][0]["vlan"] = None
        self._host_yaml["interfaces"][0]["ipv4_address"] = "192.168.2.1"
        self._host_yaml["interfaces"][0]["ipv6_address"] = "2001:db8:0:2::1"

        self.build_error()
        # no PVID vlan defined in vswitch, no default vlan; should error

    def test_dhcp4_interface(self):
        self._host_yaml["interfaces"][0]["ipv4_address"] = "dhcp"
        cfg = self.build_cfg()

        self.assertEqual("dhcp", cfg["interfaces"][0]["ipv4_address"])

    def test_invalid_interface_vswitch(self):
        self._host_yaml["interfaces"][0]["vswitch"] = "unknown"
        self.build_error()

    def test_invalid_interface_vlan(self):
        self._host_yaml["interfaces"][0]["vlan"] = 100
        self.build_error()

    def test_invalid_interface_ipv4_address(self):
        self._host_yaml["interfaces"][0]["ipv4_address"] = "invalid"
        self.build_error()

    def test_invalid_interface_ipv6_address(self):
        self._host_yaml["interfaces"][0]["ipv6_address"] = "invalid"
        self.build_error()

    def test_none_interface_ipv4_address(self):
        del self._host_yaml["interfaces"][0]["ipv4_address"]
        self.build_error()

    def test_none_interface_ipv6_address(self):
        del self._host_yaml["interfaces"][0]["ipv6_address"]
        cfg = self.build_cfg()

        # should be set to None
        self.assertIsNone(cfg["interfaces"][0]["ipv6_address"])

    def test_invalid_subnet_interface_ipv4_address(self):
        self._host_yaml["interfaces"][0]["ipv4_address"] = "192.168.2.1"
        self.build_error()

    def test_invalid_subnet_interface_ipv6_address(self):
        self._host_yaml["interfaces"][0]["ipv6_address"] = "2001:db8:0:2::1"
        self.build_error()

    def test_none_subnet_interface_ipv6_address(self):
        del self._site_yaml["vswitches"][0]["vlans"][0]["ipv6_subnet"]
        # ip address set without a subnet should error
        self.build_error()

    def test_vlan_ipv6_disabled(self):
        self._site_yaml["vswitches"][0]["vlans"][0]["ipv6_disabled"] = True
        cfg = self.build_cfg()

        self.assertIsNone(cfg["vswitches"]["public"]["vlans"][0]["ipv6_subnet"])
        self.assertIsNone(cfg["interfaces"][0]["ipv6_address"])
        self.assertFalse(cfg["interfaces"][0]["ipv6_tempaddr"])
        self.assertFalse(cfg["interfaces"][0]["accept_ra"])

    def test_find_by_name(self):
        cfg = self.build_cfg()

        with self.assertRaises(KeyError):
            interface.find_by_name(cfg, "invalid")

    def test_find_ips_self(self):
        cfg = self.build_cfg()

        matches = interface.find_ips_to_interfaces(cfg, cfg["interfaces"])

        self.assertIsNotNone(matches)
        self.assertEqual(1, len(matches))
        self.assertEqual("127.0.0.1", str(matches[0]["ipv4_address"]))
        self.assertEqual("::1", str(matches[0]["ipv6_address"]))

    def test_find_ips_other(self):
        cfg = self.build_cfg()

        matching = copy.deepcopy(cfg["interfaces"])

        self._host_yaml["interfaces"][0]["ipv4_address"] = "dhcp"
        del self._host_yaml["interfaces"][0]["ipv6_address"]

        matches = interface.find_ips_to_interfaces(cfg, matching)

        self.assertIsNotNone(matches)
        self.assertEqual(1, len(matches))
        self.assertEqual("192.168.1.1", str(matches[0]["ipv4_address"]))
        self.assertEqual("2001:db8:0:1::1", str(matches[0]["ipv6_address"]))

    def test_no_wifi_config(self):
        self._host_yaml["interfaces"][0]["name"] = "wlan0"
        # wlan without configuration should error
        self.build_error()
