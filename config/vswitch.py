"""Handles parsing and validating vswitch configuration from site YAML files."""
import logging

import config.vlan as vlan


def validate(cfg: dict):
    """Validate all the vswitches defined in the site configuration."""
    vswitches = cfg.get("vswitches")
    if vswitches is None:
        raise KeyError("no vswitches defined")
    if not isinstance(vswitches, list):
        raise KeyError("vswitches must be an array")
    if len(vswitches) == 0:
        raise KeyError("vswitches cannot be empty")

    # list of vswitches in yaml => dict of names to vswitches
    vswitches_by_name = cfg["vswitches"] = {}
    all_vlans = set()
    uplinks = set()

    for i, vswitch in enumerate(vswitches, start=1):
        if not isinstance(vswitch, dict):
            raise KeyError(f"vswitch {i} must be an object")

        # name is required and must be unique
        if ("name" not in vswitch) or (vswitch["name"] is None) or (vswitch["name"] == ""):
            raise KeyError(f"no name defined for vswitch {i}")

        vswitch_name = vswitch["name"]

        if vswitches_by_name.get(vswitch_name) is not None:
            raise KeyError(
                f"duplicate name {vswitch_name} defined for vswitch {i}")
        vswitches_by_name[vswitch_name] = vswitch

        uplink = vswitch.get("uplink")

        if uplink is not None:
            if isinstance(uplink, str):
                if uplink in uplinks:
                    raise KeyError(f"uplink '{uplink}' reused for vswitch {i}: '{vswitch_name}'")
                uplinks.add(uplink)
            elif isinstance(uplink, list):
                for link in uplink:
                    if link in uplinks:
                        # an uplink interface can only be set for a single vswitch
                        raise KeyError(f"uplink '{link}' reused for vswitch {i}: '{vswitch_name}'")
                uplinks |= set(uplink)
            else:
                raise KeyError(f"uplink {uplink} not a string or list for vswitch {i}: '{vswitch_name}'")
        else:
            vswitch["uplink"] = None

        vlan.validate(cfg["domain"], vswitch, all_vlans)
