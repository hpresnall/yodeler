"""Handles parsing and validating vswitch configuration from site YAML files."""
import logging

import config.vlan

_logger = logging.getLogger(__name__)


def validate(cfg):
    """Validate all the vswitches defined in the site configuration."""
    vswitches = cfg.get("vswitches")
    if (vswitches is None) or (len(vswitches) == 0):
        raise KeyError("no vswitches defined")

    # list of vswitches in yaml => dict of names to vswitches
    vswitches_by_name = cfg["vswitches"] = {}
    uplinks = cfg["uplinks"] = set()

    for i, vswitch in enumerate(vswitches, start=1):
        # name is required and must be unique
        if ("name" not in vswitch) or (vswitch["name"] is None) or (vswitch["name"] == ""):
            raise KeyError(f"no name defined for vswitch {i}: {vswitch}")

        vswitch_name = vswitch["name"]

        if vswitches_by_name.get(vswitch_name) is not None:
            raise KeyError(
                f"duplicate name {vswitch_name} defined for vswitch {i}: {vswitch}")
        vswitches_by_name[vswitch_name] = vswitch

        uplink = vswitch.get("uplink")

        if uplink is not None:
            if isinstance(uplink, str):
                if uplink in uplinks:
                    raise KeyError(
                        f"uplink {uplink} reused for vswitch {vswitch_name}: {vswitch}")
                uplinks.add(uplink)
            else:
                for link in uplink:
                    if link in uplinks:
                        # an uplink interface can only be set for a single vswitch
                        raise KeyError(
                            f"uplink {link} reused for vswitch {vswitch_name}: {vswitch}")
                uplinks |= set(uplink)
        else:
            vswitch["uplink"] = None

        config.vlan.validate(cfg["domain"], vswitch)
