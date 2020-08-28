# pylint: disable=missing-module-docstring
# pylint: disable=missing-class-docstring
# pylint: disable=missing-function-docstring

import test.yodeler.base as base


class TestVswitch(base.TestCfgBase):
    def test_no_vswitches(self):
        del self._cfg_dict["vswitches"]
        self.build_error()

    def test_empty_vswitches(self):
        self._cfg_dict["vswitches"] = []
        self.build_error()

    def test_no_vswitch_name(self):
        del self._cfg_dict["vswitches"][0]["name"]
        self.build_error()

    def test_empty_vswitch_name(self):
        self._cfg_dict["vswitches"][0]["name"] = ""
        self.build_error()

    def test_none_vswitch_name(self):
        self._cfg_dict["vswitches"][0]["name"] = None
        self.build_error()

    def test_duplicate_vswitch_name(self):
        self._cfg_dict["vswitches"][0]["name"] = "private"
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
