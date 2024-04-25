"""Create /etc/network/interfaces for a host.
Also handles creating a startup script to rename interfaces based on the optional 'rename-interfaces' config parameter.

Files created by this module are usable by the ifupdown-ng package.
It _will not_ be usable by the Alpine's default BusyBox ifupdown command or by
Debian's version from the ifupdown package."""
import config.interfaces

import util.file as file
import util.parse as parse

import script.shell as shell


def from_config(cfg: dict, output_dir: str):
    """Convert the interfaces to a form for use in /etc/network/interfaces.

    The interfaces must be from a validated host configuration."""
    # loopback is first
    all_interfaces = ["""auto lo
iface lo
"""]

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

    file.write("interfaces", "\n".join(all_interfaces), output_dir)


def _standard(iface: dict):
    buffer = []
    if "comment" in iface:
        buffer.append("# {comment}")

    buffer.append("auto {name}")
    buffer.append("iface {name}")

    if iface.get("parent"):
        buffer.append("  requires {parent}")
        buffer.append("")

    dhcp4 = iface["ipv4_address"] == "dhcp"
    dhcp = dhcp4 or iface["ipv6_dhcp"]

    if dhcp:
        buffer.append("  use dhcp")
        buffer.append("")

    # never set 'use ipv6-ra'
    # dhcpcd runs in all cases and will handle router advertisements

    _output_forward(iface, buffer)

    if not dhcp4:
        buffer.append("  address {ipv4_address}/{ipv4_prefixlen}")
        if iface["ipv4_gateway"] and (iface["ipv4_gateway"] != iface["ipv4_address"]):
            buffer.append("  gateway {ipv4_gateway}")
        buffer.append("")

    space = False

    # assume interface validation removes the ipv6_address if disabled by vlan
    if iface["ipv6_address"] is not None:
        buffer.append("  address {ipv6_address}")
        space = True

    for address in iface["additional_ipv6_addresses"]:
        buffer.append(f"  address {address}")
        space = True

    if space:
        buffer.append("")

    _output_wifi(iface, buffer)

    return "\n".join(buffer).format_map(iface)


def _port(cfg: dict, iface: dict):
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
        uplink = config.interfaces.find_by_name(cfg, iface["uplink"])
        _output_wifi(uplink, buffer)
        port = "\n".join(buffer).format_map(uplink)

        if "wifi_ssid" in uplink:
            del uplink["wifi_ssid"]
            del uplink["wifi_psk"]

        return port

    return "\n".join(buffer)


def _vlan(iface: dict):
    """ Create an interface for the given vlan.
    This interface should already have its address(es) set to the valid gateway address.

    # <name> vlan, id <id>
    auto <iface_name>.<id>
    iface <iface_name>.<id>
    requires <iface_name>

    address <ipv4_address>/<prefixlen>
    address <ipv6_address>/<prefixlen> # if vlan has an ipv6_subnet
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

    _output_forward(iface, buffer)

    buffer.append("  address " + str(iface["ipv4_address"]) + "/" + str(vlan["ipv4_subnet"].prefixlen))
    # this interface _is_ the gateway, so gateway is not needed

    # add IPv6 address for subnet if IPv6 is enabled
    if vlan.get("ipv6_subnet"):
        # manually set the IPv6 address
        buffer.append("\n  address " + str(iface["ipv6_address"]) + "/" + str(vlan["ipv6_subnet"].prefixlen))

    buffer.append("")

    return "\n".join(buffer)


def _output_forward(iface: dict, buffer: list[str]):
    if iface.get("forward"):
        # enable IPv4 and IPv6 forwarding
        buffer.append("  forward-ipv4 yes")
        if not iface["ipv6_disabled"]:
            buffer.append("  forward-ipv6 yes")
        buffer.append("")


def _output_wifi(iface: dict, buffer: list[str]):
    if "wifi_ssid" in iface:
        buffer.append("  use wifi")
        buffer.append("  wifi-ssid {wifi_ssid}")
        buffer.append("  wifi-psk {wifi_psk}")
        buffer.append("")


def rename_interfaces(rename_rules: list[dict], script: shell.ShellScript, output_dir: str, hostname: str):
    # create init script & add it to boot
    rename_cmds = []
    for i, rule in enumerate(rename_rules, start=1):
        if "name" not in rule:
            raise KeyError(f"no name for rename rule {i} for host '{hostname}'")
        if "mac_address" not in rule:
            raise KeyError(f"no mac_address for rename rule {i} for host '{hostname}'")

        name = rule["name"]
        mac = rule["mac_address"]

        parse.validate_mac_address(mac, f"rename rule {i} for host '{hostname}'")

        rename_cmds.append(f"  rename_iface {mac} {name}")

    file.substitute_and_write("common", "rename-eth", {"rename_cmds": "\n".join(rename_cmds)}, output_dir)

    script.comment("rename ethernet devices at boot")
    script.append("install -m 755 $DIR/rename-eth /etc/init.d")
    script.service("rename-eth", "sysinit")
    script.blank()
