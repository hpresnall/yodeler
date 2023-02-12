"""Utility functions for parsing & validating configuration values.

These functions will raise ValueErrors or KeyErrors for invalid values.
"""


def non_empty_dict(name: str, value: object) -> dict:
   return  _non_empty(name, value, dict)


def non_empty_list(name: str, value: object) -> list:
    return _non_empty(name, value, list)


def _non_empty(name: str, value, kind: type) -> object:
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

    return value


def non_empty_string(key: str, cfg: dict, dict_name: str) -> str:
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
        raise KeyError(f"{dict_name}['{key}'] must be a string")
    if not value:
        raise KeyError(f"{dict_name}['{key}'] cannot be an empty string")

    return value


def set_default_string(key: str, cfg: None | dict, default: str):
    if not key:
        raise ValueError("key cannot be empty")
    if cfg is None:
        raise ValueError("cfg cannot be None")
    if not default:
        raise ValueError("default cannot be empty")

    value = cfg.get(key)

    if not value:
        value = default

    cfg[key] = value


def read_string_list_plurals(keys: set[str], cfg: dict, value_name: str) -> set[str]:
    # combine all all the values from all the keys into a single set
    # this allows something like foo: bar or foos: [ bar, baz ]
    values = set()
    for key in keys:
        values.update(read_string_list(key, cfg, value_name))
    return values


def read_string_list(key: str, cfg: dict, value_name: str) -> set[str]:
    if not key:
        raise ValueError("key cannot be empty")
    if cfg is None:
        raise ValueError("cfg cannot be None")
    if not value_name:
        raise ValueError("value_name cannot be empty")

    values = set()

    if key not in cfg:
        return values

    if isinstance(cfg[key], str):
        values.add(cfg[key])
    elif isinstance(cfg[key], list):
        for value in cfg[key]:
            if not isinstance(value, str):
                raise KeyError(f"invalid {value_name} value '{value}'; it must be a string")
            values.add(value)
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
            raise KeyError(f"{key} in {config_name} does not define a type")

        value = cfg.setdefault(key, default_config[key])

        if isinstance(value, set):
            # YAML does not support sets so this value has be configured in code; assume config already checked
            continue

        kind = default_types[key]

        if not isinstance(value, kind):
            raise KeyError(f"{key} value '{value}' in {config_name} is {type(value)} not {kind}")
        # some default values can be empty; so do not check here
