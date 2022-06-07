"""Handles parsing and validating site and host YAML configuration files.

Site configuration is the base and defines defaults for each host.
Unless otherwise stated, any function that takes a configuration will
assume it is a dictionary returned from this module.
"""
import logging
import os.path
import ipaddress

import util.file
import util.interfaces

import roles.role
import roles.common

import config.vswitch
import config.interface


_logger = logging.getLogger(__name__)


def load_site_config(site_dir):
    """Load the base site configuration from the given site name.

    This config _is not_ valid for host configuration. load_host_config()
    _must_ be called to complete configuration."""
    site_dir = os.path.abspath(site_dir)
    site_cfg = util.file.load_yaml(os.path.join(site_dir, "site.yaml"))
    _logger.debug("loaded site YAML file from '%s'", site_dir)

    if site_cfg is None:
        raise KeyError("empty site config")

    site_cfg["site"] = os.path.basename(site_dir)
    site_cfg["site_dir"] = site_dir
    # also included in default_config
    # set here because it is needed by _validate_vswitches, _before_ the host
    # config is loaded and the defaults can be checked
    site_cfg["domain"] = site_cfg.get("domain", "")

    config.vswitch.validate(site_cfg)

    return site_cfg


def load_host_config(site_cfg, hostname):
    """Load the configuration for a given host, using the base site
    configuration.

    Rreturns a new configuration without modifying the site configuration.
    The site config _must_ be a valid configuration from load_site_config().
    The values from the host will override the site values."""
    if (site_cfg is None) or (len(site_cfg) == 0):
        raise KeyError("empty site config")

    host_dir = os.path.abspath(os.path.join(
        site_cfg["site_dir"], hostname + ".yaml"))
    host_cfg = util.file.load_yaml(host_dir)
    _logger.debug("loaded host YAML file for '%s' from '%s'", hostname, host_dir)

    if host_cfg is None:
        raise KeyError("empty host config")

    host_cfg["hostname"] = hostname
    host_cfg["host_path"] = host_dir

    # shallow copy
    cfg = {**site_cfg, **host_cfg}

    # manual merge of packages
    for key in ["packages", "remove_packages"]:
        site = site_cfg.get(key)
        host = host_cfg.get(key)

        if site is None and host is None:
            cfg[key] = set()
        elif site is None:
            cfg[key] = set(host)
        elif host is None:
            cfg[key] = set(site)
        else:
            cfg[key] = set(site)
            cfg[key] |= set(host)

    # if either site or host needs it, make sure the package is not removed
    cfg["remove_packages"] -= (cfg["packages"])

    _validate_config(cfg)
    _configure_roles(cfg)
    _configure_packages(cfg)

    config.interface.validate(cfg)

    return cfg


def config_from_string(config_string):
    """Load the configuration from the given string.

    This string must include _all_ required site and host elements.
    """
    cfg = util.file.load_yaml_string(config_string)
    return config_from_dict(cfg)


def config_from_dict(cfg):
    """Load the configuration from the given dictionary.

    This string must include _all_ required site and host elements.
    """
    if cfg is None:
        raise KeyError("empty config")

    _validate_config(cfg)
    _configure_roles(cfg)
    _configure_packages(cfg)
    config.vswitch.validate(cfg)
    config.interface.validate(cfg)

    return cfg


def _validate_config(cfg):
    for key in _REQUIRED_PROPERTIES:
        if key not in cfg:
            raise KeyError("{0} not defined".format(key))

    for key in DEFAULT_CONFIG:
        if key not in cfg:
            cfg[key] = DEFAULT_CONFIG[key]
    if "local_dns" not in cfg:
        cfg["local_dns"] = []

    # remove from script output if not needed
    if not cfg.get("install_private_ssh_key"):
        cfg["private_ssh_key"] = ""

    for dns in cfg["local_dns"]:
        try:
            ipaddress.ip_address(dns)
        except:
            raise KeyError(f"invalid local_dns IP address {dns}") from None
    for dns in cfg["external_dns"]:
        try:
            ipaddress.ip_address(dns)
        except:
            raise KeyError(f"invalid external_dns IP address {dns}") from None


def _configure_roles(cfg):
    # list of role names in yaml => list of Role subclass instances
    # Common _must_ be the first so it is configured and setup first
    role_names = set(cfg["roles"] if cfg.get("roles") is not None else [])
    cfg["roles"] = [roles.common.Common()]
    cfg["roles"][0].additional_configuration(cfg)

    # for each role, load the module, then the class
    # instantiate the class and overwrite the config
    for role in role_names:
        _logger.debug("loading module for %s role on %s", role, cfg["hostname"])

        role = role.lower()

        if role != "common":
            cfg["roles"].append(roles.role.load(role))
            cfg["roles"][-1].additional_configuration(cfg)


def _configure_packages(cfg):
    if "packages" in cfg:
        cfg["packages"] |= DEFAULT_PACKAGES
    else:
        cfg["packages"] = DEFAULT_PACKAGES

    if "remove_packages" not in cfg:
        cfg["remove_packages"] = set()

    for role in cfg["roles"]:
        cfg["packages"] |= role.additional_packages()

    # update packages based on config
    if cfg["metrics"]:
        cfg["packages"].add("prometheus-node-exporter")

     # remove iptables if there is no local firewall
    if not cfg["local_firewall"]:
        cfg["remove_packages"] |= {"iptables", "ip6tables"}
        cfg["packages"].discard("awall")

    # VMs are setup without USB, so remove the library
    if cfg["is_vm"]:
        cfg["remove_packages"].add("libusb")
    else:
        # add cpufreq and other utils to real hosts
        cfg["packages"] |= {"util-linux", "cpufreqd", "cpufrequtils"}

    # resolve conflicts in favor of adding the package
    cfg["remove_packages"] -= cfg["packages"]

    if _logger.isEnabledFor(logging.DEBUG):
        _logger.debug("adding packages %s", cfg["packages"])
        _logger.debug("removing packages %s", cfg["remove_packages"])


# properties that are unique and cannot be set as defaults
_REQUIRED_PROPERTIES = ["site", "hostname", "public_ssh_key"]

# accessible for testing
DEFAULT_PACKAGES = {"acpi", "doas", "openssh", "chrony", "awall", "dhclient"}
DEFAULT_CONFIG = {
    "is_vm": True,
    "vcpus": 1,
    "memory_mb": 128,
    "disk_size_mb": 256,
    "image_format": "raw",
    "vm_images_path": "/vmstorage",
    "root_dev": "/dev/sda",
    # configure a local firewall and metrics on all systems
    "local_firewall": True,
    "metrics": True,
    "motd": "",
    # do not install private ssh key on every host
    "install_private_ssh_key": False,
    # if not specified, no SSH access will be possible!
    "user": "nonroot",
    "password": "apassword",
    "timezone": "UTC",
    "keymap": "us us",
    "alpine_repositories": ["http://dl-cdn.alpinelinux.org/alpine/latest-stable/main"],
    "ntp_pool_servers": ["0.pool.ntp.org", "1.pool.ntp.org", "2.pool.ntp.org", "3.pool.ntp.org"],
    "external_dns": ["8.8.8.8", "9.9.9.9", "1.1.1.1"],
    # top-level domain for the site
    "domain": "",
    # domain for the host when it has multiple interfaces; used for DNS search
    "primary_domain": "",
    # for physical servers, manually specify contents of /etc/network/interfaces
    # default blank => installer will prompt
    "install_interfaces": ""
}
