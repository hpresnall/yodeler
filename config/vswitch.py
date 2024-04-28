"""Handles parsing and validating vswitch configuration from site YAML files."""
import logging

import config.vlan as vlan

import util.parse as parse

_logger = logging.getLogger(__name__)


def validate(cfg: dict):
    """Validate all the vswitches defined in the site configuration."""
    vswitches = parse.non_empty_list("vswitches", cfg.get("vswitches"))

    # list of vswitches in yaml => dict of names to vswitches
    vswitches_by_name = cfg["vswitches"] = {}
    all_vlans = set()
    uplinks = set()

    # read uplink overrides first
    # overwrite the config's uplinks, if defined
    overrides = _configure_overrides(cfg)

    for i, vswitch in enumerate(vswitches, start=1):
        parse.non_empty_dict("vswitch " + str(i), vswitch)
        location = f"vswitch['{str(i).lower()}']"

        # name is required and must be unique; lowercase for consistency
        vswitch_name = parse.non_empty_string("name", vswitch, location)
        vswitch["name"] = vswitch_name

        if vswitches_by_name.get(vswitch_name) is not None:
            raise KeyError(f"duplicate name {vswitch_name} defined for {location}")
        vswitches_by_name[vswitch_name] = vswitch

        vswitch_uplinks = parse.read_string_list_plurals({"uplink", "uplinks"}, vswitch, location + ".uplinks")
        vswitch.pop("uplink", None)

        if (vswitch_name in overrides) and overrides[vswitch_name]["uplinks"]:
            old_uplinks = vswitch_uplinks
            vswitch_uplinks = overrides[vswitch_name]["uplinks"]
            _logger.debug(f"profile['{cfg['profile']['name']}'] overriding uplinks for vswitch "
                         f"'{vswitch_name}': {old_uplinks} -> {vswitch_uplinks}")

        for j, uplink in enumerate(vswitch_uplinks, start=1):
            if uplink in uplinks:
                raise KeyError(f"{location}.uplink[{j}]' '{uplink}' reused")
            uplinks.add(uplink)

        vswitch["uplinks"] = vswitch_uplinks

        vlan.validate(cfg["domain"], vswitch, all_vlans)


def _configure_overrides(cfg: dict) -> dict[str, dict]:
    overrides = {}

    if cfg["profile"] and ("vswitches" in cfg["profile"]):
        o_loc = f"profile['{cfg['profile']['name']}'].vswitches"

        for i, vswitch in enumerate(cfg["profile"]["vswitches"], start=1):
            vswitch_name = vswitch['name']

            if ("name" in vswitch):
                override_uplinks = parse.read_string_list_plurals(
                    {"uplink", "uplinks"}, vswitch, f"{o_loc}['{vswitch_name}']")
                overrides[vswitch_name] = {"uplinks": override_uplinks}

    return overrides
