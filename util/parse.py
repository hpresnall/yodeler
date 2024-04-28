"""Utility functions for parsing & validating configuration values.

These functions will raise ValueErrors or KeyErrors for invalid values.
"""
import re

from typing import cast
from typing import Hashable


def non_empty_dict(name: str, value: object) -> dict:
    return cast(dict, _non_empty(name, value, dict))


def non_empty_list(name: str, value: object) -> list:
    return cast(list, _non_empty(name, value, list))


def _non_empty(name: str, value, kind: type) -> object:
    if not name:
        raise ValueError(f"name cannot be empty for value {value}")
    if value is None:
        raise ValueError(f"value cannot be None for name {name}")
    if not kind:
        raise ValueError(f"kind cannot be empty for name {name}, value {value}")

    if not isinstance(value, kind):
        raise ValueError(f"{name} must be a {kind}, not a {type(value)}")
    if len(value) == 0:
        raise ValueError(f"{name} cannot be empty")

    return value


def non_empty_string(key: str, cfg: None | dict, dict_name: str) -> str:
    if not key:
        raise ValueError("key cannot be empty")
    if cfg is None:
        raise ValueError("cfg cannot be None")
    if not dict_name:
        raise ValueError("dict_name cannot be empty")

    if key not in cfg:
        raise KeyError(f"{key} not in {dict_name}")

    value = cfg[key]
    if not isinstance(value, str):
        raise KeyError(f"{dict_name}['{key}'] must be a string, not a {type(value)}")
    if not value:
        raise KeyError(f"{dict_name}['{key}'] cannot be an empty string")

    return value


def set_default_string(key: str, cfg: dict, default: str) -> str:
    if not key:
        raise ValueError("key cannot be empty")
    if cfg is None:
        raise ValueError("cfg cannot be None")
    if not default:
        raise ValueError("default cannot be empty")

    value = cfg.get(key)

    if not value:
        value = default
    elif not isinstance(value, str):
        raise ValueError(f"{key} must be a string")

    cfg[key] = value
    return value


def read_string_list(key: str, cfg: dict, value_name: str) -> list[str]:
    return read_string_list_plurals({key}, cfg, value_name)


def read_string_list_plurals(keys: set[str], cfg: None | dict, value_name: str) -> list[str]:
    return _read_list_plurals(keys, cfg, value_name, str)


def read_dict_list_plurals(keys: set[str], cfg: None | dict, value_name: str) -> list[dict]:
    return _read_list_plurals(keys, cfg, value_name, dict)


def _read_list_plurals(keys: set[str], cfg: None | dict, value_name: str, value_type: type) -> list:
    # combine all all the values from all the keys into a single set
    # this allows something like foo: bar or foos: [ bar, baz ]
    if not keys:
        raise KeyError("keys cannot be empty")
    if cfg is None:
        raise ValueError("cfg cannot be None")
    if not value_name:
        raise ValueError("value_name cannot be empty")

    unique_values = set()
    values = []

    for key in keys:
        if not key:
            raise ValueError(f"{value_name}.{key} cannot be empty")

        if key not in cfg:
            continue

        # allow list of value_type or a single value
        if isinstance(cfg[key], value_type):
            value = cfg[key]

            if value:
                # only add hashable values once
                if isinstance(value, Hashable):
                    if value not in unique_values:
                        unique_values.add(value)
                        values.append(value)
                else:
                    values.append(value)
        elif isinstance(cfg[key], list):
            # for lists, check each value
            for value in cfg[key]:
                if not isinstance(value, value_type):
                    raise ValueError(f"invalid {value_name} value '{value}'; it must be a {value_type}")
                if value:
                    # only add hashable values once
                    if isinstance(value, Hashable):
                        if value not in unique_values:
                            unique_values.add(value)
                            values.append(value)
                    else:
                        values.append(value)
        else:
            raise KeyError(
                f"{key} for {value_name} must be a {value_type} or list of {value_type}, not {type(cfg[key])}")

    return values


def configure_defaults(config_name: str, default_config: dict, default_types: dict, cfg: dict):
    if not config_name:
        raise ValueError("config_name cannot be empty")
    if default_config is None:
        raise ValueError("default_config cannot be None")
    if default_types is None:
        raise ValueError("default_types cannot be None")
    if cfg is None:
        raise ValueError("cfg cannot be None")

    for key in default_config:
        if key not in default_types:
            raise KeyError(f"{key} in {config_name} does not define a type")

        use_default = False

        if key in cfg:
            value = cfg[key]
        else:
            value = default_config[key]
            use_default = True

        kind = default_types[key]

        if not isinstance(value, kind):
            raise KeyError(f"{key} value '{value}' in {config_name} is {type(value)} not {kind}")
        # some default values can be empty; so do not check here

        if use_default:
            if isinstance(value, list):
                cfg[key] = list(value)  # copy the list
            else:
                cfg[key] = value


_VALID_MAC = re.compile("^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$")


def validate_mac_address(mac_address, location: str):
    """Ensure the given MAC address is a string and represents a valid value.
    Upper and lowercase are accepted as well as ':' or '-' separators."""

    if not isinstance(mac_address, str):
        raise ValueError(f"invalid mac_address '{mac_address}' for {location}; it must be a string")
    if not _VALID_MAC.match(mac_address.upper()):
        # mac address case is up to the client, but upper() for regex here
        raise ValueError(f"invalid mac_address '{mac_address}' for {location}")
