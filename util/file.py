"""Utility functions for handling files."""

import os
import string
import yaml

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
    """Read the given file and do $variable substitution from the given config."""
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
