"""Utility functions for handling files."""

import os
import string
import yaml
import json

try:
    loader, dumper = yaml.CLoader, yaml.CDumper
except ImportError:
    loader, dumper = yaml.Loader, yaml.Dumper


def read(path, base_dir=None):
    """Read the entire file into a string."""
    if base_dir is not None:
        path = os.path.join(base_dir, path)

    with open(path) as file:
        return file.read()


def write(path, data_str, base_dir=None):
    """Write the given string to a file."""
    if base_dir is not None:
        path = os.path.join(base_dir, path)

    with open(path, "w", newline='\n') as file:
        return file.write(data_str)


def substitute(path, cfg):
    """Read the given file and do $variable substitution from the given config. Return the content as a string."""
    # use $UPPERCASE in scripts
    upper_cfg = {k.upper(): v for (k, v) in cfg.items()}
    template = string.Template(read(path))
    return template.substitute(**upper_cfg)


def load_yaml(path):
    """Load the given YAML file into an object tree."""
    with open(path, "r", encoding="utf-8") as file:
        return yaml.load(file, Loader=loader)


def load_yaml_string(yaml_str):
    """Load the given YAML string into an object tree."""
    return yaml.load(yaml_str, Loader=loader)


def output_yaml(data):
    """Output the object tree to a YAML string."""
    return yaml.dump(data)

def load_json(path):
    """Load the given JSON file into an object tree."""
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def load_json_string(json_str):
    """Load the given JSON string into an object tree."""
    return json.load(json_str)


def output_json(data):
    """Output the object tree to a JSON string."""
    return json.dumps(data, indent=2)