"""Utility functions for creating /etc/network/interfaces.

Files created by this module are usable by the ifupdown-ng package.
It _will not_ be usable by the Alpine's default BusyBox ifupdown."""


def loopback():
    """Create the loopback interface."""
    return """auto lo
iface lo
"""


def from_config(interfaces):
    """Convert the interfaces to a form for use in /etc/network/interfaces.

    The interfaces must be from a validated host configuration."""
    all_interfaces = []

    for iface in interfaces:
        buffer = []
        if "comment" in iface:
            buffer.append("# {comment}")

        buffer.append("auto {name}")
        buffer.append("iface {name}")

        if iface.get("parent"):
            buffer.append("  requires {parent}")
            buffer.append("")

        if iface["ipv4_address"] == "dhcp":
            buffer.append("  use dhcp")
        else:
            buffer.append("  address {ipv4_address}/{ipv4_prefixlen}")
            if iface["vlan"]["routable"]:
                buffer.append("  gateway {ipv4_gateway}")

        # assume interface validation removes the ipv6_address if disabled by vlan
        if iface["ipv6_address"] is not None:
            buffer.append("  address {ipv6_address}")

        if iface["accept_ra"]:
            buffer.append("  use ipv6-ra")
        # if "privext" in iface: TODO research RFCs 7217 and 8981 along with dhcpcd's slaac private temporary setting
        #     buffer.append("  use ipv6-privacy")

        buffer.append("")
        all_interfaces.append("\n".join(buffer).format_map(iface))

    return "\n".join(all_interfaces)


def port(name, parent, comment):
    """ Create an interface configuration for "port" interfaces like vswitches and vlan parents."""
    buffer = []

    if comment != "":
        buffer.append("# " + comment)

    buffer.append(f"auto {name}")
    buffer.append(f"iface {name}")

    if parent:
        buffer.append(f"  requires {parent}")

    buffer.append("")

    # no ipv4 address and no ipv6 SLAAC or DHCP

    return "\n".join(buffer)


def for_vlan(vlan, iface_name):
    """ Create a router interface for the given vlan."""
    if vlan["id"] is None:
        name = iface_name
    else:
        name = f"{iface_name}.{vlan['id']}"

    if vlan["id"] is None:
        buffer = [f"# {vlan['name']} vlan"]
    else:
        buffer= [f"# {vlan['name']} vlan, id {vlan['id']}"]
    buffer.append(f"auto {name}")
    buffer.append(f"iface {name}")
    if vlan["id"] is not None:
        buffer.append(f"  requires {iface_name}")
        buffer.append("")
    buffer.append("  address " + str(vlan["ipv4_subnet"].network_address + 1) + "/" +  str(vlan["ipv4_subnet"].prefixlen))
    # this interface _is_ the gateway, so gateway is not needed

    # disable autoconf
    if not vlan["ipv6_disable"]:
       # add IPv6 address for subnet
        if vlan.get("ipv6_subnet") is not None:
            # manually set the IPv6 address
            buffer.append("  address " + str(vlan["ipv6_subnet"].network_address + 1) + "/" +  str(vlan["ipv6_subnet"].prefixlen))

    buffer.append("")

    return "\n".join(buffer)
