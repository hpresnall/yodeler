"""Handles parsing and validating vlan configuration from site YAML files."""
import logging
import ipaddress
import collections.abc

_logger = logging.getLogger(__name__)


def validate(domain, vswitch):
    """Validate all the vlans defined in the vswitch."""
    vswitch_name = vswitch["name"]

    vlans = vswitch.get("vlans")
    if (vlans is None) or (len(vlans) == 0):
        raise KeyError(
            f"no vlans defined for vswitch {vswitch_name}: {vswitch}")

    vswitch_name = vswitch["name"]

    # list of vlans in yaml => dicts of names & ids to vswitches
    vlans_by_id = vswitch["vlans_by_id"] = {}
    vlans_by_name = vswitch["vlans_by_name"] = {}

    for i, vlan in enumerate(vlans, start=1):
        # name is required and must be unique
        if not vlan.get("name") or (vlan["name"] == ""):
            raise KeyError(
                f"no name for vlan {i} in vswitch {vswitch_name}: {vswitch}")

        vlan_name = vlan["name"]
        if vlan_name in vlans_by_name:
            raise KeyError(
                f"duplicate name {vlan_name} for vlan in vswitch {vswitch_name}: {vlan}")
        vlans_by_name[vlan_name] = vlan

        # vlan id must be unique
        # None is an allowed id and implies no vlan tagging
        vlan_id = vlan["id"] = vlan.get("id", None)

        if vlan_id in vlans_by_id:
            raise KeyError(
                f"duplicate id {vlan_id} for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
        vlans_by_id[vlan_id] = vlan

        # add default values
        for key in DEFAULT_VLAN_CONFIG:
            if key not in vlan:
                vlan[key] = DEFAULT_VLAN_CONFIG[key]

        _validate_vlan_subnet(vswitch_name, vlan, "ipv4")
        _validate_vlan_subnet(vswitch_name, vlan, "ipv6")

        # domain must be a subdomain of the top-level site
        if vlan["domain"] and (domain not in vlan["domain"]):
            raise KeyError(
                (f"domain for vlan {vlan_name}, {vlan['domain']} is not a subdomain of {domain}"
                 f" in vswitch {vswitch_name}: {vlan}"))

    _configure_default_vlan(vswitch)
    _validate_access_vlans(vswitch)


def _validate_vlan_subnet(vswitch_name, vlan, ip_version):
    # ipv4 subnet is required
    # ipv6 subnet is optional; this does not preclude addresses from a prefix assignment
    subnet = vlan.get(ip_version + "_subnet")
    vlan_name = vlan["name"]

    if subnet is None:
        if ip_version == "ipv4":
            raise KeyError(
                f"no {ip_version}_subnet for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")
        if ip_version == "ipv6":
            vlan["ipv6_subnet"] = None
            return

    # remove the subnet if the vlan disables ipv6
    if ip_version == "ipv6" and vlan["ipv6_disable"]:
        vlan["ipv6_subnet"] = None
        return

    try:
        vlan[ip_version + "_subnet"] = subnet = ipaddress.ip_network(subnet)
    except:
        raise KeyError(
            f"invalid {ip_version}_subnet for vlan {vlan_name} in vswitch {vswitch_name}: {vlan}")

    # default to DHCP range over all addresses except the router
    min_key = "dhcp_min_address_" + ip_version
    max_key = "dhcp_max_address_" + ip_version

    dhcp_min = vlan.get(min_key, DEFAULT_VLAN_CONFIG[min_key])
    dhcp_max = vlan.get(max_key, DEFAULT_VLAN_CONFIG[max_key])

    dhcp_min = subnet.network_address + dhcp_min
    dhcp_max = subnet.network_address + dhcp_max

    if dhcp_min not in subnet:
        raise KeyError((f"invalid {min_key} for vlan {vlan_name}"
                        f" in vswitch {vswitch_name}: {vlan}"))
    if dhcp_max not in subnet:
        raise KeyError((f"invalid {max_key} for vlan {vlan_name}"
                        f" in vswitch {vswitch_name}: {vlan}"))
    if dhcp_min > dhcp_max:
        raise KeyError((f"{min_key} > {max_key} for vlan {vlan_name}"
                        f" in vswitch {vswitch_name}: {vlan}"))


def _configure_default_vlan(vswitch):
    # track which vlan is marked as the default
    default_vlan = None

    for vlan in vswitch["vlans"]:
        # only allow one default
        if "default" in vlan:
            if default_vlan is not None:
                raise KeyError(f"multiple default vlans for vswitch {vswitch['name']}: {vswitch}")
            default_vlan = vlan
        else:
            vlan["default"] = False

    if default_vlan is not None:
        vswitch["default_vlan"] = default_vlan
    elif len(vswitch['vlans_by_id']) == 1:  # one vlan; make it the default
        vlan = list(vswitch['vlans_by_id'].values())[0]
        vswitch["default_vlan"] = vlan
        vlan["default"] = True
    else:
        vswitch["default_vlan"] = None


def _validate_access_vlans(vswitch):
    for vlan in vswitch["vlans"]:
        vlan_name = vlan["name"]
        access_vlans = vlan.get("access_vlans")

        if access_vlans is None:
            continue

        if (not isinstance(access_vlans, collections.abc.Sequence)
                or isinstance(access_vlans, str)):
            raise KeyError(
                f"non-array access_vlans in vlan {vlan_name} for vswitch {vswitch['name']}: {vlan}")

        # make unique
        vlan["access_vlans"] = set(access_vlans)

        for vlan_id in access_vlans:
            if vlan_id not in vswitch['vlans_by_id']:
                raise KeyError((f"invalid access_vlan id {vlan_id} in vlan {vlan_name}"
                                f" for vswitch {vswitch['name']}: {vlan}"))


# accessible for testing
DEFAULT_VLAN_CONFIG = {
    "routable": True,  # vlan will have an interface assigned on the router
    "domain": "",
    "ipv6_disable": False,
    "allow_dhcp": True,  # DHCP server will be configured
    "allow_internet": False,  # firewall will restrict outbound internet access
    # do not allow internet access when firewall is stopped
    "allow_access_stopped_firewall": False,
    "allow_dns_update": False,  # do not allow this subnet to make DDNS updates
    "dhcp_min_address_ipv4": 2,
    "dhcp_max_address_ipv4": 252,
    "dhcp_min_address_ipv6": 2,
    "dhcp_max_address_ipv6": 0xffff,
    "known_hosts": []
}
