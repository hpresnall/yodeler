"""Site is responsible for loading all configuration for a given site.
It also creates the final, static set of configuration files for each host at the site.
"""
import logging
import os
import shutil
import sys

import config.yaml as yaml

import util.shell as shell
import util.file as file

_logger = logging.getLogger(__name__)


def load_site(site_path):
    """Load to configuration for all hosts defined in the given site.
    Return a the site configuration as a map."""
    site_path = os.path.abspath(site_path)

    site_cfg = _load_site_config(site_path)

    _logger.info("processing hosts for site '%s'", site_cfg["name"])

    # TODO proper role hierarchy and ordering
    required_roles = set()  # {"dns", "router"}
    defined_roles = set()

    for path in os.listdir(site_path):
        if path == "site.yaml":
            continue

        host_cfg = _load_host_config(site_cfg, path)

        if host_cfg["is_vm"]:
            required_roles.add("vmhost")

        for role in host_cfg["roles"]:
            if (role.name != "common") and (role.name in defined_roles):
                raise Exception(
                    f"cannot have more than one {role.name} server for site {site_cfg['name']}")
            defined_roles.add(role.name)

            if role.name == "router":
                _confgure_router_hosts(host_cfg)

    for role in required_roles:
        if role not in defined_roles:
            raise Exception(
                f"required role {role} not defined for site {site_cfg['site']}")

    return site_cfg


def write_host_configs(site_cfg, output_dir):
    """Create all the configuration scripts and files for the host
    and write them to the given directory."""

    _logger.info("writing setup scripts for site to '%s'", output_dir)

    for host_cfg in site_cfg["hosts"].values():
        _logger.debug(file.output_yaml(host_cfg))
        host_dir = os.path.join(output_dir, host_cfg["hostname"])

        _logger.info("creating setup scripts for '%s'", host_cfg["hostname"])

        if os.path.exists(host_dir):
            _logger.warning(
                "removing existing host configuration scripts from '%s'", host_dir)
            shutil.rmtree(host_dir)
        os.mkdir(host_dir)

        # create a setup script that sources all the other scripts
        setup_script = shell.ShellScript("setup.sh")
        setup_script.append_self_dir()
        setup_script.append_rootinstall()

        setup_script.append(f"echo \"Setting up {host_cfg['hostname']}\"\n")

        # add all scripts from each role
        for role in host_cfg["roles"]:
            try:
                for script in role.create_scripts(host_cfg, host_dir):
                    setup_script.append(". $DIR/" + script)
            except (TypeError, AttributeError):
                _logger.fatal(("cannot run create_scripts on class %s; "
                               "it should have a create_scripts(cfg, output_dir) function "
                               "that returns an iterable list of scripts"), role)
                raise

        setup_script.write_file(host_dir)

        preview_dir(host_dir)


def _load_site_config(sites_dir):
    site_cfg = yaml.load_site_config(sites_dir)
    site_cfg["name"] = os.path.basename(sites_dir)
    site_cfg["hosts"] = {}  # map hostname to host config
    # map roles to fully qualified domain names; shared with host configs
    site_cfg["roles_to_hostnames"] = {}

    _logger.info("loaded config for site '%s'", site_cfg["name"])

    return site_cfg


def _load_host_config(site_cfg, host_path):
    hostname = host_path[:-5]  # remove .yaml

    _logger.info("loading config for host '%s' from %s", hostname, os.path.basename(host_path))

    host_cfg = yaml.load_host_config(
        site_cfg, hostname)
    _add_host_dns_to_vlans(host_cfg)
    _map_role_to_fqdn(host_cfg, site_cfg["roles_to_hostnames"])

    site_cfg["hosts"][host_cfg["hostname"]] = host_cfg

    return host_cfg


def _add_host_dns_to_vlans(cfg):
    # add hostname information for DNS
    # assume site config and vswitch & vlan objects are shared by all configs
    for iface in cfg["interfaces"]:
        vlan = iface["vlan"]

        # no domain name => no DNS
        if vlan["domain"] == "":
            continue
        vlan["hosts"].append({
            "hostname": cfg["hostname"],
            "ipv4_address": iface["ipv4_address"],
            "ipv6_address": iface["ipv6_address"],
            "mac_address": None,
            "aliases": [role.name for role in cfg["roles"] if role.name != "common"]})


def _map_role_to_fqdn(cfg, role_fqdn):
    # map roles to fully qualified domain names
    # used by DNS to configure the top-level domain
    cfg["roles_to_hostnames"] = role_fqdn

    if cfg["primary_domain"] == "":
        return

    fqdn = cfg["hostname"] + "." + cfg["primary_domain"]

    for role in cfg["roles"]:
        if role.name == "common":
            continue

        role_fqdn[role.name] = fqdn


def _confgure_router_hosts(cfg):
    # manually add host entries for router interfaces since they are defined automatically
    # assume site config and vswitch & vlan objects are shared by all configs
    for vswitch in cfg["vswitches"].values():
        for vlan in vswitch["vlans"]:
            if vlan["routable"]:
                vlan["hosts"].append({
                    "hostname": cfg["hostname"],
                    "ipv4_address": vlan["ipv4_subnet"].network_address + 1,
                    "ipv6_address": vlan["ipv6_subnet"].network_address + 1,
                    "mac_address": None,
                    "aliases": ["router"]})


def preview_dir(output_dir, limit=sys.maxsize):
    """Output all files in the given directory, up to the limit number of lines per file."""
    _logger.debug(output_dir)
    _logger.debug("")

    for file in os.listdir(output_dir):
        path = os.path.join(output_dir, file)

        if not os.path.isfile(path):
            preview_dir(path, limit)
            continue

        _logger.debug("**********")
        _logger.debug(path)
        _logger.debug("")
        line_count = 0
        with open(path) as file:
            for line in file:
                if line_count > limit:
                    break
                line_count += 1
                _logger.debug(line, end='')
        _logger.debug("")
