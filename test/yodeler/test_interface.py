# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring

import test.yodeler.base as base


class TestInterface(base.TestCfgBase):
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
