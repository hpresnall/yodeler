"""Handles parsing and validating interface configuration from host YAML files."""
import logging
import ipaddress
import random

from typing import Callable

import config.vlan

import util.parse as parse
import util.pci as pci

_logger = logging.getLogger(__name__)


def validate(cfg: dict):
    """Validate all the interfaces defined in the host."""
    ifaces = parse.non_empty_list("interfaces", cfg.get("interfaces"))

    vswitches = cfg["vswitches"]

    # domain used in /etc/resolv.conf
    matching_domain = None
    iface_counter = 0

    names = set()

    for i, iface in enumerate(ifaces, start=1):
        location = f"cfg[{cfg['hostname']}].iface[{i}]"

        parse.non_empty_dict(location, iface)

        if "name" in iface:
            iface["name"] = parse.non_empty_string("name", iface, location)
        else:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        if iface["name"] in names:
            raise ValueError(f"duplicate interface name {iface['name']} for {location}")
        names.add(iface["name"])

        try:
            parse.set_default_string("type", iface, "std")
            _validate_network(iface, vswitches)
            _validate_iface(iface, location)
        except KeyError as err:
            msg = err.args[0]
            raise KeyError(f"{msg} for {location}") from err
        except ValueError as err:
            msg = err.args[0]
            raise ValueError(f"{msg} for {location}") from err

        # host's primary domain, if set, should match one vlan
        vlan = iface["vlan"]
        if cfg["primary_domain"] == vlan["domain"]:
            matching_domain = vlan["domain"]

    if cfg["primary_domain"]:
        if matching_domain is None:
            raise KeyError(
                f"invalid primary_domain: no interface's vlan domain matches primary_domain '{cfg['primary_domain']}' for host '{cfg['hostname']}'")
    else:
        # single interface => set host domain to vlan domain
        if len(ifaces) == 1:
            cfg["primary_domain"] = ifaces[0]["vlan"]["domain"]
        # else leave host domain blank


def _validate_network(iface: dict, vswitches: dict):
    """Validate the interface's vswitch and vlan."""
    match iface["type"]:
        case "port":
            # ports (vlan parents and vswitch ifaces) do not have any network to validate
            return
        case "uplink":
            vswitch_name = iface.get("vswitch")
            if vswitch_name == "__unknown__":  # macvtap or physical host
                iface["vswitch"] = _unknown_vswitch
                return
            else:
                vswitch = vswitches.get(vswitch_name)
                if iface["vswitch"] is None:
                    raise ValueError(f"invalid vswitch '{vswitch_name}'")
                # do not return; continue checking for vlan
        case "vlan":
            # already validated in for_vlan()
            return
        case "std":
            vswitch_name = iface.get("vswitch")
            vswitch = vswitches.get(vswitch_name)
        case _:
            raise ValueError("unknown interface type " + iface["type"])

    # for std interfaces and uplinks for vswitches, confirm the vlan
    if vswitch is None:
        raise ValueError(f"invalid vswitch '{vswitch_name}'")

    # check vlan for uplink and standard ifaces
    iface["vswitch"] = vswitch

    vlan_id = iface.get("vlan")
    iface["vlan"] = config.vlan.lookup(vlan_id, vswitch)
    iface["firewall_zone"] = str(iface.get("firewall_zone", iface["vlan"]["name"])).upper()


def _validate_iface(iface: dict, location: str):
    """Validate a single interface."""
    # vlan set by validate_network
    vlan = iface["vlan"]

    # required ipv4 address, but allow special 'dhcp' value
    address = iface.get("ipv4_address")
    if address is None:
        raise KeyError("no ipv4_address defined")

    if address == "dhcp":
        if not vlan["dhcp4_enabled"]:
            raise ValueError(f"{location} ipv4 dhcp requested but vlan " +
                             f"'{vlan['name']}' has 'dhcp4_enabled' set to false")
    else:
        _validate_ipaddress(iface, "ipv4")

    if "ipv4_gateway" in iface:
        gateway = iface["ipv4_gateway"]
        subnet = iface["vlan"]["ipv4_subnet"]
        try:
            iface["ipv4_gateway"] = ipaddress.ip_address(iface["ipv4_gateway"])
        except ValueError as ve:
            raise ValueError(f"{location} invalid 'ipv4_gateway' '{gateway}'") from ve
        if iface["ipv4_gateway"] not in subnet:
            raise ValueError(f"{location} invalid 'ipv4_gateway' '{gateway}'; it is not in subnet {subnet}")
    elif iface["vlan"]["routable"]:
        iface["ipv4_gateway"] = iface["vlan"]["ipv4_subnet"].network_address + 1
    else:
        iface["ipv4_gateway"] = None

    # ipv6 disabled at vlan level of interface level => ignore ipv6 config
    iface["ipv6_disabled"] = vlan["ipv6_disabled"] or bool(iface.get("ipv6_disabled"))

    if iface["ipv6_disabled"]:
        iface["ipv6_address"] = None
        # no SLAAC
        iface["ipv6_tempaddr"] = False
        iface["accept_ra"] = False
        # no DHCP
        iface["ipv6_dhcp"] = False
        iface["additional_ipv6_addresses"] = []
        return

    # default to False, SLAAC only; will not preclude using DHCP6 for options
    iface["ipv6_dhcp"] = bool(iface.get("ipv6_dhcp"))

    address = iface.get("ipv6_address")
    if address is not None:
        if (iface["type"] == "uplink") and (vlan["id"] == -1):
            # for uplinks with hardcoded ip addresess, a subnet is required
            if "ipv6_subnet" not in iface:
                raise KeyError(f"{location} ipv6_subnet must be set when using static ipv6_address")
            try:
                iface["ipv6_subnet"] = ipaddress.ip_network(iface["ipv6_subnet"])
            except ValueError as ve:
                raise ValueError(f"{location} invalid ipv6_subnet defined") from ve

        _validate_ipaddress(iface, "ipv6")
    else:
        iface["ipv6_address"] = None

    additional = parse.read_string_list_plurals(
        {"additional_ipv6_address", "additional_ipv6_address"}, iface, f"{location}.additional_ipv6_addresses")
    iface.pop("additional_ipv6_address", None)
    iface["additional_ipv6_addresses"] = []

    for address in additional:
        try:
            iface["additional_ipv6_addresses"].append(ipaddress.ip_address(address))
        except ValueError as ve:
            raise ValueError(f"{location} invalid additional_ipv6_address '{address}'") from ve

    if iface["ipv6_dhcp"] and not vlan["dhcp6_managed"]:
        _logger.warning(
            f"{location} ipv6 dhcp enabled but vlan '{vlan['name']}' has 'dhcp6_managed' set to false; no DHCP request will be made")

    # default to True; dhcpcd will also create RFC 7217 addresses
    iface["ipv6_tempaddr"] = True if "ipv6_tempaddr" not in iface else bool(iface["ipv6_tempaddr"])

    # default to True
    iface["accept_ra"] = True if "accept_ra" not in iface else bool(iface["accept_ra"])

    if iface["name"].startswith("wl"):  # wlxx or wlanx
        if not ("wifi_ssid" in iface) and not ("wifi_psk" in iface):
            raise KeyError(f"{location} both 'wifi_ssd' and 'wifi_psk' must be defined for WiFi interfaces")

    # for testing, allow asking for, but not assigning a prefix delegation
    iface["ipv6_ask_for_prefix"] = bool(iface.get("ipv6_ask_for_prefix"))
    if iface["ipv6_ask_for_prefix"]:
        _validate_prefix_len(iface, location)


def _validate_ipaddress(iface: dict, ip_version: str):
    key = ip_version + "_address"
    value = iface.get(key)
    if not value:
        raise ValueError(f"invalid {key} '{value}'")
    try:
        iface[key] = address = ipaddress.ip_address(value)
    except ValueError as ve:
        raise ValueError(f"invalid {key} '{value}'") from ve

    if ip_version + "_subnet" in iface["vlan"]:
        subnet = iface["vlan"].get(ip_version + "_subnet")
    else:
        subnet = iface.get(ip_version + "_subnet")

    if subnet is None:
        raise ValueError(f"subnet must be defined when setting an IP address")

    if address not in subnet:
        raise ValueError(f"invalid address {address}; it is not in subnet {subnet}")

    if ip_version == "ipv4":
        iface["ipv4_prefixlen"] = subnet.prefixlen

    if ip_version == "ipv6":
        iface["ipv6_prefixlen"] = subnet.prefixlen
        # gateway provided by router advertisements


def find_by_name(cfg: dict, iface_name: str) -> dict:
    for iface in cfg["interfaces"]:
        if iface["name"] == iface_name:
            return iface
    raise KeyError(f"cannot find interface config for '{iface_name}'")


def find_ips_to_interfaces(cfg: dict, to_match: list[dict], prefer_routable: bool = True, first_match_only: bool = True) -> list[dict]:
    """Find the IP addresses that the host configuration should use to connect to the given set of interfaces.

    cfg is a fully configured host and to_match is the list of interfaces from another configured host.
    If the interfaces are the same, localhost addresses will be returned.

    By default, a single match is returned; this can be changed by setting first_match_only to False.
    Interfaces that can be reached by routable vlans are preferred and returned first in the list unless
    prefer_routable is set to False.
    """
    matches = []
    for iface in cfg["interfaces"]:
        match = _match_iface(iface, to_match, prefer_routable, first_match_only)

        if match and first_match_only:
            return match

        matches.extend(match)
    return matches


def find_ips_from_vlan(vswitch: dict, vlan: dict, to_match: list[dict]):
    """Find the IP addresses that any host on the vlan should use to connect to the given set of interfaces.

    vswitch and vlan are fully configured object and to_match is the list of interfaces from a configured host.
    """
    # fake interface that will never match localhost
    ifaces = [{"vswitch": vswitch, "vlan": vlan, "ipv4_address": "dhcp"}]

    return find_ips_to_interfaces({"interfaces": ifaces}, to_match, first_match_only=False)


def _match_iface(iface: dict, to_match: list[dict], prefer_routable=True, first_match_only=True):
    # split matches into addresses based on routability of the vlans
    routed = []
    unrouted = []

    for match in to_match:
        # valid match if interfaces are on the same vlan or the same vswitch and both vlans are routable
        # will not match across vswitches; vlan name is unique across all vswtiches
        if iface["vlan"]["name"] != match["vlan"]["name"]:
            if ((iface["vswitch"]["name"] == match["vswitch"]["name"])
                    and iface["vlan"]["routable"] and match["vlan"]["routable"]):
                candidates = routed
            else:
                continue
        else:
            candidates = unrouted

        ip4 = iface["ipv4_address"]
        ip6 = iface.get("ipv6_address")  # optional

        if (ip4 == "dhcp"):
            ip4 = None
        if not ip6:
            ip6 = "noip6"  # prevent matching ipv4 dhcp and no ipv6 with localhost

        if (ip4 == match["ipv4_address"]) or (ip6 == match.get("ipv6_address")):
            # localhost beats all other possible matches
            return [{
                "ipv4_address": ipaddress.ip_address("127.0.0.1"),
                "ipv6_address": ipaddress.ip_address("::1"),
                "src_iface": iface,
                "dst_iface": match
            }]
        else:
            ip4 = None if match["ipv4_address"] == "dhcp" else match["ipv4_address"]
            ip6 = match.get("ipv6_address")

            if ip4 or ip6:
                candidates.append({
                    "ipv4_address": ip4,
                    "ipv6_address": ip6,
                    "src_iface": iface,
                    "dest_iface": match
                })

    if prefer_routable:
        matches = routed + unrouted
    else:
        matches = unrouted + routed

    if first_match_only:
        del matches[1:]

    return matches


def check_accessiblity(to_check: list[dict], vswitches: list[dict], ignore_vlan: Callable = lambda *_: False) -> set[str]:
    """Check if the the given list of interfaces can reach all the vlans on the given vswitches.
    Returns an empty set if all vlans are accessible. Otherwise returns a set of vlan names, as strings.

    Optionally accepts an additional check function that can remove a vlan from consideration. This function will be
    passed a single vlan. If the vlan should be removed, even if it is not accessible by the given interfaces, the
    function should return 'True'."""
    # find all the vlans this host can access
    accessible_vlans = set()

    for iface in to_check:
        if iface["type"] not in {"std", "vlan"}:
            continue

        if iface["vlan"]["routable"]:
            for vlan in iface["vswitch"]["vlans"]:
                if vlan["routable"]:  # router will make all routable vlans accessible
                    accessible_vlans.add(vlan["name"])
        else:  # non-routable vlans must have an interface on the vlan
            accessible_vlans.add(iface["vlan"]["name"])

    # look for missing vlans
    for vswitch in vswitches:
        for vlan in vswitch["vlans"]:
            if (vlan["name"] in accessible_vlans) or ignore_vlan(vlan):
                accessible_vlans.remove(vlan["name"])

    return accessible_vlans


def for_vlan(parent: str, vswitch: dict, vlan: dict, mac_address: str | None) -> dict:
    if not vswitch:
        raise KeyError("vswitch must be specified")
    if not vlan:
        raise KeyError("vlan must be specified")

    if vlan["id"] not in vswitch["vlans_by_id"]:
        raise KeyError(f"invalid vlan '{vlan['id']}'; not defined in vswitch '{vswitch['name']}'")

    iface = {
        "type": "vlan",
        "vswitch": vswitch,
        "vlan": vlan,
        "accept_ra": False,  # assume prefix delgation assigns addresses and router configures a static ipv6 address
        "ipv6_dhcp": False,
        "forward": True
    }

    iface["ipv4_address"] = str(vlan["ipv4_subnet"].network_address + 1)

    if vlan["id"] is None:
        # this is the default, untagged vlan; it _is_ the interface
        iface["name"] = parent
        iface["mac_address"] = mac_address
    else:
        iface["name"] = f"{parent}.{vlan['id']}"
        iface["parent"] = parent

    if vlan.get("ipv6_subnet"):
        # manually set the IPv6 address
        iface["ipv6_address"] = str(vlan["ipv6_subnet"].network_address + 1)

    return iface


# set the minimal set of properties tht allow all functions to accept the objects, but not match by any criteria
_unknown_vswitch = {"name": "__none__", "vlans_by_name": {}, "vlans_by_id": {}, "vlans": []}
# ports should not be assigned addresses, so disable ipv6
_port_vlan = {
    "id": -1, "name": "__none__", "domain": "__unknown__",
    "routable": False, "dhcp4_enabled": True, "ipv6_disabled": True,
    "ipv4_subnet": ipaddress.ip_network("255.255.255.0/24")
}
# uplinks can enable ipv6 but set managed to avoid warning messages in _validate_iface
_uplink_vlan = {
    "id": -1, "name": "__none__", "domain": "__unknown__",
    "routable": False, "dhcp4_enabled": True, "ipv6_disabled": False, "dhcp6_managed": True}


def for_port(name: str, comment: str, subtype: str, parent=None, uplink=None, mac_address=None) -> dict:
    """ Create an interface configuration for "port" interfaces like vswitches and vlan parents.
    Ports must be configured but will never have IP addressed assigned.
    """

    return {
        "type": "port",
        "subtype": subtype,
        "name": name,
        "comment": comment,
        "parent": parent,
        "uplink": uplink,
        "ipv4_address": ipaddress.ip_address("255.255.255.255"),
        "vlan": _port_vlan,
        "vswitch": _unknown_vswitch,
        "mac_address": mac_address
    }


def configure_uplink(cfg: dict, name: str):
    """Configure the interface definition for a router's wan uplink.
    Allows partial configuration of IP addresses, including DHCP.
    For VMs, requires either a 'macvtap' interface, a 'passthrough' interface + PCI address 
    or a 'vswitch' + 'vlan' to use for connectivity."""
    uplink = cfg.get("uplink")
    location = cfg["hostname"]

    if uplink is None:
        raise KeyError(f"{location} must define an uplink")

    # default to the first interface
    parse.set_default_string("name", uplink, "eth0")

    # allow some end user configuration of the uplink interface YAML
    # but it will always use forwarding
    uplink["type"] = "uplink"
    uplink["comment"] = "internet uplink"
    uplink["forward"] = True
    uplink["name"] = name

    if (cfg["is_vm"]):
        uplink["mac_address"] = random_mac_address()
    else:
        # used for renaming; physical servers should set rename rules in yaml
        uplink["mac_address"] = None

    # delegated prefixes for ipv6; used by dhcpcd
    uplink["ipv6_delegated_prefixes"] = []

    location += ".uplink"

    if cfg["is_vm"]:
        # uplink can be an existing vswitch or a physical iface either on the host via macvtap or PCI passthrough
        if "macvtap" in uplink:
            uplink_iface = uplink["macvtap"]

            if not isinstance(uplink_iface, str):
                raise ValueError(f"{location}.macvtap must define an interface as a string")

            # ensure interface is not being used elsewhere
            for vswitch in cfg["vswitches"].values():
                if uplink_iface in vswitch["uplinks"]:
                    raise ValueError(f"{location}.macvtap "
                                     "{uplink_iface} cannot be shared with the uplink " + f"for vswitch '{vswitch['name']}'")

            # set name here to distinguish from vswitch uplink; validate will convert to full object
            uplink["vswitch"] = "__unknown__"
            uplink["vlan"] = _uplink_vlan
        elif "passthrough" in uplink:
            if not isinstance(uplink["passthrough"], dict):
                raise ValueError(f"{location} 'passthrough' must be a dict of 'name' & 'pci_address")

            passthrough = uplink["passthrough"]
            passthrough["bus"], passthrough["slot"], passthrough["function"] = pci.split(
                passthrough["pci_address"], location + ".passthough")

            # passthrough will create a SR-IOV virtual function which _can_ be shared with other uplinks

            # set name here to distinguish from vswitch uplink; validate will convert to full object
            uplink["vswitch"] = "__unknown__"
            uplink["vlan"] = _uplink_vlan
        elif "vswitch" not in uplink:
            raise ValueError((f"{location} must define a vswitch+vlan or a macvtap/passthrough host interface"))

    else:  # physical host uplinks are treated like normal ifaces, but without a vswitch+vlan
        uplink["vswitch"] = "__unknown__"
        uplink["vlan"] = _uplink_vlan

    _validate_prefix_len(uplink, location)

    # validate will check IP address configuration
    return uplink


def _validate_prefix_len(iface: dict, location: str):
    prefixlen = iface.get("ipv6_pd_prefixlen")

    if prefixlen is None:
        iface["ipv6_pd_prefixlen"] = 56
    elif not isinstance(prefixlen, int):
        raise ValueError(f"{location}.ipv6_pd_prefixlen {prefixlen} must be an integer")
    elif prefixlen >= 64:
        raise ValueError(f"{location}.ipv6_pd_prefixlen {prefixlen} must be < 64")
    elif prefixlen < 48:
        raise ValueError(f"{location}.ipv6_pd_prefixlen {prefixlen} must be >= 48")


def random_mac_address() -> str:
    """Create a mac address for virtual interfaces."""
    octets = ["52", "54"]  # all libvirt mac addresses start with 52:54
    for i in range(4):
        octets.append(format(random.randint(0, 255), "02x"))
    return ":".join(octets)


def validate_renaming(cfg: dict):
    """Validate rename_interfaces defined in the host, if any."""
    if "rename_interface" in cfg:
        renamings = cfg.pop("rename_interface")
        cfg["rename_interfaces"] = renamings
    elif "rename_interfaces" in cfg:
        renamings = cfg["rename_interfaces"]
    else:
        # optional
        return

    location = f"{cfg['hostname']}.rename_interfaces"

    if not isinstance(renamings, list):
        raise ValueError(f"{location} must be a list")

    for i, rename in enumerate(renamings, start=1):
        m_loc = location + f"[{i}]"

        if not isinstance(rename, dict):
            raise ValueError(f"{m_loc} must be a dict, not a {type(rename)}")

        # must include name and valid MAC address
        parse.non_empty_string("name", rename, m_loc)

        mac_address = rename.get("mac_address")
        parse.validate_mac_address(mac_address, m_loc)
