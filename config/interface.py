"""Handles parsing and validating interface configuration from host YAML files."""
import logging
import ipaddress

import config.vlan

_logger = logging.getLogger(__name__)


def validate(cfg):
    """Validate all the interfaces defined in the host."""
    ifaces = cfg.get("interfaces")
    if (ifaces is None) or (len(ifaces) == 0):
        for role in cfg["roles"]:
            if role.name == "router":
                cfg["interfaces"] = []
                return  # router role defines all required interfaces
        raise KeyError("no interfaces defined")

    vswitches = cfg["vswitches"]

    # domain used in /etc/resolv.conf
    matching_domain = None
    iface_counter = 0

    for i, iface in enumerate(ifaces):
        if "name" not in iface:
            iface["name"] = f"eth{iface_counter}"
            iface_counter += 1

        try:
            validate_network(iface, vswitches)
            validate_iface(iface)
        except KeyError as err:
            msg = err.args[0]
            raise KeyError(f"{msg} for interface {i}: {iface['name']}") from err

        # host's primary domain, if set, should match one vlan
        vlan = iface["vlan"]
        if cfg["primary_domain"] == vlan["domain"]:
            matching_domain = vlan["domain"]

    if cfg["primary_domain"] != "":
        if matching_domain is None:
            raise KeyError(
                f"invalid primary_domain: no vlan domain matches {cfg['primary_domain']}")
    else:
        # single interface => set host domain to vlan domain
        if len(ifaces) == 1:
            cfg["primary_domain"] = ifaces[0]["vlan"]["domain"]
        # else leave host domain blank


def validate_network(iface, vswitches):
    """Validate the interface's vswitch and vlan."""
    vswitch_name = iface.get("vswitch")
    vswitch = vswitches.get(vswitch_name)

    if vswitch is None:
        raise KeyError(f"invalid vswitch {vswitch_name}")

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
        raise KeyError("no ipv4_address defined for interface")

    if address != "dhcp":
        _validate_ipaddress(iface, "ipv4")

        if vlan is None:
            # no vlan => cannot lookup subnet so it must be defined explicitly
            if "ipv4_subnet" not in iface:
                raise KeyError("ipv4_subnet must be set when using static ipv4_address")
            try:
                ipaddress.ip_network(iface["ipv4_subnet"])
            except Exception as exp:
                raise KeyError("invalid ipv4_subnet") from exp

    # ipv6 disabled at vlan level of interface level => ignore address
    ipv6_disable = (vlan["ipv6_disable"] or iface.get("ipv6_disable")
                    if vlan is not None else iface.get("ipv6_disable"))

    if ipv6_disable:
        iface["ipv6_address"] = None
        # no SLAAC
        iface["privext"] = False
        iface["accept_ra"] = False
    else:
        address = iface.get("ipv6_address")
        if address is not None:
            _validate_ipaddress(iface, "ipv6")

            if vlan is None:
                # no vlan => cannot lookup subnet so it must be defined explicitly
                if "ipv6_subnet" not in iface:
                    raise KeyError("ipv6_subnet must be set when using static ipv6_address")

                try:
                    ipaddress.ip_network(iface["ipv6_subnet"])
                except:
                    raise KeyError("invalid ipv6_subnet defined") from None
        else:
            iface["ipv6_address"] = None

        iface["privext"] = bool(iface.get("privext"))
        iface["accept_ra"] = True if "accept_ra" not in iface else bool(iface.get("accept_ra"))


def _validate_ipaddress(iface, ip_version):
    key = ip_version + "_address"
    try:
        value = iface.get(key)
        iface[key] = address = ipaddress.ip_address(value)
    except Exception as exp:
        raise KeyError(f"invalid {key} {value}") from exp

    subnet = iface['vlan'][ip_version + "_subnet"]

    if subnet is None:
        raise KeyError(
            f"subnet for vlan {iface['vlan']['id']} cannot be None when specifying an IP address")

    if address not in subnet:
        raise KeyError(
            (f"invalid address {address}; "
             f"it is not in vlan {iface['vlan']['id']}'s subnet {subnet}"))

    if ip_version == "ipv4":
        iface["ipv4_prefixlen"] = subnet.prefixlen
        iface["ipv4_gateway"] = subnet.network_address + 1
    if ip_version == "ipv6":
        iface["ipv6_prefixlen"] = subnet.prefixlen
        # gateway provided by router advertisements
