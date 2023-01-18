"""Utility functions for creating /etc/network/interfaces.

Files created by this module are usable by the ifupdown-ng package.
It _will not_ be usable by the Alpine's default BusyBox ifupdown command or by
the Debian's version from the ifupdown package."""
import config.interface


def from_config(cfg):
    """Convert the interfaces to a form for use in /etc/network/interfaces.

    The interfaces must be from a validated host configuration."""
    # loopback is first
    all_interfaces = ["""auto lo
# iface lo
# """]

    for iface in cfg["interfaces"]:
        match iface["type"]:
            case "std":
                interface = _standard(iface)
            case "port":
                interface = _port(cfg, iface)
            case "vlan":
                interface = _vlan(iface)
            case "uplink":
                interface = _standard(iface)
            case _:
                raise ValueError(f"unknown interface type '{iface['type']}'")

        all_interfaces.append(interface)

    return "\n".join(all_interfaces)


def _standard(iface):
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

    # TODO research RFCs 7217 and 8981 along with dhcpcd's slaac private temporary setting
    # TODO uncomment when /usr/libexex/ifupdown-nd/ipv6-tempaddr is provided by Alpine
    # if iface["ipv6_tempaddr"]:
    #    buffer.append("  use ipv6-tempaddr")

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

    return "\n".join(buffer).format_map(iface)


def _port(cfg, iface):
    """ Create an interface configuration for "port" interfaces like vswitches and vlan parents.

    # <comment>
    auto <name>
    iface <name>
      requires <parent> # if exists

    If uplink is specified, WiFi configuration will be moved from the uplink to the new port.
    """
    buffer = []
    name = iface["name"]

    if "comment" in iface:
        buffer.append("# " + iface["comment"])

    buffer.append(f"auto {name}")
    buffer.append(f"iface {name}")

    if iface["parent"]:
        buffer.append(f"  requires {iface['parent']}")

    buffer.append("")

    # no ipv4 address and no ipv6 SLAAC or DHCP

    # move wifi config from uplink to this interface
    if iface["uplink"]:
        uplink = config.interface.find_by_name(cfg, iface["uplink"])
        _output_wifi(uplink, buffer)
        port = "\n".join(buffer).format_map(uplink)

        if "wifi_ssid" in uplink:
            del uplink["wifi_ssid"]
            del uplink["wifi_psk"]

        return port

    return "\n".join(buffer)


def _vlan(iface):
    """ Create a router interface for the given vlan.

    # <name> vlan, id <id>
    auto <iface_name>.<id>
    iface <iface_name>.<id>
    requires <iface_name>

    address <ipv4_subnet>.1/<prefixlen>
    address <ipv6_subnet>::1/<prefixlen> # if vlan has an ipv6_subnet
    """
    vlan = iface["vlan"]
    iface_name = iface["name"]

    if vlan["id"] is None:
        buffer = [f"# {vlan['name']} vlan"]
    else:
        buffer = [f"# {vlan['name']} vlan, id {vlan['id']}"]

    buffer.append(f"auto {iface_name}")
    buffer.append(f"iface {iface_name}")
    if vlan["id"] is not None:
        buffer.append(f"  requires {iface['parent']}")
        buffer.append("")
    subnet = vlan["ipv4_subnet"] if "ipv4_subnet" else iface["ipv4_subnet"]
    buffer.append("  address " + str(iface["ipv4_address"]) + "/" + str(subnet.prefixlen))
    # this interface _is_ the gateway, so gateway is not needed

    # add IPv6 address for subnet
    if vlan.get("ipv6_subnet"):
        # manually set the IPv6 address
        buffer.append("\n  address " + str(iface["ipv6_address"]) + "/" + str(vlan["ipv6_subnet"].prefixlen))

    buffer.append("")

    return "\n".join(buffer)


def _output_wifi(iface, buffer):
    if "wifi_ssid" in iface:
        buffer.append("  use wifi")
        buffer.append("  wifi-ssid {wifi_ssid}")
        buffer.append("  wifi-psk {wifi_psk}")
        buffer.append("")
