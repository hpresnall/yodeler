# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring

import test.config.base as base


class TestVswitch(base.TestCfgBase):
    def test_no_vswitches(self):
        del self._site_yaml["vswitches"]
        self.build_error()

    def test_empty_vswitches(self):
        self._site_yaml["vswitches"] = []
        self.build_error()

    def test_string_vswitches(self):
        self._site_yaml["vswitches"] = "invalid"
        self.build_error()

    def test_num_vswitches(self):
        self._site_yaml["vswitches"] = 123
        self.build_error()

    def test_nonobject_vswitch(self):
        self._site_yaml["vswitches"] = ["invalid"]
        self.build_error()

    def test_no_vswitch_name(self):
        del self._site_yaml["vswitches"][0]["name"]
        self.build_error()

    def test_empty_vswitch_name(self):
        self._site_yaml["vswitches"][0]["name"] = ""
        self.build_error()

    def test_none_vswitch_name(self):
        self._site_yaml["vswitches"][0]["name"] = None
        self.build_error()

    def test_duplicate_vswitch_name(self):
        self._site_yaml["vswitches"][0]["name"] = "private"
        self.build_error()

    def test_no_uplink(self):
        del self._site_yaml["vswitches"][0]["uplink"]
        cfg = self.build_cfg()

        # key should exist and be empty
        self.assertFalse(cfg["vswitches"]["public"]["uplinks"])

    def test_invalid_type_uplink(self):
        self._site_yaml["vswitches"][0]["uplink"] = 0
        self.build_error()

    def test_multi_uplink(self):
        del self._site_yaml["vswitches"][0]["uplink"]
        self._site_yaml["vswitches"][0]["uplinks"] = ["eth0", "eth1"]
        cfg = self.build_cfg()

        # key should exist
        self.assertEqual(2, len(cfg["vswitches"]["public"]["uplinks"]))

    def test_reused_uplink(self):
        self._site_yaml["vswitches"][1]["uplink"] = "eth0"
        self.build_error()

    def test_reused_uplink_multi(self):
        self._site_yaml["vswitches"][0]["uplink"] = "eth0"
        self._site_yaml["vswitches"][1]["uplink"] = ["eth0", "eth1"]
        self.build_error()
