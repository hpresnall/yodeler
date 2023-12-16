"""Handles parsing and validating host configuration from YAML files."""
import logging
import os
import shutil
import sys
import re

import util.file as file
import util.shell as shell
import util.parse as parse

import config.interface as interface

import roles.role
import roles.common

import ipaddress

_logger = logging.getLogger(__name__)

_valid_hostname = "^[A-Za-z0–9][A-Za-z0–9\\-]{1,63}[A-Za-z0–9]$"

def load(site_cfg: dict, host_path: str | None) -> dict:
    """Load the given host YAML file from given path, using the existing site config.

    Return a configuration that is a combination of the site and host configuration.
    This merged configuration is valid for creating a set of scripts for a specific host.
    """
    if not host_path:
        raise ValueError("host_path cannot be empty")

    host_path = os.path.abspath(host_path)

    _logger.info("loading host config from '%s'", os.path.basename(host_path))

    host_yaml = file.load_yaml(host_path)

    parse.set_default_string("hostname", host_yaml, os.path.basename(host_path)[:-5])  # remove .yaml

    host_cfg = validate(site_cfg, host_yaml)

    _logger.debug("loaded host '%s' from '%s'", host_cfg["hostname"], host_path)

    return host_cfg


def validate(site_cfg: dict | str | None, host_yaml: dict | str | None) -> dict:
    """Validate the given YAML formatted host configuration.

    Returns a configuration file that is a combination of the site and host configuration.
    This merged configuration is valid for creating a set of scripts for a specific host.
    """
    site_cfg = parse.non_empty_dict("site_cfg", site_cfg)
    host_yaml = parse.non_empty_dict("host_yaml", host_yaml)

    hostname = parse.non_empty_string("hostname", host_yaml, "host_yaml").lower()  # lowercase for consistency

    if not re.match(_valid_hostname, hostname):
        raise ValueError(f"invalid hostname '{hostname}'")
    if hostname in site_cfg["hosts"]:
        raise ValueError(f"duplicate hostname '{hostname}'")
    if hostname in site_cfg["firewall"]["static_hosts"]:
        raise ValueError(f"duplicate hostname '{hostname}' in firewall.static_hosts")
    host_yaml["hostname"] = hostname

    # silently ignore attempts to overwrite site config
    host_yaml.pop("vswitches", None)
    host_yaml.pop("firewall", None)
    host_yaml.pop("external_ntp", None)
    host_yaml.pop("external_dns", None)

    # shallow copy site config; host values overwrite site values
    host_cfg = {**site_cfg, **host_yaml}

    # since site_cfg is shared with all host's config, all hosts can find other hosts
    site_cfg["hosts"][hostname] = host_cfg

    _set_defaults(host_cfg)

    _load_roles(host_cfg)

    # order matters here
    # add all interfaces, then validate
    for role in host_cfg["roles"]:
        role.configure_interfaces()
    interface.validate(host_cfg)

    # aliases are validated against other hosts, interface vlan DHCP reservations and firewall static hosts
    _configure_aliases(host_cfg)

    # add any additional configuration; this may include aliases
    for role in host_cfg["roles"]:
        role.additional_configuration()

    # allow role.additional_packages() to use interfaces, aliases and additional config
    _configure_packages(site_cfg, host_yaml, host_cfg)

    # note role.validate() is called _after_ all hosts are loaded

    return host_cfg


def write_scripts(host_cfg: dict, output_dir: str):
    """Create the configuration scripts and files for the host and write them to the given directory."""
    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug(file.output_yaml(host_cfg))

    host_dir = os.path.join(output_dir, host_cfg["hostname"])

    _logger.info("writing setup scripts for '%s'", host_cfg["hostname"])

    if os.path.exists(host_dir):
        _logger.debug("removing existing host configuration scripts from '%s'", host_dir)
        shutil.rmtree(host_dir)
    os.mkdir(host_dir)

    # create a setup script that sources all the other scripts
    setup = shell.ShellScript("setup.sh")
    setup.comment("DO NOT run this script directly! It will be run in a chrooted environment _after_ installing Alpine.")
    setup.comment("Run yodel.sh instead!")
    setup.blank()
    setup.append_self_dir()
    setup.add_log_function()
    setup.append_rootinstall()

    # load any envvars passed in from bootstrap scripts
    setup.append("source /tmp/envvars")
    setup.blank()

    # add all scripts from each role
    for role in host_cfg["roles"]:
        name = role.name.upper()
        setup.append(f"echo \"########## {name} ##########\"")
        setup.append(f"log Configuring role {name}")
        setup.blank()
        try:
            role.write_config(setup, host_dir)
        except:
            _logger.fatal(("cannot run write_config for role '%s'"), role.name)
            raise
        setup.blank()

    setup.write_file(host_dir)

    if host_cfg["is_vm"]:
        _bootstrap_vm(host_cfg, host_dir)
    else:
        _bootstrap_physical(host_cfg, host_dir)

    _preview_dir(host_dir)


def validate_site_defaults(site_cfg: dict):
    # ensure overridden default values are the correct type and arrays only contain strings
    parse.configure_defaults("site_yaml", DEFAULT_SITE_CONFIG, _DEFAULT_SITE_CONFIG_TYPES, site_cfg)

    for key in ("alpine_repositories", "external_ntp", "external_dns"):
        site_cfg[key] = parse.read_string_list(key, site_cfg, f"site '{site_cfg['site_name']}'")

    for dns in site_cfg["external_dns"]:
        try:
            ipaddress.ip_address(dns)
        except ValueError as ve:
            raise KeyError(f"invalid 'external_dns' IP address {dns}") from ve


def _set_defaults(cfg: dict):
    for i, key in enumerate(_REQUIRED_PROPERTIES):
        if key not in cfg:
            raise KeyError(f"{key} not defined")

        value = cfg[key]
        kind = _REQUIRED_PROPERTIES_TYPES[i]

        if not isinstance(value, kind):
            raise KeyError(f"{key} value '{value}' in '{cfg['hostname']}' is {type(value)} not {kind}")

    parse.configure_defaults(cfg["hostname"], DEFAULT_CONFIG, _DEFAULT_CONFIG_TYPES, cfg)

    # remove from script output if not needed
    if not cfg["install_private_ssh_key"]:
        cfg["private_ssh_key"] = ""

    if not cfg["is_vm"]:
        # physical installs need a interface configure to download APKs and a disk to install the OS
        cfg.setdefault("install_interfaces", """auto lo
iface lo inet loopback
auto eth0
iface eth0 inet dhcp""")
        cfg.setdefault("root_dev", "/dev/sda")
        cfg.setdefault("root_partition", "3")

        parse.non_empty_string("install_interfaces", cfg, cfg["hostname"] + " cfg")
        parse.non_empty_string("root_dev", cfg, cfg["hostname"] + " cfg")
        parse.non_empty_string("root_partition", cfg, cfg["hostname"] + " cfg")

    # also called in site.py; this call ensures overridden values from the host are also valid
    validate_site_defaults(cfg)


def _load_roles(cfg: dict):
    # list of role names in yaml => list of Role subclass instances

    # allow both 'role' and 'roles'; only store 'roles'
    role_names = set(parse.read_string_list_plurals({"role", "roles"}, cfg, "role for " + cfg["hostname"]))
    cfg.pop("role", None)

    # Common _must_ be the first so it is configured and setup first
    common = roles.role.load("common", cfg)
    common.configure_interfaces()
    cfg["roles"] = [common]
    role_names.discard("common")

    # router or fakeisp must be next so all interfaces are configured before other roles use them
    # vmhost renames existing interfaces
    ordered_roles = []

    if "router" in role_names:
        ordered_roles.append("router")
        role_names.discard("router")
    if "fakeisp" in role_names:
        ordered_roles.append("fakeisp")
        role_names.discard("fakeisp")
    if "vmhost" in role_names:
        ordered_roles.append("vmhost")
        role_names.discard("vmhost")

    ordered_roles.extend(role_names)

    for role_name in ordered_roles:
        _logger.debug("loading role '%s' for '%s'", role_name, cfg["hostname"])

        role_name = role_name.lower()
        role = roles.role.load(role_name, cfg)

        cfg["roles"].append(role)

        # assume roles_to_hostnames is shared by site and all hosts
        # note common role is _not_ added to this dict
        if role_name not in cfg["roles_to_hostnames"]:
            cfg["roles_to_hostnames"][role_name] = []

        cfg["roles_to_hostnames"][role_name].append(cfg['hostname'])


def _configure_aliases(cfg: dict):
    hostname = cfg["hostname"]
    # allow both 'alias' and 'aliases'; only store 'aliases'
    aliases = parse.read_string_list_plurals(
        {"alias", "aliases"}, cfg, "alias for " + cfg["hostname"])
    cfg.pop("alias", None)

    # final set of aliases is all defined values plus roles
    cfg["aliases"] = set()

    for alias in aliases:
        if not re.match(_valid_hostname, alias):
            raise ValueError(f"invalid alias '{alias}' for host '{hostname}'")
        cfg["aliases"].add(alias.lower())

    for role in cfg["roles"]:
        if role.name != "common":
            role.add_alias(role.name)  # role names are already lowercase

    # ensure hostname is not duplicated by a role
    cfg["aliases"].discard(cfg["hostname"])

    for alias in cfg["aliases"]:
        if alias in cfg["firewall"]["static_hosts"]:
            raise ValueError(f"alias '{alias}' for host '{hostname}' is already used in firewall.static_hosts")

        # ensure no clashes with other hosts; site.py already checked for duplicate hostnames
        for other_hostname, other_host in cfg["hosts"].items():
            if other_hostname == hostname:
                continue
            if alias in other_host["aliases"]:
                raise ValueError(f"alias '{alias}' for host '{hostname}' is already used as an alias for '{other_hostname}'")

    # ensure no clashes with DHCP reservations
    aliases = set(cfg["aliases"])
    aliases.add(cfg["hostname"])

    for iface in cfg["interfaces"]:
        if iface["type"] not in {"std", "vlan"}:
            continue

        vlan = iface["vlan"]["name"]
        vlan_aliases = iface["vlan"]["known_aliases"]

        if not aliases.isdisjoint(vlan_aliases):
            raise ValueError(
                f"vlan '{vlan}' contains DHCP reservations {aliases.intersection(vlan_aliases)} that conflict with a global hostname or alias")

    # cannot check against all aliases in the site here since all hosts may not have been defined


def _configure_packages(site_cfg: dict, host_yaml: dict, host_cfg: dict):
    # manually merge packages use set for uniqueness and union/intersection operations
    for key in ["packages", "remove_packages"]:
        site = site_cfg.get(key)
        host = host_yaml.get(key)

        if site is None:
            site = set()
        if host is None:
            host = set()

        # combine; host overwrites site
        host_cfg[key] = set(site)
        host_cfg[key] |= set(host)

    for role in host_cfg["roles"]:
        host_cfg["packages"] |= role.additional_packages()

    # update packages based on config
    if host_cfg["metrics"]:
        host_cfg["packages"].add("prometheus-node-exporter")

     # remove iptables if there is no local firewall
    if not host_cfg["local_firewall"]:
        host_cfg["remove_packages"] |= {"iptables"}
        host_cfg["packages"].discard("awall")

    if not host_cfg["is_vm"]:
        # add cpufreq and other utils to real hosts
        host_cfg["packages"] |= {"util-linux", "cpufreqd", "cpufrequtils"}

    # resolve conflicts in favor of adding the package
    host_cfg["remove_packages"] -= host_cfg["packages"]

    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug("adding packages %s", host_cfg["packages"])
        _logger.debug("removing packages %s", host_cfg["remove_packages"])


def _bootstrap_physical(cfg: dict, output_dir: str):
    # boot with install media; run /media/<install_dev>/<site>/<host>/yodel.sh
    # setup.sh will run in the installed host via chroot
    yodel = shell.ShellScript("yodel.sh")
    yodel.comment("Run this script to configure a Yodeler physical server")
    yodel.comment("Run in a booted Alpine Linux install image")
    yodel.blank()
    yodel.append_self_dir()
    yodel.substitute("templates/physical/ensure_writable.sh", cfg)
    yodel.setup_logging(cfg["hostname"])
    yodel.substitute("templates/physical/create_physical.sh", cfg)
    yodel.write_file(output_dir)

    # create Alpine setup answerfile
    # use external DNS for initial Alpine setup
    cfg["external_dns_str"] = " ".join(cfg["external_dns"])
    file.write("answerfile", file.substitute("templates/physical/answerfile", cfg), output_dir)


def _bootstrap_vm(cfg: dict, output_dir: str):
    # setup.sh will run in the VM via chroot
    yodel = shell.ShellScript("yodel.sh")
    yodel.comment("Run this script to configure a Yodeler VM")
    yodel.comment("Run in a KVM host configured by Yodeler")
    yodel.blank()
    yodel.append_self_dir()
    yodel.setup_logging(cfg["hostname"])
    yodel.substitute("templates/vm/create_vm.sh", cfg)
    yodel.write_file(output_dir)

    # helper script to delete VM image & remove VM
    delete_vm = shell.ShellScript("delete_vm.sh", errexit=False)
    delete_vm.substitute("templates/vm/delete_vm.sh", cfg)
    delete_vm.write_file(output_dir)

    # helper script to start VM
    start_vm = shell.ShellScript("start_vm.sh", errexit=False)
    start_vm.substitute("templates/vm/start_vm.sh", cfg)
    start_vm.write_file(output_dir)


def _preview_dir(output_dir: str, line_count: int = sys.maxsize):
    """Debug function that recursively logs the content of all files in the given directory.
    By default logs the the whole file. Use the line_count to limit the number of lines output for each file."""
    if not _logger.isEnabledFor(logging.DEBUG):
        return

    _logger.debug(output_dir)
    _logger.debug("")

    for file in os.listdir(output_dir):
        path = os.path.join(output_dir, file)

        if not os.path.isfile(path):
            _preview_dir(path, line_count)
            continue

        line_count = 0
        lines = [path + "\n"]

        with open(path) as file:
            for line in file:
                if line_count > line_count:
                    break

                line_count += 1
                lines.append(line)
        _logger.debug("".join(lines))


# properties that are unique and cannot be set as defaults
# usually set by the site and copied to the host
_REQUIRED_PROPERTIES = ["site_name", "public_ssh_key"]
_REQUIRED_PROPERTIES_TYPES = [str, str]

# site-level properties defined here since they should be checked when loading the site YAML _and_ for each host YAML
# accessible for testing
DEFAULT_SITE_CONFIG = {
    "timezone": "UTC",
    "keymap": "us us",
    # note sets here for comparisions on test, but list type in _TYPES since that is what YAML will load
    # running type will also be parsed as sets
    "alpine_repositories": ["http://dl-cdn.alpinelinux.org/alpine/latest-stable/main", "http://dl-cdn.alpinelinux.org/alpine/latest-stable/community"],
    "external_ntp": ["0.pool.ntp.org", "1.pool.ntp.org", "2.pool.ntp.org", "3.pool.ntp.org"],
    "external_dns": ["8.8.8.8", "9.9.9.9", "1.1.1.1"],
    "metrics": True,
    # top-level domain for the site; empty => no local DNS
    "domain": "",
    # if not specified, no SSH access will be possible!
    "user": "nonroot",
    "password": "apassword",
    "before_chroot": "# no configuration needed before chroot"
}

_DEFAULT_SITE_CONFIG_TYPES = {
    "timezone": str,
    "keymap": str,
    "alpine_repositories": list,
    "external_ntp": list,
    "external_dns": list,
    "metrics": bool,
    "domain": str,
    "user": str,
    "password": str,
    "before_chroot": str
}

# accessible for testing
DEFAULT_CONFIG = {
    "is_vm": True,
    "autostart": True,
    "host_share": True,
    "host_backup": True,
    "vcpus": 1,
    "memory_mb": 128,
    "disk_size_mb": 256,
    "image_format": "raw",
    "vm_images_path": "/vmstorage",
    # configure a local firewall and metrics on all systems
    "local_firewall": True,
    "motd": "",
    # do not install private ssh key on every host
    "install_private_ssh_key": False,
    # domain for the host when it has multiple interfaces; used for DNS search
    "primary_domain": ""
}

_DEFAULT_CONFIG_TYPES = {
    "is_vm": bool,
    "autostart": bool,
    "host_share": bool,
    "host_backup": bool,
    "vcpus": int,
    "memory_mb": int,
    "disk_size_mb": int,
    "image_format": str,
    "vm_images_path": str,
    "root_dev": str,
    "root_partition": str,  # default disk layout puts /root on /dev/sda3
    "local_firewall": bool,
    "motd": str,
    "install_private_ssh_key": bool,
    "primary_domain": str,
    "install_interfaces": str
}
