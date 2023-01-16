"""Handles parsing and validating interface configuration from host YAML files."""
import logging
import ipaddress

import config.vlan

_logger = logging.getLogger(__name__)


def validate(cfg):
    """Validate all the interfaces defined in the host."""
    ifaces = cfg.get("interfaces")

    if ifaces is None:
        raise KeyError(f"no interfaces defined for host '{cfg['hostname']}'")
    if not isinstance(ifaces, list):
        raise KeyError(f"interfaces must be an array for host '{cfg['hostname']}'")
    if len(ifaces) == 0:
        raise KeyError(f"interfaces cannot be empty for host '{cfg['hostname']}'")

    vswitches = cfg["vswitches"]

    # domain used in /etc/resolv.conf
    matching_domain = None
    iface_counter = 0

    for i, iface in enumerate(ifaces):
        if not isinstance(iface, dict):
            raise KeyError(f"iface {i} must be an object for host '{cfg['hostname']}'")

        if "name" not in iface:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        try:
            if ("type" not in iface):
                iface["type"] = None
                validate_network(iface, vswitches)
                validate_iface(iface)
            # ports have no configuration; vlan ifaces are defined by the vlan config
            else:
                if iface["type"] not in {"vlan", "port", "uplink"}:
                    raise KeyError("only 'vlan' and 'port' types are supported")
                if iface["type"] == "uplink":
                    validate_iface(iface)
                    if "vswitch" in iface:
                        validate_network(iface, vswitches)
        except KeyError as err:
            msg = err.args[0]
            raise KeyError(f"{msg} for interface {i} on host '{cfg['hostname']}': '{iface['name']}'") from err

        # host's primary domain, if set, should match one vlan
        vlan = iface.get("vlan")
        if vlan and (cfg["primary_domain"] == vlan["domain"]):
            matching_domain = vlan["domain"]

    if cfg["primary_domain"]:
        if matching_domain is None:
            raise KeyError(
                f"invalid primary_domain: no interface's vlan domain matches primary_domain '{cfg['primary_domain']}'")
    else:
        # single interface => set host domain to vlan domain
        if vlan and (len(ifaces) == 1):
            cfg["primary_domain"] = ifaces[0]["vlan"]["domain"]
        # else leave host domain blank


def validate_network(iface, vswitches):
    """Validate the interface's vswitch and vlan."""
    vswitch_name = iface.get("vswitch")
    vswitch = vswitches.get(vswitch_name)

    if vswitch is None:
        if iface.get("vlan") is None:
            return  # no vlan => ipv4_subnet required for non-dhcp; will be confirmed in validate_interface()
        else:
            raise KeyError(f"invalid vswitch '{vswitch_name}'")

    iface["vswitch"] = vswitch

    vlan_id = iface.get("vlan")
    iface["vlan"] = config.vlan.lookup(vlan_id, vswitch)
    iface["firewall_zone"] = iface.get("firewall_zone", vswitch_name).upper()


def validate_iface(iface):
    """Validate a single interface."""
    # vlan set by _validate_network in default cause
    # some Roles need interfaces on undefined networks, e.g. a router's public iface
    vlan = iface.get("vlan")

    # required ipv4 address, but allow special 'dhcp' value
    address = iface.get("ipv4_address")
    if address is None:
        raise KeyError("no ipv4_address defined")

    if address != "dhcp":
        if vlan is None:
            # no vlan => cannot lookup subnet so it must be defined explicitly
            if "ipv4_subnet" not in iface:
                raise KeyError("ipv4_subnet must be set when using static ipv4_address")
            try:
                iface["ipv4_subnet"] = ipaddress.ip_network(iface["ipv4_subnet"])
            except Exception as exp:
                raise KeyError(f"invalid ipv4_subnet {iface['ipv4_subnet']}") from exp

        _validate_ipaddress(iface, "ipv4")

    # ipv6 disabled at vlan level of interface level => ignore address
    ipv6_disable = (vlan["ipv6_disable"] or iface.get("ipv6_disable")
                    if vlan is not None else iface.get("ipv6_disable"))

    if ipv6_disable:
        iface["ipv6_address"] = None
        # no SLAAC
        iface["ipv6_tempaddr"] = False
        iface["accept_ra"] = False
        # no DHCP
        iface["ipv6_dhcp"] = False
    else:
        address = iface.get("ipv6_address")
        if address is not None:
            if vlan is None:
                # no vlan => cannot lookup subnet so it must be defined explicitly
                if "ipv6_subnet" not in iface:
                    raise KeyError("ipv6_subnet must be set when using static ipv6_address")
                try:
                    iface["ipv6_subnet"] = ipaddress.ip_network(iface["ipv6_subnet"])
                except:
                    raise KeyError("invalid ipv6_subnet defined") from None

            _validate_ipaddress(iface, "ipv6")
        else:
            iface["ipv6_address"] = None

        # default to False, SLAAC only
        # note will not preclude using DHCP6 for options
        iface["ipv6_dhcp"] = bool(iface.get("ipv6_dhcp"))

        if (iface["ipv6_dhcp"]) and vlan and (not vlan["dhcp_managed"]):
            _logger.warning(f"ipv6 dhcp enabled but vlan '{vlan['name']}' has 'dhcp_managed' set to False")

        # default to False; dhcpcd will use another temporary address method
        iface["ipv6_tempaddr"] = bool(iface.get("ipv6_tempaddr"))

        # default to True
        iface["accept_ra"] = True if "accept_ra" not in iface else bool(iface.get("accept_ra"))

        if iface["name"].startswith("wl"):  # wlxx or wlanx
            if not ("wifi_ssid" in iface) and not ("wifi_psk" in iface):
                raise KeyError("both 'wifi_ssd' and 'wifi_psk' must be defined for WiFi interfaces")


def _validate_ipaddress(iface, ip_version):
    key = ip_version + "_address"
    try:
        value = iface.get(key)
        iface[key] = address = ipaddress.ip_address(value)
    except Exception as exp:
        raise KeyError(f"invalid {key} '{value}'") from exp

    if iface.get("vlan"):
        subnet = iface["vlan"].get(ip_version + "_subnet")
    else:
        subnet = iface.get(ip_version + "_subnet")

    if subnet is None:
        raise KeyError(f"subnet cannot be None when specifying an IP address")

    if address not in subnet:
        raise KeyError(f"invalid address {address}; it is not in subnet {subnet}")

    if ip_version == "ipv4":
        iface["ipv4_prefixlen"] = subnet.prefixlen
        iface["ipv4_gateway"] = subnet.network_address + 1
    if ip_version == "ipv6":
        iface["ipv6_prefixlen"] = subnet.prefixlen
        # gateway provided by router advertisements


def find_by_name(cfg: dict, iface_name: str):
    for iface in cfg["interfaces"]:
        if iface["name"] == iface_name:
            return iface
    raise KeyError(f"cannot find interface config for '{iface_name}'")


def find_ips_to_interfaces(cfg: dict, to_match: list[dict], prefer_routable=True, first_match_only=True):
    """Find the IP addresses that the host configuration should use to connect to the given set of interfaces.

    cfg is a fully configured host and to_match is the list of interfaces from another configured host.
    If the interfaces are the same, localhost addresses will be returned.

    By default, a single match is returned; this can be changed by setting first_match_only to False.
    Interfaces that can be reached by routable vlans are preferred and returned first in the list unless
    prefer_routable is set to False.
    """
    matches = []
    for iface in cfg["interfaces"]:
        if ("type" in iface) and iface["type"]:
            continue

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
        ip6 = iface.get("ipv6_address")  # can be None

        if (ip4 == "dhcp"):
            ip4 = None
        if not ip6:
            ip6 = "noip6"  # prevent matching ipv4 dhcp and no ipv6 with localhost

        if (ip4 == match["ipv4_address"]) or (ip6 == match.get("ipv6_address")):
            # localhost beats all other possible matches
            return [{
                "ipv4_address": ipaddress.ip_address("127.0.0.1"),
                "ipv6_address": ipaddress.ip_address("::1")
            }]
        else:
            ip4 = None if match["ipv4_address"] == "dhcp" else match["ipv4_address"]
            ip6 = match.get("ipv6_address")

            if ip4 or ip6:
                candidates.append({
                    "ipv4_address": ip4,
                    "ipv6_address": ip6
                })

    if prefer_routable:
        matches = routed + unrouted
    else:
        matches = unrouted + routed

    if first_match_only:
        del matches[1:]

    return matches
