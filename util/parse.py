"""Utility functions for parsing & validating configuration values.

These functions will raise ValueErrors or KeyErrors for invalid values.
"""


def non_empty_dict(name: str, value: any):
    _non_empty(name, value, dict)


def non_empty_list(name: str, value: any):
    _non_empty(name, value, list)


def _non_empty(name: str, value: any, kind: type):
    if not name:
        raise ValueError("name cannot be empty")
    if value is None:
        raise ValueError("value cannot be None")
    if not kind:
        raise ValueError("kind cannot be empty")

    if value is None:
        raise ValueError(f"{name} cannot be empty")
    if not isinstance(value, kind):
        raise ValueError(f"{name} must be a {kind}, not a {type(value)}")
    if len(value) == 0:
        raise ValueError(f"{name} cannot be empty")


def non_empty_string(key: str, cfg: dict, dict_name: str) -> str:
    if not key:
        raise ValueError("key cannot be empty")
    if cfg is None:
        raise ValueError("config cannot be None")
    if not dict_name:
        raise ValueError("dict_name cannot be empty")

    if key not in cfg:
        raise KeyError(f"{key} not in {dict_name}")

    value = cfg[key]
    if not isinstance(value, str):
        raise KeyError(f"{dict_name}['{key}'] must be a string")
    if not value:
        raise KeyError(f"{dict_name}['{key}'] cannot be an empty string")

    return value


def read_string_list(key: str, cfg: dict, value_name: str) -> list[str]:
    if not key:
        raise ValueError("key cannot be empty")
    if cfg is None:
        raise ValueError("config cannot be None")
    if not value_name:
        raise ValueError("value_name cannot be empty")

    values = []

    if key not in cfg:
        return values

    if isinstance(cfg[key], str):
        values.append(cfg[key])
    elif isinstance(cfg[key], list):
        for value in cfg[key]:
            if not isinstance(value, str):
                raise KeyError(f"invalid {value_name} value '{value}'; it must be a string")
            values.append(value)
    else:
        raise KeyError(f"{key} for {value_name} must be a str or list, not {type(cfg[key])}")

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
            raise KeyError(f"{key} in '{config_name}' does not define a type")

        if key not in cfg:
            cfg[key] = default_config[key]

        value = cfg[key]
        kind = default_types[key]

        if not isinstance(value, kind):
            raise KeyError(f"{key} value '{value}' in '{config_name}' is {type(value)} not {kind}")
        # some default values can be empty; so do not check here
