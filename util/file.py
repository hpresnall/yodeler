"""Utility functions for handling files."""

import os
import string
import yaml
import json
import shutil

try:
    loader, dumper = yaml.CLoader, yaml.CDumper
except ImportError:
    loader, dumper = yaml.Loader, yaml.Dumper


def read(path: str, base_dir=None):
    """Read the entire file into a string."""
    if base_dir is not None:
        path = os.path.join(base_dir, path)

    with open(path) as file:
        return file.read()


def write(path: str, data_str: str, base_dir=None):
    """Write the given string to a file."""
    if base_dir is not None:
        path = os.path.join(base_dir, path)

    with open(path, "w", newline='\n') as file:
        return file.write(data_str)


def substitute(path: str, cfg: dict):
    """Read the given file and do $variable substitution from the given config. Return the content as a string."""
    # use $UPPERCASE in scripts
    upper_cfg = {k.upper(): v for (k, v) in cfg.items()}
    template = string.Template(read(path))
    return template.substitute(**upper_cfg)


def load_yaml(path: str):
    """Load the given YAML file into an object tree."""
    with open(path, "r", encoding="utf-8") as file:
        return yaml.load(file, Loader=loader)


def load_yaml_string(yaml_str: str):
    """Load the given YAML string into an object tree."""
    return yaml.load(yaml_str, Loader=loader)


def output_yaml(data: object):
    """Output the object tree to a YAML string."""
    return yaml.dump(data, indent=2)


def load_json(path: str):
    """Load the given JSON file into an object tree."""
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_json_string(json_str: str):
    """Load the given JSON string into an object tree."""
    return json.loads(json_str)


def output_json(data: object):
    """Output the object tree to a JSON string."""
    return json.dumps(data, indent=2)


def copy_template(role_name: str, file_name: str,  output_dir: str):
    shutil.copy(os.path.join("templates", role_name, file_name), output_dir)
