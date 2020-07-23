"""Handles parsing and validating site and host YAML configuration files.

Site configuration is the base and defines defaults for each host.
Unless otherwise stated, any function that takes a configuration will
assume it is a dictionary returned from this module.
"""
import collections.abc
import logging
import os.path
import ipaddress

import util.file
import util.interfaces

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

    _validate_vswitches(site_cfg)

    return site_cfg


def load_host_config(site_cfg, hostname):
    """Load the configuration for a given host, using the base site
    configuration.

    Rreturns a new configuration without modifying the site configuration.
    The site config _must_ be a valid configuration from load_site_config().
    The values from the host will override the site values."""
    if site_cfg is None:
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
    _configure_packages(cfg)

    _validate_interfaces(cfg)

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
    _configure_packages(cfg)
    _validate_vswitches(cfg)
    _validate_interfaces(cfg)

    return cfg


def _validate_config(cfg):
    for key in _REQUIRED_PROPERTIES:
        if key not in cfg:
            raise KeyError("{0} not defined".format(key))

    for key in DEFAULT_CONFIG:
        if key not in cfg:
            cfg[key] = DEFAULT_CONFIG[key]

    # remove from script output if not needed
    if not cfg.get("install_private_ssh_key"):
        cfg["private_ssh_key"] = ""

    for dns in cfg["local_dns"]:
        try:
            ipaddress.ip_address(dns)
        except:
            raise KeyError(f"invalid local_dns IP address {dns}")
    for dns in cfg["external_dns"]:
        try:
            ipaddress.ip_address(dns)
        except:
            raise KeyError(f"invalid external_dns IP address {dns}")


def _configure_packages(cfg):
    if "packages" in cfg:
        cfg["packages"] |= DEFAULT_PACKAGES
    else:
        cfg["packages"] = DEFAULT_PACKAGES

    if "remove_packages" not in cfg:
        cfg["remove_packages"] = set()

    # update packages based on config
    if cfg["metrics"]:
        cfg["packages"].add("prometheus-node-exporter")

     # remove iptables if there is no local firewall
    if not cfg["local_firewall"]:
        cfg["remove_packages"] |= {"iptables", "ip6tables"}

    # VMs are setup without USB, so remove the library
    if cfg["is_vm"]:
        cfg["remove_packages"].add("libusb")
    else:
        # add cpufreq and other utils to real hosts
        cfg["packages"] |= {"util-linux", "cpufreqd", "cpufrequtils"}

    # remove conflicts
    cfg["packages"] -= (cfg["remove_packages"])


def _validate_vswitches(cfg):
    vswitches = cfg.get("vswitches")
    if (vswitches is None) or (len(vswitches) == 0):
        raise KeyError("no vswitches defined")

    # list of vswitches in yaml => dict of names to vswitches
    vswitches_by_name = cfg["vswitches"] = {}
    uplinks = cfg["uplinks"] = set()

    for i, vswitch in enumerate(vswitches, start=1):
        # name is required and must be unique
        if ("name" not in vswitch) or (vswitch["name"] is None) or (vswitch["name"] == ""):
            raise KeyError(f"no name defined for vswitch {i}: {vswitch}")

        vswitch_name = vswitch["name"]

        if vswitches_by_name.get(vswitch_name) is not None:
            raise KeyError(
                f"duplicate name {vswitch_name} defined for vswitch {i}: {vswitch}")
        vswitches_by_name[vswitch_name] = vswitch

        uplink = vswitch.get("uplink")

        if uplink is not None:
            if isinstance(uplink, str):
                if uplink in uplinks:
                    raise KeyError(
                        f"uplink {uplink} reused for vswitch {vswitch_name}: {vswitch}")
                uplinks.add(uplink)
            else:
                for link in uplink:
                    if link in uplinks:
                        # an uplink interface can only be set for a single vswitch
                        raise KeyError(
                            f"uplink {link} reused for vswitch {vswitch_name}: {vswitch}")
                uplinks |= set(uplink)
        else:
            vswitch["uplink"] = None

        _validate_vlans(cfg["domain"], vswitch)


def _validate_vlans(domain, vswitch):
    vswitch_name = vswitch["name"]

    vlans = vswitch.get("vlans")
    if (vlans is None) or (len(vlans) == 0):
        raise KeyError(
            f"no vlans defined for vswitch {vswitch_name}: {vswitch}")

    vswitch_name = vswitch["name"]

    # list of vlans in yaml => dicts of names & ids to vswitches
    vlans_by_id = vswitch["vlans_by_id"] = {}
    vlans_by_name = vswitch["vlans_by_name"] = {}

    for i, vlan in enumerate(vlans, start=1):
        # name is required and must be unique
        if not vlan.get("name") or (vlan["name"] == ""):
            raise KeyError(
                f"no name for vlan {i} in vswitch {vswitch_name}: {vswitch}")

        vlan_name = vlan["name"]
        if vlan_name in vlans_by_name:
            raise KeyError(
                f"duplicate name {vlan_name} for vlan in vswitch {vswitch_name}: {vlan}")
        vlans_by_name[vlan_name] = vlan

        # vlan id must be unique
        # None is an allowed id and implies no vlan tagging
        vlan_id = vlan["id"] = vlan.get("id", None)

        if vlan_id in vlans_by_id:
            raise KeyError(
                f"duplicate id {vlan_id} for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
        vlans_by_id[vlan_id] = vlan

        # add default values
        for key in DEFAULT_VLAN_CONFIG:
            if key not in vlan:
                vlan[key] = DEFAULT_VLAN_CONFIG[key]

        _validate_vlan_subnet(vswitch_name, vlan, "ipv4", 2, 252)
        _validate_vlan_subnet(vswitch_name, vlan, "ipv6", 2, 0xffff)

        # domain must be a subdomain of the top-level site
        if vlan["domain"] and (domain not in vlan["domain"]):
            raise KeyError(
                (f"domain for vlan {vlan_name}, {vlan['domain']} is not a subdomain of {domain}"
                 f" in vswitch {vswitch_name}: {vlan}"))
    # end for each vlan

    _configure_default_vlan(vswitch)
    _validate_access_vlans(vswitch)


def _validate_vlan_subnet(vswitch_name, vlan, ip_version, dhcp_min, dhcp_max):
    # ipv4 subnet is required
    # ipv6 subnet is optional; this does not preclude addresses from a prefix assignment
    subnet = vlan.get(ip_version + "_subnet")
    vlan_name = vlan["name"]

    if subnet is None:
        if ip_version == "ipv4":
            raise KeyError(
                f"no {ip_version}_subnet for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
        if ip_version == "ipv6":
            vlan["ipv6_subnet"] = None
            return
        else:
            raise ValueError("invalid ip version {ip_version}")

    try:
        vlan[ip_version + "_subnet"] = subnet = ipaddress.ip_network(subnet)
    except:
        raise KeyError(
            f"invalid {ip_version}_subnet for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")

    # default to DHCP range over all addresses except the router
    dhcp_min = vlan.get("dhcp_min_address_" + ip_version, dhcp_min)
    dhcp_max = vlan.get("dhcp_max_address_" + ip_version, dhcp_max)

    dhcp_min = subnet.network_address + dhcp_min
    dhcp_max = subnet.network_address + dhcp_max

    if dhcp_min not in subnet:
        raise KeyError((f"invalid dhcp_min_address_{ip_version} for vlan {vlan_name}"
                        f" in vswitch {vswitch_name}: {vlan}"))
    if dhcp_max not in subnet:
        raise KeyError((f"invalid dhcp_max_address_{ip_version} for vlan {vlan_name}"
                        f" in vswitch {vswitch_name}: {vlan}"))
    if dhcp_min > dhcp_max:
        raise KeyError((f"dhcp_min_address_{ip_version} > dhcp_max_address_{ip_version}"
                        f" for vlan {vlan_name}"
                        f" in vswitch {vswitch_name}: {vlan}"))


def _configure_default_vlan(vswitch):
    # track which vlan is marked as the default
    default_vlan = None

    for vlan in vswitch["vlans"]:
        # only allow one default
        if "default" in vlan:
            if default_vlan is not None:
                raise KeyError(f"multiple default vlans for vswitch {vswitch['name']}: {vswitch}")
            default_vlan = vlan
        else:
            vlan["default"] = False

    if default_vlan is not None:
        vswitch["default_vlan"] = default_vlan
    elif len(vswitch['vlans_by_id']) == 1:  # one vlan; make it the default
        vlan = list(vswitch['vlans_by_id'].values())[0]
        vswitch["default_vlan"] = vlan
        vlan["default"] = True
    else:
        vswitch["default_vlan"] = None


def _validate_access_vlans(vswitch):
    for vlan in vswitch["vlans"]:
        vlan_name = vlan["name"]
        access_vlans = vlan.get("access_vlans")

        if access_vlans is None:
            continue

        if (not isinstance(access_vlans, collections.abc.Sequence)
                or isinstance(access_vlans, str)):
            raise KeyError(
                f"non-array access_vlans in vlan {vlan_name} for vswitch {vswitch['name']}: {vlan}")

        # make unique
        vlan["access_vlans"] = set(access_vlans)

        for vlan_id in access_vlans:
            if vlan_id not in vswitch['vlans_by_id']:
                raise KeyError((f"invalid access_vlan id {vlan_id} in vlan {vlan_name}"
                                f" for vswitch {vswitch['name']}: {vlan}"))


def _validate_interfaces(cfg):
    ifaces = cfg.get("interfaces")
    if (ifaces is None) or (len(ifaces) == 0):
        raise KeyError("no interfaces defined")

    vswitches = cfg["vswitches"]
    matching_domain = None
    iface_counter = 0

    for i, iface in enumerate(ifaces):
        if "name" not in iface:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        try:
            util.interfaces.validate(iface, vswitches)
        except KeyError as err:
            msg = err.args[0]
            raise KeyError(f"{msg} for interface {i}: {iface}")

        vlan = iface["vlan"]
        if cfg["primary_domain"] == vlan["domain"]:
            matching_domain = vlan["domain"]

    if cfg["primary_domain"] != "":
        if matching_domain is None:
            raise KeyError(
                f"invalid primary_domain: no vlan domain matches {cfg['primary_domain']}")
    else:
        if len(ifaces) == 1:
            cfg["primary_domain"] = ifaces[0]["vlan"]["domain"]


# properties that are unique and cannot be set as defaults
_REQUIRED_PROPERTIES = ["site", "hostname", "public_ssh_key"]
DEFAULT_PACKAGES = {"acpi", "sudo", "openssh", "chrony", "awall", "dhclient"}
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
    "local_dns": [],
    "external_dns": ["8.8.8.8", "9.9.9.9", "1.1.1.1"],
    # top-level domain for the site
    "domain": "",
    # domain for the host when it has multiple interfaces
    "primary_domain": "",
    "roles": [],
    # for physical servers, manually specify contents of /etc/network/interfaces
    # default blank => installer will prompt
    "install_interfaces": ""
}

DEFAULT_VLAN_CONFIG = {
    "routable": True,  # vlan will have an interface assigned on the router
    "domain": "",
    "ipv6_disable": False,
    "allow_dhcp": True,  # DHCP server will be configured
    "allow_internet": False,  # firewall will restrict outbound internet access
    # do not allow internet access when firewall is stopped
    "allow_access_stopped_firewall": False,
    "allow_dns_update": False,  # do not allow this subnet to make DDNS updates
    "dhcp_min_address_ipv4": 2,
    "dhcp_max_address_ipv4": 252,
    "dhcp_min_address_ipv6": 2,
    "dhcp_max_address_ipv6": 0xffff,
    "known_hosts": []
}
