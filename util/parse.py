"""Utility functions for parsing & validating configuration values.

These functions will raise ValueErrors or KeyErrors for invalid values.
"""
import re

from typing import cast
from typing import Hashable


def non_empty_dict(location: str, value: None | dict) -> dict:
    return cast(dict, _non_empty(location, value, dict))


def non_empty_list(location: str, value: None | list) -> list:
    return cast(list, _non_empty(location, value, list))


def get_dict(location: str, key: str, cfg: None | dict) -> dict:
    return cast(dict, _non_empty_from_key(location, key, cfg, dict))


def get_list(location: str, key: str, cfg: None | dict) -> list:
    return cast(list, _non_empty_from_key(location, key, cfg, list))


def get_string(location: str, key: str, cfg: None | dict) -> str:
    return cast(str, _non_empty_from_key(location, key, cfg, str))


def _non_empty_from_key(location: str, key: str, cfg: None | dict, kind: type) -> object:
    if not key:
        raise KeyError(f"key cannot be empty for {location}")
    if not cfg:
        raise ValueError(f"cfg must be defined for {location}")
    if not key in cfg:
        raise KeyError(f"'{key}' not in {location}")

    return _non_empty("" if not location else f"{location}['{key}']", cfg[key], kind)


def _non_empty(location: str, value, kind: type) -> object:
    if not location:
        raise ValueError(f"location cannot be empty")
    if value is None:
        raise ValueError(f"value must be defined for {location}")
    if not kind:
        raise ValueError(f"kind cannot be empty for {location}={value}")

    if not isinstance(value, kind):
        raise ValueError(f"{location} must be a {kind}, not a {type(value)}")
    if len(value) == 0:
        raise ValueError(f"{location} cannot be empty")

    return value


def set_string_default(location: str, key: str, cfg: None | dict, default: str) -> str:
    return cast(str, _set_default(location, key, cfg, default, str))


def set_int_default(location: str, key: str, cfg: None | dict, default: int) -> int:
    return cast(int, _set_default(location, key, cfg, default, int))


def set_bool_default(location: str, key: str, cfg: dict | None, default: bool) -> bool:
    return cast(bool, _set_default(location, key, cfg, default, bool))


def _set_default(location: str, key: str, cfg: dict | None, default: object, kind: type) -> object:
    if not location:
        raise ValueError(f"location cannot be empty")
    if not key:
        raise KeyError(f"key cannot be empty for {location}")

    location = f"{location}['{key}']"
    if cfg is None:
        raise ValueError(f"cfg must be defined for {location}")

    if cfg:
        value = cfg.get(key)

        if not value:
            value = default
    else:
        value = default

    if (kind != bool) and not default:
        raise ValueError(f"{location} default cannot be empty")
    if not isinstance(value, kind):
        raise ValueError(f"{location} must be a {kind}, not a {type(value)}")

    cfg[key] = value

    return value


def get_string_list(location: str, key: str, cfg: None | dict) -> list[str]:
    return get_string_list_plurals(location, {key}, cfg)


def get_string_list_plurals(location: str, keys: set[str], cfg: None | dict) -> list[str]:
    return _get_list_plurals(location, keys, cfg, str)


def get_dict_list_plurals(location: str, keys: set[str], cfg: None | dict) -> list[dict]:
    return _get_list_plurals(location, keys, cfg, dict)


def _get_list_plurals(location: str, keys: set[str], cfg: None | dict, value_type: type) -> list:
    # combine all all the values from all the keys into a single set
    # this allows something like foo: bar or foos: [ bar, baz ]
    # silently ignores empty strings
    if not location:
        raise ValueError("location cannot be empty")
    if not keys:
        raise KeyError(f"keys cannot be empty for {location}")
    if cfg is None:
        raise ValueError(f"cfg must be defined for {location}")

    unique_values = set()
    values = []

    for key in keys:
        if not key:
            raise ValueError(f"{location} cannot have an empty key in {keys}")

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
                    raise ValueError(f"invalid {location}['{key}'] value '{value}'; it must be a {value_type}")
                if value:
                    # only add hashable values once
                    if isinstance(value, Hashable):
                        if value not in unique_values:
                            unique_values.add(value)
                            values.append(value)
                    else:
                        values.append(value)
        else:
            raise ValueError(
                f"{location}['{key}'] must be a {value_type} or list of {value_type}, not {type(cfg[key])}")

    # note not checking if values is empty
    # all calls to these functions are currently for optional config params

    return values


def configure_defaults(location: str, default_config: dict, default_types: dict, cfg: dict):
    if not location:
        raise ValueError(f"location cannot be empty")
    if not default_config:
        raise ValueError("default_config must be defined for {location}")
    if not default_types:
        raise ValueError("default_types must be defined for {location}")
    if cfg is None:
        raise ValueError(f"cfg must be defined for {location}")
    if len(default_config) != len(default_types):
        raise ValueError(f"default_config and default_types must be the same size for {location}")

    for key in default_config:
        if key not in default_types:
            raise KeyError(f"{location}['{key}'] does not define a type")

        use_default = False

        if key in cfg:
            value = cfg[key]
        else:
            value = default_config[key]
            use_default = True

        kind = default_types[key]

        if not isinstance(value, kind):
            raise KeyError(f"{location}['{key}'] value '{value}' is {type(value)} not {kind}")
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

    # mac address case is up to the client, but upper() for regex here
    if not _VALID_MAC.match(mac_address.upper()):
        raise ValueError(f"invalid mac_address '{mac_address}' for {location}")
