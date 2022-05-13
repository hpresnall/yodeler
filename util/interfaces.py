"""Utility functions for creating /etc/network/interfaces.

Files created by this module are usable by Debian's ifupdown package.
It _will not_ be usable by the Alpine's default BusyBox ifupdown."""


def loopback():
    """Create the loopback stanza."""
    return """auto lo
iface lo inet loopback
iface lo inet6 loopback
"""


def from_config(interfaces):
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
            if iface["vlan"]["routable"]:
                buffer.append(f"  gateway {iface['ipv4_gateway']}")

        buffer.append(_IPV6_TEMPLATE.format_map(iface))

        # assume interface validate removes the ipv6_address if disabled by vlan
        if iface["ipv6_address"] is not None:
            buffer.append(_IPV6_ADDRESS_TEMPLATE.format_map(iface))

        buffer.append("")

    return "\n".join(buffer)


def port(name, comment):
    """ Create an interface configuration for "port" interfaces like vswitches and vlan parents."""
    if comment != "":
        comment = "# " + comment + "\n"

    # no ipv4 address and no ipv6 SLAAC or DHCP
    return f"""{comment}auto {name}
iface {name} inet manual
iface {name} inet6 auto
  dhcp 0
  accept_ra 0
  privext 0
"""


def for_vlan(vlan, iface_name):
    """ Create a router interface for the given vlan."""
    if vlan["id"] is None:
        name = iface_name
    else:
        name = f"{iface_name}.{vlan['id']}"

    comment = "# " + vlan["name"] + " vlan\n"
    iface = {"name": name,
             "ipv4_address": vlan["ipv4_subnet"].network_address + 1,
             "ipv4_netmask": vlan["ipv4_subnet"].netmask}

    # this interface _is_ the gateway, so gateway is not needed
    interface = comment
    interface += _IPV4_STATIC_TEMPLATE.format_map(iface)

    # disable autoconf
    if not vlan["ipv6_disable"]:
        iface["ipv6_dhcp"] = 0
        iface["privext"] = 0
        iface["accept_ra"] = 0

        interface += "\n"
        interface += _IPV6_TEMPLATE.format_map(iface)

        # add IPv6 address for subnet
        if vlan.get("ipv6_subnet") is not None:
            # manually set the IPv6 address
            fmt = {
                "name": name,
                "ipv6_address": vlan["ipv6_subnet"].network_address + 1,
                "ipv6_prefixlen": vlan["ipv6_subnet"].prefixlen
            }
            interface += "\n"
            interface += _IPV6_ADDRESS_TEMPLATE.format_map(fmt)

        interface += "\n"

    return interface


# static IPv4 address with gateway
_IPV4_STATIC_TEMPLATE = """auto {name}
iface {name} inet static
  address {ipv4_address}
  netmask {ipv4_netmask}"""

# SLAAC IPv6
# note always auto even when IPv6 is disabled; config will turn off dhcp and ra
_IPV6_TEMPLATE = """iface {name} inet6 auto
  dhcp {ipv6_dhcp}
  accept_ra {accept_ra}
  privext {privext}"""

# static IPv6 addresses are added manually with the ip command
_IPV6_ADDRESS_TEMPLATE = """  post-up ip -6 addr add {ipv6_address}/{ipv6_prefixlen} dev {name}
  pre-down ip -6 addr del {ipv6_address}/{ipv6_prefixlen} dev {name}"""
