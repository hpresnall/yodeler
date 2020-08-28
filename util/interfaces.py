"""Utility for creating /etc/network/interfaces.

Files created by this module are usable by Debian's ifupdown package.
It _will not_ be usable by the Alpine default BusyBox ifupdown."""


def loopback():
    """Create the loopback stanza."""
    return """auto lo
iface lo inet loopback
iface lo inet6 loopback
"""


def as_etc_network(interfaces):
    """Convert the interfaces to a form for use in /etc/network/interfaces.

    The interfaces must be from a validated host configuration."""
    buffer = []

    for iface in interfaces:
        if "comment" in iface:
            buffer.append("# " + iface["comment"])

        if iface["ipv4_address"] == "dhcp":
            buffer.append("auto {name}\niface {name} inet dhcp".format_map(iface))
        else:
            buffer.append(_IPV4_STATIC_TEMPLATE.format_map(iface))

        if iface["vlan"]["ipv6_disable"]:
            iface["ipv6_method"] = "manual"
        else:
            iface["ipv6_method"] = "auto"

        buffer.append(_IPV6_TEMPLATE.format_map(iface))
        del iface["ipv6_method"]

        # assume interface validate removes the ipv6_address if disabled by vlan
        if iface["ipv6_address"] is not None:
            buffer.append(_IPV6_ADDRESS_TEMPLATE.format_map(iface))

        buffer.append("")

    return "\n".join(buffer)


def create_port(name, comment):
    """ Create an interface configuration for "port" interfaces like vswitches and vlan parents."""
    if comment != "":
        comment = "# " + comment + "\n"

    # no ipv4 address and no ipv6 SLAAC or DHCP
    return f"""{comment}auto {name}
iface public inet manual
iface public inet6 auto
  dhcp 0
  accept_ra 0
  privext 0
"""


def create_router_for_vlan(vlan, iface_name):
    """ Create an interface configuration for "port" interfaces like vswitches and vlan parents."""
    comment = "# " + vlan["name"] + " vlan\n"
    name = f"{iface_name}.{vlan['id']}"
    ipv4_address = vlan["ipv4_subnet"].network_address + 1
    ipv4_netmask = vlan["ipv4_subnet"].netmask

    # this interface is the gateway, so gateway is not needed
    interface = f"""{comment}auto {name}
iface {name} inet manual
  address {ipv4_address}
  netmask {ipv4_netmask}"""

    # always listen for router advertisements
    if not vlan["ipv6_disable"]:
        interface += f"""
iface {name} inet6 auto
  dhcp 0
  accept_ra 1
  privext 0
"""
        # add IPv6 address for subnet
        if vlan.get("ipv6_subnet") is not None:
            # manually set the IPv6 address
            fmt = {
                "name": name,
                "ipv6_address": vlan["ipv6_subnet"].network_address + 1,
                "ipv6_prefixlen": vlan["ipv6_subnet"].prefixlen
            }
            interface += _IPV6_ADDRESS_TEMPLATE.format_map(fmt)
            interface += "\n"
        else:
            interface += "\n"

    return interface


# static IPv4 address with gateway
_IPV4_STATIC_TEMPLATE = """auto {name}
iface {name} inet manual
  address {ipv4_address}
  netmask {ipv4_netmask}
  gateway {ipv4_gateway}"""

# SLAAC IPv6 address and / or DHCP address
_IPV6_TEMPLATE = """iface {name} inet6 {ipv6_method}
  dhcp {ipv6_dhcp}
  accept_ra {accept_ra}
  privext {privext}"""

# static IPv6 addresses are added manually with the ip command
_IPV6_ADDRESS_TEMPLATE = """  post-up ip -6 addr add {ipv6_address}/{ipv6_prefixlen} dev {name}
  pre-down ip -6 addr del {ipv6_address}/{ipv6_prefixlen} dev {name}"""
