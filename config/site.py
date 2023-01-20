"""Site is responsible for loading all configuration for a given site.
It also creates the final, static set of configuration files for each host at the site.
"""
import logging
import os
import copy

import util.file as file

import config.vswitch as vswitch
import config.host as host

import roles.role

_logger = logging.getLogger(__name__)


def load(site_dir: str) -> dict:
    """Load 'site.yaml' from the given directory and validate it. This method also loads and validates all the host
    configuration for the site.

    Return the site configuration that can be used in a subsequent call to write_host_configs().
    """
    if not site_dir:
        raise ValueError("site_dir cannot be empty")

    site_dir = os.path.abspath(site_dir)

    _logger.info("loading site config from '%s'", site_dir)

    site_yaml = file.load_yaml(os.path.join(site_dir, "site.yaml"))

    if "site_name" not in site_yaml:
        site_yaml["site_name"] = os.path.basename(site_dir)
    site_yaml["site_dir"] = site_dir

    site_cfg = validate(site_yaml)

    _load_all_hosts(site_cfg)

    _logger.debug("loaded site '%s' from '%s'", site_cfg["site_name"], site_dir)

    return site_cfg


def validate(site_yaml: dict) -> dict:
    """Validate the given YAML formatted site configuration.

    This configuration _is not_ valid for creating a set of scripts for a specific host.
    Instead, this configuration must be used as the base for loading host YAML files.
    """
    if site_yaml is None:
        raise ValueError("empty site config")
    if not isinstance(site_yaml, dict):
        raise ValueError("site config must be a dictionary")

    if "site_name" not in site_yaml:
        raise KeyError("site_name cannot be empty")
    if not isinstance(site_yaml["site_name"], str):
        raise KeyError("site_name must be a string")
    if not site_yaml["site_name"]:
        raise KeyError("site_name cannot be empty")

    site_cfg = copy.deepcopy(site_yaml)

    for key in DEFAULT_CONFIG:
        if key not in site_cfg:
            site_cfg[key] = DEFAULT_CONFIG[key]

    vswitch.validate(site_cfg)

    # map hostname to host config
    site_cfg["hosts"] = {}
    # map roles to fully qualified domain names; shared with host configs
    site_cfg["roles_to_hostnames"] = {}

    return site_cfg


def _load_all_hosts(site_cfg: dict):
    """Load and validate all host YAML files for the given site."""
    _logger.debug("loading hosts for site '%s'", site_cfg["site_name"])

    # TODO proper role hierarchy and ordering
    required_roles = set()  # {"dns", "router"}
    defined_roles = set()

    site_dir = site_cfg["site_dir"]

    for host_path in os.listdir(site_dir):
        if host_path == "site.yaml":
            continue
        if not host_path.endswith(".yaml"):
            _logger.debug("skipping file %s", host_path)
            continue

        host_cfg = host.load(site_cfg, os.path.join(site_dir, host_path))

        if host_cfg["is_vm"]:
            required_roles.add("vmhost")

        for role in host_cfg["roles"]:
            if (role.name != "common") and (role.name in defined_roles):
                raise Exception(f"cannot have more than one {role.name} server for site '{site_cfg['site_name']}'")
            defined_roles.add(role.name)

    for role in required_roles:
        if role not in defined_roles:
            raise Exception(f"required role {role} not defined for site '{site_cfg['site_name']}'")

    _logger.debug("loaded %d hosts for site '%s'", len(site_cfg["hosts"]), site_cfg["site_name"])


def write_host_scripts(site_cfg: dict, output_dir: str):
    """Create the configuration scripts and files for the site's hosts and write them to the given directory."""
    _logger.info("writing setup scripts for site to '%s'", output_dir)

    _validate_site(site_cfg)

    for host_cfg in site_cfg["hosts"].values():
        host.write_scripts(host_cfg, output_dir)

def _validate_site(site_cfg: dict):
    # confirm site contains all necessary roles
    for role_class in roles.role.Role.__subclasses__():
        role_name = role_class.__name__.lower()

        if role_name == "common":
            hostnames = site_cfg["hosts"].keys()
        else:
            hostnames = site_cfg["roles_to_hostnames"][role_name]

        count = len(hostnames)

        if count < role_class.minimum_instances(site_cfg):
            raise ValueError((f"role '{role_name}' requires at least {role_class.minimum_instances()} host defined;"
                              f" site '{site_cfg['site_name']}' has {count} hosts: {hostnames}"))
        if count > role_class.maximum_instances(site_cfg):
            raise ValueError((f"role '{role_name}' cannot have more than {role_class.minimum_instances()} host defined;"
                              f" site '{site_cfg['site_name']}' has {count} hosts: {hostnames}"))

    for host_cfg in site_cfg["hosts"].values():
        for role in host_cfg["roles"]:
            role.validate()

# accessible for testing
DEFAULT_CONFIG = {
    "timezone": "UTC",
    "keymap": "us us",
    "alpine_repositories": ["http://dl-cdn.alpinelinux.org/alpine/latest-stable/main", "http://dl-cdn.alpinelinux.org/alpine/latest-stable/community"],
    "external_ntp": ["0.pool.ntp.org", "1.pool.ntp.org", "2.pool.ntp.org", "3.pool.ntp.org"],
    "external_dns": ["8.8.8.8", "9.9.9.9", "1.1.1.1"],
    "metrics": True,
    # top-level domain for the site; empty => no local DNS
    "domain": "",
    # if not specified, no SSH access will be possible!
    "user": "nonroot",
    "password": "apassword",
}
