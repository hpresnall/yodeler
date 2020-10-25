"""Setup is responsible for loading all configuration for a given site.
It also creates the final, static set of configuration files for each host at the site.
"""
import logging
import os
import shutil

import yodeler.config as config

import util.shell as shell

_logger = logging.getLogger(__name__)


def load_all_configs(sites_dir, site_name):
    """Load to configuration for all hosts defined in the given site.
    Return a map of hostnames to configurations."""
    sites_dir = os.path.join(os.path.abspath(sites_dir), site_name)
    site_cfg = _load_site_config(sites_dir)

    _logger.info("processing hosts for site '%s'", site_name)

    host_cfgs = {}
    role_fqdn = {}  # map roles to fully qualified domain names

    roles = set()

    for path in os.listdir(sites_dir):
        if path == "site.yaml":
            continue

        host_cfg = _load_host_config(site_cfg, path)
        host_cfgs[host_cfg["hostname"]] = host_cfg

        _configure_dns(host_cfg)
        _map_role_to_fqdn(host_cfg, role_fqdn)

        for role in host_cfg["roles"]:
            if (role.name != "common") and (role.name in roles):
                raise Exception(f"cannot redefine role {role.name} in {host_cfg['hostname']}")
            roles.add(role.name)

            if role.name == "router":
                _confgure_router_hosts(host_cfg)

    required_roles = {"vmhost", "dns", "router"}
    for role in required_roles:
        if role not in roles:
            raise Exception(f"required role {role} not defined for site {site_cfg['site']}")

    return host_cfgs


def _load_site_config(sites_dir):
    site_cfg = config.load_site_config(sites_dir)
    _logger.info("loaded config for site '%s' from %s", site_cfg["site"], sites_dir)
    return site_cfg


def _load_host_config(site_cfg, host_path):
    host_cfg = config.load_host_config(site_cfg, host_path[:-5])  # remove .yaml
    _logger.info("loaded config for '%s' from %s",
                 host_cfg["hostname"], os.path.basename(host_path))
    return host_cfg


def _configure_dns(cfg):
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


def create_scripts_for_host(cfg, output_dir):
    """Create all the configuration scripts and files for the host
    and write them to the given directory."""
    host_dir = os.path.join(output_dir, cfg["hostname"])
    cfg["config_dir"] = host_dir

    if os.path.exists(host_dir):
        _logger.warning("removing existing host configuration at %s", host_dir)
        shutil.rmtree(host_dir)

    _logger.info("creating setup scripts for %s", cfg["hostname"])

    # copy files from config directly
    shutil.copytree("config", host_dir)

    # create a setup script that sources all the other scripts
    setup_script = shell.ShellScript("setup.sh")
    setup_script.append_self_dir()
    setup_script.append_rootinstall()

    setup_script.append(f"echo \"Setting up {cfg['hostname']}\"\n")

    # add all scripts from each role
    for role in cfg["roles"]:
        try:
            for script in role.create_scripts(cfg, host_dir):
                setup_script.append(". $DIR/" + script)
        except (TypeError, AttributeError):
            _logger.fatal(("cannot run create_scripts on class %s; "
                           "it should have a create_scripts(cfg, output_dir) function "
                           "that returns an iterable list of scripts"), role)
            raise

    setup_script.write_file(host_dir)
