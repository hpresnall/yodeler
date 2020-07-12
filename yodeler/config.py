import collections.abc
import logging
import os.path
import ipaddress

import util.file as file

_logger = logging.getLogger(__name__)


def load_site_config(site_dir):
    """Load the base site configuration from the given site name.

    This config _is not_ valid for host configuration. load_host_config()
    _must_ be called to complete configuration."""
    site_dir = os.path.abspath(site_dir)
    site_cfg = file.load_yaml(os.path.join(site_dir, "site.yaml"))
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
    host_cfg = file.load_yaml(host_dir)
    _logger.debug("loaded host YAML file for '%s' from '%s'", hostname, host_dir)

    if host_cfg is None:
        raise KeyError("empty host config")

    host_cfg["hostname"] = hostname
    host_cfg["host_path"] = host_dir

    # shallow copy
    cfg = {**site_cfg, **host_cfg}

    # manual merge of packages
    for key in ["packages", "remove_packages"]:
        sp = site_cfg.get(key)
        hp = host_cfg.get(key)

        if sp is None and hp is None:
            cfg[key] = set()
        elif sp is None:
            cfg[key] = set(hp)
        elif hp is None:
            cfg[key] = set(sp)
        else:
            cfg[key] = set(sp)
            cfg[key] |= set(hp)

    # if either site or host needs it, make sure the package is not removed
    cfg["remove_packages"] -= (cfg["packages"])

    _validate_config(cfg)
    _configure_packages(cfg)

    _validate_interfaces(cfg)

    return cfg


def config_from_string(config_string):
    cfg = file.load_yaml_string(config_string)
    return config_from_dict(cfg)


def config_from_dict(cfg):
    if cfg is None:
        raise KeyError("empty config")

    _validate_config(cfg)
    _configure_packages(cfg)
    _validate_vswitches(cfg)
    _validate_interfaces(cfg)

    return cfg


def _validate_config(cfg):
    for key in required_properties:
        if key not in cfg:
            raise KeyError("{0} not defined".format(key))

    for key in default_config.keys():
        if key not in cfg:
            cfg[key] = default_config[key]

    # remove from script output if not needed
    if not cfg.get("install_private_ssh_key"):
        cfg["private_ssh_key"] = ""

    for d in cfg["local_dns"]:
        try:
            ipaddress.ip_address(d)
        except:
            raise KeyError(f"invalid local_dns IP address {d}")
    for d in cfg["external_dns"]:
        try:
            ipaddress.ip_address(d)
        except:
            raise KeyError(f"invalid external_dns IP address {d}")


def _configure_packages(cfg):
    if "packages" in cfg:
        cfg["packages"] |= (default_packages)
    else:
        cfg["packages"] = set(default_packages)

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
                for u in uplink:
                    if u in uplinks:
                        # an uplink interface can only be set for a single vswitch
                        raise KeyError(
                            f"uplink {uplink} reused for vswitch {vswitch_name}: {vswitch}")
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

    # track which vlan is marked as the default
    default_vlan = None

    for i, vlan in enumerate(vlans, start=1):
        # name is required and must be unique
        if (vlan.get("name") is None) or (vlan["name"] == ""):
            raise KeyError(
                f"no name defined for vlan {i} in vswitch {vswitch_name}: {vswitch}")

        vlan_name = vlan["name"]
        if vlans_by_name.get(vlan_name) is not None:
            raise KeyError(
                f"duplicate vlan name {vlan_name} for vlan in vswitch {vswitch_name}: {vlan}")
        vlans_by_name[vlan_name] = vlan

        # vlan id must be unique
        # None is an allowed id and implies no vlan tagging
        if "id" not in vlan:
            vlan["id"] = None

        vlan_id = vlan["id"]
        if vlans_by_id.get(vlan_id) is not None:
            raise KeyError(
                f"duplicate vlan id {vlan_id} for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
        vlans_by_id[vlan_id] = vlan

        # only allow one default
        if vlan.get("default"):
            if default_vlan is not None:
                raise KeyError(
                    f"multiple default vlans for vswitch {vswitch_name}: {vswitch}")
            default_vlan = vlan
        else:
            vlan["default"] = False

        # ipv4 subnet is required
        subnet = vlan.get("ipv4_subnet")
        if subnet is None:
            raise KeyError(
                f"no ipv4_subnet defined for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")

        try:
            vlan["ipv4_subnet"] = subnet = ipaddress.ip_network(subnet)
        except:
            raise KeyError(
                f"invalid ipv4_subnet defined for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")

        # default to DHCP range over all addresses except the router
        dhcp_min = vlan.get("dhcp_min_address_ipv4", 2)
        dhcp_max = vlan.get("dhcp_max_address_ipv4", 254)

        dhcp_min = subnet.network_address + dhcp_min
        dhcp_max = subnet.network_address + dhcp_max

        if dhcp_min not in subnet:
            raise KeyError(
                f"invalid dhcp_min_address_ipv4 defined for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
        if dhcp_max not in subnet:
            raise KeyError(
                f"invalid dhcp_max_address_ipv4 defined for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
        if dhcp_min > dhcp_max:
            raise KeyError(
                f"dhcp_min_address_ipv4 > dhcp_max_address_ipv4 for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")

        # ipv6 subnet is optional
        # this does not preclude addresses from a prefix assignment
        subnet = vlan.get("ipv6_subnet")
        if subnet is not None:
            try:
                vlan["ipv6_subnet"] = subnet = ipaddress.ip_network(subnet)
            except:
                raise KeyError(
                    f"invalid ipv6_subnet defined for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")

            # default to DHCP range over all addresses in the first segment except the router
            dhcp_min = vlan.get("dhcp_min_address_ipv6", 2)
            dhcp_max = vlan.get("dhcp_max_address_ipv6", 0xffff)

            dhcp_min = subnet.network_address + dhcp_min
            dhcp_max = subnet.network_address + dhcp_max

            if dhcp_min not in subnet:
                raise KeyError(
                    f"invalid dhcp_min_address_ipv6 defined for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
            if dhcp_max not in subnet:
                raise KeyError(
                    f"invalid dhcp_max_address_ip6 defined for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
            if dhcp_min > dhcp_max:
                raise KeyError(
                    f"dhcp_min_address_ipv6 > dhcp_max_address_ipv6 for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
        else:
            vlan["ipv6_subnet"] = None

        # add default values
        for key in default_vlan_config.keys():
            if key not in vlan:
                vlan[key] = default_vlan_config[key]

        if vlan["domain"] and (domain not in vlan["domain"]):
            raise KeyError(
                f"domain defined for vlan {vlan_name}, {vlan['domain']} is not a subdomain of {domain} in vswitch {vswitch_name}: {vlan}")
    # end for each vlan

    if default_vlan is not None:
        vswitch["default_vlan"] = default_vlan
    elif len(vlans_by_id) == 1:  # one vlan; make it the default
        vlan = list(vlans_by_id.values())[0]
        vswitch["default_vlan"] = vlan
        vlan["default"] = True
    else:
        vswitch["default_vlan"] = None

    # second pass to validate access_vlans
    for vlan in vswitch["vlans"]:
        vlan_name = vlan["name"]
        access_vlans = vlan.get("access_vlans")
        if access_vlans is None:
            continue
        if not isinstance(access_vlans, collections.abc.Sequence):
            raise KeyError(
                f"invalid non-array access_vlans in vlan {vlan_name} for vswitch {vswitch_name}: {vlan}")

        # make unique
        vlan["access_vlans"] = set(access_vlans)

        for id in access_vlans:
            if vlans_by_id.get(id) is None:
                raise KeyError(
                    f"invalid access_vlan id {id} in vlan {vlan_name} for vswitch {vswitch_name}: {vlan}")


def _validate_interfaces(cfg):
    interfaces = cfg.get("interfaces")
    if (interfaces is None) or (len(interfaces) == 0):
        raise KeyError("no interfaces defined")

    matching_domain = None

    for i, iface in enumerate(interfaces):
        # vswitch is required
        vswitch_name = iface.get("vswitch")

        if (vswitch_name is None) or (vswitch_name == ""):
            raise KeyError(f"no vswitch defined for interface {i}: {iface}")

        vswitch = cfg["vswitches"].get(vswitch_name)
        if vswitch is None:
            raise KeyError(
                f"invalid vswitch {vswitch_name} for interface {i}: {iface}")

        iface["vswitch"] = vswitch

        vlan_id = iface.get("vlan")
        # allow interface vlan to be a name or id
        if isinstance(vlan_id, str):
            lookup = vswitch["vlans_by_name"]
        else:
            lookup = vswitch["vlans_by_id"]  # also handles None

        # no vlan set; could be a PVID vlan on the vswitch
        # if not, use the default vlan
        vlan = lookup.get(vlan_id)
        if vlan_id is None:
            if vlan is None:
                vlan = vswitch["default_vlan"]
                if vlan is None:
                    raise KeyError(
                        f"vlan must be set for interface {i} when vswitch {vswitch_name} has no default vlan: {iface}")
        else:
            if vlan is None:
                raise KeyError(
                    f"invalid vlan {vlan_id} for interface {i}; not defined in vswitch {vswitch_name}: {iface}")

        iface["vlan"] = vlan

        if cfg["primary_domain"] == vlan["domain"]:
            matching_domain = vlan["domain"]

        # required ipv4 address, but allow special 'dhcp' value
        address = iface.get("ipv4_address")
        if address is None:
            raise KeyError(
                f"no ipv4_address defined for interface {i}: {iface}")
        elif address == "dhcp":
            iface["ipv4_method"] = "dhcp"
        else:
            iface["ipv4_method"] = "static"
            try:
                address = iface["ipv4_address"] = ipaddress.ip_address(
                    address)
            except:
                raise KeyError(
                    f"invalid ipv4_address {address} defined for interface {i}: {iface}")

            subnet = vlan["ipv4_subnet"]
            if address not in subnet:
                raise KeyError(
                    f"invalid ipv4_address {address} for interface {i}; it is not in vlan {vlan_id}'s subnet {subnet}: {iface}")

            iface["ipv4_netmask"] = subnet.netmask
            iface["ipv4_gateway"] = subnet.network_address + 1

        # ipv6 disabled at vlan level
        if vlan["ipv6_disable"]:
            iface["ipv6_method"] = "manual"
        else:
            # optional ipv6 address, but always enable autoconfg
            iface["ipv6_method"] = "auto"

        address = iface.get("ipv6_address")
        if address is not None:
            subnet = vlan.get("ipv6_subnet")
            if subnet is None:
                raise KeyError(
                    f"invalid ipv6_address for interface {i}; no ipv6 subnet defined for vlan {vlan_id}: {iface}")

            try:
                address = iface["ipv6_address"] = ipaddress.ip_address(
                    address)
            except:
                raise KeyError(
                    f"invalid ipv6_address {address} defined for interface {i}: {iface}")

            if address not in subnet:
                raise KeyError(
                    f"invalid ipv6_address {address} for interface {i}; it is not in vlan {vlan_id}'s subnet {subnet}: {iface}")

            iface["ipv6_prefixlen"] = subnet.prefixlen
        else:
            iface["ipv6_address"] = None

        # add default values
        for key in default_interface_config.keys():
            if key not in iface:
                iface[key] = default_interface_config[key]
            elif iface[key]:
                if "privext" == key:
                    if iface[key] > 2:
                        raise KeyError(f"invalid privext for interface {i}; it must be 0, 1 or 2: {iface}")
                    else:
                        iface[key] = int(iface[key])
                else:
                    iface[key] = 1
            else:
                iface[key] = 0

        iface["firewall_zone"] = iface.get(
            "firewall_zone", vswitch_name.upper())

        # assume interfaces are defined in order and that Alpine assigns them as ethx
        iface["name"] = f"eth{i}"
    # end for each iface

    if cfg["primary_domain"]:
        if (matching_domain is None):
            raise KeyError(
                f"invalid primary_domain: no vlan domain matches {cfg['primary_domain']}")
    else:
        if (len(interfaces) == 1):
            cfg["primary_domain"] = interfaces[0]["vlan"]["domain"]


# properties that are unique and cannot be set as defaults
required_properties = ["site", "hostname", "public_ssh_key"]
default_packages = {"acpi", "sudo", "openssh", "chrony", "awall", "dhclient"}
default_config = {
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
    # location of cached apks in vmhost; used by vm creation script
    "apk_cache": "/root/yodeler_apks",
    "alpine_repositories": ["http://dl-cdn.alpinelinux.org/alpine/latest-stable/main"],
    "ntp_pool_servers": ["0.pool.ntp.org", "1.pool.ntp.org", "2.pool.ntp.org", "3.pool.ntp.org"],
    "local_dns": [],
    "external_dns": ["8.8.8.8", "9.9.9.9", "1.1.1.1"],
    # top-level domain for the site
    "domain": "",
    # domain for the host when it has multiple interfaces
    "primary_domain": "",
    "roles": []
}

default_vlan_config = {
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

default_interface_config = {
    "ipv6_dhcp": 1,
    "accept_ra": 1,
    "privext": 2
}
