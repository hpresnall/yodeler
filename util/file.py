"""Shared helper functions.
"""

import os
import string
import yaml

try:
    loader, dumper = yaml.CLoader, yaml.CDumper
except ImportError:
    loader, dumper = yaml.Loader, yaml.Dumper


def read(path, base_dir=None):
    if base_dir is not None:
        path = os.path.join(base_dir, path)

    with open(path) as f:
        return f.read()


def write(path, data, base_dir=None):
    if base_dir is not None:
        path = os.path.join(base_dir, path)

    with open(path, "w", newline='\n') as f:
        return f.write(data)


def substitute(path, cfg):
    # use $UPPERCASE in scripts
    upper_cfg = {k.upper(): v for (k, v) in cfg.items()}
    template = string.Template(read(path))
    return template.substitute(**upper_cfg)


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as f:
        return yaml.load(f, Loader=loader)


def load_yaml_string(string):
    return yaml.load(string, Loader=loader)


def output_yaml(y):
    return yaml.dump(y)
