"""Utility for /etc/network/interfaces configuration.

Files created by this module are usable by Debian's ifupdown package.
It _will not_ be usable by the Alpine default BusyBox ifupdown."""
import ipaddress


def validate(iface, vswitches):
    """ Validate a single interface from the config."""
    if iface is None:
        raise ValueError("interface cannot be None")
    if vswitches is None:
        raise ValueError("vswitches cannont be None")

    # vswitch is required
    vswitch_name = iface.get("vswitch")

    if (vswitch_name is None) or (vswitch_name == ""):
        raise KeyError("no vswitch defined for interface")

    vswitch = vswitches.get(vswitch_name)
    if vswitch is None:
        raise KeyError(f"invalid vswitch {vswitch_name}")

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
                raise KeyError(f"vlan must be set when vswitch {vswitch_name} has no default vlan")
    else:
        if vlan is None:
            raise KeyError(f"invalid vlan {vlan_id}; not defined in vswitch {vswitch_name}")

    iface["vlan"] = vlan

    # required ipv4 address, but allow special 'dhcp' value
    address = iface.get("ipv4_address")
    if address is None:
        raise KeyError("no ipv4_address defined for interface")

    if address == "dhcp":
        iface["ipv4_method"] = "dhcp"
    else:
        iface["ipv4_method"] = "static"
        try:
            iface["ipv4_address"] = ipaddress.ip_address(address)
        except:
            raise KeyError(f"invalid ipv4_address {address}")

        subnet = vlan["ipv4_subnet"]
        if iface["ipv4_address"] not in subnet:
            raise KeyError(
                (f"invalid ipv4_address {iface['ipv4_address']};"
                 f" it is not in vlan {vlan_id}'s subnet {subnet}"))

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
            raise KeyError(f"invalid ipv6_address; no ipv6 subnet defined for vlan {vlan_id}")

        try:
            iface["ipv6_address"] = ipaddress.ip_address(address)
        except:
            raise KeyError(f"invalid ipv6_address {address}")

        if iface["ipv6_address"] not in subnet:
            raise KeyError(
                (f"invalid ipv6_address {iface['ipv6_address']};"
                 f" it is not in vlan {vlan_id}'s subnet {subnet}"))

        iface["ipv6_prefixlen"] = subnet.prefixlen
    else:
        iface["ipv6_address"] = None

    # add default values
    for key in default_interface_config:
        if key not in iface:
            iface[key] = default_interface_config[key]
        elif iface[key]:
            if key == "privext":
                if iface[key] > 2:
                    raise KeyError("invalid privext; it must be 0, 1 or 2")
                else:
                    iface[key] = int(iface[key])
            else:
                iface[key] = 1
        else:
            iface[key] = 0

    iface["firewall_zone"] = iface.get("firewall_zone", vswitch_name.upper())


def create_port(name):
    """ Create an interface configuration for "port" interfaces like vswitches and vlan parents.

    The resulting object _will not_ pass validate() but it will be output by as_etc_network().
    """
    return {
        "name": name,
        # special value; not set or used in config.py
        # but as_etc_network() will create a 0 ipv4 address
        "ipv4_method": "vswitch",
        "ipv6_method": "auto",
        # do not assign any ipv4 address other than link local
        "ipv6_address": None,
        "ipv6_dhcp": 0,
        "accept_ra": 0,
        "privext": 0,
        "vlan": {"domain": ""}}  # for util.resolv.create_conf()


def as_etc_network(interfaces):
    """Convert the interfaces to a form for use in /etc/network/interfaces.

    The list of interfaces should have passed through validate() first."""
    buffer = [_LOOPBACK]

    for iface in interfaces:
        if "comment" in iface:
            buffer.append("# " + iface["comment"])

        if iface["ipv4_method"] == "static":
            if iface["vlan"]["routable"]:
                template = _IPV4_STATIC_TEMPLATE
            else:
                template = _IPV4_STATIC_UNROUTABLE_TEMPLATE
            buffer.append(template.format_map(iface))
        elif iface["ipv4_method"] == "dhcp":
            buffer.append("auto {name}\niface {name} inet {ipv4_method}".format_map(iface))
        elif iface["ipv4_method"] == "vswitch":
            buffer.append(_IPV4_VSWITCH_TEMPLATE.format_map(iface))
        else:
            raise KeyError(f"invalid ipv4_method {iface['ipv4_method']} for interface {iface}")
        # use auto method for vswitches; note create_port() disables ra and dhcp
        if iface["ipv6_method"] == "manual":
            # disable IPv6; no SLAAC or DHCP
            buffer.append("iface {name} inet6 {ipv6_method}".format_map(iface))

        else:
            buffer.append(_IPV6_AUTO_TEMPLATE.format_map(iface))

            if iface["ipv6_address"] is not None:
                buffer.append(_IPV6_ADDRESS_TEMPLATE.format_map(iface))

        buffer.append("")

    return "\n".join(buffer)


_LOOPBACK = """auto lo
iface lo inet loopback
iface lo inet6 loopback
"""

default_interface_config = {
    "ipv6_dhcp": 1,
    "accept_ra": 1,
    "privext": 2
}

# static IPv4 address with gateway
_IPV4_STATIC_TEMPLATE = """auto {name}
iface {name} inet {ipv4_method}
  address {ipv4_address}
  netmask {ipv4_netmask}
  gateway {ipv4_gateway}"""

# static IPv4 with no gateway
_IPV4_STATIC_UNROUTABLE_TEMPLATE = """auto {name}
iface {name} inet {ipv4_method}
  address {ipv4_address}
  netmask {ipv4_netmask}"""

# vswitches manually set 0 IP
_IPV4_VSWITCH_TEMPLATE = """auto {name}
iface {name} inet manual
  post-up ip addr add 0.0.0.0/32 dev {name}
  pre-down ip addr del 0.0.0.0/32 dev {name}"""

# SLAAC IPv6 address and / or DHCP address
_IPV6_AUTO_TEMPLATE = """iface {name} inet6 {ipv6_method}
  dhcp {ipv6_dhcp}
  accept_ra {accept_ra}
  privext {privext}"""

# static IPv6 addresses are added manually with the ip command
_IPV6_ADDRESS_TEMPLATE = """  post-up ip -6 addr add {ipv6_address}/{ipv6_prefixlen} dev {name}
  pre-down ip -6 addr del {ipv6_address}/{ipv6_prefixlen} dev {name}"""
