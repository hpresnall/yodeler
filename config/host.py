"""Handles parsing and validating host configuration from YAML files."""
import logging
import os

import util.file as file

import config.interface as interface

import roles.common

import ipaddress

_logger = logging.getLogger(__name__)


def load(site_cfg: dict, host_path: str) -> dict:
    """Load the given host YAML file from given path, using the existing site config.
    The site config will be merged with the host configuration."""
    if not host_path:
        raise ValueError("host_path cannot be empty")

    host_path = os.path.abspath(host_path)

    _logger.info("loading host config from '%s'", os.path.basename(host_path))

    host_cfg = file.load_yaml(host_path)

    if "hostname" in host_cfg:
        host_cfg["hostname"] = host_cfg.pop("hostname")
    else:
        host_cfg["hostname"] = os.path.basename(host_path)[:-5]  # remove .yaml

    host_cfg = load_from_dict(site_cfg, host_cfg)

    _logger.debug("loaded host '%s' from '%s'", host_cfg["hostname"], host_path)

    return host_cfg


def load_from_dict(site_cfg: dict, cfg: dict) -> dict:
    if site_cfg is None:
        raise ValueError("empty site config")
    if not isinstance(site_cfg, dict):
        raise ValueError("site config must be a dictionary")
    if len(site_cfg) == 0:
        raise KeyError("empty site config")

    if cfg is None:
        raise KeyError("empty host config")
    if not isinstance(cfg, dict):
        raise KeyError("host config must be a dictionary")
    if len(cfg) == 0:
        raise KeyError("empty host config")

    if "hostname" not in cfg:
        raise KeyError("hostname cannot be empty")
    if not cfg["hostname"]:
        raise KeyError("hostname cannot be empty")

    # shallow copy site config; host values overwrite site values
    host_cfg = {**site_cfg, **cfg}

    # manually merge of packages
    for key in ["packages", "remove_packages"]:
        site = site_cfg.get(key)
        host = cfg.get(key)

        if site is None and host is None:
            host_cfg[key] = set()
        elif site is None:
            host_cfg[key] = set(host)
        elif host is None:
            host_cfg[key] = set(site)
        else:
            # combine; host overwrites site
            host_cfg[key] = set(site)
            host_cfg[key] |= set(host)

    _validate_config(host_cfg)
    _configure_roles(host_cfg)
    interface.validate(host_cfg)
    _configure_packages(host_cfg)

    site_cfg["hosts"][host_cfg["hostname"]] = host_cfg

    return host_cfg


def _validate_config(cfg):
    for key in _REQUIRED_PROPERTIES:
        if key not in cfg:
            raise KeyError("{0} not defined".format(key))

    for key in DEFAULT_CONFIG:
        if key not in cfg:
            cfg[key] = DEFAULT_CONFIG[key]
    if "local_dns" not in cfg:
        cfg["local_dns"] = []
    # external_dns defined in DEFAULT_CONFIG

    # remove from script output if not needed
    if not cfg["install_private_ssh_key"]:
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
    # instantiate the class and add addtional config
    for role in role_names:
        _logger.debug("loading module for %s role on %s", role, cfg["hostname"])

        role = role.lower()

        if role != "common":
            cfg["roles"].append(roles.role.load(role))
            cfg["roles"][-1].additional_configuration(cfg)


def _configure_packages(cfg):
    for role in cfg["roles"]:
        cfg["packages"] |= role.additional_packages(cfg)

    # update packages based on config
    if cfg["metrics"]:
        cfg["packages"].add("prometheus-node-exporter")

     # remove iptables if there is no local firewall
    if not cfg["local_firewall"]:
        cfg["remove_packages"] |= {"iptables", "ip6tables"}
        cfg["packages"].discard("awall")

    if not cfg["is_vm"]:
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
DEFAULT_CONFIG = {
    "is_vm": True,
    "vcpus": 1,
    "memory_mb": 128,
    "disk_size_mb": 256,
    "image_format": "raw",
    "vm_images_path": "/vmstorage",
    "root_dev": "/dev/sda",
    "root_partition": "3",  # default disk layout puts /root on /dev/sda3
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
    "alpine_repositories": ["http://dl-cdn.alpinelinux.org/alpine/latest-stable/main", "http://dl-cdn.alpinelinux.org/alpine/latest-stable/community"],
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
