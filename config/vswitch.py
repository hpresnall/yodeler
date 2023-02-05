"""Handles parsing and validating vswitch configuration from site YAML files."""
import logging

import config.vlan as vlan

import util.parse as parse


def validate(cfg: dict):
    """Validate all the vswitches defined in the site configuration."""
    vswitches = cfg.get("vswitches")
    parse.non_empty_list("vswitches", vswitches)

    # list of vswitches in yaml => dict of names to vswitches
    vswitches_by_name = cfg["vswitches"] = {}
    all_vlans = set()
    uplinks = set()

    for i, vswitch in enumerate(vswitches, start=1):
        parse.non_empty_dict("vswitch " + str(i), vswitch)

        # name is required and must be unique
        vswitch_name = parse.non_empty_string("name", vswitch, "vswitch" + str(i))

        if vswitches_by_name.get(vswitch_name) is not None:
            raise KeyError(f"duplicate name {vswitch_name} defined for vswitch {i}")
        vswitches_by_name[vswitch_name] = vswitch

        vswitch_uplinks = parse.read_string_list("uplink", vswitch, f"vswitch {i}: '{vswitch_name}'")

        for uplink in vswitch_uplinks:
            if uplink in uplinks:
                raise KeyError(f"uplink '{uplink}' reused for vswitch {i}: '{vswitch_name}'")
            uplinks.add(uplink)

        vswitch["uplink"] = vswitch_uplinks if vswitch_uplinks else None

        vlan.validate(cfg["domain"], vswitch, all_vlans)
