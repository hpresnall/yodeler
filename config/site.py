"""Site is responsible for loading all configuration for a given site.
It also creates the final, static set of configuration files for each host at the site.
"""
import logging
import os
import copy

import util.file as file
import util.parse as parse

import config.vswitch as vswitch
import config.host as host

import roles.role

_logger = logging.getLogger(__name__)


def load(site_dir: str | None) -> dict:
    """Load 'site.yaml' from the given directory and validate it. This method also loads and validates all the host's
    configurations for the site.

    Return the site configuration that can be used in a subsequent call to write_host_scripts().
    """
    if not site_dir:
        raise ValueError("site_dir cannot be empty")

    site_dir = os.path.abspath(site_dir)

    _logger.info("loading site config from '%s'", site_dir)

    site_yaml = file.load_yaml(os.path.join(site_dir, "site.yaml"))

    parse.set_default_string("site_name", site_yaml, os.path.basename(site_dir))

    site_cfg = validate(site_yaml)

    _load_all_hosts(site_cfg, site_dir)

    _logger.debug("loaded site '%s' from '%s'", site_cfg["site_name"], site_dir)

    return site_cfg


def validate(site_yaml: dict | str | None) -> dict:
    """Validate the given YAML formatted site configuration.

    This configuration _is not_ valid for creating a set of scripts for a specific host.
    Instead, this configuration must be used as the base for loading host YAML files.
    """
    site_yaml = parse.non_empty_dict("site_yaml", site_yaml)

    parse.non_empty_string("site_name", site_yaml, "site_yaml")

    site_cfg = copy.deepcopy(site_yaml)

    host.validate_site_defaults(site_cfg)

    vswitch.validate(site_cfg)

    # map hostname to host config
    site_cfg["hosts"] = {}
    # map roles to fully qualified domain names; shared with host configs
    site_cfg["roles_to_hostnames"] = {}

    return site_cfg


def _load_all_hosts(site_cfg: dict, site_dir: str):
    """Load and validate all host YAML files for the given site."""
    _logger.debug("loading hosts for site '%s'", site_cfg["site_name"])

    for host_path in os.listdir(site_dir):
        if host_path == "site.yaml":
            continue
        if not host_path.endswith(".yaml"):
            _logger.debug("skipping file %s", host_path)
            continue

        host.load(site_cfg, os.path.join(site_dir, host_path))

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
            hostnames = site_cfg["roles_to_hostnames"][role_name] if role_name in site_cfg["roles_to_hostnames"] else []

        count = len(hostnames)

        if count < role_class.minimum_instances(site_cfg):
            raise ValueError((f"role '{role_name}' requires at least {role_class.minimum_instances(site_cfg)} host defined;"
                              f" site '{site_cfg['site_name']}' has {count} hosts: {hostnames}"))
        if count > role_class.maximum_instances(site_cfg):
            raise ValueError((f"role '{role_name}' cannot have more than {role_class.minimum_instances(site_cfg)} host defined;"
                              f" site '{site_cfg['site_name']}' has {count} hosts: {hostnames}"))

    # confirm all hostnames and aliases are unique
    aliases = set()
    for host_cfg in site_cfg["hosts"].values():
        aliases.update(host_cfg["aliases"])

    hostnames = set()
    for host_cfg in site_cfg["hosts"].values():
        hostname = host_cfg["hostname"]

        if hostname in hostnames:
            raise KeyError("duplicate hostname '{hostname}'")
        if hostname in aliases:
            raise KeyError("hostname '{hostname}' cannot be the same as another host's alias")

        hostnames.add(hostname)

    for host_cfg in site_cfg["hosts"].values():
        for role in host_cfg["roles"]:
            role.validate()
