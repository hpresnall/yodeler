# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring

import test.config.base as base


class TestVlan(base.TestCfgBase):
    def test_no_vlans(self):
        del self._cfg_dict["vswitches"][0]["vlans"]
        self.build_error()

    def test_empty_vlans(self):
        self._cfg_dict["vswitches"][0]["vlans"] = []
        self.build_error()

    def test_no_vlan_name(self):
        del self._cfg_dict["vswitches"][0]["vlans"][0]["name"]
        self.build_error()

    def test_empty_vlan_name(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["name"] = ""
        self.build_error()

    def test_none_vlan_name(self):
        self._cfg_dict["vswitches"][0]["vlans"][0]["name"] = None
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

        # multiple ifaces, primary_domain should be unset
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
        # cannot set ip address with no subnet
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
