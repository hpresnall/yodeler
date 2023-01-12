"""Utility functions for creating /etc/network/interfaces.

Files created by this module are usable by the ifupdown-ng package.
It _will not_ be usable by the Alpine's default BusyBox ifupdown command or by
the Debian's version from the ifupdown package."""


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

        if iface.get("forward"):
            buffer.append("  use forward")  # enable IPv4 and IPv6 forwarding

        space = dhcp = (iface["ipv4_address"] == "dhcp") or iface["ipv6_dhcp"]
        if dhcp:
            buffer.append("  use dhcp")

        if iface["accept_ra"]:
            buffer.append("  use ipv6-ra")
            space |= True

        # if "tempaddr" in iface: TODO research RFCs 7217 and 8981 along with dhcpcd's slaac private temporary setting
        #     buffer.append("  use ipv6-privacy")

        if space:
            buffer.append("")
            space = False

        if not dhcp:
            buffer.append("  address {ipv4_address}/{ipv4_prefixlen}")
            if iface["vlan"]["routable"]:
                buffer.append("  gateway {ipv4_gateway}")
            space = True

        if space:
            buffer.append("")
            space = False

        # assume interface validation removes the ipv6_address if disabled by vlan
        if iface["ipv6_address"] is not None:
            buffer.append("  address {ipv6_address}")
            space = True

        if space:
            buffer.append("")

        _output_wifi(iface, buffer)

        all_interfaces.append("\n".join(buffer).format_map(iface))

    return "\n".join(all_interfaces)


def port(name, parent, comment, uplink=None):
    """ Create an interface configuration for "port" interfaces like vswitches and vlan parents.

    # <comment>
    auto <name>
    iface <name>
      requires <parent> # if exists

    If uplink is specified, WiFi configuration will be moved from the uplink to the new port.
    """
    buffer = []

    if comment:
        buffer.append("# " + comment)

    buffer.append(f"auto {name}")
    buffer.append(f"iface {name}")

    if parent:
        buffer.append(f"  requires {parent}")

    buffer.append("")

    # no ipv4 address and no ipv6 SLAAC or DHCP

    if uplink:
        _output_wifi(uplink, buffer)
        port = "\n".join(buffer).format_map(uplink)

        if "wifi_ssid" in uplink:
            del uplink["wifi_ssid"]
            del uplink["wifi_psk"]

        return port

    return "\n".join(buffer)


def for_vlan(vlan, iface_name):
    """ Create a router interface for the given vlan.

    # <name> vlan, id <id>
    auto <iface_name>.<id>
    iface <iface_name>.<id>
    requires <iface_name>

    address <ipv4_subnet>.1/<prefixlen>
    address <ipv6_subnet>::1/<prefixlen> # if <ipv6_disable> != False
    """
    if vlan["id"] is None:
        name = iface_name
        buffer = [f"# {vlan['name']} vlan"]
    else:
        name = f"{iface_name}.{vlan['id']}"
        buffer = [f"# {vlan['name']} vlan, id {vlan['id']}"]

    buffer.append(f"auto {name}")
    buffer.append(f"iface {name}")
    if vlan["id"] is not None:
        buffer.append(f"  requires {iface_name}")
        buffer.append("")
    buffer.append("  address " + str(vlan["ipv4_subnet"].network_address + 1) +
                  "/" + str(vlan["ipv4_subnet"].prefixlen))
    # this interface _is_ the gateway, so gateway is not needed

    # disable autoconf
    if not vlan["ipv6_disable"]:
       # add IPv6 address for subnet
        if vlan.get("ipv6_subnet") is not None:
            # manually set the IPv6 address
            buffer.append("\n  address " + str(vlan["ipv6_subnet"].network_address +
                          1) + "/" + str(vlan["ipv6_subnet"].prefixlen))

    buffer.append("")

    return "\n".join(buffer)


def _output_wifi(iface, buffer):
    if "wifi_ssid" in iface:
        buffer.append("  use wifi")
        buffer.append("  wifi-ssid {wifi_ssid}")
        buffer.append("  wifi-psk {wifi_psk}")
        buffer.append("")
